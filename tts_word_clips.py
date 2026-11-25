"""Speak with pyttsx3, using saved pronunciation recordings only as references."""

from __future__ import annotations

import re
import threading

from silva.audio import ensure_audible
from silva.logger import log_error
from silva.tts_pronunciation import prepare_for_speech, prefetch_text_async
from silva.users.word_pronunciations import active_word_variants, normalize_spoken, normalize_word

_TOKEN_RE = re.compile(r"\b([^\W\d_][\w']*)\b", re.UNICODE)


def _variants_by_word() -> dict[str, list]:
    groups: dict[str, list] = {}
    for row in active_word_variants():
        word = normalize_word(str(getattr(row, "word", "") or ""))
        if word:
            groups.setdefault(word, []).append(row)
    return groups


def _timestamp(row) -> str:
    digits = "".join(char for char in str(getattr(row, "updated_at", "") or "") if char.isdigit())
    return digits[:14]


def _cue_in_text(cue: str, word: str, text: str) -> bool:
    key = normalize_word(cue)
    if not key or key == word:
        return False
    return f" {key} " in f" {normalize_word(text)} "


def _choose_variant(word: str, variants: list, text: str):
    ranked = []
    for row in variants:
        context = str(getattr(row, "context", "") or "")
        sound = str(getattr(row, "spoken_as", "") or "")
        if _cue_in_text(context, word, text):
            score = 3
        elif _cue_in_text(sound, word, text):
            score = 2
        else:
            score = 0
        if getattr(row, "active", False):
            score += 1
        ranked.append((score, _timestamp(row), row))
    if not ranked:
        return None
    return max(ranked, key=lambda item: (item[0], item[1]))[2]


def _trained_spans(text: str, groups: dict[str, list]) -> list[tuple[str, int, int]]:
    matches = list(_TOKEN_RE.finditer(text))
    if not matches or not groups:
        return []
    normalized = [normalize_word(match.group(0)) for match in matches]
    keys = sorted(groups, key=lambda key: (-len(key.split()), -len(key)))
    spans: list[tuple[str, int, int]] = []
    index = 0
    while index < len(matches):
        found = None
        for key in keys:
            parts = key.split()
            width = len(parts)
            if index + width > len(matches):
                continue
            if normalized[index : index + width] == parts:
                found = (key, matches[index].start(), matches[index + width - 1].end(), width)
                break
        if found is None:
            index += 1
            continue
        key, start, end, width = found
        spans.append((key, start, end))
        index += width
    return spans


def build_speech_parts(text: str) -> list[tuple[str, str, str]]:
    """Return ordered (kind, value, fallback) pieces for spoken output."""
    groups = _variants_by_word()
    if not groups:
        return [("say", text, "")]

    spans = _trained_spans(text, groups)
    if not spans:
        return [("say", text, "")]

    parts: list[tuple[str, str, str]] = []
    cursor = 0
    for word, start, end in spans:
        before = text[cursor:start]
        if before:
            parts.append(("say", before, ""))
        chosen = _choose_variant(word, groups[word], text)
        learned = normalize_spoken(str(getattr(chosen, "spoken_as", "") or "")) if chosen else ""
        parts.append(("learned", learned or word, text[start:end]))
        cursor = end
    trailing = text[cursor:]
    if trailing:
        parts.append(("say", trailing, ""))

    merged: list[tuple[str, str, str]] = []
    for kind, value, fallback in parts:
        if kind == "say" and merged and merged[-1][0] == "say":
            merged[-1] = ("say", merged[-1][1] + value, "")
        elif value:
            merged.append((kind, value, fallback))
    return merged or [("say", text, "")]


def speak_parts(self, text: str, engine, stop_event: threading.Event | None = None) -> bool:
    if stop_event is not None and stop_event.is_set():
        return False
    spoken = "".join(value or fallback for _kind, value, fallback in build_speech_parts(text)).strip()
    if not spoken:
        return True
    engine.say(spoken)
    engine.runAndWait()
    return True


def speak_impl(self, text: str) -> bool:
    cleaned = re.sub(r"\s+", " ", (text or "").replace("\u2014", ", ").replace("\u2013", ", ")).strip()
    if not cleaned:
        return True

    prefetch_text_async(cleaned)
    spoken = prepare_for_speech(cleaned)
    self.stop()
    self._wait_for_mic_handoff()
    ensure_audible()
    self.warmup()

    engine = self._build_engine()
    try:
        with self._engine_lock:
            self._active_engine = engine
        speak_parts(self, spoken, engine)
        engine.stop()
    except Exception as exc:
        try:
            engine.stop()
        except Exception:
            pass
        log_error(f"TTS speak failed: {exc}")
        return False
    finally:
        with self._engine_lock:
            if self._active_engine is engine:
                self._active_engine = None
        del engine
    return True
