from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

from silva.config import CONFIG_DIR
from silva.conversation.speech_policy import is_privileged
from silva.users.manager import get_active_user

UPDATE_FILE = CONFIG_DIR / "team_updates.json"

_SUBMIT_RE = re.compile(
    r"\b(?:submit|suggest|add)\s+(?:team\s+)?(?:update|idea)\s+(.+)",
    re.I,
)
_APPROVE_RE = re.compile(r"\bapprove\s+(?:team\s+)?update\s+(.+)", re.I)
_REJECT_RE = re.compile(r"\breject\s+(?:team\s+)?update\s+(.+)", re.I)
_LIST_RE = re.compile(r"\b(?:list|show)\s+(?:team\s+)?updates?\b", re.I)
_EMAIL_RE = re.compile(r"\b(?:from email|email|reply to)\s+([^\s@]+@[^\s@]+\.[^\s@]+)\b", re.I)


def _read() -> list[dict]:
    if not UPDATE_FILE.exists():
        return []
    try:
        data = json.loads(UPDATE_FILE.read_text(encoding="utf-8"))
        records = data.get("updates") or []
        return [item for item in records if isinstance(item, dict)]
    except (OSError, json.JSONDecodeError):
        return []


def _write(records: list[dict]) -> None:
    UPDATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = UPDATE_FILE.with_suffix(".json.tmp")
    temp.write_text(json.dumps({"updates": records}, indent=2), encoding="utf-8")
    os.replace(temp, UPDATE_FILE)


def list_updates(status: str = "", limit: int = 50) -> list[dict]:
    records = _read()
    if status:
        records = [item for item in records if str(item.get("status") or "") == status]
    return records[-max(1, int(limit)) :][::-1]


def submit_update(
    text: str,
    *,
    user_id: str = "",
    user_name: str = "",
    email: str = "",
) -> dict:
    matched = _EMAIL_RE.search(str(text or ""))
    source_email = str(email or "").strip() or (matched.group(1) if matched else "")
    value = _EMAIL_RE.sub("", str(text or "")).strip(" .")
    record = {
        "id": uuid.uuid4().hex[:8],
        "text": value,
        "status": "pending",
        "user_id": str(user_id or ""),
        "user_name": str(user_name or ""),
        "email": source_email,
        "submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    records = _read()
    records.append(record)
    _write(records)

    from silva.notifications.dispatch import notify_owner_async

    notify_owner_async(
        f"New team update from {user_name or user_id}: {value}",
        reason="team_update",
        prefer_telegram=True,
    )
    return record


def _find(query: str) -> tuple[list[dict], dict | None]:
    value = str(query or "").strip().lower()
    records = _read()
    if not value:
        return records, None
    exact = [item for item in records if str(item.get("id") or "").lower() == value]
    if exact:
        return exact, exact[0]
    matches = [
        item
        for item in records
        if value in str(item.get("text") or "").lower()
        or value in str(item.get("id") or "").lower()
    ]
    return matches, matches[0] if len(matches) == 1 else None


def _decide(query: str, status: str, *, approver_id: str, reply: str = "", email_reply: bool = False) -> tuple[bool, str]:
    _matches, exact = _find(query)
    if exact is None:
        return False, "I could not find one clear team update."
    records = _read()
    for item in records:
        if item.get("id") == exact.get("id"):
            item["status"] = status
            item["decided_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            item["decided_by"] = str(approver_id or "")
            item["reply"] = str(reply or "")
            item["email_reply"] = bool(email_reply)
    _write(records)

    if status == "approved":
        from silva.dev.future_tasks import add_task

        add_task(str(exact.get("text") or ""), created_by=str(approver_id or ""), assigned_to="")
        return True, f"Approved team update {exact['id']} and added it to future updates."

    _notify_rejection(exact, reply=reply, email_reply=email_reply)
    return True, f"Rejected team update {exact['id']}."


def approve_update(
    query: str,
    *,
    approver_id: str = "",
    reply: str = "",
    email_reply: bool = False,
) -> tuple[bool, str]:
    return _decide(query, "approved", approver_id=approver_id, reply=reply, email_reply=email_reply)


def reject_update(
    query: str,
    *,
    approver_id: str = "",
    reply: str = "",
    email_reply: bool = False,
) -> tuple[bool, str]:
    return _decide(query, "rejected", approver_id=approver_id, reply=reply, email_reply=email_reply)


def _notify_rejection(record: dict, *, reply: str = "", email_reply: bool = False) -> None:
    message = (
        f"Team update {record.get('id', '')} was not approved and will not be added to Silva.\n"
        f"Update: {record.get('text', '')}\n"
        f"Reply: {reply or 'No extra reply was provided.'}"
    )
    try:
        from silva.gui.update_popup import show_message_popup

        show_message_popup(message, title="Silva update not approved")
    except Exception:
        pass
    if email_reply:
        from silva.notifications.email import send_email_reply

        send_email_reply(str(record.get("email") or ""), "update not approved", message)


def match_team_update_speech(text: str) -> tuple[str, str] | None:
    value = str(text or "").strip()
    if not value:
        return None
    if _LIST_RE.search(value):
        return ("list", "")
    approve = _APPROVE_RE.search(value)
    if approve:
        return ("approve", approve.group(1).strip(" ."))
    reject = _REJECT_RE.search(value)
    if reject:
        return ("reject", reject.group(1).strip(" ."))
    submit = _SUBMIT_RE.search(value)
    if submit:
        return ("submit", submit.group(1).strip(" ."))
    return None


def is_team_update_command(text: str) -> bool:
    return match_team_update_speech(text) is not None


def handle_team_update_speech(assistant, text: str) -> bool:
    parsed = match_team_update_speech(text)
    if parsed is None:
        return False
    action, value = parsed
    getter = getattr(assistant, "_user_id", None)
    user_id = getter() if callable(getter) else str((get_active_user() or {}).get("id") or "guest")
    user = get_active_user() or {}
    name = str(user.get("name") or user_id)

    if action == "submit":
        record = submit_update(value, user_id=user_id, user_name=name)
        assistant.say(f"Submitted team update {record['id']}.", interruptible=False)
        return True

    if not is_privileged(user_id):
        assistant.say("Only the owner or an admin can approve or reject team updates.", interruptible=False)
        return True

    if action == "list":
        items = list_updates("pending", 5)
        if not items:
            assistant.say("There are no pending team updates.", interruptible=False)
        else:
            lines = [f"{item['id']}: {item.get('text', '')[:60]}" for item in items]
            assistant.say("Pending team updates: " + "; ".join(lines), interruptible=False)
        return True

    if action == "approve":
        ok, message = approve_update(value, approver_id=user_id)
    else:
        ok, message = reject_update(value, approver_id=user_id)
    assistant.say(message, interruptible=False)
    return True
