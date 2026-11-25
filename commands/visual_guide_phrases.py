"""Phrase detection for screen capture and visual guides."""

from __future__ import annotations

import re
from dataclasses import dataclass

VIDEO_RE = re.compile(
    r"\b(record|video|clip|capture)\b.{0,30}\b(screen|game|this|video)\b|"
    r"\b(screen|game)\b.{0,20}\b(record|video)\b",
    re.I,
)

SCREENSHOT_RE = re.compile(
    r"\b(screenshot|screen shot|capture this|snap this|picture of this)\b",
    re.I,
)

WHAT_IS_RE = re.compile(
    r"\b(what is this|what's this|what am i looking at|what is that|identify this)\b",
    re.I,
)

WHAT_MEANS_RE = re.compile(
    r"\b("
    r"what does this mean|what does that mean|what do this mean|what do that mean|"
    r"can you tell me what this means|can you tell me what that means|"
    r"tell me what this means|tell me what that means|"
    r"what this means|what that means|explain this|explain that|"
    r"can you explain this|what is this mean"
    r")\b",
    re.I,
)

HOW_WORKS_RE = re.compile(
    r"\b(how does this work|how do i (make|get|craft|build|use) this|how to (make|get|craft|build|use))\b",
    re.I,
)

STEP_BY_STEP_RE = re.compile(
    r"\b(step by step|give me steps|walk me through|guide me through)\b",
    re.I,
)

STEP_DONE_RE = re.compile(
    r"\b(i'?m done|done with that|finished that|next step|step done|completed that)\b",
    re.I,
)

RESTART_STEP_RE = re.compile(
    r"\b(restart step|start over|reset steps|redo step)\b",
    re.I,
)


@dataclass
class VisualGuideSpeech:
    kind: str
    query: str = ""
    want_video: bool = False


def match_visual_guide_speech(text: str) -> VisualGuideSpeech | None:
    stripped = text.strip()
    if not stripped:
        return None
    from silva.commands.help_phrases import is_capability_ask, is_feature_detail_ask, is_help_request

    if is_help_request(text) or is_feature_detail_ask(text) or is_capability_ask(text):
        return None
    lower = stripped.lower()
    want_video = bool(VIDEO_RE.search(lower))
    query = stripped

    if STEP_DONE_RE.search(lower):
        return VisualGuideSpeech(kind="step_done")
    if RESTART_STEP_RE.search(lower):
        return VisualGuideSpeech(kind="restart_steps")
    if STEP_BY_STEP_RE.search(lower):
        return VisualGuideSpeech(kind="step_by_step")

    if WHAT_IS_RE.search(lower):
        return VisualGuideSpeech(kind="analyze", query=query, want_video=want_video)
    if WHAT_MEANS_RE.search(lower):
        return VisualGuideSpeech(kind="analyze", query=query, want_video=want_video)
    if HOW_WORKS_RE.search(lower):
        return VisualGuideSpeech(kind="analyze", query=query, want_video=True)
    if SCREENSHOT_RE.search(lower) or want_video:
        return VisualGuideSpeech(kind="capture", query=query, want_video=want_video)
    if "what is this" in lower or "how does this work" in lower:
        return VisualGuideSpeech(kind="analyze", query=query, want_video=want_video)
    return None
