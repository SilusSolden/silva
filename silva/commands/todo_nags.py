"""Speak/print daily to-do reminders without flooding the console."""

from __future__ import annotations

import time

from silva.config import load_config
from silva.logger import log_response
from silva.users.features import FEATURE_NOTES, feature_allowed
from silva.users.manager import get_active_user


def announce_todo_nags(assistant) -> None:
    if assistant._scheduled_alerts_paused():
        return
    user = get_active_user()
    if not feature_allowed(user, FEATURE_NOTES):
        return
    if assistant._speaking:
        return

    from silva.commands.notes_store import check_due_todo_nags
    from silva.gui.todo_reminder_popup import show_todo_reminder_popup

    config = load_config()
    user_id = user.get("id", "guest")
    due_interval = max(20, int(config.get("todo_nag_due_seconds", 90)))
    events = check_due_todo_nags(
        user_id,
        lead_minutes=int(config.get("todo_nag_lead_minutes", 15)),
        early_interval_seconds=int(config.get("todo_nag_early_seconds", 180)),
        due_interval_seconds=due_interval,
    )
    if not events:
        return

    shown = getattr(assistant, "_todo_nag_shown", None)
    if not isinstance(shown, dict):
        assistant._todo_nag_shown = {}
        shown = assistant._todo_nag_shown
    now_ts = time.time()

    for event in events:
        item = event.get("item") or {}
        item_id = str(event.get("id") or item.get("id") or "")
        message = str(event.get("message") or "").strip()
        if not message:
            continue
        last = float(shown.get(item_id, 0.0) or 0.0)
        if item_id and now_ts - last < due_interval:
            continue
        if item_id:
            shown[item_id] = now_ts
        print(f"Silva: {message}")
        log_response(message)
        if assistant._asleep:
            continue
        if not event.get("popup_open"):
            try:
                show_todo_reminder_popup(user_id, item, message)
            except Exception:
                pass
        assistant.say(message, interruptible=False, also_print=False)
