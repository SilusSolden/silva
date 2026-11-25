"""Assistant-facing appointment command helpers."""

from __future__ import annotations

from datetime import datetime

from silva.commands.appointment_phrases import (
    match_appointment_speech,
    parse_reminder_preferences,
)
from silva.commands.appointments import (
    cancel_appointment,
    complete_appointment,
    create_appointment,
    format_appointment_list,
    list_appointments,
    set_reminder,
    split_title_and_when,
    _format_when,
)


def handle_appointment_speech(user_id: str, text: str) -> tuple[str | None, dict | None]:
    speech = match_appointment_speech(text)
    if speech is None:
        return None, None

    if speech.action == "list":
        return format_appointment_list(user_id), None

    if speech.action == "cancel":
        if cancel_appointment(user_id, speech.query):
            return "Appointment cancelled.", None
        return "I could not find that appointment to cancel.", None

    if speech.action == "complete":
        if complete_appointment(user_id, speech.query):
            return "Marked that appointment as done.", None
        return "I could not find that appointment.", None

    if speech.action == "when":
        rows = list_appointments(user_id)
        query = speech.query.lower()
        for item in rows:
            if query in item.get("title", "").lower() or not query:
                when = datetime.fromisoformat(item["when"])
                return f"{item['title']} is scheduled for {_format_when(when)}.", None
        return "I could not find a matching upcoming appointment.", None

    if speech.action == "create":
        return _start_create(user_id, speech.query)

    return None, None


def _start_create(user_id: str, query: str) -> tuple[str, dict | None]:
    title, when = split_title_and_when(query)
    reminder = parse_reminder_preferences(query)

    if when is None:
        return (
            "Tell me the appointment name, date, and time. "
            "For example: dentist tomorrow at 2 PM.",
            None,
        )

    if reminder.get("enabled"):
        appt = create_appointment(user_id, title=title, when=when, reminder=reminder)
        return _confirm_created(appt), None

    appt = create_appointment(user_id, title=title, when=when, reminder={"enabled": False})
    return (
        f"Saved {title} for {_format_when(when)}. "
        "Do you want a reminder before it? Say yes or no.",
        {"phase": "await_reminder_ask", "appointment_id": appt["id"]},
    )


def _confirm_created(appt: dict) -> str:
    when = datetime.fromisoformat(appt["when"])
    reminder = appt.get("reminder", {})
    msg = f"Scheduled {appt['title']} for {_format_when(when)}."
    if reminder.get("enabled"):
        parts = []
        offsets = reminder.get("offsets_minutes") or []
        if offsets:
            parts.append(
                "Reminders "
                + ", ".join(f"{m} minutes before" for m in sorted(offsets, reverse=True))
            )
        periodic = reminder.get("periodic_every_minutes")
        if periodic:
            parts.append(f"checks every {periodic} minutes beforehand")
        if parts:
            msg += " " + " and ".join(parts) + "."
    return msg


def continue_appointment_flow(user_id: str, text: str, flow: dict) -> tuple[str, dict | None]:
    """Handle yes/no and reminder configuration after appointment create."""
    phase = flow.get("phase")
    appointment_id = flow.get("appointment_id")

    if phase == "await_reminder_ask":
        normalized = text.strip().lower()
        if normalized in {"no", "nope", "nah", "skip", "none", "dont", "don't"}:
            return "Okay, no reminder set.", None
        if normalized in {"yes", "yeah", "yep", "sure", "ok", "okay"}:
            flow["phase"] = "await_reminder_config"
            return (
                "How early should I remind you? "
                "You can say 30 minutes, one hour, or every 15 minutes before it.",
                flow,
            )
        reminder = parse_reminder_preferences(text)
        if reminder.get("enabled") and appointment_id:
            set_reminder(user_id, appointment_id, reminder)
            return _reminder_set_message(reminder), None
        return "Say yes or no, or tell me the reminder time.", flow

    if phase == "await_reminder_config":
        reminder = parse_reminder_preferences(text)
        if not reminder.get("enabled"):
            reminder["enabled"] = True
            reminder.setdefault("offsets_minutes", [30])
        if appointment_id:
            set_reminder(user_id, appointment_id, reminder)
        return _reminder_set_message(reminder), None

    return "I lost track of that appointment flow.", None


def _reminder_set_message(reminder: dict) -> str:
    offsets = reminder.get("offsets_minutes") or []
    periodic = reminder.get("periodic_every_minutes")
    parts = ["Reminder set."]
    if offsets:
        parts.append(
            "I'll alert you "
            + ", ".join(f"{m} minutes before" for m in sorted(offsets, reverse=True))
            + "."
        )
    if periodic:
        parts.append(f"I'll also check every {periodic} minutes as it gets closer.")
    return " ".join(parts)
