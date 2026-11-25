"""Personal notes and to-do items stored under the Silva config directory."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from silva.config import CONFIG_DIR
from silva.logger import log_info

NOTES_FILE = CONFIG_DIR / "notes.json"
_LOCK = threading.RLock()


def _now() -> datetime:
    return datetime.now().replace(second=0, microsecond=0)


def _empty() -> dict:
    return {"notes": [], "todos": [], "archived_todos": []}


def _load() -> dict:
    if not NOTES_FILE.exists():
        return _empty()
    try:
        data = json.loads(NOTES_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("notes", [])
            data.setdefault("todos", [])
            data.setdefault("archived_todos", [])
            if (
                isinstance(data["notes"], list)
                and isinstance(data["todos"], list)
                and isinstance(data["archived_todos"], list)
            ):
                return data
    except (json.JSONDecodeError, OSError):
        pass
    return _empty()


def _save(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2)
    fd, tmp_name = tempfile.mkstemp(prefix="notes.", suffix=".tmp", dir=str(CONFIG_DIR))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(tmp_name, NOTES_FILE)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _new_id() -> str:
    return uuid.uuid4().hex[:10]


def add_note(
    user_id: str,
    text: str,
    *,
    remind_at: datetime | None = None,
) -> dict:
    text = " ".join(text.strip().split())
    entry = {
        "id": _new_id(),
        "user_id": user_id,
        "text": text,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "reminder": {
            "enabled": remind_at is not None,
            "when": remind_at.isoformat(timespec="minutes") if remind_at else None,
            "notified": False,
        },
    }
    with _LOCK:
        data = _load()
        data["notes"].append(entry)
        _save(data)
    log_info(f"Note saved ({entry['id']}): {text[:160]}")
    return entry


def list_notes(user_id: str) -> list[dict]:
    with _LOCK:
        return [item for item in _load()["notes"] if item.get("user_id") == user_id]


def find_notes(user_id: str, query: str) -> list[dict]:
    needle = query.strip().lower()
    if not needle:
        return list_notes(user_id)
    return [item for item in list_notes(user_id) if needle in str(item.get("text", "")).lower()]


def delete_note(user_id: str, query: str) -> dict | None:
    needle = query.strip().lower()
    with _LOCK:
        data = _load()
        match = None
        kept = []
        for item in data["notes"]:
            if (
                match is None
                and item.get("user_id") == user_id
                and (not needle or needle in str(item.get("text", "")).lower() or item.get("id") == query)
            ):
                match = item
                continue
            kept.append(item)
        if match is None:
            return None
        data["notes"] = kept
        _save(data)
    log_info(f"Note deleted ({match.get('id')}): {str(match.get('text', ''))[:120]}")
    return match


def set_note_reminder(user_id: str, query: str, when: datetime) -> dict | None:
    needle = query.strip().lower()
    with _LOCK:
        data = _load()
        match = None
        for item in data["notes"]:
            if item.get("user_id") != user_id:
                continue
            if needle and needle not in str(item.get("text", "")).lower() and item.get("id") != query:
                continue
            item["reminder"] = {
                "enabled": True,
                "when": when.isoformat(timespec="minutes"),
                "notified": False,
            }
            match = item
            break
        if match is None:
            return None
        _save(data)
    return match


def _nag_state() -> dict:
    return {
        "enabled": False,
        "started_at": None,
        "last_nudge_at": None,
        "nudge_count": 0,
        "dismissed_for_date": None,
        "popup_open": False,
    }


def add_todo(
    user_id: str,
    text: str,
    *,
    repeat: str | None = None,
    due_hour: int | None = None,
    due_minute: int | None = None,
) -> dict:
    text = " ".join(text.strip().split())
    daily = str(repeat or "").lower() == "daily"
    entry = {
        "id": _new_id(),
        "user_id": user_id,
        "text": text,
        "done": False,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "completed_at": None,
        "repeat": "daily" if daily else None,
        "due_hour": int(due_hour) if daily and due_hour is not None else None,
        "due_minute": int(due_minute or 0) if daily and due_hour is not None else None,
        "nag": {**_nag_state(), "enabled": True} if daily and due_hour is not None else None,
    }
    with _LOCK:
        data = _load()
        data["todos"].append(entry)
        _save(data)
    log_info(f"To-do saved ({entry['id']}): {text[:160]} daily={daily}")
    return entry


def list_todos(user_id: str, *, include_done: bool = True) -> list[dict]:
    with _LOCK:
        items = [item for item in _load()["todos"] if item.get("user_id") == user_id]
    if include_done:
        return items
    return [item for item in items if not item.get("done")]


def numbered_todos(user_id: str, *, include_done: bool = True) -> list[tuple[int, dict]]:
    return [(index + 1, item) for index, item in enumerate(list_todos(user_id, include_done=include_done))]


def todo_by_number(user_id: str, number: int) -> dict | None:
    for index, item in numbered_todos(user_id):
        if index == int(number):
            return item
    return None


def latest_todo(user_id: str) -> dict | None:
    items = list_todos(user_id)
    return items[-1] if items else None


def update_todo(
    user_id: str,
    item_id: str,
    *,
    text: str | None = None,
    due_hour: int | None = None,
    due_minute: int | None = None,
    repeat: str | None = None,
) -> dict | None:
    with _LOCK:
        data = _load()
        match = None
        for item in data["todos"]:
            if item.get("user_id") != user_id or item.get("id") != item_id:
                continue
            if text is not None:
                item["text"] = " ".join(text.strip().split())
            if repeat is not None:
                item["repeat"] = "daily" if str(repeat).lower() == "daily" else None
            if due_hour is not None:
                item["due_hour"] = int(due_hour)
                item["due_minute"] = int(due_minute or 0)
                item["repeat"] = item.get("repeat") or "daily"
                nag = item.get("nag") or _nag_state()
                nag["enabled"] = True
                item["nag"] = nag
            match = item
            break
        if match is None:
            return None
        _save(data)
    return match


def move_todo(user_id: str, src_number: int, dest_number: int) -> dict | None:
    with _LOCK:
        data = _load()
        mine = [item for item in data["todos"] if item.get("user_id") == user_id]
        others = [item for item in data["todos"] if item.get("user_id") != user_id]
        src = int(src_number) - 1
        dest = int(dest_number) - 1
        if src < 0 or src >= len(mine):
            return None
        dest = max(0, min(dest, len(mine) - 1))
        item = mine.pop(src)
        mine.insert(dest, item)
        data["todos"] = others + mine
        _save(data)
    return item


def clear_todos(user_id: str, *, archive: bool = True) -> int:
    with _LOCK:
        data = _load()
        kept = []
        moved = []
        for item in data["todos"]:
            if item.get("user_id") != user_id:
                kept.append(item)
                continue
            if archive:
                item["archived_at"] = datetime.now().isoformat(timespec="seconds")
                nag = item.get("nag") or _nag_state()
                nag["popup_open"] = False
                nag["enabled"] = False
                item["nag"] = nag
                moved.append(item)
        count = len(moved) if archive else len(data["todos"]) - len(kept)
        data["todos"] = kept
        if archive and moved:
            data.setdefault("archived_todos", []).extend(moved)
        _save(data)
    return count


def set_todo_done(user_id: str, item_id: str, done: bool = True) -> dict | None:
    with _LOCK:
        data = _load()
        match = None
        for item in data["todos"]:
            if item.get("user_id") == user_id and item.get("id") == item_id:
                item["done"] = bool(done)
                item["completed_at"] = datetime.now().isoformat(timespec="seconds") if done else None
                match = item
                break
        if match is None:
            return None
        _save(data)
    return match


def complete_todo_by_query(user_id: str, query: str, done: bool = True) -> dict | None:
    needle = query.strip().lower()
    with _LOCK:
        data = _load()
        match = None
        for item in data["todos"]:
            if item.get("user_id") != user_id:
                continue
            if needle and needle not in str(item.get("text", "")).lower() and item.get("id") != query:
                continue
            if done and item.get("done"):
                continue
            item["done"] = bool(done)
            item["completed_at"] = datetime.now().isoformat(timespec="seconds") if done else None
            match = item
            break
        if match is None:
            return None
        _save(data)
    return match


def _text_matches(item: dict, query: str) -> bool:
    needle = query.strip().lower()
    if not needle:
        return True
    if item.get("id") == query:
        return True
    return needle in str(item.get("text", "")).lower()


def find_todos(user_id: str, query: str, *, include_done: bool = True) -> list[dict]:
    return [
        item
        for item in list_todos(user_id, include_done=include_done)
        if _text_matches(item, query)
    ]


def delete_todo(user_id: str, query: str) -> dict | None:
    needle = query.strip().lower()
    with _LOCK:
        data = _load()
        match = None
        kept = []
        for item in data["todos"]:
            if (
                match is None
                and item.get("user_id") == user_id
                and (not needle or needle in str(item.get("text", "")).lower() or item.get("id") == query)
            ):
                match = item
                continue
            kept.append(item)
        if match is None:
            return None
        data["todos"] = kept
        _save(data)
    return match


def archive_todo(user_id: str, query: str) -> dict | None:
    """Take a to-do off the active list but keep it in case they want it back."""
    with _LOCK:
        data = _load()
        match = None
        kept = []
        for item in data["todos"]:
            if (
                match is None
                and item.get("user_id") == user_id
                and _text_matches(item, query)
            ):
                match = item
                continue
            kept.append(item)
        if match is None:
            return None
        match["archived_at"] = datetime.now().isoformat(timespec="seconds")
        nag = match.get("nag") or _nag_state()
        nag["popup_open"] = False
        nag["enabled"] = False
        match["nag"] = nag
        data["todos"] = kept
        data.setdefault("archived_todos", []).append(match)
        _save(data)
    log_info(f"To-do archived ({match.get('id')}): {str(match.get('text', ''))[:120]}")
    return match


def list_archived_todos(user_id: str) -> list[dict]:
    with _LOCK:
        return [item for item in _load().get("archived_todos", []) if item.get("user_id") == user_id]


def restore_todo(user_id: str, query: str) -> dict | None:
    needle = query.strip().lower()
    with _LOCK:
        data = _load()
        match = None
        kept = []
        for item in data.get("archived_todos", []):
            if (
                match is None
                and item.get("user_id") == user_id
                and (not needle or needle in str(item.get("text", "")).lower() or item.get("id") == query)
            ):
                match = item
                continue
            kept.append(item)
        if match is None:
            return None
        match.pop("archived_at", None)
        match["done"] = False
        match["completed_at"] = None
        if match.get("repeat") == "daily":
            nag = match.get("nag") or _nag_state()
            nag["enabled"] = True
            nag["popup_open"] = False
            nag["dismissed_for_date"] = None
            nag["last_nudge_at"] = None
            match["nag"] = nag
        data["archived_todos"] = kept
        data["todos"].append(match)
        _save(data)
    log_info(f"To-do restored ({match.get('id')}): {str(match.get('text', ''))[:120]}")
    return match


def active_nag_todo(user_id: str) -> dict | None:
    with _LOCK:
        for item in _load()["todos"]:
            if item.get("user_id") != user_id:
                continue
            nag = item.get("nag") or {}
            if nag.get("popup_open"):
                return item
    return None


def mark_todo_nag_popup(user_id: str, item_id: str, *, is_open: bool) -> None:
    with _LOCK:
        data = _load()
        for item in data["todos"]:
            if item.get("user_id") == user_id and item.get("id") == item_id:
                nag = item.get("nag") or _nag_state()
                nag["popup_open"] = bool(is_open)
                item["nag"] = nag
                _save(data)
                return


def dismiss_todo_nag(user_id: str, item_id: str, *, now: datetime | None = None) -> dict | None:
    stamp = (now or datetime.now()).date().isoformat()
    with _LOCK:
        data = _load()
        match = None
        for item in data["todos"]:
            if item.get("user_id") == user_id and item.get("id") == item_id:
                nag = item.get("nag") or _nag_state()
                nag["dismissed_for_date"] = stamp
                nag["popup_open"] = False
                item["nag"] = nag
                match = item
                break
        if match is None:
            return None
        _save(data)
    return match


def _due_today(item: dict, now: datetime) -> datetime | None:
    hour = item.get("due_hour")
    if hour is None:
        return None
    try:
        minute = int(item.get("due_minute") or 0)
        return now.replace(hour=int(hour), minute=minute, second=0, microsecond=0)
    except (TypeError, ValueError):
        return None


def _reset_daily_if_new_day(item: dict, today: str) -> bool:
    if item.get("repeat") != "daily":
        return False
    changed = False
    completed = str(item.get("completed_at") or "")
    if item.get("done") and (not completed or completed[:10] != today):
        item["done"] = False
        item["completed_at"] = None
        changed = True
    nag = item.get("nag")
    if isinstance(nag, dict) and nag.get("dismissed_for_date") and nag.get("dismissed_for_date") != today:
        nag["dismissed_for_date"] = None
        nag["last_nudge_at"] = None
        nag["nudge_count"] = 0
        nag["popup_open"] = False
        nag["enabled"] = True
        item["nag"] = nag
        changed = True
    return changed


def format_due_clock(item: dict) -> str:
    hour = item.get("due_hour")
    if hour is None:
        return ""
    minute = int(item.get("due_minute") or 0)
    when = datetime.now().replace(hour=int(hour), minute=minute)
    return when.strftime("%I:%M %p").lstrip("0")


def check_due_todo_nags(
    user_id: str,
    *,
    now: datetime | None = None,
    lead_minutes: int = 15,
    early_interval_seconds: int = 180,
    due_interval_seconds: int = 90,
) -> list[dict]:
    """Slow spoken/popup nudges until the user closes the reminder themselves."""
    clock = now or datetime.now()
    due_now = clock.replace(second=0, microsecond=0)
    today = due_now.date().isoformat()
    events: list[dict] = []
    with _LOCK:
        data = _load()
        changed = False
        for item in data["todos"]:
            if item.get("user_id") != user_id:
                continue
            if _reset_daily_if_new_day(item, today):
                changed = True
            if item.get("repeat") != "daily" or item.get("done"):
                continue
            nag = item.get("nag") or _nag_state()
            if not nag.get("enabled", True):
                continue
            if nag.get("dismissed_for_date") == today:
                continue
            if nag.get("popup_open"):
                continue
            due_at = _due_today(item, due_now)
            if due_at is None:
                continue
            start_at = due_at - timedelta(minutes=max(1, int(lead_minutes)))
            if due_now < start_at:
                continue
            due = due_now >= due_at
            interval = due_interval_seconds if due else early_interval_seconds
            last_raw = nag.get("last_nudge_at")
            last = None
            if last_raw:
                try:
                    last = datetime.fromisoformat(str(last_raw))
                except ValueError:
                    last = None
            if last is not None and (clock - last).total_seconds() < max(20, int(interval)):
                continue
            nag["last_nudge_at"] = clock.isoformat(timespec="seconds")
            nag["nudge_count"] = int(nag.get("nudge_count") or 0) + 1
            nag["started_at"] = nag.get("started_at") or clock.isoformat(timespec="seconds")
            item["nag"] = nag
            changed = True
            title = str(item.get("text") or "that to-do")
            due_clock = format_due_clock(item)
            if due:
                message = f"It's time for {title}." + (f" That was set for {due_clock}." if due_clock else "")
            else:
                minutes = max(1, int((due_at - due_now).total_seconds() // 60))
                message = f"Heads up — {title} is in {minutes} minute{'s' if minutes != 1 else ''}."
                if due_clock:
                    message += f" That's at {due_clock}."
            events.append(
                {
                    "id": item.get("id"),
                    "text": title,
                    "message": message,
                    "due": due,
                    "popup_open": bool(nag.get("popup_open")),
                    "item": item,
                }
            )
        if changed:
            _save(data)
    return events


def check_due_note_reminders(user_id: str) -> list[str]:
    now = _now()
    messages: list[str] = []
    with _LOCK:
        data = _load()
        changed = False
        for item in data["notes"]:
            if item.get("user_id") != user_id:
                continue
            reminder = item.get("reminder") or {}
            if not reminder.get("enabled") or reminder.get("notified"):
                continue
            when_raw = reminder.get("when")
            if not when_raw:
                continue
            try:
                when = datetime.fromisoformat(str(when_raw))
            except ValueError:
                continue
            if now >= when:
                title = str(item.get("text") or "your note")
                messages.append(f"Reminder from your notes: {title}")
                reminder["notified"] = True
                item["reminder"] = reminder
                changed = True
        if changed:
            _save(data)
    return messages


def notes_file_path() -> Path:
    return NOTES_FILE
