"""Wake and sleep phrase handling for Silva."""

from __future__ import annotations

import re

from silva.config import load_config

DEFAULT_WAKE_PHRASES: tuple[str, ...] = (
    "wake up silva",
    "silva wake up",
    "hey silva",
    "wake silva",
    "silva wake",
    "wake up",
    "im back silva",
    "i'm back silva",
    "silva please wake up",
    "please wake up silva",
    "hey silva wake up",
    "silva im back",
    "silva i'm back",
    "silva you there",
    "silva are you there",
    "silva come back",
    "silva wake up now",
    "yo silva",
    "okay silva",
    "ok silva wake up",
)

DEFAULT_SLEEP_PHRASES: tuple[str, ...] = (
    "go to sleep",
    "go to sleep silva",
    "go back to sleep",
    "going to sleep",
    "going back to sleep",
    "back to sleep",
    "silva sleep",
    "sleep mode",
    "sleep silva",
    "sleep now",
    "time to sleep",
    "silva go to sleep",
    "silva go back to sleep",
    "put silva to sleep",
    "put to sleep",
    "you can sleep",
    "you can go to sleep",
    "go sleep",
    "all right then go back to sleep",
    "all right now go back to sleep",
    "alright then go back to sleep",
    "alright now go back to sleep",
    "okay then go back to sleep",
    "okay now go back to sleep",
    "ok then go back to sleep",
    "ok now go back to sleep",
)


def _normalize(text: str) -> str:
    text = text.strip().lower()
    text = text.replace("'", "")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def get_wake_phrases() -> tuple[str, ...]:
    config = load_config()
    custom = config.get("wake_phrases")
    if isinstance(custom, list) and custom:
        return tuple(str(p) for p in custom)
    return DEFAULT_WAKE_PHRASES


def get_sleep_phrases() -> tuple[str, ...]:
    config = load_config()
    custom = config.get("sleep_phrases")
    if isinstance(custom, list) and custom:
        return tuple(str(p) for p in custom)
    return DEFAULT_SLEEP_PHRASES


def is_wake_command(text: str) -> bool:
    """Wake phrases while Silva is asleep — includes natural Silva + wake wording."""
    from silva.wake_context import is_direct_wake_command

    return is_direct_wake_command(text)


_SLEEP_FILLER_RE = re.compile(
    r"^(?:(?:all right|alright|okay|ok|please|now|just|then|"
    r"none of them|none of those|none of you|no one|nobody)(?: then| now)?\s+)+",
    re.I,
)

_SLEEP_DIRECT_RE = re.compile(
    r"^(?:go (?:back )?to sleep|going (?:back )?to sleep|back to sleep|"
    r"silva sleep|sleep mode|sleep silva|sleep now|time to sleep|"
    r"put silva to sleep|put to sleep|you can (?:go to )?sleep|go sleep)\b",
    re.I,
)

_SLEEP_QUESTION_RE = re.compile(
    r"^(?:what|how|can|could|would|should|do|does|did|is|are|tell|explain|describe)\b",
    re.I,
)
_SLEEP_QUESTION_COMMAND_RE = re.compile(
    r"^(?:are|can|could|would|will) you (?:please )?"
    r"(?:going|go) (?:back )?to sleep\b"
    r".{0,120}\b(?:so|because|cuz|cause|since)\b",
    re.I,
)


def is_sleep_command(text: str) -> bool:
    normalized_raw = _normalize(text)
    normalized = _SLEEP_FILLER_RE.sub("", normalized_raw).strip()
    if not normalized:
        return False
    if re.search(
        r"\bwhy (?:are|is|won t|wont) you (?:not )?(?:going|go|going to) to sleep\b",
        normalized,
    ):
        return True
    if _SLEEP_DIRECT_RE.match(normalized):
        return True
    if _SLEEP_QUESTION_COMMAND_RE.match(normalized_raw):
        return True
    try:
        from silva.commands.help_phrases import should_yield_to_feature_help

        if should_yield_to_feature_help(text):
            return False
    except Exception:
        pass
    if _SLEEP_QUESTION_RE.match(normalized_raw):
        return False
    for phrase in get_sleep_phrases():
        phrase_norm = _normalize(phrase)
        if normalized == phrase_norm or phrase_norm in normalized:
            return True
    return False
