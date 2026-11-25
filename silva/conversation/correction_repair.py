"""Repair misheard follow-up corrections and redispatch the intended question."""

from __future__ import annotations

import re
import time
from typing import Any

_CANDIDATES: dict[str, dict[str, Any]] = {}
_TTL_SECONDS = 180.0
_REPEAT_WAIT_SECONDS = 30.0

_GENERIC_CORRECTION_RE = re.compile(
    r"^(?:no[,]?\s+)?(?:that(?:'s| is)?\s+)?(?:not\s+what\s+i\s+(?:said|meant|mean|asked(?:\s+you)?|requested)|wrong|"
    r"nope[,]?\s+not\s+that|that(?:'s| is)?\s+not\s+it|"
    r"none\s+of\s+that(?:\s+is)?\s+what\s+i\s+asked)\b|"
    r"^that(?:'s| is)?\s+not\s+what\s+i\s+(?:asked|asked you|said|meant|mean|requested)\b|"
    r"^(?:again\s+)?i\s+never\s+said\s+(?:that|it|any\s+of\s+that)\b|"
    r"\b(?:not|wasn't|wasnt|isn't|isnt|was\s+not|is\s+not)\s+a\s+"
    r"(?:math|other)\s+(?:problem|question)\b|"
    r"\bnot\s+what\s+i\s+(?:said|meant|mean|asked(?:\s+you)?|requested)\b|"
    r"\bnot\s+the\s+way\s+i\s+want\b|"
    r"\bwhy\s+(?:are|is)\s+(?:you|it)\s+(?:not\s+)?.*\bthe\s+way\s+i\s+want\b",
    re.I,
)

_CORRECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"^(?:no|nope|actually|sorry)?[,]?\s*i\s+never\s+said\s+.*?\s*,?\s*"
        r"i\s+(?:said|meant|mean)\s+(.+)$",
        re.I,
    ),
    re.compile(
        r"^(?:no|nope|actually|sorry)?[,]?\s*i\s+(?:didn'?t|did\s+not)\s+say\s+.*?\s+"
        r"i\s+(?:said|meant|mean)\s+(.+)$",
        re.I,
    ),
    re.compile(
        r"^(?:that(?:'s|\s+is)?\s+)?not\s+what\s+i\s+(?:said|meant|mean)\s+"
        r"i\s+(?:said|meant|mean)\s+(.+)$",
        re.I,
    ),
    re.compile(r"^(?:no|nope|actually|sorry)?[,]?\s*i\s+(?:said|meant|mean)\s+(.+)$", re.I),
    re.compile(r"^what i\s+(?:said|meant|mean)\s+was\s+(.+)$", re.I),
    re.compile(
        r"^what i\s+(?:was\s+)?(?:trying|meaning|meant|mean|intended)\s+to\s+(?:say|ask)\s+"
        r"(?:is\s+|was\s+)?(.+)$",
        re.I,
    ),
    re.compile(r"^i\s+said\s+(.+?)\s+not\s+(.+)$", re.I),
    re.compile(r"^not\s+(.+?)\s*,?\s*i\s+(?:said|meant|mean)\s+(.+)$", re.I),
)


def _key(user_id: str | None) -> str:
    return str(user_id or "guest")


def _assistant_key(assistant) -> str:
    getter = getattr(assistant, "_user_id", None)
    return _key(getter() if callable(getter) else "guest")


def _clean(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+not\s+what\s+i\s+(?:said|meant|mean).*$", "", text, flags=re.I)
    text = re.sub(r"\s+instead.*$", "", text, flags=re.I)
    if "not working correctly" not in text.lower():
        text = re.sub(r"\s+not\s+.+$", "", text, flags=re.I)
    text = re.sub(r"\b(fillers?|pillows?)\s+on$", r"\1", text, flags=re.I)
    return re.sub(r"[.!?,;:]+$", "", text).strip()


def parse_correction(text: str) -> str | None:
    value = str(text or "").strip()
    if not value:
        return None
    for index, pattern in enumerate(_CORRECTION_PATTERNS):
        match = pattern.match(value)
        if not match:
            continue
        group = 2 if index == len(_CORRECTION_PATTERNS) - 1 and match.lastindex == 2 else 1
        corrected = _clean(match.group(group))
        if not corrected or _is_discardable_correction(corrected):
            continue
        return corrected
    return None


def _has_sleep_intent(text: str) -> bool:
    from silva.wake import is_sleep_command

    value = str(text or "").strip()
    return is_sleep_command(value) or bool(
        re.search(r"\bgo\s+(?:back\s+)?to\s+sleep\b", value, re.I)
    )


def is_generic_correction(text: str) -> bool:
    value = str(text or "").strip()
    if not value or _has_sleep_intent(value):
        return False
    return bool(_GENERIC_CORRECTION_RE.search(value))


def note_feature_detail_clarification(assistant, text: str, reply: str) -> None:
    from silva.commands.help_phrases import _WHICH_FEATURE

    if reply != _WHICH_FEATURE:
        return
    getter = getattr(assistant, "_user_id", None)
    user_id = getter() if callable(getter) else "guest"
    _CANDIDATES[_key(user_id)] = {
        "kind": "feature_detail",
        "text": str(text or "").strip(),
        "created_at": time.time(),
    }


_REPAIRABLE_QUESTION_RE = re.compile(
    r"\b(?:what|why|how|who|when|where|tell me|explain|describe|details?|mean|means)\b",
    re.I,
)

_UNUSABLE_CORRECTION_RE = re.compile(
    r"^(?:(?:you|your|are|is|so|such|dumb|stupid|freaking|fucking|fricking|damn|"
    r"goddamn|bloody|little|ass| mother)\s+)*"
    r"(?:bitch|bitches|asshole|assholes|dick|cunt|bastard|shit|fuck|fucker|damn)\b"
    r"[\s.!?]*$",
    re.I,
)

_CORRUPTED_REPEAT_RE = re.compile(
    r"\b(?:when\s+i\s+said\s+was|i\s+said\s+was|or\s+piss\s+me\s+off|"
    r"never\s+said\s+that|not\s+what\s+i\s+said|what\s+i\s+actually\s+said|"
    r"recorded\s+it|it\s+took\s+what\s+i\s+said)\b",
    re.I,
)

_CORRECTION_FILLERS = frozenset(
    {
        "again",
        "anything",
        "before",
        "by the way",
        "here",
        "it",
        "now",
        "something",
        "that",
        "that again",
        "there",
        "this",
        "them",
        "what",
        "whatever",
        "you",
        "your",
    }
)


def _is_discardable_correction(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    if _normalize_correction(text) in _CORRECTION_FILLERS:
        return True
    return bool(_UNUSABLE_CORRECTION_RE.search(text) or _CORRUPTED_REPEAT_RE.search(text))


def _normalize_correction(value: str) -> str:
    text = str(value or "").strip().lower().replace("'", "")
    return re.sub(r"[^a-z0-9\s]", " ", text).strip()


def note_repairable_question(assistant, text: str) -> None:
    value = str(text or "").strip()
    if not value or len(value) > 240:
        return
    if parse_correction(value) or not _REPAIRABLE_QUESTION_RE.search(value):
        return
    getter = getattr(assistant, "_user_id", None)
    user_id = getter() if callable(getter) else "guest"
    key = _key(user_id)
    existing = _CANDIDATES.get(key)
    if existing is not None and time.time() - float(existing.get("created_at", 0.0)) <= _TTL_SECONDS:
        return
    _CANDIDATES[key] = {
        "kind": "question",
        "text": value,
        "created_at": time.time(),
    }


def note_pronunciation_question(assistant, text: str, word: str) -> None:
    value = str(text or "").strip()
    target = str(word or "").strip()
    if not value or not target:
        return
    getter = getattr(assistant, "_user_id", None)
    user_id = getter() if callable(getter) else "guest"
    _CANDIDATES[_key(user_id)] = {
        "kind": "pronunciation",
        "word": target,
        "text": value,
        "created_at": time.time(),
    }


def clear_candidate(user_id: str | None) -> None:
    _CANDIDATES.pop(_key(user_id), None)


def candidate_for(user_id: str | None) -> dict[str, Any] | None:
    key = _key(user_id)
    candidate = _CANDIDATES.get(key)
    if candidate is None:
        return None
    if time.time() - float(candidate.get("created_at", 0.0)) > _TTL_SECONDS:
        _CANDIDATES.pop(key, None)
        return None
    return dict(candidate)


def has_candidate_for(user_id: str | None) -> bool:
    return candidate_for(user_id) is not None


def has_candidate() -> bool:
    return any(has_candidate_for(user_id) for user_id in list(_CANDIDATES))


def is_correction_repair_command(text: str) -> bool:
    if not has_candidate() or _has_sleep_intent(text):
        return False
    return parse_correction(text) is not None or is_generic_correction(text)


def _repaired_text(candidate: dict[str, Any], correction: str) -> str:
    if candidate.get("kind") == "pronunciation":
        return f"how do you say {correction}"
    if candidate.get("kind") == "feature_detail":
        return f"can you tell me in detail what {correction} mean"
    if candidate.get("kind") == "question":
        if re.match(
            r"^(?:can you|could you|would you|will you|please|tell me|what|why|how|who|when|where|explain|describe|give me)",
            correction,
            re.I,
        ):
            return correction
        return f"can you tell me what {correction} are"
    return correction


def _set_repeat_wait(candidate: dict[str, Any], key: str, text: str) -> None:
    candidate["awaiting_exact_repeat"] = True
    candidate["repeat_wait_since"] = time.time()
    candidate["rejected_text"] = str(text or "").strip()
    _CANDIDATES[key] = candidate


def is_awaiting_exact_repeat(assistant) -> bool:
    candidate = _CANDIDATES.get(_assistant_key(assistant))
    if not candidate or not candidate.get("awaiting_exact_repeat"):
        return False
    if time.time() - float(candidate.get("repeat_wait_since", 0.0)) > _REPEAT_WAIT_SECONDS:
        candidate.pop("awaiting_exact_repeat", None)
        return False
    return True


def handle_exact_repeat(assistant, text: str) -> bool:
    """Accept a silent repeat as corrected words; ignore corrupted follow-ups."""
    if getattr(assistant, "_correction_repair_active", False) is True:
        return False
    if not is_awaiting_exact_repeat(assistant):
        return False
    value = str(text or "").strip()
    if not value or _CORRUPTED_REPEAT_RE.search(value):
        return True
    if len(value.split()) < 2:
        return True
    key = _assistant_key(assistant)
    candidate = _CANDIDATES.get(key)
    if not candidate:
        return False
    correction = _clean(value)
    if not correction:
        return True
    repaired = _repaired_text(candidate, correction)
    from silva.logger import log_info

    log_info(f"Exact repeat accepted: {value[:120]} -> {repaired[:120]}")
    _CANDIDATES.pop(key, None)
    assistant._correction_repair_active = True
    try:
        return bool(assistant._handle_input(repaired, _phrase_retry=True))
    finally:
        assistant._correction_repair_active = False


def handle_correction_repair(assistant, text: str) -> bool:
    if getattr(assistant, "_correction_repair_active", False) is True:
        return False
    if _has_sleep_intent(text):
        return False
    key = _assistant_key(assistant)
    candidate = _CANDIDATES.get(key)
    if candidate is None:
        return False
    if time.time() - float(candidate.get("created_at", 0.0)) > _TTL_SECONDS:
        _CANDIDATES.pop(key, None)
        return False
    correction = parse_correction(text)
    if not correction:
        if is_generic_correction(text):
            _set_repeat_wait(candidate, key, text)
            from silva.logger import log_info

            log_info(f"Silent repeat wait after correction: {text[:120]}")
            return True
        return False
    if _UNUSABLE_CORRECTION_RE.search(correction) or _CORRUPTED_REPEAT_RE.search(correction):
        _set_repeat_wait(candidate, key, text)
        from silva.logger import log_info

        log_info(f"Silent repeat wait for unusable correction: {text[:120]}")
        return True

    repaired = _repaired_text(candidate, correction)
    from silva.logger import log_info

    log_info(f"Correction repair: {text[:120]} -> {repaired[:120]}")
    _CANDIDATES.pop(key, None)
    assistant._correction_repair_active = True
    try:
        return bool(assistant._handle_input(repaired, _phrase_retry=True))
    finally:
        assistant._correction_repair_active = False


def reset_state_for_tests() -> None:
    _CANDIDATES.clear()
