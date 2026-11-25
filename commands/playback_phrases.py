"""Natural-language video play / pause phrase matching."""

from __future__ import annotations

import re
from dataclasses import dataclass

PAUSE_PHRASES: tuple[str, ...] = (
    "pause the video",
    "pause video",
    "pause the movie",
    "pause movie",
    "pause playback",
    "pause the playback",
    "pause it",
    "pause this",
    "pause that",
    "pause show",
    "pause the show",
    "pause stream",
    "pause the stream",
    "hold the video",
    "hold the movie",
    "freeze the video",
    "stop the video",
    "stop video",
    "stop the movie",
    "stop movie",
    "stop playback",
    "stop playing",
    "stop the show",
)

PLAY_PHRASES: tuple[str, ...] = (
    "play the video",
    "play video",
    "play the movie",
    "play movie",
    "play playback",
    "play it",
    "play this",
    "play that",
    "play show",
    "play the show",
    "play stream",
    "play the stream",
    "resume the video",
    "resume video",
    "resume the movie",
    "resume movie",
    "resume playback",
    "resume it",
    "resume this",
    "resume playing",
    "resume the show",
    "continue the video",
    "continue video",
    "continue the movie",
    "continue movie",
    "continue playback",
    "continue playing",
    "keep playing",
    "unpause",
    "unpause the video",
    "unpause video",
    "start the video",
    "start video",
    "start the movie",
    "start movie",
    "start playback",
    "start playing again",
)

TOGGLE_PHRASES: tuple[str, ...] = (
    "pause or play",
    "play or pause",
    "toggle video",
    "toggle playback",
    "toggle play pause",
    "play pause",
    "pause play",
)

EXACT_PHRASES: frozenset[str] = frozenset(
    {
        "pause",
        "play",
        "resume",
        "continue",
        "unpause",
        "stop",
    }
)

_POLITE_PREFIXES: tuple[str, ...] = (
    "can you ",
    "could you ",
    "would you ",
    "will you ",
    "please ",
    "go ahead and ",
)

_WAKE_PREFIXES: tuple[str, ...] = (
    "hey silva ",
    "silva ",
    "hey silver ",
    "silver ",
    "okay silva ",
    "ok silva ",
)


@dataclass
class PlaybackSpeech:
    action: str


def _normalize(text: str) -> str:
    text = text.strip().lower()
    text = text.replace("'", "")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _strip_leading(text: str) -> str:
    normalized = _normalize(text)
    changed = True
    while changed:
        changed = False
        for prefix in _WAKE_PREFIXES:
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix) :].strip()
                changed = True
                break
        for prefix in _POLITE_PREFIXES:
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix) :].strip()
                changed = True
                break
    return normalized


def _matches(normalized: str, phrase: str) -> bool:
    if normalized == phrase:
        return True
    if normalized.startswith(phrase + " "):
        return True
    if len(phrase.split()) >= 2 and phrase in normalized:
        return True
    return False


def match_playback_speech(text: str) -> PlaybackSpeech | None:
    normalized = _strip_leading(text)
    if not normalized:
        return None

    if normalized in EXACT_PHRASES:
        action = normalized
        if action in {"continue", "unpause", "start"}:
            action = "play"
        if action == "stop":
            action = "pause"
        return PlaybackSpeech(action)

    for phrase in PAUSE_PHRASES:
        if _matches(normalized, phrase):
            return PlaybackSpeech("pause")

    for phrase in PLAY_PHRASES:
        if _matches(normalized, phrase):
            return PlaybackSpeech("play")

    for phrase in TOGGLE_PHRASES:
        if _matches(normalized, phrase):
            return PlaybackSpeech("toggle")

    if "pause" in normalized and "play" in normalized:
        return PlaybackSpeech("toggle")
    if normalized.startswith("pause"):
        return PlaybackSpeech("pause")
    if normalized.startswith(("play", "resume", "continue", "unpause", "start")):
        return PlaybackSpeech("play")

    return None


def is_playback_command(text: str) -> bool:
    return match_playback_speech(text) is not None
