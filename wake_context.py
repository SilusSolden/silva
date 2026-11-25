"""Smart wake while asleep — more phrases, avoid interrupting calls/conversations."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from silva.config import load_config
from silva.wake import _normalize, get_wake_phrases


WAKE_NEAR_SILVA_RE = re.compile(
    r"\b(silva|silver|sylvia)\b.{0,24}\b(wake|wakeup|awake|up)\b|\b(wake|wakeup|awake)\b.{0,24}\b(silva|silver|sylvia)\b",
    re.I,
)

WAKE_CORRECTION_RE = re.compile(
    r"\b(?:i said|i meant|i meant to say)\b.{0,40}\bwake(?: up|up)?\b",
    re.I,
)

WAKE_SELF_RE = re.compile(
    r"\b(?:wake yourself up|wake up yourself|wake yourself|wake up)\b",
    re.I,
)

EXACT_DIRECT_WAKE_PHRASES = (
    "wake yourself up",
    "wake up yourself",
    "wake yourself",
    "wake up silva",
    "silva wake up",
)

BACKGROUND_HINTS = (
    "tell him",
    "tell her",
    "tell them",
    "on the phone",
    "on a call",
    "video call",
    "facetime",
    "discord call",
    "what do you think",
    "did you hear",
    "hold on",
    "one second",
    "give me a minute",
)


@dataclass(frozen=True)
class WakeDecision:
    action: str  # wake | pending | ignore
    silent: bool = False
    reason: str = ""


def _smart_wake_enabled() -> bool:
    return bool(load_config().get("wake_smart_detection_enabled", True))


def _pending_seconds() -> float:
    return float(load_config().get("wake_pending_seconds", 3.0))


def _silent_when_busy() -> bool:
    return bool(load_config().get("wake_silent_when_busy", True))


STT_MISHEARING_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (r"\bsilver\b", "silva"),
    (r"\bsylvia\b", "silva"),
    (r"\bsalvador\b", "silva"),
    (r"\bsolver\b", "silva"),
    (r"\bbreak yourself up\b", "wake yourself up"),
    (r"\bbreak up yourself\b", "wake up yourself"),
    (r"\bbreak yourself\b", "wake yourself"),
)


def _normalize_stt_mishearings(text: str) -> str:
    normalized = _normalize(text)
    for pattern, replacement in STT_MISHEARING_REPLACEMENTS:
        normalized = re.sub(pattern, replacement, normalized)
    return normalized


def is_direct_wake_command(text: str) -> bool:
    raw = _normalize(text)
    if raw in EXACT_DIRECT_WAKE_PHRASES:
        return True
    normalized = _normalize_stt_mishearings(text)
    if not normalized:
        return False
    for phrase in get_wake_phrases():
        phrase_norm = _normalize(phrase)
        if normalized == phrase_norm:
            return True
        if "silva" in phrase_norm and phrase_norm in normalized:
            return True
    if WAKE_NEAR_SILVA_RE.search(normalized):
        return True
    if WAKE_CORRECTION_RE.search(normalized):
        return True
    extra = (
        "silva please wake up",
        "please wake up silva",
        "silva im back",
        "silva i'm back",
        "silva you there",
        "silva are you there",
        "silva come back",
        "silva wake up now",
        "hey silva wake up",
        "okay silva wake up",
        "ok silva wake up",
        "yo silva wake up",
        "silva activate",
        "silva listen",
    )
    for phrase in extra:
        if _normalize(phrase) in normalized or normalized == _normalize(phrase):
            return True
    return _relaxed_silva_wake(normalized)


def _is_named_small_talk(normalized: str) -> bool:
    """Chat directed at Silva is not a wake command."""
    small_talk = (
        "how are you",
        "how you doing",
        "how are ya",
        "hows it going",
        "how is it going",
        "how have you been",
        "whats up",
        "what is up",
        "whats going on",
        "what is going on",
        "thank you",
        "thanks",
        "appreciate it",
        "good job",
        "nice job",
    )
    return any(phrase in normalized for phrase in small_talk)


_WAKE_CUE_RE = re.compile(
    r"\b(wake|wakeup|awake|listen|hello|hey|yo|okay|ok|come back|"
    r"you up|are you there|you there|im back|i m back|i am back)\b"
)


def _relaxed_silva_wake(normalized: str) -> bool:
    """Catch natural Silva address phrases that STT may phrase differently."""
    normalized = _normalize_stt_mishearings(normalized)
    if "silva" not in normalized:
        return False
    if _is_named_small_talk(normalized):
        return False
    return bool(_WAKE_CUE_RE.search(normalized))


def is_wake_candidate(text: str) -> bool:
    if is_direct_wake_command(text):
        return True
    normalized = _normalize_stt_mishearings(text)
    if WAKE_SELF_RE.search(normalized):
        return True
    if "silva" not in normalized:
        return False
    wake_words = ("wake", "wakeup", "awake", "back", "there", "listen", "hello silva", "hey silva")
    return any(word in normalized for word in wake_words)


def looks_like_background_conversation(text: str) -> bool:
    normalized = _normalize(text)
    if not normalized:
        return False
    if is_direct_wake_command(text):
        return False
    words = normalized.split()
    if len(words) >= 12 and "silva" not in normalized.split()[:3]:
        return True
    if any(hint in normalized for hint in BACKGROUND_HINTS):
        return True
    if normalized.count("?") >= 2 and "silva" not in normalized[:20]:
        return True
    return False


def evaluate_wake(text: str) -> WakeDecision:
    if not text or not text.strip():
        return WakeDecision("ignore", reason="empty")

    normalized = _normalize(text)

    if is_direct_wake_command(text):
        if _smart_wake_enabled() and looks_like_background_conversation(text):
            return WakeDecision("pending", silent=True, reason="direct_but_busy")
        return WakeDecision("wake", silent=False, reason="direct_wake")

    if _relaxed_silva_wake(normalized):
        if _smart_wake_enabled() and looks_like_background_conversation(text):
            return WakeDecision("pending", silent=True, reason="relaxed_but_busy")
        return WakeDecision("wake", silent=False, reason="relaxed_wake")

    if not _smart_wake_enabled():
        return WakeDecision("ignore", reason="not_direct")

    if is_wake_candidate(text):
        if looks_like_background_conversation(text):
            return WakeDecision("pending", silent=True, reason="candidate_busy")
        return WakeDecision("pending", silent=False, reason="candidate")

    return WakeDecision("ignore", reason="no_wake_intent")


def wait_for_clear_moment(*, poll_seconds: float | None = None) -> bool:
    """Pause, optionally peek camera, return True when ok to wake."""
    delay = poll_seconds if poll_seconds is not None else _pending_seconds()
    time.sleep(max(0.5, delay))
    if not bool(load_config().get("wake_use_camera_peek", False)):
        return True
    try:
        from silva.media.silent_observer import peek_user_presence

        presence = peek_user_presence()
        if presence == "clear":
            return True
        if presence == "absent":
            return True
    except Exception:
        pass
    return True


def expanded_wake_phrases() -> tuple[str, ...]:
    base = get_wake_phrases()
    extras = (
        "silva please wake up",
        "please wake up silva",
        "hey silva wake up",
        "silva im back",
        "silva you there",
        "silva are you there",
        "silva come back",
        "silva wake up now",
        "yo silva",
        "okay silva",
        "ok silva wake up",
    )
    merged = list(base)
    for item in extras:
        if item not in merged:
            merged.append(item)
    return tuple(merged)
