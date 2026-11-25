from __future__ import annotations

import json
import uuid
from datetime import datetime

from silva.config import CONFIG_DIR
from silva.users.admin_access import is_capability_enabled
from silva.users.manager import is_owner
from silva.users.tiers import normalize_tier

CHAT_FILE = CONFIG_DIR / "admin_live_chat.json"
MODERATION_FILE = CONFIG_DIR / "live_chat_moderation.json"
_MAX_MESSAGES = 1000


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _user_id(user: dict | None) -> str:
    return str((user or {}).get("id") or "guest")


def _user_name(user: dict | None) -> str:
    return str((user or {}).get("name") or (user or {}).get("id") or "Guest")


def _load_json(path, fallback):
    if not path.exists():
        return fallback
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback
    return data if isinstance(data, type(fallback)) else fallback


def _save_json(path, data) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _load_messages() -> list[dict]:
    return [dict(item) for item in _load_json(CHAT_FILE, []) if isinstance(item, dict)]


def _save_messages(messages: list[dict]) -> None:
    _save_json(CHAT_FILE, messages[-_MAX_MESSAGES:])


def _moderation() -> dict:
    return _load_json(MODERATION_FILE, {})


def can_reply_live_chat(user: dict | None) -> bool:
    active = user or {}
    if is_owner(active):
        return True
    if is_capability_enabled(active, "live_chat_reply"):
        return True
    return normalize_tier(active.get("tier")) >= 4


def can_moderate_live_chat(user: dict | None) -> bool:
    active = user or {}
    if is_owner(active):
        return True
    if is_capability_enabled(active, "live_chat_moderation"):
        return True
    return normalize_tier(active.get("tier")) >= 4


def speaker_label(user: dict | None) -> str:
    active = user or {}
    name = _user_name(active)
    if is_owner(active):
        return "owner"
    role = str(active.get("role") or active.get("chat_role") or "").strip().lower().replace("_", " ")
    if "rep" in role or "representative" in role:
        return f"chat rep - {name}"
    if can_reply_live_chat(active):
        return f"admin - {name}"
    return f"{name} (user)"


def is_live_chat_blocked(user_id: str) -> bool:
    entry = _moderation().get(str(user_id or "guest"), {})
    return bool(isinstance(entry, dict) and entry.get("blocked"))


def _notify(message: str, reason: str) -> None:
    from silva.notifications.dispatch import notify_owner_async

    notify_owner_async(message, reason=reason, force=False, prefer_telegram=True)


def _popup(user_id: str, reason: str) -> None:
    from silva.gui.live_chat_instance import request_live_chat_popup

    request_live_chat_popup(user_id=user_id, reason=reason)


def submit_live_chat_message(user: dict | None, text: str, *, kind: str = "help") -> dict:
    active = user or {}
    user_id = _user_id(active)
    message = str(text or "").strip()
    if is_live_chat_blocked(user_id):
        return {
            "id": "",
            "user_id": user_id,
            "status": "blocked",
            "text": message,
            "author_label": speaker_label(active),
        }
    if not message:
        return {
            "id": "",
            "user_id": user_id,
            "status": "empty",
            "text": "",
            "author_label": speaker_label(active),
        }

    entry = {
        "id": uuid.uuid4().hex[:12],
        "thread_id": user_id,
        "user_id": user_id,
        "user_name": _user_name(active),
        "author_id": user_id,
        "author_name": _user_name(active),
        "author_label": speaker_label(active),
        "role": "staff" if can_reply_live_chat(active) else "user",
        "direction": "user_to_staff" if not can_reply_live_chat(active) else "staff_to_user",
        "text": message,
        "kind": str(kind or "help"),
        "status": "open",
        "created_at": _now(),
        "unread_for_staff": not can_reply_live_chat(active),
        "unread_for_user": False,
        "reply": "",
        "replied_by": "",
        "replied_at": "",
    }
    messages = _load_messages()
    messages.append(entry)
    _save_messages(messages)

    _notify(f"Live chat from {entry['author_label']} ({user_id}): {message}", "live_chat")
    _popup(user_id, "user_message")
    return dict(entry)


def list_live_chat_messages(
    *, status: str | None = None, user_id: str | None = None
) -> list[dict]:
    messages = _load_messages()
    if user_id is not None:
        wanted = str(user_id)
        messages = [
            item
            for item in messages
            if str(item.get("user_id") or "") == wanted or str(item.get("thread_id") or "") == wanted
        ]
    if status:
        messages = [item for item in messages if str(item.get("status") or "") == status]
    return [dict(item) for item in messages]


def reply_live_chat_message(message_id: str, responder: dict | None, reply: str) -> tuple[bool, str]:
    if not can_reply_live_chat(responder):
        return False, "Only the owner, chat reps, and admins can reply in live chat."
    text = str(reply or "").strip()
    if not text:
        return False, "Type a reply first."

    messages = _load_messages()
    target = None
    for item in messages:
        if str(item.get("id")) == str(message_id):
            target = item
            break
    if target is None:
        return False, "Chat message not found."

    user_id = str(target.get("user_id") or target.get("thread_id") or "guest")
    entry = {
        "id": uuid.uuid4().hex[:12],
        "thread_id": str(target.get("thread_id") or user_id),
        "user_id": user_id,
        "user_name": str(target.get("user_name") or "Guest"),
        "author_id": _user_id(responder),
        "author_name": _user_name(responder),
        "author_label": speaker_label(responder),
        "role": "staff",
        "direction": "staff_to_user",
        "text": text,
        "kind": str(target.get("kind") or "reply"),
        "status": "replied",
        "created_at": _now(),
        "unread_for_staff": False,
        "unread_for_user": True,
        "reply_to": str(message_id),
        "reply": "",
        "replied_by": "",
        "replied_at": "",
    }
    target["reply"] = text
    target["replied_by"] = entry["author_label"]
    target["replied_at"] = entry["created_at"]
    target["status"] = "replied"
    target["unread_for_staff"] = False
    messages.append(entry)
    _save_messages(messages)

    _notify(
        f"Live chat reply from {entry['author_label']} to {entry['user_name']}: {text}",
        "live_chat_reply",
    )
    _popup(user_id, "staff_reply")
    return True, ""


def unread_live_chat_count(*, user_id: str | None = None, staff: bool = False) -> int:
    count = 0
    for item in list_live_chat_messages():
        if staff:
            if item.get("unread_for_staff"):
                count += 1
            continue
        if user_id is None:
            continue
        if str(item.get("user_id") or "") == str(user_id) and item.get("unread_for_user"):
            count += 1
    return count


def mark_live_chat_read(*, user_id: str | None = None, staff: bool = False) -> None:
    messages = _load_messages()
    changed = False
    for item in messages:
        if staff and item.get("unread_for_staff"):
            item["unread_for_staff"] = False
            changed = True
        elif (
            not staff
            and user_id is not None
            and str(item.get("user_id") or "") == str(user_id)
            and item.get("unread_for_user")
        ):
            item["unread_for_user"] = False
            changed = True
    if changed:
        _save_messages(messages)


def set_live_chat_blocked(reviewer: dict | None, user_id: str, *, blocked: bool, reason: str = "") -> tuple[bool, str]:
    if not can_moderate_live_chat(reviewer):
        return False, "Only the owner, chat reps, and admins can moderate live chat."
    target = str(user_id or "guest")
    moderation = _moderation()
    entry = moderation.get(target) if isinstance(moderation.get(target), dict) else {}
    entry["blocked"] = bool(blocked)
    entry["reason"] = str(reason or "").strip()
    entry["updated_by"] = speaker_label(reviewer)
    entry["updated_at"] = _now()
    moderation[target] = entry
    _save_json(MODERATION_FILE, moderation)

    status = "Live chat typing blocked" if blocked else "Live chat typing restored"
    system_entry = {
        "id": uuid.uuid4().hex[:12],
        "thread_id": target,
        "user_id": target,
        "user_name": str(entry.get("name") or target),
        "author_id": _user_id(reviewer),
        "author_name": _user_name(reviewer),
        "author_label": speaker_label(reviewer),
        "role": "staff",
        "direction": "system",
        "text": f"{status}. {entry['reason']}".strip(),
        "kind": "moderation",
        "status": "system",
        "created_at": entry["updated_at"],
        "unread_for_staff": False,
        "unread_for_user": True,
    }
    messages = _load_messages()
    messages.append(system_entry)
    _save_messages(messages)
    _popup(target, "moderation")
    return True, f"{status} for {target}."


def kick_live_chat_user(reviewer: dict | None, user_id: str, *, reason: str = "") -> tuple[bool, str]:
    ok, message = set_live_chat_blocked(
        reviewer,
        user_id,
        blocked=True,
        reason=reason or "Removed from live chat for rude language.",
    )
    if ok:
        message = f"Kicked {user_id} from live chat. They cannot send another message until unblocked."
    return ok, message
