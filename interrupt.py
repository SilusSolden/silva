"""Interrupt phrase handling for Silva."""

from __future__ import annotations

import re

from silva.config import load_config

DEFAULT_INTERRUPT_PHRASES: tuple[str, ...] = (
    "stop",
    "stop it",
    "stop speaking",
    "silva stop",
    "silva stop talking",
    "please stop",
    "cancel",
    "interrupt",
    "quiet",
    "enough",
    "halt",
    "never mind",
    "nevermind",
    "stop talking",
    "be quiet",
)


def _normalize(text: str) -> str:
    text = text.strip().lower()
    text = text.replace("'", "")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def get_interrupt_phrases() -> tuple[str, ...]:
    config = load_config()
    custom = config.get("interrupt_phrases")
    if isinstance(custom, list) and custom:
        return tuple(str(p) for p in custom)
    return DEFAULT_INTERRUPT_PHRASES


def get_interrupt_min_chars() -> int:
    value = int(load_config().get("interrupt_min_chars", 160))
    # Older defaults blocked stop on most spoken replies.
    if value in {400, 550}:
        return 160
    return max(80, value)


def estimated_display_lines(text: str, *, chars_per_line: int | None = None) -> int:
    width = chars_per_line or int(load_config().get("interrupt_bar_chars_per_line", 52))
    lines = 0
    for paragraph in text.replace("\r", "").split("\n"):
        chunk = paragraph.strip()
        if not chunk:
            continue
        lines += max(1, (len(chunk) + width - 1) // width)
    return lines


def should_show_interrupt_bar(text: str) -> bool:
    if not bool(load_config().get("interrupt_bar_enabled", True)):
        return False
    min_lines = int(load_config().get("interrupt_bar_min_lines", 5))
    min_chars = int(load_config().get("interrupt_bar_min_chars", 550))
    stripped = text.strip()
    if len(stripped) < min_chars:
        return False
    return estimated_display_lines(stripped) >= min_lines


def is_interrupt_command(text: str) -> bool:
    normalized = _normalize(text)
    if not normalized:
        return False
    words = normalized.split()
    for phrase in get_interrupt_phrases():
        phrase_norm = _normalize(phrase)
        if not phrase_norm:
            continue
        if normalized == phrase_norm:
            return True
        phrase_words = phrase_norm.split()
        if len(phrase_words) == 1:
            if phrase_words[0] in words:
                return True
            continue
        width = len(phrase_words)
        for index in range(len(words) - width + 1):
            if words[index : index + width] == phrase_words:
                return True
    return False
