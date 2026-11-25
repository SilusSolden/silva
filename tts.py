"""Local text-to-speech — pyttsx3 only."""

from __future__ import annotations

import threading
import time

import pyttsx3

from silva.config import load_config


def _pick_female_voice_index(voices) -> int:
    for index, voice in enumerate(voices):
        name = voice.name.lower()
        if "zira" in name or "female" in name:
            return index
    return 1 if len(voices) > 1 else 0


class TextToSpeech:
    """pyttsx3 only — fresh engine per reply so mic use cannot mute output on Windows."""

    def __init__(self, rate: int = 170, volume: float = 0.65, voice_index: int | None = None):
        self._rate = rate
        self._volume = max(0.0, min(1.0, volume))
        self._voice_index = voice_index
        self._voice_id: str | None = None
        self._engine_lock = threading.Lock()
        self._active_engine = None
        self._mic_handoff_pending = False
        self._post_mic_delay = float(load_config().get("tts_post_mic_delay_seconds", 0.25))

    def note_mic_used(self) -> None:
        """Call after STT finishes so the next speak() waits for the mic to release."""
        self._post_mic_delay = float(load_config().get("tts_post_mic_delay_seconds", 0.25))
        self._mic_handoff_pending = True

    def set_rate(self, rate: int) -> None:
        self._rate = rate

    def _wait_for_mic_handoff(self) -> None:
        if self._mic_handoff_pending:
            delay = max(0.0, self._post_mic_delay)
            if delay:
                time.sleep(delay)
            self._mic_handoff_pending = False

    def warmup(self) -> None:
        """Pick the voice once at startup so the first reply starts faster."""
        if self._voice_id is not None:
            return
        engine = pyttsx3.init()
        voices = engine.getProperty("voices")
        if self._voice_index is None:
            self._voice_index = _pick_female_voice_index(voices)
        if 0 <= self._voice_index < len(voices):
            self._voice_id = voices[self._voice_index].id
        engine.stop()
        del engine

    def _build_engine(self):
        engine = pyttsx3.init()
        engine.setProperty("rate", self._rate)
        engine.setProperty("volume", self._volume)
        if self._voice_id:
            engine.setProperty("voice", self._voice_id)
        return engine

    def stop(self) -> None:
        from silva.tts_interrupt import stop_impl

        stop_impl(self)

    def speak(self, text: str) -> bool:
        from silva.tts_word_clips import speak_impl

        return speak_impl(self, text)

    def speak_interruptible(self, text: str, stop_event: threading.Event) -> bool:
        from silva.tts_interrupt import speak_interruptible_impl

        return speak_interruptible_impl(self, text, stop_event)

    def list_voices(self) -> list[str]:
        self.warmup()
        engine = self._build_engine()
        names = [voice.name for voice in engine.getProperty("voices")]
        engine.stop()
        del engine
        return names
