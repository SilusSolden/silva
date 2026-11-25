"""Reject interruption speech that is not a complete sentence or command."""

from __future__ import annotations

import re
import time

from silva.config import load_config

_TERMINAL_RE = re.compile(r"[.!?][\"')\]]?$")
_PARTIAL_TAILS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "but",
        "because",
        "for",
        "from",
        "he",
        "her",
        "his",
        "how",
        "i",
        "if",
        "in",
        "is",
        "it",
        "me",
        "my",
        "of",
        "on",
        "or",
        "our",
        "she",
        "so",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "they",
        "this",
        "to",
        "up",
        "us",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
    }
)
_CLAUSE_RE = re.compile(
    r"\b(?:i|you|we|they|he|she|it)\s+(?:am|are|is|was|were|need|want|can|could|would|should|have|has|had|do|does|did|will)\b",
    re.I,
)


def enabled() -> bool:
    return bool(load_config().get("interruption_complete_sentence_enabled", True))


def _normalized(text: str) -> str:
    return " ".join(str(text or "").split()).strip()


def is_complete_sentence(text: str) -> bool:
    value = _normalized(text)
    if not value:
        return False
    if is_complete_command(value):
        return True
    words = re.findall(r"[\w']+", value.lower())
    if len(words) < 2:
        return False
    if words[-1] in _PARTIAL_TAILS:
        return False
    if _TERMINAL_RE.search(value):
        return True
    return len(words) >= 4 and bool(_CLAUSE_RE.search(value))


def should_handle_interruption_speech(text: str) -> bool:
    if not enabled():
        return True
    return is_complete_sentence(text)


def should_ignore_after_interruption(text: str, *, interrupted_at: float = 0.0, window_seconds: float = 6.0) -> bool:
    if not enabled() or not interrupted_at:
        return False
    if time.time() - interrupted_at > max(0.0, window_seconds):
        return False
    value = _normalized(text)
    if not value:
        return True
    if is_complete_command(value):
        return False
    return not is_complete_sentence(value)


def is_complete_command(text: str) -> bool:
    from silva.stt_quick_commands import is_complete_command as stt_is_complete_command

    return stt_is_complete_command(text)
