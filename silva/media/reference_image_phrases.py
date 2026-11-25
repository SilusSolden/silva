"""Spoken commands for the reference image library."""

from __future__ import annotations

import re

_OPEN_RE = re.compile(
    r"\b(?:open|show|view|browse|display)\s+(?:the\s+|my\s+|standalone\s+)?"
    r"(?:images?|pictures?|image\s+library|image\s+viewer|reference\s+library|reference\s+images?)\b",
    re.I,
)
_SCAN_RE = re.compile(
    r"\b(?:scan|check|look through|look at|import|ingest|store|save|grab)\b"
    r".{0,60}\b(?:downloads?|downloaded images?|images? from downloads|pictures? from downloads)\b",
    re.I,
)
_FIND_RE = re.compile(
    r"\b(?:find|look up|search|show|match|do you have|what images do you have)\b"
    r".{0,60}\b(?:reference|reference image|reference images|image reference|image references)\b",
    re.I,
)
_TRIGGER_RE = re.compile(
    r"\b(?:scan|check|look|through|at|import|ingest|store|save|grab|downloads?|downloaded|images?|"
    r"pictures?|from|find|up|search|show|match|do|you|have|what|reference|references|image|images)\b",
    re.I,
)
_FILLER_RE = re.compile(r"\b(?:the|a|an|my|for|about|on|in|please|silva)\b", re.I)


def match_reference_image_speech(text: str) -> str | None:
    stripped = str(text or "").strip()
    if not stripped:
        return None
    if _OPEN_RE.search(stripped):
        return "open"
    if _SCAN_RE.search(stripped):
        return "scan"
    if _FIND_RE.search(stripped):
        return "find"
    return None


def is_reference_image_speech(text: str) -> bool:
    return match_reference_image_speech(text) is not None


def reference_query(text: str) -> str:
    cleaned = _TRIGGER_RE.sub(" ", str(text or ""))
    cleaned = _FILLER_RE.sub(" ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()
