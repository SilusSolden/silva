"""Resolve misheard speech using saved phrase recordings — no popups."""

from __future__ import annotations

import speech_recognition as sr

from silva.logger import log_info
from silva.users.phrase_recordings import match_phrase_recording, phrase_recording_enabled


def resolve_text_with_phrase_audio(
    text: str | None,
    audio: sr.AudioData | None,
    *,
    active_user_id: str | None = None,
    phrase_kinds: set[str] | None = None,
) -> tuple[str | None, bool]:
    """Return (resolved_text, used_phrase_audio). Silent — no UI."""
    if not phrase_recording_enabled() or audio is None:
        return text, False

    match = match_phrase_recording(
        audio,
        active_user_id=active_user_id,
        phrase_kinds=phrase_kinds,
    )
    if match is None:
        return text, False

    intended = match.intended_text.strip()
    if not intended:
        return text, False

    heard = (text or "").strip()
    if heard.lower() == intended.lower():
        return text, False

    log_info(
        f"Phrase recording matched for {match.user_id}: "
        f"{match.intended_text!r} (score {match.score:.2f}, sample {match.sample_id})"
    )
    return intended, True
