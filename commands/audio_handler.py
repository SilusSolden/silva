"""Assistant-facing app audio mute / unmute helpers."""

from __future__ import annotations

from silva.audio_sessions import describe_active_audio, mute_app, unmute_app
from silva.commands.audio_phrases import match_audio_speech


def handle_audio_speech(_user_id: str, text: str) -> str | None:
    speech = match_audio_speech(text)
    if speech is None:
        return None

    if speech.action == "list":
        return describe_active_audio()

    if not speech.target:
        active = describe_active_audio()
        return (
            "Tell me which app to mute, like mute chrome or silva mute this sons of the forest. "
            f"{active}"
        )

    if speech.action == "mute":
        _ok, message = mute_app(speech.target)
        return message

    if speech.action == "unmute":
        _ok, message = unmute_app(speech.target)
        return message

    return None
