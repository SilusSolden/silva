"""Answer where the user is using Silva's saved/Windows location — not a Wikipedia guide."""

from __future__ import annotations

from silva.logger import log_info


def handle_location_speech(assistant, text: str) -> bool:
    from silva.commands.location_phrases import is_location_command

    if not is_location_command(text):
        return False

    from silva.location import resolve_location

    log_info(f"Location command: {text[:120]}")
    try:
        place = resolve_location(prefer_fresh=True)
    except RuntimeError as exc:
        assistant.say(str(exc), interruptible=False)
        return True
    except Exception:
        assistant.say("I couldn't tell where you are right now.", interruptible=False)
        return True

    city = (place.city or "").strip() or "an unknown city"
    assistant.say(f"You're in {city}.", interruptible=False)
    return True
