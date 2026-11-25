from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

from silva.config import CONFIG_DIR
from silva.conversation.speech_policy import is_privileged
from silva.users.manager import get_active_user, is_owner

TASK_FILE = CONFIG_DIR / "future_tasks.json"

_ADD_RE = re.compile(
    r"\b(?:add|queue|note|put|write)\s+(?:that|this)?\s*(?:to|in|into)?\s*"
    r"(?:the\s+)?future updates?\s*(?:that|saying)?\s*:?\s*(.+)",
    re.I,
)
_DELETE_RE = re.compile(
    r"\b(?:delete|remove|drop)\s+(?:the\s+)?(?:future update|task)\s+(.+)",
    re.I,
)
_ASSIGN_RE = re.compile(
    r"\bassign\s+(?:the\s+)?(?:future update|task)\s+(.+?)\s+to\s+(.+)",
    re.I,
)
_LIST_RE = re.compile(r"\b(?:list|show|read|what.s in)\s+(?:the\s+)?future updates?\b", re.I)
_COMPLETE_RE = re.compile(
    r"\b(?:complete|finish|mark)\s+(?:the\s+)?(?:future update|task)\s+(.+)",
    re.I,
)
_VERIFY_RE = re.compile(
    r"\b(?:verify|check|approve)\s+(?:the\s+)?(?:completed\s+)?(?:future update|task)\s+(.+)",
    re.I,
)


def _read() -> list[dict]:
    try:
        if TASK_FILE.exists():
            data = json.loads(TASK_FILE.read_text(encoding="utf-8"))
            records = data.get("tasks") or []
            return [item for item in records if isinstance(item, dict)]
    except (OSError, json.JSONDecodeError):
        pass
    return []


def _write(records: list[dict]) -> None:
    TASK_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = TASK_FILE.with_suffix(".json.tmp")
    temp.write_text(json.dumps({"tasks": records}, indent=2), encoding="utf-8")
    os.replace(temp, TASK_FILE)


def list_tasks(limit: int = 30) -> list[dict]:
    return _read()[-max(1, int(limit)) :][::-1]


def add_task(text: str, *, created_by: str = "", assigned_to: str = "") -> dict:
    value = str(text or "").strip(" .")
    record = {
        "id": uuid.uuid4().hex[:8],
        "text": value,
        "status": "open",
        "assigned_to": str(assigned_to or ""),
        "created_by": str(created_by or ""),
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "voice",
    }
    records = _read()
    records.append(record)
    _write(records)
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


def delete_task(query: str) -> tuple[bool, str]:
    matches, exact = _find(query)
    if exact is None:
        return False, "I could not find one clear future update to delete."
    records = [item for item in _read() if item.get("id") != exact.get("id")]
    _write(records)
    return True, f"Deleted future update {exact['id']}: {exact.get('text', '')[:80]}"


def assign_task(query: str, admin: str) -> tuple[bool, str]:
    from silva.users.manager import load_store

    matches, exact = _find(query)
    if exact is None:
        return False, "I could not find one clear future update to assign."
    target = str(admin or "").strip().lower()
    users = load_store().get("users") or {}
    chosen = None
    for user_id, user in users.items():
        role = str(user.get("role") or "").lower()
        tier = int(user.get("tier") or 0)
        if role not in ("admin", "owner") and tier < 4:
            continue
        if (
            str(user_id).lower() == target
            or str(user.get("name") or "").lower() == target
            or target in str(user.get("name") or "").lower()
        ):
            chosen = user_id
            break
    if chosen is None:
        return False, "I could not find an admin with that name."
    records = _read()
    for record in records:
        if record.get("id") == exact.get("id"):
            record["assigned_to"] = chosen
            record["status"] = "assigned"
    _write(records)
    name = str(users.get(chosen, {}).get("name") or chosen)
    return True, f"Assigned future update {exact['id']} to {name}."


def complete_task(query: str) -> tuple[bool, str]:
    matches, exact = _find(query)
    if exact is None:
        return False, "I could not find one clear future update to complete."
    records = _read()
    for record in records:
        if record.get("id") == exact.get("id"):
            record["status"] = "○"
            record["completed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            record["verified"] = False
    _write(records)
    return True, f"Marked future update {exact['id']} complete. It shows a blank circle until verified."


def verify_task(query: str, *, verifier_id: str = "") -> tuple[bool, str]:
    matches, exact = _find(query)
    if exact is None:
        return False, "I could not find one clear future update to verify."
    if str(exact.get("status") or "") != "○":
        return False, "That update is not waiting for verification."
    records = [
        item
        for item in _read()
        if item.get("id") != exact.get("id")
    ]
    _write(records)
    return True, f"Verified future update {exact['id']}. It has been deleted."


def match_future_task_speech(text: str) -> tuple[str, str, str] | None:
    value = str(text or "").strip()
    if not value:
        return None
    if _LIST_RE.search(value):
        return ("list", "", "")
    assign = _ASSIGN_RE.search(value)
    if assign:
        return ("assign", assign.group(1).strip(), assign.group(2).strip())
    delete = _DELETE_RE.search(value)
    if delete:
        return ("delete", delete.group(1).strip(" ."), "")
    verify = _VERIFY_RE.search(value)
    if verify:
        return ("verify", verify.group(1).strip(" ."), "")
    complete = _COMPLETE_RE.search(value)
    if complete:
        return ("complete", complete.group(1).strip(" ."), "")
    add = _ADD_RE.search(value)
    if add:
        return ("add", add.group(1).strip(" ."), "")
    return None


def is_future_task_command(text: str) -> bool:
    return match_future_task_speech(text) is not None


def handle_future_task_speech(assistant, text: str) -> bool:
    parsed = match_future_task_speech(text)
    if parsed is None:
        return False
    user = get_active_user() or {}
    if not is_owner(user):
        assistant.say("Only the owner can manage future updates.", interruptible=False)
        return True
    action, value, target = parsed
    owner_id = str(user.get("id") or "owner")
    if action == "add":
        record = add_task(value, created_by=owner_id)
        assistant.say(f"Added future update {record['id']}: {record['text'][:100]}", interruptible=False)
        return True
    if action == "delete":
        ok, message = delete_task(value)
        assistant.say(message, interruptible=False)
        return True
    if action == "assign":
        ok, message = assign_task(value, target)
        assistant.say(message, interruptible=False)
        return True
    if action == "complete":
        ok, message = complete_task(value)
        assistant.say(message, interruptible=False)
        return True
    if action == "verify":
        if not is_privileged(owner_id):
            assistant.say("Only the owner or an admin can verify future updates.", interruptible=False)
            return True
        ok, message = verify_task(value, verifier_id=owner_id)
        assistant.say(message, interruptible=False)
        return True
    tasks = list_tasks(5)
    if not tasks:
        assistant.say("There are no future updates yet.", interruptible=False)
        return True
    lines = [f"{item['id']}: {item.get('text', '')[:60]}" for item in tasks]
    assistant.say("Future updates: " + "; ".join(lines), interruptible=False)
    return True
