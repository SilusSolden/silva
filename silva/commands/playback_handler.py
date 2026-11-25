"""Assistant-facing video play / pause helpers."""

from __future__ import annotations

from silva.commands.playback_phrases import match_playback_speech
from silva.media.playback import pause_playback, play_playback, stop_playback, toggle_playback


def handle_playback_speech(_user_id: str, text: str) -> str | None:
    speech = match_playback_speech(text)
    if speech is None:
        return None

    if speech.action == "pause":
        ok, message = pause_playback()
        return message if ok else message

    if speech.action == "play":
        ok, message = play_playback()
        return message if ok else message

    if speech.action == "toggle":
        ok, message = toggle_playback()
        return message if ok else message

    if speech.action == "stop":
        ok, message = stop_playback()
        return message if ok else message

    return None
