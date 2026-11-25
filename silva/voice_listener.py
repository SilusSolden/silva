"""Always-on background microphone listener for Silva."""

from __future__ import annotations

import queue
import threading
import time

import speech_recognition as sr

from silva.logger import log_error
from silva.stt import SpeechToText


class ContinuousVoiceListener:
    """Keep the mic active in a background thread and queue recognized speech."""

    def __init__(self) -> None:
        self._stt: SpeechToText | None = None
        self._queue: queue.Queue[tuple[str, sr.AudioData]] = queue.Queue()
        self._pause = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, stt: SpeechToText) -> None:
        if self._thread is not None and self._thread.is_alive():
            self._stt = stt
            return
        self._stt = stt
        self._stop.clear()
        self._pause.clear()
        self._thread = threading.Thread(target=self._loop, name="silva-voice-listener", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def pause(self) -> None:
        self._pause.set()

    def resume(self) -> None:
        self._pause.clear()

    def poll(self) -> tuple[str | None, sr.AudioData | None]:
        try:
            text, audio = self._queue.get_nowait()
            return text, audio
        except queue.Empty:
            return None, None

    def _loop(self) -> None:
        while not self._stop.is_set():
            if self._pause.is_set():
                time.sleep(0.03)
                continue
            stt = self._stt
            if stt is None:
                time.sleep(0.05)
                continue
            try:
                text, audio = stt.listen_with_audio(
                    timeout=None,
                    announce=False,
                    fast_end=True,
                )
                if text and audio is not None:
                    self._queue.put((text, audio))
            except Exception as exc:
                log_error("Continuous voice listener failed", exc=exc)
                time.sleep(0.4)
