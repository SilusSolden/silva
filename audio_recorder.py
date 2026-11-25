"""Record microphone audio to WAV and SpeechRecognition AudioData."""

from __future__ import annotations

import math
import struct
import threading
import wave

import pyaudio
import speech_recognition as sr

SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2
CHUNK = 1024
MIN_RECORD_SECONDS = 1.5
MIN_RMS = 0.012


def list_input_devices() -> list[dict]:
    pa = pyaudio.PyAudio()
    devices: list[dict] = []
    try:
        try:
            default_index = pa.get_default_input_device_info()["index"]
        except OSError:
            default_index = None

        for index in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(index)
            if int(info.get("maxInputChannels", 0)) <= 0:
                continue
            host = ""
            try:
                host = str(pa.get_host_api_info_by_index(int(info.get("hostApi", 0))).get("name") or "")
            except Exception:
                host = ""
            devices.append(
                {
                    "index": index,
                    "name": str(info.get("name", "Unknown")),
                    "is_default": index == default_index,
                    "host_api": host,
                }
            )
    finally:
        pa.terminate()
    return devices


def default_input_device() -> tuple[int | None, str]:
    try:
        from silva.media.devices import current_input_device

        return current_input_device()
    except Exception:
        pass
    pa = pyaudio.PyAudio()
    try:
        info = pa.get_default_input_device_info()
        return int(info["index"]), str(info.get("name", "Default microphone"))
    except OSError:
        return None, "System default microphone"
    finally:
        pa.terminate()


def pause_live_listen() -> None:
    """Free the mic so profile recording can open it."""
    try:
        from silva.media.devices import set_capture_active

        set_capture_active(False)
    except Exception:
        pass
    try:
        from silva.stt import release_active_microphone

        release_active_microphone()
    except Exception:
        pass


def frames_rms(frames: list[bytes]) -> float:
    raw = b"".join(frames)
    if len(raw) < 4:
        return 0.0
    count = len(raw) // 2
    samples = struct.unpack(f"{count}h", raw[: count * 2])
    if not samples:
        return 0.0
    mean_sq = sum((value / 32768.0) ** 2 for value in samples) / len(samples)
    return math.sqrt(mean_sq)


def frames_seconds(frames: list[bytes]) -> float:
    raw_len = sum(len(chunk) for chunk in frames)
    return raw_len / float(SAMPLE_RATE * SAMPLE_WIDTH * CHANNELS)


def _api_rank(host_api: str) -> int:
    api = (host_api or "").lower()
    if "mme" in api:
        return 3
    if "directsound" in api:
        return 2
    if "wasapi" in api:
        return 0
    return 1


def _pick_device_index(pa: pyaudio.PyAudio, preferred_name: str, preferred_index: int | None) -> tuple[int | None, str]:
    wanted = (preferred_name or "").strip().lower()
    best_index = preferred_index
    best_name = preferred_name or "System default microphone"
    best_rank = -1
    try:
        count = pa.get_device_count()
    except Exception:
        return preferred_index, best_name
    for index in range(count):
        try:
            info = pa.get_device_info_by_index(index)
        except Exception:
            continue
        if int(info.get("maxInputChannels", 0)) <= 0:
            continue
        name = str(info.get("name", "Unknown"))
        host = ""
        try:
            host = str(pa.get_host_api_info_by_index(int(info.get("hostApi", 0))).get("name") or "")
        except Exception:
            host = ""
        rank = _api_rank(host)
        if wanted and wanted[:18] in name.lower():
            rank += 10
        elif wanted and name.lower()[:18] in wanted:
            rank += 8
        if rank > best_rank:
            best_rank = rank
            best_index = index
            best_name = name
    return best_index, best_name


class VoiceRecorder:
    def __init__(self, *, device_index: int | None = None) -> None:
        self._device_index = device_index
        self._device_name = ""
        self._frames: list[bytes] = []
        self._recording = False
        self._thread: threading.Thread | None = None
        self._pa: pyaudio.PyAudio | None = None
        self._stream = None
        self._last_error: str | None = None
        self._lock = threading.Lock()

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def device_name(self) -> str:
        return self._device_name

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def start(self) -> bool:
        if self._recording:
            return True
        pause_live_listen()
        with self._lock:
            self._frames = []
        self._last_error = None
        self._recording = True
        self._thread = threading.Thread(target=self._record_loop, daemon=True, name="silva-voice-record")
        self._thread.start()
        return True

    def stop(self) -> None:
        self._recording = False
        stream = self._stream
        if stream is not None:
            try:
                stream.stop_stream()
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None

    def _record_loop(self) -> None:
        self._pa = pyaudio.PyAudio()
        try:
            preferred_index, preferred_name = default_input_device()
            if self._device_index is not None:
                preferred_index = self._device_index
            device_index, self._device_name = _pick_device_index(self._pa, preferred_name, preferred_index)
            open_kwargs = {
                "format": pyaudio.paInt16,
                "channels": CHANNELS,
                "rate": SAMPLE_RATE,
                "input": True,
                "frames_per_buffer": CHUNK,
            }
            if device_index is not None:
                open_kwargs["input_device_index"] = device_index
            self._stream = self._pa.open(**open_kwargs)
            while self._recording:
                data = self._stream.read(CHUNK, exception_on_overflow=False)
                if data:
                    with self._lock:
                        self._frames.append(data)
        except OSError as exc:
            self._last_error = f"Microphone unavailable: {exc}"
            self._recording = False
        finally:
            if self._stream is not None:
                try:
                    self._stream.stop_stream()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            if self._pa is not None:
                try:
                    self._pa.terminate()
                except Exception:
                    pass
                self._pa = None

    def snapshot_frames(self) -> list[bytes]:
        with self._lock:
            return list(self._frames)

    def rms(self) -> float:
        return frames_rms(self.snapshot_frames())

    def seconds(self) -> float:
        return frames_seconds(self.snapshot_frames())

    def has_audio(self) -> bool:
        return self.seconds() >= MIN_RECORD_SECONDS and self.rms() >= MIN_RMS

    def reject_reason(self) -> str | None:
        if self.last_error:
            return self.last_error
        seconds = self.seconds()
        rms = self.rms()
        if seconds < MIN_RECORD_SECONDS:
            return "That recording was too short. Speak for a couple of seconds, then click Save Voice."
        if rms < MIN_RMS:
            return "I barely heard you. Speak closer to the microphone, then click Save Voice."
        return None

    def to_audio_data(self) -> sr.AudioData | None:
        frames = self.snapshot_frames()
        if not frames:
            return None
        raw = b"".join(frames)
        return sr.AudioData(raw, SAMPLE_RATE, SAMPLE_WIDTH)

    def save_wav(self, path) -> None:
        frames = self.snapshot_frames()
        raw = b"".join(frames)
        if not raw:
            raise RuntimeError("No audio recorded.")
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(CHANNELS)
            handle.setsampwidth(SAMPLE_WIDTH)
            handle.setframerate(SAMPLE_RATE)
            handle.writeframes(raw)

    @staticmethod
    def load_wav(path) -> sr.AudioData:
        with sr.AudioFile(str(path)) as source:
            recognizer = sr.Recognizer()
            audio = recognizer.record(source)
        return audio


def wav_preview_levels(path, bars: int = 48) -> dict:
    """Read a saved voice WAV into a simple waveform for the profile example."""
    from pathlib import Path

    target = Path(path)
    empty = {"levels": [0.0] * bars, "seconds": 0.0, "name": target.name, "exists": False}
    if not target.is_file():
        return empty
    try:
        with wave.open(str(target), "rb") as handle:
            frames = handle.getnframes()
            rate = handle.getframerate() or SAMPLE_RATE
            width = handle.getsampwidth() or SAMPLE_WIDTH
            raw = handle.readframes(frames)
    except Exception:
        return empty
    if frames <= 0 or len(raw) < 2:
        return {**empty, "exists": True}
    count = len(raw) // width
    if width == 2:
        samples = struct.unpack(f"{count}h", raw[: count * 2])
        peak = 32768.0
    else:
        samples = list(raw[:count])
        peak = 128.0
    if not samples:
        return {**empty, "exists": True, "seconds": frames / float(rate)}
    chunk = max(1, len(samples) // bars)
    levels: list[float] = []
    for index in range(bars):
        piece = samples[index * chunk : (index + 1) * chunk]
        if not piece:
            levels.append(0.0)
            continue
        rms = math.sqrt(sum((value / peak) ** 2 for value in piece) / len(piece))
        levels.append(min(1.0, rms * 3.0))
    return {
        "levels": levels,
        "seconds": frames / float(rate),
        "name": target.name,
        "exists": True,
    }


def play_wav_file(path=None, *, blocking: bool = False, stop: bool = False) -> None:
    """Play a saved WAV. Preview uses async; speech overrides wait until the clip ends."""
    import sys
    from pathlib import Path

    if sys.platform != "win32":
        raise RuntimeError("Voice playback is only set up on Windows.")

    import winsound

    if stop or path is None:
        winsound.PlaySound(None, winsound.SND_PURGE)
        return

    target = Path(path)
    if not target.is_file():
        raise RuntimeError("No saved voice file to play.")
    winsound.PlaySound(None, winsound.SND_PURGE)
    flags = winsound.SND_FILENAME | winsound.SND_NODEFAULT
    if not blocking:
        flags |= winsound.SND_ASYNC
    winsound.PlaySound(str(target), flags)
