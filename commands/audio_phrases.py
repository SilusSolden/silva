"""Natural-language app audio mute / unmute phrase matching."""

from __future__ import annotations

import re
from dataclasses import dataclass


MUTE_PREFIXES: tuple[str, ...] = (
    "mute",
    "silence",
    "quiet",
    "turn off sound for",
    "turn off audio for",
    "turn off sound on",
    "turn off audio on",
    "turn sound off for",
    "turn audio off for",
    "turn sound off on",
    "turn audio off on",
    "stop sound from",
    "stop audio from",
    "stop sound on",
    "stop audio on",
    "kill sound for",
    "kill audio for",
    "shut off sound for",
    "shut off audio for",
    "no sound from",
    "no audio from",
)

UNMUTE_PREFIXES: tuple[str, ...] = (
    "unmute",
    "turn sound back on for",
    "turn audio back on for",
    "turn sound back on",
    "turn audio back on",
    "turn sound on for",
    "turn audio on for",
    "turn sound on",
    "turn audio on",
    "enable sound for",
    "enable audio for",
    "bring back sound for",
    "bring back audio for",
    "restore sound for",
    "restore audio for",
)

LIST_PHRASES: tuple[str, ...] = (
    "what is playing audio",
    "whats playing audio",
    "what apps are playing audio",
    "what apps have audio",
    "what is making sound",
    "whats making sound",
    "what apps are making sound",
    "who is playing sound",
    "list audio apps",
    "list apps with audio",
    "show audio apps",
    "show apps with sound",
    "what has sound",
    "what has audio",
)

THIS_PATTERNS: tuple[str, ...] = (
    "mute this",
    "silence this",
    "quiet this",
    "unmute this",
    "turn off sound for this",
    "turn off audio for this",
    "turn sound off for this",
    "turn audio off for this",
    "turn sound back on for this",
    "turn audio back on for this",
)

GAME_PATTERNS: tuple[str, ...] = (
    "mute the game",
    "mute that game",
    "mute this game",
    "silence the game",
    "quiet the game",
    "unmute the game",
    "unmute that game",
    "unmute this game",
    "turn off game sound",
    "turn off game audio",
    "turn game sound back on",
    "turn game audio back on",
)

VIDEO_PATTERNS: tuple[str, ...] = (
    "mute the video",
    "mute that video",
    "mute this video",
    "silence the video",
    "unmute the video",
    "unmute that video",
    "unmute this video",
    "mute the movie",
    "mute that movie",
    "mute this movie",
    "unmute the movie",
    "unmute that movie",
    "unmute this movie",
)


@dataclass
class AudioSpeech:
    action: str
    target: str = ""


def _normalize(text: str) -> str:
    text = text.strip().lower()
    text = text.replace("'", "")
    return re.sub(r"\s+", " ", text)


def _strip_wake(text: str) -> str:
    normalized = _normalize(text)
    if normalized.startswith("hey silva "):
        normalized = normalized[len("hey silva ") :].strip()
    elif normalized.startswith("silva "):
        normalized = normalized[len("silva ") :].strip()

    for prefix in (
        "can you ",
        "could you ",
        "please ",
        "would you ",
        "go ahead and ",
    ):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :].strip()
            break

    return normalized


def _extract_quoted_target(text: str) -> str | None:
    match = re.search(r'["\']([^"\']+)["\']', text)
    if match:
        return match.group(1).strip()
    return None


def _target_from_prefix(normalized: str, prefix: str) -> str:
    tail = normalized[len(prefix) :].strip(" ,.")
    tail = re.sub(r"^(the|that|this)\s+", "", tail)
    return tail.strip()


def match_audio_speech(text: str) -> AudioSpeech | None:
    normalized = _strip_wake(text)
    if not normalized:
        return None

    quoted = _extract_quoted_target(text)

    for phrase in LIST_PHRASES:
        if normalized == phrase or normalized.startswith(phrase):
            return AudioSpeech("list")

    for pattern in GAME_PATTERNS:
        if normalized == pattern or normalized.startswith(pattern):
            action = "unmute" if pattern.startswith("unmute") or "back on" in pattern else "mute"
            return AudioSpeech(action, "game")

    for pattern in VIDEO_PATTERNS:
        if normalized == pattern or normalized.startswith(pattern):
            action = "unmute" if pattern.startswith("unmute") else "mute"
            return AudioSpeech(action, "video")

    for pattern in THIS_PATTERNS:
        if normalized.startswith(pattern + " "):
            target = quoted or _target_from_prefix(normalized, pattern)
            if target:
                action = "unmute" if "unmute" in pattern or "back on" in pattern else "mute"
                return AudioSpeech(action, target)
        if normalized == pattern and quoted:
            action = "unmute" if "unmute" in pattern or "back on" in pattern else "mute"
            return AudioSpeech(action, quoted)

    for prefix in UNMUTE_PREFIXES:
        if normalized.startswith(prefix + " "):
            target = quoted or _target_from_prefix(normalized, prefix)
            if target:
                return AudioSpeech("unmute", target)
        if normalized == prefix and quoted:
            return AudioSpeech("unmute", quoted)

    for prefix in MUTE_PREFIXES:
        if normalized.startswith(prefix + " "):
            target = quoted or _target_from_prefix(normalized, prefix)
            if target:
                return AudioSpeech("mute", target)
        if normalized == prefix and quoted:
            return AudioSpeech("mute", target)

    if quoted:
        if "unmute" in normalized or "turn sound back on" in normalized or "turn audio back on" in normalized:
            return AudioSpeech("unmute", quoted)
        if "mute" in normalized or "silence" in normalized or "quiet" in normalized:
            return AudioSpeech("mute", quoted)

    return None


def is_audio_command(text: str) -> bool:
    return match_audio_speech(text) is not None
