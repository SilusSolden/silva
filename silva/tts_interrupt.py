"""Reloadable interruptible pyttsx3 speak — sentence chunks so stop can land."""

from __future__ import annotations

import re
import threading

from silva.audio import ensure_audible
from silva.logger import log_error
from silva.tts_pronunciation import prepare_for_speech, prefetch_text_async
from silva.tts_word_clips import speak_parts

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def speech_chunks(text: str, *, max_len: int = 220) -> list[str]:
    parts = [part.strip() for part in _SENTENCE_SPLIT.split(text) if part.strip()]
    if not parts:
        return [text.strip()] if text.strip() else []
    chunks: list[str] = []
    buf = ""
    for part in parts:
        if buf and len(buf) + 1 + len(part) > max_len:
            chunks.append(buf)
            buf = part
        else:
            buf = f"{buf} {part}".strip() if buf else part
    if buf:
        chunks.append(buf)
    return chunks


def _speak_chunk(self, chunk: str, stop_event: threading.Event) -> bool:
    if stop_event.is_set():
        self.stop()
        return False
    finished = threading.Event()

    def run(piece: str = chunk) -> None:
        engine = self._build_engine()
        with self._engine_lock:
            self._active_engine = engine
        try:
            speak_parts(self, piece, engine, stop_event)
        except Exception as exc:
            log_error(f"Interruptible TTS failed: {exc}")
        finally:
            try:
                engine.stop()
            except Exception:
                pass
            with self._engine_lock:
                if self._active_engine is engine:
                    self._active_engine = None
            del engine
            finished.set()

    thread = threading.Thread(target=run, daemon=True, name="silva-tts-chunk")
    thread.start()
    while not finished.is_set():
        if stop_event.is_set():
            self.stop()
            thread.join(timeout=1.0)
            return False
        finished.wait(timeout=0.05)
    return True


def stop_impl(self) -> None:
    """Abort the current pyttsx3 engine from any thread."""
    with self._engine_lock:
        engine = self._active_engine
        if engine is None:
            return
        for method_name in ("stop", "endLoop"):
            method = getattr(engine, method_name, None)
            if callable(method):
                try:
                    method()
                except Exception:
                    pass


def speak_interruptible_impl(self, text: str, stop_event: threading.Event) -> bool:
    cleaned = re.sub(r"\s+", " ", text.replace("\u2014", ", ").replace("\u2013", ", ")).strip()
    if not cleaned:
        return True

    prefetch_text_async(cleaned)
    spoken = prepare_for_speech(cleaned)
    self.stop()
    self._wait_for_mic_handoff()
    ensure_audible()
    self.warmup()

    for chunk in speech_chunks(spoken):
        if not _speak_chunk(self, chunk, stop_event):
            return False
    return True
