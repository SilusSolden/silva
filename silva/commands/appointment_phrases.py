"""Natural-language appointment / calendar phrase matching."""

from __future__ import annotations

import re
from dataclasses import dataclass

CREATE_PREFIXES: tuple[str, ...] = (
    "set appointment",
    "set an appointment",
    "schedule appointment",
    "schedule an appointment",
    "add appointment",
    "add an appointment",
    "create appointment",
    "create an appointment",
    "book appointment",
    "book an appointment",
    "set a reminder for",
    "remind me to",
    "remind me about",
    "add to my calendar",
    "add to calendar",
    "put on my calendar",
    "calendar appointment",
    "set this for",
    "schedule this for",
    "set for",
    "schedule for",
    "make an appointment",
    "make appointment",
)

LIST_PHRASES: tuple[str, ...] = (
    "list appointments",
    "list my appointments",
    "show appointments",
    "show my appointments",
    "my appointments",
    "my schedule",
    "show my schedule",
    "what's on my calendar",
    "whats on my calendar",
    "what is on my calendar",
    "my calendar",
    "upcoming appointments",
    "what do i have scheduled",
)

CANCEL_PREFIXES: tuple[str, ...] = (
    "cancel appointment",
    "cancel my appointment",
    "delete appointment",
    "delete my appointment",
    "remove appointment",
    "remove my appointment",
)

COMPLETE_PREFIXES: tuple[str, ...] = (
    "complete appointment",
    "mark appointment done",
    "mark appointment complete",
    "appointment done",
    "finished appointment",
)

WHAT_TIME_PHRASES: tuple[str, ...] = (
    "what time is my",
    "when is my",
    "when is the appointment",
)


@dataclass
class AppointmentSpeech:
    action: str
    query: str = ""


def _normalize(text: str) -> str:
    text = text.strip().lower()
    text = text.replace("'", "")
    return re.sub(r"\s+", " ", text)


def match_appointment_speech(text: str) -> AppointmentSpeech | None:
    normalized = _normalize(text)
    if not normalized:
        return None

    for phrase in LIST_PHRASES:
        if normalized == phrase or normalized.startswith(phrase + " "):
            return AppointmentSpeech("list")

    for prefix in CANCEL_PREFIXES:
        if normalized.startswith(prefix + " "):
            return AppointmentSpeech("cancel", normalized[len(prefix) + 1 :].strip())
        if normalized == prefix:
            return AppointmentSpeech("cancel")

    for prefix in COMPLETE_PREFIXES:
        if normalized.startswith(prefix + " "):
            return AppointmentSpeech("complete", normalized[len(prefix) + 1 :].strip())
        if normalized == prefix:
            return AppointmentSpeech("complete")

    for phrase in WHAT_TIME_PHRASES:
        if phrase in normalized:
            return AppointmentSpeech("when", normalized.replace(phrase, "").strip())

    for prefix in CREATE_PREFIXES:
        if normalized.startswith(prefix + " "):
            return AppointmentSpeech("create", normalized[len(prefix) + 1 :].strip())
        if normalized == prefix:
            return AppointmentSpeech("create")

    if normalized.startswith("appointment "):
        return AppointmentSpeech("create", normalized[len("appointment ") :].strip())

    return None


def is_appointment_command(text: str) -> bool:
    return match_appointment_speech(text) is not None


def parse_reminder_preferences(text: str) -> dict:
    """Parse reminder options from speech."""
    normalized = _normalize(text)
    result = {
        "enabled": False,
        "offsets_minutes": [],
        "periodic_every_minutes": None,
        "periodic_start_minutes_before": 120,
    }

    if normalized in {"no", "nope", "nah", "no reminder", "skip", "none", "dont remind me", "don't remind me"}:
        return result

    if normalized in {"yes", "yeah", "yep", "sure", "ok", "okay", "please"}:
        result["enabled"] = True
        result["offsets_minutes"] = [30]
        return result

    if any(w in normalized for w in ("yes", "sure", "remind", "timer", "alert", "notify")):
        result["enabled"] = True

    for match in re.finditer(r"(\d+)\s*(minute|minutes|min|mins|hour|hours|hr|hrs)\b", normalized):
        amount = int(match.group(1))
        unit = match.group(2)
        minutes = amount * 60 if unit.startswith("hour") or unit.startswith("hr") else amount
        if minutes > 0 and minutes not in result["offsets_minutes"]:
            result["offsets_minutes"].append(minutes)

    word_map = {
        "fifteen minutes": 15,
        "thirty minutes": 30,
        "half an hour": 30,
        "one hour": 60,
        "an hour": 60,
        "two hours": 120,
    }
    for phrase, minutes in word_map.items():
        if phrase in normalized and minutes not in result["offsets_minutes"]:
            result["offsets_minutes"].append(minutes)

    periodic = re.search(
        r"(?:every|check every|periodic(?:ally)? every)\s+(\d+)\s*(minute|minutes|min|mins|hour|hours|hr|hrs)\b",
        normalized,
    )
    if periodic:
        amount = int(periodic.group(1))
        unit = periodic.group(2)
        result["periodic_every_minutes"] = amount * 60 if unit.startswith("hour") or unit.startswith("hr") else amount
        result["enabled"] = True

    if result["enabled"] and not result["offsets_minutes"] and not result["periodic_every_minutes"]:
        result["offsets_minutes"] = [30]

    return result
