"""Appointments, calendar storage, and reminder timers."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta

from silva.config import CONFIG_DIR
from silva.logger import log_info

APPOINTMENTS_FILE = CONFIG_DIR / "appointments.json"

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def _now() -> datetime:
    return datetime.now().replace(second=0, microsecond=0)


def _normalize(text: str) -> str:
    text = text.strip().lower()
    text = text.replace("'", "")
    return re.sub(r"\s+", " ", text)


def _load() -> list[dict]:
    if not APPOINTMENTS_FILE.exists():
        return []
    try:
        data = json.loads(APPOINTMENTS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _save(items: list[dict]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    APPOINTMENTS_FILE.write_text(json.dumps(items, indent=2), encoding="utf-8")


def parse_clock_time(text: str) -> tuple[int, int] | None:
    """Hour and minute from phrases like 8 am, at 7:30 pm, noon."""
    return _parse_time(text)


def _parse_time(text: str) -> tuple[int, int] | None:
    text = _normalize(text)
    match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|a m|p m)?", text)
    if not match:
        if "noon" in text:
            return 12, 0
        if "midnight" in text:
            return 0, 0
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    meridiem = (match.group(3) or "").replace(" ", "")
    if meridiem == "pm" and hour < 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    return hour, minute


def _next_weekday(target_weekday: int, now: datetime) -> datetime:
    days = (target_weekday - now.weekday()) % 7
    if days == 0:
        days = 7
    return now + timedelta(days=days)


def parse_datetime_from_text(text: str, *, now: datetime | None = None) -> datetime | None:
    """Best-effort parse of date/time phrases inside appointment speech."""
    now = now or _now()
    raw = text.strip()
    normalized = _normalize(raw)
    if not normalized:
        return None

    relative = re.search(r"\bin (\d+) (minute|minutes|min|hour|hours|hr|day|days)\b", normalized)
    if relative:
        amount = int(relative.group(1))
        unit = relative.group(2)
        if unit.startswith("hour") or unit == "hr":
            return now + timedelta(hours=amount)
        if unit.startswith("day"):
            return now + timedelta(days=amount)
        return now + timedelta(minutes=amount)

    hour_minute = _parse_time(normalized)
    base = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if "tomorrow" in normalized:
        base = base + timedelta(days=1)
    elif "today" in normalized:
        pass
    else:
        next_day = re.search(r"next (monday|tuesday|wednesday|thursday|friday|saturday|sunday)", normalized)
        if next_day:
            base = _next_weekday(WEEKDAYS[next_day.group(1)], now)
        else:
            weekday = re.search(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", normalized)
            if weekday:
                target = WEEKDAYS[weekday.group(1)]
                delta = (target - now.weekday()) % 7
                base = base + timedelta(days=delta)

    numeric_date = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", normalized)
    if numeric_date:
        month = int(numeric_date.group(1))
        day = int(numeric_date.group(2))
        year = int(numeric_date.group(3)) if numeric_date.group(3) else now.year
        if year < 100:
            year += 2000
        try:
            base = datetime(year, month, day)
        except ValueError:
            return None

    month_date = re.search(
        r"\b(january|february|march|april|may|june|july|august|september|october|november|december)"
        r"\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s+(\d{4}))?",
        normalized,
    )
    if month_date:
        month_names = [
            "january", "february", "march", "april", "may", "june",
            "july", "august", "september", "october", "november", "december",
        ]
        month = month_names.index(month_date.group(1)) + 1
        day = int(month_date.group(2))
        year = int(month_date.group(3)) if month_date.group(3) else now.year
        try:
            base = datetime(year, month, day)
        except ValueError:
            return None

    if hour_minute is None:
        return None
    hour, minute = hour_minute
    when = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if when <= now and "tomorrow" not in normalized and numeric_date is None and month_date is None:
        when += timedelta(days=1)
    return when


def split_title_and_when(text: str) -> tuple[str, datetime | None]:
    """Separate appointment title from embedded date/time phrase."""
    normalized = _normalize(text)
    when = parse_datetime_from_text(text)
    title = text.strip()

    strip_patterns = [
        r"\bin (\d+) (minute|minutes|min|hour|hours|hr|day|days)\b",
        r"\btomorrow\b",
        r"\btoday\b",
        r"\bnext (monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b",
        r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}(?:st|nd|rd|th)?(?:\s+\d{4})?\b",
        r"\bat \d{1,2}(?::\d{2})?\s*(?:am|pm|a m|p m)?\b",
        r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm|a m|p m)\b",
        r"\bnoon\b",
        r"\bmidnight\b",
        r"\bremind me\b.*",
        r"\b(\d+|thirty|fifteen|one|two)\s*(minute|minutes|min|hour|hours|hr)\b.*",
        r"\bevery (\d+) (minute|minutes|min|hour|hours|hr)\b.*",
    ]
    cleaned = normalized
    for pattern in strip_patterns:
        cleaned = re.sub(pattern, " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.-")
    if cleaned:
        title = cleaned
    elif when is not None:
        title = "Appointment"
    return title.title() if title else "Appointment", when


def _format_when(when: datetime) -> str:
    return when.strftime("%A, %B %d at %I:%M %p").replace(" 0", " ")


def create_appointment(
    user_id: str,
    *,
    title: str,
    when: datetime,
    reminder: dict | None = None,
) -> dict:
    items = _load()
    entry = {
        "id": uuid.uuid4().hex[:10],
        "user_id": user_id,
        "title": title.strip() or "Appointment",
        "when": when.isoformat(timespec="minutes"),
        "created_at": _now().isoformat(timespec="seconds"),
        "completed": False,
        "reminder": reminder
        or {
            "enabled": False,
            "offsets_minutes": [],
            "periodic_every_minutes": None,
            "periodic_start_minutes_before": 120,
            "notified_keys": [],
        },
    }
    items.append(entry)
    _save(items)
    log_info(f"Appointment created: {entry['title']} at {entry['when']}")
    return entry


def list_appointments(user_id: str, *, include_past: bool = False) -> list[dict]:
    now = _now()
    results = []
    for item in _load():
        if item.get("user_id") != user_id or item.get("completed"):
            continue
        when = datetime.fromisoformat(item["when"])
        if not include_past and when < now:
            continue
        results.append(item)
    results.sort(key=lambda row: row["when"])
    return results


def cancel_appointment(user_id: str, query: str) -> bool:
    query = _normalize(query)
    items = _load()
    for item in items:
        if item.get("user_id") != user_id or item.get("completed"):
            continue
        title = _normalize(item.get("title", ""))
        if query in title or title in query or query in item.get("id", ""):
            item["completed"] = True
            item["cancelled_at"] = _now().isoformat(timespec="seconds")
            _save(items)
            return True
    if items:
        upcoming = list_appointments(user_id)
        if len(upcoming) == 1:
            upcoming[0]["completed"] = True
            upcoming[0]["cancelled_at"] = _now().isoformat(timespec="seconds")
            _save(items)
            return True
    return False


def complete_appointment(user_id: str, query: str) -> bool:
    return cancel_appointment(user_id, query)


def format_appointment_list(user_id: str) -> str:
    rows = list_appointments(user_id)
    if not rows:
        return "You have no upcoming appointments."
    lines = ["Here are your upcoming appointments:"]
    for item in rows[:10]:
        when = datetime.fromisoformat(item["when"])
        reminder = item.get("reminder", {})
        extra = ""
        if reminder.get("enabled"):
            offsets = reminder.get("offsets_minutes") or []
            periodic = reminder.get("periodic_every_minutes")
            parts = []
            if offsets:
                parts.append("reminders at " + ", ".join(f"{m} min before" for m in sorted(offsets, reverse=True)))
            if periodic:
                parts.append(f"checks every {periodic} minutes")
            if parts:
                extra = " (" + "; ".join(parts) + ")"
        lines.append(f"- {item['title']} on {_format_when(when)}{extra}")
    return "\n".join(lines)


def _reminder_due(item: dict, now: datetime) -> list[str]:
    when = datetime.fromisoformat(item["when"])
    reminder = item.get("reminder") or {}
    if not reminder.get("enabled"):
        return []

    notified = set(reminder.get("notified_keys") or [])
    messages: list[str] = []
    title = item.get("title", "your appointment")

    due_key = "due"
    if now >= when and due_key not in notified:
        messages.append(f"It's time for {title}.")
        notified.add(due_key)

    for offset in reminder.get("offsets_minutes") or []:
        key = f"offset:{offset}"
        trigger = when - timedelta(minutes=int(offset))
        if key not in notified and now >= trigger > when - timedelta(days=1):
            messages.append(
                f"Reminder: {title} is in {offset} minutes, at {_format_when(when)}."
            )
            notified.add(key)

    periodic = reminder.get("periodic_every_minutes")
    if periodic:
        start_before = int(reminder.get("periodic_start_minutes_before") or 120)
        start = when - timedelta(minutes=start_before)
        if now >= start:
            elapsed = int((now - start).total_seconds() // 60)
            slot = elapsed - (elapsed % int(periodic))
            key = f"periodic:{slot}"
            if key not in notified and now < when + timedelta(minutes=1):
                remaining = int((when - now).total_seconds() // 60)
                if remaining > 0:
                    messages.append(
                        f"Scheduled check-in: {title} is in about {remaining} minutes."
                    )
                notified.add(key)

    if messages:
        reminder["notified_keys"] = sorted(notified)
        item["reminder"] = reminder
    return messages


def check_due_reminders(user_id: str) -> list[str]:
    now = _now()
    items = _load()
    messages: list[str] = []
    changed = False
    for item in items:
        if item.get("user_id") != user_id or item.get("completed"):
            continue
        due = _reminder_due(item, now)
        if due:
            messages.extend(due)
            changed = True
    if changed:
        _save(items)
    return messages


def set_reminder(user_id: str, appointment_id: str, reminder: dict) -> bool:
    items = _load()
    for item in items:
        if item.get("user_id") == user_id and item.get("id") == appointment_id:
            item["reminder"] = {
                "enabled": bool(reminder.get("enabled")),
                "offsets_minutes": sorted(set(reminder.get("offsets_minutes") or []), reverse=True),
                "periodic_every_minutes": reminder.get("periodic_every_minutes"),
                "periodic_start_minutes_before": int(
                    reminder.get("periodic_start_minutes_before") or 120
                ),
                "notified_keys": [],
            }
            _save(items)
            return True
    return False
