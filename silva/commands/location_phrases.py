"""Spoken ways to ask where Silva thinks you are — not a crafting-guide status."""

from __future__ import annotations

import re

from silva.commands.help_phrases import should_yield_to_feature_help

_PUNCT_RE = re.compile(r"[^\w\s]")
_SPACE_RE = re.compile(r"\s+")

_WAKE_PREFIXES = (
    "hey silva ",
    "ok silva ",
    "okay silva ",
    "yo silva ",
    "silva ",
    "hey silver ",
    "silver ",
    "please ",
    "hey ",
    "can you tell me ",
    "could you tell me ",
    "tell me ",
)

LOCATION_EXACT = frozenset(
    {
        "where am i",
        "where am i at",
        "where am i now",
        "where am i right now",
        "where am i located",
        "where are we",
        "where are we at",
        "where are we now",
        "where are we right now",
        "whats my location",
        "what is my location",
        "whats my city",
        "what is my city",
        "what city am i in",
        "what city are we in",
        "what city is this",
        "where is this",
        "my location",
        "current location",
        "current city",
    }
)

_GUIDE_STATUS = frozenset(
    {
        "where was i",
        "what step am i on",
        "what step am i at",
    }
)


def _fold(text: str) -> str:
    normalized = (text or "").strip().lower().replace("'", "")
    normalized = _PUNCT_RE.sub(" ", normalized)
    normalized = _SPACE_RE.sub(" ", normalized).strip()
    changed = True
    while changed and normalized:
        changed = False
        for prefix in _WAKE_PREFIXES:
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix) :].strip()
                changed = True
                break
    return normalized


def is_location_command(text: str) -> bool:
    if should_yield_to_feature_help(text):
        return False
    normalized = _fold(text)
    if not normalized or normalized in _GUIDE_STATUS:
        return False
    return normalized in LOCATION_EXACT
