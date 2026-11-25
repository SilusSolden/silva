"""Speech for camera auto-detect, test runs, and combo-cam warnings."""

from __future__ import annotations

import re

DETECT_PHRASES: tuple[str, ...] = (
    "auto detect camera",
    "auto detect the camera",
    "autodetect camera",
    "detect my camera",
    "detect the camera",
    "scan for a camera",
    "scan for camera",
    "i plugged in a camera",
    "i plugged in my camera",
    "new camera",
    "test the camera",
    "test my camera",
    "camera test",
    "camera test run",
    "run a camera test",
    "turn on camera",
    "turn on the camera",
    "turn on my camera",
    "use my camera",
    "use the camera",
)

_CANCEL_EXACT: frozenset[str] = frozenset(
    {
        "no",
        "nope",
        "nah",
        "skip",
        "not now",
        "dont",
        "cancel",
        "cancel the test",
        "cancel the camera",
        "cancel camera test",
        "dont use it",
        "dont use that camera",
        "dont save",
    }
)

_DURATION_30 = re.compile(
    r"\b(30|thirty)\s*(second|seconds|sec|secs)\b|\bhalf a minute\b|\bhalf minute\b",
    re.I,
)
_DURATION_60 = re.compile(
    r"\b(60|sixty)\s*(second|seconds|sec|secs)\b|\b(1|one|a)\s*(minute|min)\b",
    re.I,
)


def _normalize(text: str) -> str:
    text = text.strip().lower()
    text = text.replace("'", "")
    return re.sub(r"\s+", " ", text)


def is_camera_setup_command(text: str) -> bool:
    if not text or not text.strip():
        return False
    normalized = _normalize(text)
    if any(normalized == phrase or normalized.startswith(phrase + " ") for phrase in DETECT_PHRASES):
        return True
    if parse_test_duration(text) is not None and "camera" in normalized:
        return True
    return False


def parse_test_duration(text: str) -> int | None:
    if _DURATION_60.search(text or ""):
        return 60
    if _DURATION_30.search(text or ""):
        return 30
    return None


def is_camera_cancel_speech(text: str) -> bool:
    """Decline the camera offer. 'Stop' is not cancel — that only stops Silva talking."""
    normalized = _normalize(text)
    if not normalized:
        return False
    if normalized in _CANCEL_EXACT:
        return True
    return normalized.startswith("cancel the test") or normalized.startswith("dont use")
