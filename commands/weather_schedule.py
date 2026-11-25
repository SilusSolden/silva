"""Scheduled automatic weather display for Silva."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Callable

from silva.config import CONFIG_DIR, load_config
from silva.logger import log_info

STATE_FILE = CONFIG_DIR / "weather_schedule_state.json"


def scheduled_display_enabled() -> bool:
    return bool(load_config().get("weather_scheduled_display_enabled", True))


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _config_int(key: str, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        value = int(load_config().get(key, default))
    except (TypeError, ValueError):
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def build_display_slots(for_day: date | None = None) -> list[tuple[int, int]]:
    """Return sorted (hour, minute) slots for the configured daily schedule."""
    for_day = for_day or date.today()
    config = load_config()

    start_hour = _config_int("weather_morning_display_start_hour", 8, minimum=0, maximum=23)
    end_hour = _config_int("weather_morning_display_end_hour", 9, minimum=0, maximum=23)
    interval = _config_int("weather_morning_display_interval_minutes", 30, minimum=15, maximum=120)
    noon_hour = _config_int("weather_noon_display_hour", 12, minimum=0, maximum=23)
    evening_hour = _config_int("weather_evening_display_hour", 21, minimum=0, maximum=23)

    slots: list[tuple[int, int]] = []
    if start_hour <= end_hour:
        current = datetime.combine(for_day, time(start_hour, 0))
        end_dt = datetime.combine(for_day, time(end_hour, 0))
        while current <= end_dt:
            slots.append((current.hour, current.minute))
            current += timedelta(minutes=interval)

    slots.append((noon_hour, 0))
    slots.append((evening_hour, 0))
    return sorted(set(slots))


def slot_key(for_day: date, hour: int, minute: int) -> str:
    return f"{for_day.isoformat()}_{hour:02d}:{minute:02d}"


def _slot_start(for_day: date, hour: int, minute: int) -> datetime:
    return datetime.combine(for_day, time(hour, minute))


def _slot_window_end(for_day: date, slot: tuple[int, int], all_slots: list[tuple[int, int]]) -> datetime:
    start = _slot_start(for_day, slot[0], slot[1])
    if slot in all_slots:
        index = all_slots.index(slot)
        if index + 1 < len(all_slots):
            next_hour, next_minute = all_slots[index + 1]
            return _slot_start(for_day, next_hour, next_minute)
    return start + timedelta(hours=2)


def active_display_slot(now: datetime | None = None) -> tuple[str, tuple[int, int]] | None:
    """Return (slot_key, slot) when now is inside a scheduled display window."""
    if not scheduled_display_enabled():
        return None

    now = now or datetime.now()
    slots = build_display_slots(now.date())
    for hour, minute in slots:
        slot = (hour, minute)
        start = _slot_start(now.date(), hour, minute)
        end = _slot_window_end(now.date(), slot, slots)
        if start <= now < end:
            return slot_key(now.date(), hour, minute), slot
    return None


def _shown_slots(state: dict) -> set[str]:
    items = state.get("shown_slots", [])
    if not isinstance(items, list):
        return set()
    return {str(item) for item in items}


def _prune_old_shown(state: dict, today: date) -> None:
    today_key = today.isoformat()
    state["shown_slots"] = [
        str(item) for item in _shown_slots(state) if str(item).split("_", 1)[0] == today_key
    ]


def mark_slot_shown(slot_id: str) -> None:
    state = _load_state()
    shown = _shown_slots(state)
    shown.add(slot_id)
    state["shown_slots"] = sorted(shown)
    state.pop("pending_slot", None)
    _save_state(state)


def check_scheduled_weather_display(
    *,
    user_id: str | None,
    is_busy: Callable[[], bool],
) -> bool:
    """
    Show the weather popup during configured schedule windows.
    Defers while Silva is busy with heavy tasks; retries until the window closes.
    Returns True when a popup was shown.
    """
    if not scheduled_display_enabled():
        return False

    active = active_display_slot()
    state = _load_state()
    _prune_old_shown(state, date.today())

    if active is None:
        if state.get("pending_slot"):
            state.pop("pending_slot", None)
            _save_state(state)
        return False

    slot_id, _slot = active
    shown = _shown_slots(state)

    if slot_id in shown:
        state.pop("pending_slot", None)
        _save_state(state)
        return False

    if is_busy():
        if state.get("pending_slot") != slot_id:
            state["pending_slot"] = slot_id
            _save_state(state)
            log_info(f"Scheduled weather display deferred for slot {slot_id} while Silva is busy.")
        return False

    from silva.commands.weather import show_scheduled_weather_popup

    if not show_scheduled_weather_popup(user_id=user_id):
        return False

    mark_slot_shown(slot_id)
    log_info(f"Scheduled weather display shown for slot {slot_id}.")
    return True
