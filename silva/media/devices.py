"""Silent auto-detect for the active microphone and playback device.

Webcam mics are skipped unless they look decent and nothing else is plugged in.
Does not open cameras. Camera presence lives in silva.media.camera.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass

from silva.config import load_config
from silva.logger import log_info

DEDICATED_MIC_HINTS: tuple[str, ...] = (
    "fifine",
    "am8",
    "xlr",
    "dynamic",
    "yeti",
    "blue yeti",
    "rode",
    "shure",
    "audio-technica",
    "audio technica",
    "hyperx quadcast",
    "quadcast",
    "samson",
    "atr2100",
    "atr 2100",
    "podcast",
    "streaming mic",
    "usb microphone",
    "usb mic",
    "studio microphone",
    "studio mic",
)

HEADSET_MIC_HINTS: tuple[str, ...] = (
    "headset",
    "headphone",
    "rig 600",
    "rig600",
    "rig 500",
    "nacon",
    "plantronics",
    "steelseries",
    "arctis",
    "turtle beach",
    "hyperx cloud",
    "cloud ii",
    "cloud 2",
    "bluetooth",
    "hands-free",
    "hands free",
    "dongle",
)

WEBCAM_MIC_HINTS: tuple[str, ...] = (
    "webcam",
    "web cam",
    "facecam",
    "face cam",
    "integrated camera",
    "usb camera",
    "hd camera",
    "hd webcam",
    "onn",
    "lifeCam",
    "life cam",
)

# Always skip — cheap camera mics that heat up / freeze when camera + mic run together.
WEBCAM_MIC_BLOCK: tuple[str, ...] = (
    "onn",
    "integrated webcam",
    "integrated camera",
    "usb 2.0 camera",
    "usb2.0 camera",
    "hd webcam",
)

OUTPUT_SPEAKER_HINTS: tuple[str, ...] = (
    "headset",
    "headphone",
    "headphones",
    "rig 600",
    "rig600",
    "nacon",
    "plantronics",
    "steelseries",
    "arctis",
    "bluetooth",
    "speakers",
    "realtek",
    "hdmi",
    "displayport",
    "nvidia",
    "amd",
)

OUTPUT_MIC_JACK_HINTS: tuple[str, ...] = (
    "fifine",
    "am8",
    "yeti",
    "microphone",
    "usb mic",
    "quadcast",
    "rode",
    "podcast",
)

_state_lock = threading.Lock()
_pa_lock = threading.RLock()
_last_poll = 0.0
_current_input: "AudioDevice | None" = None
_current_output: "AudioDevice | None" = None
_seen_input_names: set[str] = set()
_capture_active = False


def portaudio_lock() -> threading.RLock:
    """One PortAudio user at a time. Scanning while the mic is open crashes Windows."""
    return _pa_lock


def set_capture_active(active: bool) -> None:
    """Skip PortAudio device scans while SpeechRecognition has the mic open."""
    global _capture_active
    with _state_lock:
        _capture_active = bool(active)


def is_capture_active() -> bool:
    with _state_lock:
        return _capture_active


@dataclass(frozen=True)
class AudioDevice:
    index: int
    name: str
    is_default: bool = False
    host_api: str = ""
    kind: str = "input"


def _lower(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def _contains_any(name: str, hints: tuple[str, ...]) -> bool:
    lowered = _lower(name)
    return any(hint in lowered for hint in hints)


def is_webcam_mic(name: str) -> bool:
    lowered = _lower(name)
    if "microphone" in lowered and _contains_any(name, WEBCAM_MIC_HINTS):
        return True
    return _contains_any(name, WEBCAM_MIC_HINTS) and not _contains_any(name, DEDICATED_MIC_HINTS)


def is_blocked_webcam_mic(name: str) -> bool:
    return _contains_any(name, WEBCAM_MIC_BLOCK)


def is_decent_webcam_mic(name: str) -> bool:
    """Cheap built-in camera mics are not decent. Conference/array mics can be."""
    if is_blocked_webcam_mic(name):
        return False
    lowered = _lower(name)
    if any(token in lowered for token in ("array", "studio", "conference", "4k", "dual")):
        return True
    return False


def score_input(device: AudioDevice, *, extra_hints: tuple[str, ...] = ()) -> int:
    name = device.name
    if is_blocked_webcam_mic(name):
        return -1000
    if is_webcam_mic(name) and not is_decent_webcam_mic(name):
        return -400
    score = 0
    if extra_hints and _contains_any(name, extra_hints):
        score += 80
    if _contains_any(name, DEDICATED_MIC_HINTS):
        score += 120
    if _contains_any(name, HEADSET_MIC_HINTS):
        score += 40
    if device.is_default:
        score += 15
    api = _lower(device.host_api)
    # SpeechRecognition + WASAPI exclusive often hangs stream.read on Windows.
    if "mme" in api:
        score += 10
    elif "directsound" in api:
        score += 6
    elif "wasapi" in api:
        score += 1
    if is_webcam_mic(name) and is_decent_webcam_mic(name):
        score += 5
    return score


def score_output(device: AudioDevice) -> int:
    name = device.name
    score = 0
    # USB mics often show up as "Speakers (FIFINE ...)" — keep hearing on the headset.
    if _contains_any(name, OUTPUT_MIC_JACK_HINTS):
        score -= 90
    if _contains_any(name, OUTPUT_SPEAKER_HINTS):
        score += 50
    if device.is_default:
        score += 25
    api = _lower(device.host_api)
    if "wasapi" in api:
        score += 8
    return score


def _input_api_rank(host_api: str) -> int:
    api = _lower(host_api)
    if "mme" in api:
        return 3
    if "directsound" in api:
        return 2
    if "wasapi" in api:
        return 0
    return 1


def _dedupe_by_name(devices: list[AudioDevice], *, for_input: bool = False) -> list[AudioDevice]:
    best: dict[str, AudioDevice] = {}
    for item in devices:
        key = _lower(item.name)
        previous = best.get(key)
        if previous is None:
            best[key] = item
            continue
        if for_input:
            if _input_api_rank(item.host_api) > _input_api_rank(previous.host_api):
                best[key] = item
            elif item.is_default and not previous.is_default and _input_api_rank(item.host_api) == _input_api_rank(
                previous.host_api
            ):
                best[key] = item
            continue
        prev_wasapi = "wasapi" in _lower(previous.host_api)
        new_wasapi = "wasapi" in _lower(item.host_api)
        if new_wasapi and not prev_wasapi:
            best[key] = item
        elif item.is_default and not previous.is_default:
            best[key] = item
    return list(best.values())


def pick_input(
    devices: list[AudioDevice],
    *,
    current_name: str | None = None,
    allow_webcam_mic: bool = False,
    extra_hints: tuple[str, ...] = (),
) -> AudioDevice | None:
    usable: list[AudioDevice] = []
    for item in _dedupe_by_name(devices, for_input=True):
        if is_blocked_webcam_mic(item.name):
            continue
        if is_webcam_mic(item.name) and not allow_webcam_mic and not is_decent_webcam_mic(item.name):
            continue
        usable.append(item)

    if not usable:
        return None

    ranked = sorted(usable, key=lambda item: score_input(item, extra_hints=extra_hints), reverse=True)
    best = ranked[0]
    if not current_name:
        return best

    current = next((item for item in usable if _lower(item.name) == _lower(current_name)), None)
    if current is None:
        return best

    current_score = score_input(current, extra_hints=extra_hints)
    best_score = score_input(best, extra_hints=extra_hints)
    # Switch only when a clearly better device is now present (new dedicated mic).
    if best_score >= current_score + 50:
        return best
    return current


def pick_output(
    devices: list[AudioDevice],
    *,
    current_name: str | None = None,
) -> AudioDevice | None:
    usable = _dedupe_by_name(devices)
    if not usable:
        return None
    ranked = sorted(usable, key=score_output, reverse=True)
    best = ranked[0]
    if not current_name:
        return best
    current = next((item for item in usable if _lower(item.name) == _lower(current_name)), None)
    if current is None:
        return best
    if score_output(best) >= score_output(current) + 40:
        return best
    return current


def _enumerate_pyaudio() -> tuple[list[AudioDevice], list[AudioDevice]]:
    import pyaudio

    pa = pyaudio.PyAudio()
    inputs: list[AudioDevice] = []
    outputs: list[AudioDevice] = []
    try:
        try:
            default_in = int(pa.get_default_input_device_info()["index"])
        except Exception:
            default_in = None
        try:
            default_out = int(pa.get_default_output_device_info()["index"])
        except Exception:
            default_out = None

        try:
            count = int(pa.get_device_count())
        except Exception:
            count = 0
        for index in range(count):
            try:
                info = pa.get_device_info_by_index(index)
            except Exception:
                continue
            name = str(info.get("name") or "Unknown")
            try:
                host = str(pa.get_host_api_info_by_index(int(info.get("hostApi", 0))).get("name") or "")
            except Exception:
                host = ""
            if int(info.get("maxInputChannels", 0)) > 0:
                inputs.append(
                    AudioDevice(
                        index=index,
                        name=name,
                        is_default=index == default_in,
                        host_api=host,
                        kind="input",
                    )
                )
            if int(info.get("maxOutputChannels", 0)) > 0:
                outputs.append(
                    AudioDevice(
                        index=index,
                        name=name,
                        is_default=index == default_out,
                        host_api=host,
                        kind="output",
                    )
                )
    finally:
        try:
            pa.terminate()
        except Exception:
            pass
    return inputs, outputs


def _extra_mic_hints() -> tuple[str, ...]:
    config = load_config()
    extra = config.get("preferred_mic_hints") or []
    if isinstance(extra, str):
        extra = [extra]
    return tuple(str(item).lower() for item in extra if str(item).strip())


def _allow_webcam_mic() -> bool:
    return bool(load_config().get("allow_webcam_mic", False))


def poll_audio_devices(*, force: bool = False) -> None:
    """Silent refresh of the active mic and speakers. Never runs while the mic stream is open."""
    global _last_poll, _current_input, _current_output, _seen_input_names
    if not bool(load_config().get("device_auto_detect", True)):
        return
    interval = float(load_config().get("device_poll_seconds", 5.0))
    now = time.time()
    with _pa_lock:
        with _state_lock:
            if _capture_active:
                return
            if not force and now - _last_poll < max(2.0, interval):
                return
            _last_poll = now
        try:
            inputs, outputs = _enumerate_pyaudio()
        except Exception:
            with _state_lock:
                _current_input = None
            return

    extra = _extra_mic_hints()
    with _state_lock:
        previous_in = _current_input
        previous_out = _current_output
        chosen_in = pick_input(
            inputs,
            current_name=previous_in.name if previous_in else None,
            allow_webcam_mic=_allow_webcam_mic(),
            extra_hints=extra,
        )
        chosen_out = pick_output(
            outputs,
            current_name=previous_out.name if previous_out else None,
        )
        appeared = {item.name for item in inputs} - _seen_input_names
        _seen_input_names = {item.name for item in inputs}
        _current_input = chosen_in
        _current_output = chosen_out

    if chosen_in is not None and (
        previous_in is None
        or previous_in.name != chosen_in.name
        or previous_in.index != chosen_in.index
    ):
        log_info(f"Microphone auto-detect: using {chosen_in.name}")
    if chosen_out is not None and (previous_out is None or previous_out.name != chosen_out.name):
        log_info(f"Audio output auto-detect: following {chosen_out.name}")
    if appeared:
        log_info("Audio device connected: " + ", ".join(sorted(appeared)))


def peek_input_device() -> tuple[int | None, str]:
    with _state_lock:
        if _current_input is None:
            return None, "System default microphone"
        return _current_input.index, _current_input.name


def current_input_device() -> tuple[int | None, str]:
    if not is_capture_active():
        poll_audio_devices()
    return peek_input_device()


def current_output_device() -> tuple[int | None, str]:
    poll_audio_devices()
    with _state_lock:
        if _current_output is None:
            return None, "System default speakers"
        return _current_output.index, _current_output.name


def reset_device_state() -> None:
    global _last_poll, _current_input, _current_output, _seen_input_names
    with _state_lock:
        _last_poll = 0.0
        _current_input = None
        _current_output = None
        _seen_input_names = set()
