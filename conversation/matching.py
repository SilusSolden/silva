"""Phrase matching helpers for natural conversation routing."""

from __future__ import annotations

import re


def normalize(text: str) -> str:
    text = text.strip().lower()
    text = text.replace("'", "")
    return re.sub(r"\s+", " ", text)


def contains_phrase(text: str, phrase: str) -> bool:
    """Match a phrase on word boundaries so 'yo' does not match inside 'you'."""
    phrase = phrase.strip().lower()
    if not phrase:
        return False
    pattern = r"\b" + re.escape(phrase).replace(r"\ ", r"\s+") + r"\b"
    return bool(re.search(pattern, text))


def contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(contains_phrase(text, phrase) for phrase in phrases)


def dedupe_repeated_phrase(text: str) -> str:
    """Remove duplicated halves from STT merges (e.g. 'how are you how are you')."""
    normalized = normalize(text)
    words = normalized.split()
    if len(words) < 2:
        return text.strip()

    half = len(words) // 2
    if half >= 1 and words[:half] == words[half : half + half]:
        return " ".join(words[:half])

    for seg_len in range(min(8, len(words) // 2), 2, -1):
        for later in range(1, len(words) - seg_len + 1):
            segment = words[later : later + seg_len]
            for earlier in range(later):
                if words[earlier : earlier + seg_len] == segment:
                    return " ".join(words[: earlier + seg_len])

    return text.strip()
