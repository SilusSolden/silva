"""Natural-language measurement phrase matching."""

from __future__ import annotations

import re
from dataclasses import dataclass

CAMERA_PHRASES: tuple[str, ...] = (
    "look at this in my hand",
    "look at this in hand",
    "look at what i am holding",
    "look at what im holding",
    "look at what i'm holding",
    "look at this next to me",
    "look at this beside me",
    "measure what i am holding",
    "measure what im holding",
    "measure what i'm holding",
    "measure this in my hand",
    "measure this in hand",
    "can you look at this",
    "can you measure this",
    "tell me the measurements of what you see",
    "what are the measurements of what you see",
    "use the camera to measure",
    "turn on the camera and measure",
    "camera measure",
)

SCREEN_PHRASES: tuple[str, ...] = (
    "look at my screen",
    "look at the screen",
    "look at whats on my screen",
    "look at what's on my screen",
    "look at what is on my screen",
    "measure whats on my screen",
    "measure what's on my screen",
    "measure what is on my screen",
    "measure my screen",
    "measure the screen",
    "screenshot and measure",
    "take a screenshot and measure",
    "capture my screen and measure",
    "look at the picture on my screen",
    "look at this on my screen",
)

MEASURE_PREFIXES: tuple[str, ...] = (
    "measure",
    "how big is",
    "how large is",
    "how long is",
    "how wide is",
    "how tall is",
    "what size is",
    "what are the dimensions of",
    "what are the measurements of",
    "size of",
    "dimensions of",
)

RECALL_PHRASES: tuple[str, ...] = (
    "recall my last measurement",
    "recall last measurement",
    "what was my last measurement",
    "repeat my last measurement",
    "last measurement",
)

HISTORY_PHRASES: tuple[str, ...] = (
    "show my measurements",
    "list my measurements",
    "measurement history",
)


@dataclass
class MeasurementSpeech:
    action: str
    query: str = ""
    source: str = "camera"


def _normalize(text: str) -> str:
    text = text.strip().lower()
    text = text.replace("'", "")
    return re.sub(r"\s+", " ", text)


def match_measurement_speech(text: str) -> MeasurementSpeech | None:
    normalized = _normalize(text)
    if not normalized:
        return None

    for phrase in RECALL_PHRASES:
        if normalized == phrase or normalized.startswith(phrase):
            return MeasurementSpeech("recall")

    for phrase in HISTORY_PHRASES:
        if normalized == phrase or normalized.startswith(phrase):
            return MeasurementSpeech("history")

    for phrase in SCREEN_PHRASES:
        if phrase in normalized:
            query = normalized.replace(phrase, "").strip(" ,.")
            return MeasurementSpeech("measure", query, source="screen")

    for phrase in CAMERA_PHRASES:
        if phrase in normalized:
            query = normalized.replace(phrase, "").strip(" ,.")
            return MeasurementSpeech("measure", query, source="camera")

    for prefix in MEASURE_PREFIXES:
        if normalized.startswith(prefix + " "):
            query = normalized[len(prefix) + 1 :].strip()
            source = "screen" if "screen" in normalized else "camera"
            return MeasurementSpeech("measure", query, source=source)
        if normalized == prefix:
            return MeasurementSpeech("measure", "", source="camera")

    if normalized.startswith("hey silva") or normalized.startswith("silva"):
        tail = normalized.replace("hey silva", "", 1).replace("silva", "", 1).strip(" ,.")
        for phrase in CAMERA_PHRASES:
            if phrase in tail:
                query = tail.replace(phrase, "").strip(" ,.")
                return MeasurementSpeech("measure", query, source="camera")

    return None


def is_measurement_command(text: str) -> bool:
    return match_measurement_speech(text) is not None
