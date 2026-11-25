"""Recognize thinking fillers without rewriting them into commands."""

from __future__ import annotations

import re

_FILLERS = frozenset({"uh", "uhh", "uhm", "umm", "um", "erm", "er", "hmm", "hm"})
_UNCERTAIN_TAILS = _FILLERS | {"on"}


def words(text: str) -> list[str]:
    return re.findall(r"[a-z]+", str(text or "").lower())


def is_filler_only(text: str) -> bool:
    tokens = words(text)
    return bool(tokens) and all(token in _FILLERS for token in tokens)


def is_trailing_uncertainty(text: str) -> bool:
    tokens = words(text)
    return bool(tokens) and tokens[-1] in _UNCERTAIN_TAILS


def should_ignore_movement_uncertainty(text: str, *, receding_audio: bool) -> bool:
    return bool(receding_audio) and is_trailing_uncertainty(text)
