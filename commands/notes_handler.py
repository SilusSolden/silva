"""Handle spoken notes, reminders, and to-do list commands."""

from __future__ import annotations

from silva.commands.appointments import _format_when, parse_datetime_from_text, split_title_and_when
from silva.commands.notes_phrases import (
    TYPE_FAIL_LIMIT,
    is_no_speech,
    is_weak_note_body,
    is_yes_speech,
    looks_like_mumble,
    match_notes_speech,
    match_reminder_choice,
    needs_todo_confirm,
    parse_todo_clock,
    parse_todo_number,
    strip_daily_todo_text,
)
from silva.commands.notes_store import (
    active_nag_todo,
    add_note,
    add_todo,
    archive_todo,
    clear_todos,
    complete_todo_by_query,
    delete_note,
    delete_todo,
    dismiss_todo_nag,
    find_notes,
    format_due_clock,
    latest_todo,
    list_archived_todos,
    list_notes,
    list_todos,
    move_todo,
    numbered_todos,
    restore_todo,
    set_note_reminder,
    todo_by_number,
)
from silva.config import load_config


def type_fail_limit() -> int:
    try:
        return max(2, int(load_config().get("notes_type_fail_limit", TYPE_FAIL_LIMIT)))
    except (TypeError, ValueError):
        return TYPE_FAIL_LIMIT


def _await_body_flow(kind: str, fails: int = 1) -> dict:
    return {"phase": "await_body", "kind": kind, "fails": fails}


def _open_type_flow(kind: str) -> dict:
    return {"phase": "open_type", "kind": kind}


def _type_prompt(kind: str) -> str:
    if kind == "todo":
        return "I opened a box so you can type it. Press Enter or Save."
    return "I opened a box so you can type the note. Press Enter or Save."


def _speech_unsure(text: str) -> bool:
    confidence = None
    try:
        from silva.stt import last_listen_confidence

        confidence = last_listen_confidence()
    except Exception:
        confidence = None
    return looks_like_mumble(text, confidence=confidence)


def _open_type_for_mumble(kind: str) -> tuple[str, dict]:
    return _type_prompt(kind if kind in {"note", "todo"} else "todo"), _open_type_flow(
        kind if kind in {"note", "todo"} else "todo"
    )


def _ask_todo_confirm(
    body: str,
    *,
    daily: bool = False,
    time_hm: tuple[int, int] | None = None,
) -> tuple[str, dict]:
    clock = ""
    if time_hm:
        clock = format_due_clock({"due_hour": time_hm[0], "due_minute": time_hm[1]})
    heard = (body or "").strip() or "that to-do"
    extra = f", {clock}" if clock else ""
    return (
        f"I heard {heard}{extra}. Is that right?",
        {
            "phase": "await_body",
            "kind": "confirm_todo",
            "query": body,
            "daily": daily,
            "time_hm": time_hm,
            "fails": 1,
        },
    )


def _todo_needs_confirm(text: str) -> bool:
    confidence = None
    try:
        from silva.stt import last_listen_confidence

        confidence = last_listen_confidence()
    except Exception:
        confidence = None
    return needs_todo_confirm(text, confidence=confidence)


def _maybe_fail_to_type(kind: str, fails: int) -> tuple[str, dict]:
    if fails >= type_fail_limit():
        return _type_prompt(kind), _open_type_flow(kind)
    if kind == "todo":
        return (
            "I didn't catch the to-do. Say it again, or say type the to-do if you want to type it.",
            _await_body_flow(kind, fails),
        )
    return (
        "I didn't catch the note. Say it again, or say type the note if you want to type it.",
        _await_body_flow(kind, fails),
    )


def _save_note(user_id: str, body: str) -> str:
    title, when = split_title_and_when(body)
    remind_at = when or parse_datetime_from_text(body)
    note_text = title if title and title.lower() != "appointment" else body.strip()
    if not note_text or note_text.lower() == "appointment":
        note_text = body.strip()
    entry = add_note(user_id, note_text, remind_at=remind_at)
    msg = f"Noted. {entry['text']}"
    if remind_at is not None:
        msg += f" I'll remind you { _format_when(remind_at) }."
    return msg


def _save_todo(
    user_id: str,
    body: str,
    *,
    daily: bool = False,
    time_hm: tuple[int, int] | None = None,
) -> str:
    clock = time_hm or parse_todo_clock(body)
    title = strip_daily_todo_text(body) if daily or clock else body
    if not title:
        title = body.strip()
    hour, minute = clock if clock else (None, None)
    item = add_todo(
        user_id,
        title,
        repeat="daily" if daily or clock else None,
        due_hour=hour,
        due_minute=minute,
    )
    try:
        from silva.gui.todo_popup import refresh_todo_popup

        refresh_todo_popup(user_id)
    except Exception:
        pass
    number = len(numbered_todos(user_id))
    clock = format_due_clock(item) if item.get("due_hour") is not None else ""
    try:
        from silva.gui.todo_added_toast import show_todo_added_toast

        show_todo_added_toast(number, str(item.get("text") or ""), clock)
    except Exception:
        pass
    if item.get("repeat") == "daily" and item.get("due_hour") is None:
        return f"Added {number}. {item['text']}. What time?"
    if clock:
        return f"Added {number}. {item['text']}, {clock}."
    return f"Added {number}. {item['text']}."


def _refresh_todos(user_id: str) -> None:
    try:
        from silva.gui.todo_popup import refresh_todo_popup

        refresh_todo_popup(user_id)
    except Exception:
        pass


def _archive_message(user_id: str, query: str) -> str:
    target = query
    if is_weak_note_body(query):
        current = active_nag_todo(user_id)
        if current is None:
            return ""
        target = str(current.get("id") or current.get("text") or "")
    archived = archive_todo(user_id, target)
    _refresh_todos(user_id)
    try:
        from silva.gui.todo_reminder_popup import close_todo_reminder_popup

        close_todo_reminder_popup(str(archived.get("id")) if archived else None)
    except Exception:
        pass
    if archived:
        return (
            f"I took {archived.get('text', 'that to-do')} off your list. "
            "Say bring it back if you still need it later."
        )
    return ""


def _format_notes(user_id: str, query: str = "") -> str:
    rows = find_notes(user_id, query) if query else list_notes(user_id)
    if not rows:
        if query:
            return f"I don't have a note about {query}."
        return "You don't have any notes yet. Say note this, then what you want saved."
    lines = ["Here are your notes:"] if not query else [f"Here's what I have about {query}:"]
    for item in rows[-12:]:
        reminder = item.get("reminder") or {}
        extra = ""
        if reminder.get("enabled") and reminder.get("when") and not reminder.get("notified"):
            try:
                from datetime import datetime

                extra = f" Reminder {_format_when(datetime.fromisoformat(str(reminder['when'])))}."
            except ValueError:
                extra = " Reminder set."
        lines.append(f"- {item.get('text', '')}{extra}")
    if len(rows) > 12:
        lines.append(f"That's the latest 12 of {len(rows)} notes.")
    return " ".join(lines) if len(lines) <= 4 else "\n".join(lines)


def _format_todo_line(number: int, item: dict) -> str:
    return f"{number}. {item.get('text', '')}"


def _format_todos(user_id: str) -> str:
    rows = numbered_todos(user_id)
    if not rows:
        return "Your to-do list is empty."
    lines = [_format_todo_line(number, item) for number, item in rows]
    return "\n".join(lines)


def _choice_prompt(user_id: str, action: str) -> tuple[str, dict | None]:
    rows = numbered_todos(user_id)
    if not rows:
        return "Your to-do list is empty.", None
    if len(rows) == 1:
        return "", {"phase": "one_item", "item": rows[0][1], "number": 1}
    verb = {"delete": "delete", "archive": "take off", "edit": "change", "move": "move", "complete": "check off"}.get(
        action, action
    )
    lines = [f"Which one should I {verb}? Say the number."]
    for number, item in rows:
        lines.append(_format_todo_line(number, item))
    return "\n".join(lines), {"phase": "await_body", "kind": "pick_todo", "action": action, "fails": 1}


def _resolve_todo(user_id: str, query: str, number: int | None = None) -> dict | None:
    if number is not None:
        found = todo_by_number(user_id, number)
        if found:
            return found
    parsed = parse_todo_number(query) if query else None
    if parsed is not None:
        found = todo_by_number(user_id, parsed)
        if found:
            return found
    if query:
        for item in list_todos(user_id):
            if query.strip().lower() in str(item.get("text", "")).lower() or item.get("id") == query:
                return item
    return None


def handle_notes_speech(user_id: str, text: str) -> tuple[str | None, dict | None]:
    speech = match_notes_speech(text)
    if speech is None:
        return None, None

    if speech.action == "cancel":
        return "Okay, I won't save that.", None

    if speech.action == "type":
        kind = speech.kind if speech.kind in {"note", "todo"} else "note"
        return _type_prompt(kind), _open_type_flow(kind)

    if speech.action == "open_todo":
        return "Opening your to-do list.", {"phase": "open_todo"}

    if speech.action == "close_todo":
        return "Closing your to-do list.", {"phase": "close_todo"}

    if speech.action == "list_todo":
        return _format_todos(user_id), None

    if speech.action == "ask_reminder":
        return "Notes or to-do list?", _await_body_flow("pick_reminder")

    if speech.action == "list_notes":
        return _format_notes(user_id), None

    if speech.action == "search_note":
        if is_weak_note_body(speech.query):
            return "What should I look up in your notes?", _await_body_flow("search")
        return _format_notes(user_id, speech.query), None

    if speech.action == "delete_note":
        if is_weak_note_body(speech.query):
            return "Which note should I delete?", _await_body_flow("delete_note")
        deleted = delete_note(user_id, speech.query)
        if deleted:
            return f"Deleted the note: {deleted.get('text', '')}", None
        return "I could not find that note.", None

    if speech.action == "remind_note":
        if is_weak_note_body(speech.query):
            return "Which note should I remind you about, and when?", _await_body_flow("remind_note")
        title, when = split_title_and_when(speech.query)
        remind_at = when or parse_datetime_from_text(speech.query)
        if remind_at is None:
            return "Tell me when to remind you about that note.", {
                "phase": "await_body",
                "kind": "remind_note",
                "fails": 1,
                "query": speech.query,
            }
        updated = set_note_reminder(user_id, title if title.lower() != "appointment" else speech.query, remind_at)
        if updated is None:
            add_note(user_id, title if title.lower() != "appointment" else speech.query, remind_at=remind_at)
            return (
                f"I didn't have that note yet, so I saved it and will remind you {_format_when(remind_at)}.",
                None,
            )
        return f"I'll remind you about {updated.get('text', 'that note')} {_format_when(remind_at)}.", None

    if speech.action == "add_todo":
        if _speech_unsure(speech.query):
            return _open_type_for_mumble("todo")
        if is_weak_note_body(speech.query):
            kind = "daily_todo" if speech.daily else "todo"
            prompt = "What daily to-do should I add, and at what time?" if speech.daily else "What should I add to your to-do list?"
            return prompt, _await_body_flow(kind)
        if speech.daily and speech.time_hm is None:
            return "What time?", {
                "phase": "await_body",
                "kind": "daily_time",
                "fails": 1,
                "query": speech.query,
            }
        if _todo_needs_confirm(speech.query) or _todo_needs_confirm(text):
            return _ask_todo_confirm(speech.query, daily=speech.daily, time_hm=speech.time_hm)
        return _save_todo(user_id, speech.query, daily=speech.daily, time_hm=speech.time_hm), None

    if speech.action == "clear_todos":
        count = clear_todos(user_id, archive=True)
        _refresh_todos(user_id)
        try:
            from silva.gui.todo_reminder_popup import close_todo_reminder_popup

            close_todo_reminder_popup()
        except Exception:
            pass
        if not count:
            return "Your to-do list was already empty.", None
        return "I cleared the to-do list. You can add them again.", None

    if speech.action == "undo_last_todo":
        last = latest_todo(user_id)
        if last is None:
            return "There's no to-do to undo.", None
        msg = _archive_message(user_id, str(last.get("id")))
        return msg or "I couldn't undo that.", None

    if speech.action == "edit_todo":
        item = _resolve_todo(user_id, speech.query, speech.number)
        if item is None:
            prompt, flow = _choice_prompt(user_id, "edit")
            if flow and flow.get("phase") == "one_item":
                item = flow["item"]
            elif flow:
                return prompt, {**flow, "kind": "pick_todo"}
            else:
                return prompt, None
        return "I opened a box so you can type the new wording. Press Enter or Save.", {
            "phase": "open_type",
            "kind": "todo",
            "replace_id": str(item.get("id")),
        }

    if speech.action == "move_todo":
        src = speech.number or parse_todo_number(speech.query)
        dest = speech.dest_number
        if src is None:
            prompt, flow = _choice_prompt(user_id, "move")
            if flow and flow.get("phase") == "await_body":
                return prompt, flow
            return "Which number should I move, and where? Say move 2 to 1.", None
        if dest is None:
            return "Where should I move it? Say to 1, or up, or down.", {
                "phase": "await_body",
                "kind": "move_dest",
                "fails": 1,
                "number": src,
            }
        moved = move_todo(user_id, src, dest)
        _refresh_todos(user_id)
        if moved is None:
            return "I couldn't move that to-do.", None
        return f"Moved. {moved.get('text', 'That to-do')} is now number {max(1, dest)}.", None

    if speech.action == "archive_todo":
        item = _resolve_todo(user_id, speech.query, speech.number)
        if item is not None:
            msg = _archive_message(user_id, str(item.get("id")))
            return msg or "I could not find that on your to-do list.", None
        msg = _archive_message(user_id, speech.query)
        if msg:
            return msg, None
        if is_weak_note_body(speech.query):
            prompt, flow = _choice_prompt(user_id, "archive")
            if flow and flow.get("phase") == "one_item":
                msg = _archive_message(user_id, str(flow["item"].get("id")))
                return msg or "I could not find that on your to-do list.", None
            if flow:
                return prompt, flow
            return "Which to-do do you no longer need?", _await_body_flow("archive_todo")
        prompt, flow = _choice_prompt(user_id, "archive")
        if flow and flow.get("phase") == "await_body":
            return prompt, flow
        return "I could not find that on your to-do list.", None

    if speech.action == "restore_todo":
        if is_weak_note_body(speech.query):
            rows = list_archived_todos(user_id)
            if len(rows) == 1:
                restored = restore_todo(user_id, str(rows[0].get("id")))
                _refresh_todos(user_id)
                if restored:
                    return f"I put {restored.get('text', 'that to-do')} back on your list.", None
            if not rows:
                return "I don't have any removed to-dos to bring back.", None
            return "Which to-do should I bring back?", _await_body_flow("restore_todo")
        restored = restore_todo(user_id, speech.query)
        _refresh_todos(user_id)
        if restored:
            return f"I put {restored.get('text', 'that to-do')} back on your list.", None
        return "I couldn't find that in your saved to-dos. Say what is my to-do list to hear what's active.", None

    if speech.action == "complete_todo":
        if is_weak_note_body(speech.query):
            return "Which to-do did you finish?", _await_body_flow("complete_todo")
        done = complete_todo_by_query(user_id, speech.query, done=True)
        try:
            from silva.gui.todo_popup import refresh_todo_popup

            refresh_todo_popup(user_id)
        except Exception:
            pass
        if done:
            dismiss_todo_nag(user_id, str(done.get("id") or ""))
            try:
                from silva.gui.todo_reminder_popup import close_todo_reminder_popup

                close_todo_reminder_popup(str(done.get("id") or ""))
            except Exception:
                pass
            return f"Checked off {done.get('text', 'that to-do')}.", None
        return "I could not find that on your to-do list.", None

    if speech.action == "delete_todo":
        item = _resolve_todo(user_id, speech.query, speech.number)
        if item is None and is_weak_note_body(speech.query) and speech.number is None:
            prompt, flow = _choice_prompt(user_id, "delete")
            if flow and flow.get("phase") == "one_item":
                item = flow["item"]
            elif flow:
                return prompt, flow
            else:
                return prompt, None
        if item is None:
            prompt, flow = _choice_prompt(user_id, "delete")
            if flow and flow.get("phase") == "one_item":
                item = flow["item"]
            elif flow:
                return prompt, flow
            return "I could not find that on your to-do list.", None
        deleted = delete_todo(user_id, str(item.get("id")))
        _refresh_todos(user_id)
        if deleted:
            label = speech.number or parse_todo_number(speech.query)
            prefix = f"{label}. " if label else ""
            return f"Removed {prefix}{deleted.get('text', 'that to-do')}.", None
        return "I could not find that on your to-do list.", None

    if speech.action == "add_note":
        if _speech_unsure(speech.query):
            return _open_type_for_mumble("note")
        if is_weak_note_body(speech.query):
            return "What should I note?", _await_body_flow("note")
        return _save_note(user_id, speech.query), None

    return None, None


def continue_notes_flow(user_id: str, text: str, flow: dict) -> tuple[str, dict | None]:
    kind = str(flow.get("kind") or "note")
    fails = int(flow.get("fails") or 0)
    normalized = text.strip().lower()
    if normalized in {"cancel", "never mind", "nevermind", "forget it", "stop that"}:
        return "Okay, I won't save that.", None

    if kind == "pick_reminder":
        choice = match_reminder_choice(text)
        if choice == "note":
            return _format_notes(user_id), None
        if choice == "todo":
            rows = numbered_todos(user_id)
            msg = _format_todos(user_id)
            if rows:
                return msg, {"phase": "open_todo"}
            return msg, None
        return "Notes or to-do list?", {
            "phase": "await_body",
            "kind": "pick_reminder",
            "fails": fails + 1,
        }

    if kind == "confirm_todo":
        body = str(flow.get("query") or "").strip()
        daily = bool(flow.get("daily"))
        time_hm = flow.get("time_hm")
        if isinstance(time_hm, list):
            time_hm = tuple(time_hm)
        if is_yes_speech(text):
            if not body:
                return _type_prompt("todo"), _open_type_flow("todo")
            return _save_todo(user_id, body, daily=daily, time_hm=time_hm), None
        if is_no_speech(text):
            return _type_prompt("todo"), _open_type_flow("todo")
        if _speech_unsure(text):
            return _open_type_for_mumble("todo")
        if not is_weak_note_body(text):
            clock = parse_todo_clock(text) or time_hm
            return _save_todo(user_id, text, daily=daily or clock is not None, time_hm=clock), None
        return _maybe_fail_to_type("todo", fails + 1)

    speech = match_notes_speech(text)
    if speech is not None and speech.action not in {"cancel"}:
        if speech.action != "add_note" or not is_weak_note_body(speech.query):
            return handle_notes_speech(user_id, text)

    if _speech_unsure(text) and kind in {"todo", "daily_todo", "note", "daily_time"}:
        return _open_type_for_mumble("todo" if "todo" in kind or kind == "daily_time" else "note")

    if kind == "pick_todo":
        number = parse_todo_number(text)
        if number is None:
            if _speech_unsure(text):
                return _open_type_for_mumble("todo")
            return _maybe_fail_to_type("todo", fails + 1)
        item = todo_by_number(user_id, number)
        if item is None:
            return "I don't have that number. Say what is my to-do list.", None
        action = str(flow.get("action") or "delete")
        if action == "edit":
            return _type_prompt("todo"), {"phase": "open_type", "kind": "todo", "replace_id": str(item.get("id"))}
        if action == "move":
            return "Where should I move it? Say to 1, or up, or down.", {
                "phase": "await_body",
                "kind": "move_dest",
                "fails": 1,
                "number": number,
            }
        if action == "archive":
            msg = _archive_message(user_id, str(item.get("id")))
            return msg or "I couldn't take that off the list.", None
        if action == "complete":
            done = complete_todo_by_query(user_id, str(item.get("id")), done=True)
            _refresh_todos(user_id)
            if done:
                return f"Checked off {number}. {done.get('text', '')}.", None
            return "I could not find that on your to-do list.", None
        deleted = delete_todo(user_id, str(item.get("id")))
        _refresh_todos(user_id)
        if deleted:
            return f"Removed {number}. {deleted.get('text', '')}.", None
        return "I could not find that on your to-do list.", None

    if kind == "move_dest":
        src = int(flow.get("number") or 0)
        dest = parse_todo_number(text)
        if dest is None:
            return _maybe_fail_to_type("todo", fails + 1)
        moved = move_todo(user_id, src, dest)
        _refresh_todos(user_id)
        if moved is None:
            return "I couldn't move that to-do.", None
        return f"Moved. {moved.get('text', 'That to-do')} is now number {dest}.", None

    if kind == "search":
        if is_weak_note_body(text):
            return _maybe_fail_to_type("note", fails + 1)
        return _format_notes(user_id, text), None

    if kind == "delete_note":
        if is_weak_note_body(text):
            return _maybe_fail_to_type("note", fails + 1)
        deleted = delete_note(user_id, text)
        if deleted:
            return f"Deleted the note: {deleted.get('text', '')}", None
        return "I could not find that note.", None

    if kind == "remind_note":
        query = str(flow.get("query") or text)
        title, when = split_title_and_when(text)
        remind_at = when or parse_datetime_from_text(text)
        if remind_at is None:
            return _maybe_fail_to_type("note", fails + 1)
        needle = title if title.lower() != "appointment" else query
        updated = set_note_reminder(user_id, needle, remind_at)
        if updated is None:
            add_note(user_id, needle, remind_at=remind_at)
            return f"Saved it and I'll remind you {_format_when(remind_at)}.", None
        return f"I'll remind you about {updated.get('text', 'that note')} {_format_when(remind_at)}.", None

    if kind == "complete_todo":
        if is_weak_note_body(text):
            return _maybe_fail_to_type("todo", fails + 1)
        done = complete_todo_by_query(user_id, text, done=True)
        try:
            from silva.gui.todo_popup import refresh_todo_popup

            refresh_todo_popup(user_id)
        except Exception:
            pass
        if done:
            dismiss_todo_nag(user_id, str(done.get("id") or ""))
            try:
                from silva.gui.todo_reminder_popup import close_todo_reminder_popup

                close_todo_reminder_popup(str(done.get("id") or ""))
            except Exception:
                pass
            return f"Checked off {done.get('text', 'that to-do')}.", None
        return "I could not find that on your to-do list.", None

    if kind == "delete_todo":
        if is_weak_note_body(text):
            return _maybe_fail_to_type("todo", fails + 1)
        deleted = delete_todo(user_id, text)
        _refresh_todos(user_id)
        if deleted:
            return f"Removed {deleted.get('text', 'that to-do')} from your list for good.", None
        return "I could not find that on your to-do list.", None

    if kind == "archive_todo":
        if is_weak_note_body(text):
            return _maybe_fail_to_type("todo", fails + 1)
        msg = _archive_message(user_id, text)
        if msg:
            return msg, None
        return "I could not find that on your to-do list.", None

    if kind == "restore_todo":
        if is_weak_note_body(text):
            return _maybe_fail_to_type("todo", fails + 1)
        restored = restore_todo(user_id, text)
        _refresh_todos(user_id)
        if restored:
            return f"I put {restored.get('text', 'that to-do')} back on your list.", None
        return "I couldn't find that in your saved to-dos.", None

    if kind == "daily_time":
        clock = parse_todo_clock(text)
        if clock is None:
            return _maybe_fail_to_type("todo", fails + 1)
        title = str(flow.get("query") or "").strip() or "that to-do"
        return _save_todo(user_id, title, daily=True, time_hm=clock), None

    if is_weak_note_body(text):
        return _maybe_fail_to_type(kind if kind in {"note", "todo"} else "note", fails + 1)

    if kind in {"todo", "daily_todo"}:
        daily = kind == "daily_todo" or parse_todo_clock(text) is not None
        return _save_todo(user_id, text, daily=daily, time_hm=parse_todo_clock(text)), None
    return _save_note(user_id, text), None


def handle_silence_during_notes(flow: dict | None) -> tuple[str | None, dict | None]:
    if not flow or flow.get("phase") != "await_body":
        return None, flow
    kind = str(flow.get("kind") or "note")
    fails = int(flow.get("fails") or 0) + 1
    if fails >= type_fail_limit():
        return _type_prompt(kind if kind in {"note", "todo"} else "note"), _open_type_flow(
            kind if kind in {"note", "todo"} else "note"
        )
    flow = dict(flow)
    flow["fails"] = fails
    return None, flow
