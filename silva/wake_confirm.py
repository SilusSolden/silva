"""Listen for wake confirmation by voice while a typing prompt is open."""

from __future__ import annotations

import threading
import time

from silva.gui.wake_prompt import prompt_wake_confirmation
from silva.wake import (
    get_wake_confirm_timeout,
    is_wake_command,
    is_wake_confirm_no,
    is_wake_confirm_yes,
)


def confirm_wake_intent(stt, *, voice_mode: bool) -> str:
    """
    Ask if the user is trying to wake Silva using voice and a typing box.
    Returns: 'wake', 'no', or 'timeout'.
    """
    timeout = get_wake_confirm_timeout()
    voice_result: dict[str, str] = {"value": ""}

    def listen_for_voice() -> None:
        if not voice_mode or stt is None:
            return
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                text = stt.listen(timeout=3.0, phrase_limit=8)
            except Exception:
                time.sleep(0.2)
                continue
            if not text:
                continue
            print(f"You: {text}")
            if is_wake_command(text) or is_wake_confirm_yes(text):
                voice_result["value"] = "wake"
                return
            if is_wake_confirm_no(text):
                voice_result["value"] = "no"
                return

    voice_thread: threading.Thread | None = None
    if voice_mode and stt is not None:
        voice_thread = threading.Thread(target=listen_for_voice, daemon=True)
        voice_thread.start()

    typed_result = prompt_wake_confirmation()

    if voice_thread is not None:
        voice_thread.join(timeout=0.5)

    if voice_result["value"] == "wake" or typed_result == "wake":
        return "wake"
    if voice_result["value"] == "no" or typed_result == "no":
        return "no"
    return "timeout"
