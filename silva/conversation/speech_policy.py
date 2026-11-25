from __future__ import annotations

import json
import re
import threading
from pathlib import Path

from silva.config import CONFIG_DIR
from silva.users.manager import get_active_user, load_store

POLICY_FILE = CONFIG_DIR / "speech_policy.json"

_ALLOW_RE = re.compile(
    r"\b(?:allow|enable|turn on|permit)\b.*\b(?:unfiltered|raw|curse|swear|profanity)\b"
    r"(?:\s+(?:replies|language|words|cursing|swearing))?"
    r"(?:\s+(?:for|on)\s+(.+))?",
    re.I,
)
_ALLOW_SHORT_RE = re.compile(
    r"\b(?:unfiltered|raw|curse|swear) (?:replies|language|words)\s+on(?:\s+(?:for|on)\s+(.+))?",
    re.I,
)
_DENY_RE = re.compile(
    r"\b(?:disable|turn off|stop|block|remove)\b.*\b(?:unfiltered|raw|curse|swear|profanity)\b"
    r"(?:\s+(?:replies|language|words|cursing|swearing))?"
    r"(?:\s+(?:for|on)\s+(.+))?",
    re.I,
)
_DENY_SHORT_RE = re.compile(
    r"\b(?:unfiltered|raw|curse|swear) (?:replies|language|words)\s+off(?:\s+(?:for|on)\s+(.+))?",
    re.I,
)
_AGE_RE = re.compile(
    r"\b(?:my age is|i am|i'm|verify my age|age verification)\s+(\d{1,3})\b",
    re.I,
)
_CLEAR_RE = re.compile(
    r"\b(?:clear|remove|wipe|delete|empty)\b.*\b(?:blacklist|block list|blocked words|"
    r"blocked phrases|don't say phrases|dont say phrases)\b",
    re.I,
)

_lock = threading.Lock()


def _default() -> dict:
    return {"users": {}}


def load_policy() -> dict:
    if not POLICY_FILE.exists():
        return _default()
    try:
        data = json.loads(POLICY_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {"users": data.get("users") if isinstance(data.get("users"), dict) else {}}
    except (OSError, json.JSONDecodeError):
        pass
    return _default()


def save_policy(data: dict) -> None:
    POLICY_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = POLICY_FILE.with_suffix(".json.tmp")
    temp.write_text(json.dumps({"users": data.get("users") or {}}, indent=2), encoding="utf-8")
    temp.replace(POLICY_FILE)


def _key(user_id: str) -> str:
    return str(user_id or "guest")


def _find_user(user_id: str) -> dict:
    key = _key(user_id)
    active = get_active_user() or {}
    if str(active.get("id") or "") == key:
        return active
    return (load_store().get("users") or {}).get(key) or {}


def is_privileged(user_id: str = "") -> bool:
    key = _key(user_id)
    user = _find_user(key)
    if not user:
        return False
    store = load_store()
    if str(user.get("id") or "") == str(store.get("owner_id") or ""):
        return True
    role = str(user.get("role") or "").lower()
    tier = int(user.get("tier") or 0)
    permissions = user.get("permissions") or []
    return role in ("owner", "admin") or tier >= 4 or "all" in permissions


def resolve_user(query: str) -> str:
    value = str(query or "").strip().strip(".,")
    if not value:
        return ""
    lowered = value.lower()
    for user_id, user in (load_store().get("users") or {}).items():
        name = str(user.get("name") or "").lower()
        if lowered in (str(user_id).lower(), name) or lowered in name.split():
            return str(user_id)
    return value


def entry(user_id: str) -> dict:
    key = _key(user_id)
    data = load_policy()
    users = data.setdefault("users", {})
    item = users.get(key)
    if not isinstance(item, dict):
        item = {}
        users[key] = item
    return item


def is_age_verified(user_id: str) -> bool:
    return bool(entry(user_id).get("age_verified"))


def age_band(user_id: str) -> str:
    return str(entry(user_id).get("age_band") or "")


def mark_age_verified(user_id: str, *, band: str, verified_by: str) -> None:
    with _lock:
        data = load_policy()
        item = data.setdefault("users", {}).setdefault(_key(user_id), {})
        item["age_verified"] = True
        item["age_band"] = str(band or "")
        item["age_verified_by"] = str(verified_by or "")
        item["age_attempts"] = 0
        item["age_gate"] = True
        if not is_privileged(user_id):
            item["unfiltered"] = True
        save_policy(data)


def record_age_attempt(user_id: str) -> int:
    with _lock:
        data = load_policy()
        item = data.setdefault("users", {}).setdefault(_key(user_id), {})
        attempts = int(item.get("age_attempts") or 0) + 1
        item["age_attempts"] = attempts
        save_policy(data)
        return attempts


def allows_unfiltered(user_id: str = "") -> bool:
    key = _key(user_id)
    item = entry(key)
    if "unfiltered" in item:
        enabled = bool(item.get("unfiltered"))
    else:
        enabled = is_privileged(key)
    if not enabled:
        return False
    if item.get("age_gate") and not item.get("age_verified"):
        return False
    return True


def set_unfiltered(user_id: str, enabled: bool, *, actor_id: str = "") -> tuple[bool, str]:
    target = _key(user_id)
    actor = _key(actor_id or user_id)
    privileged = is_privileged(actor)
    if not privileged and actor != target:
        return False, "Only the owner or an admin can change replies for another user."
    if enabled and not is_privileged(target) and not is_age_verified(target):
        return False, "Verify face and age before allowing unfiltered replies."
    with _lock:
        data = load_policy()
        item = data.setdefault("users", {}).setdefault(target, {})
        item["unfiltered"] = bool(enabled)
        if enabled and not is_privileged(target):
            item["age_gate"] = True
        save_policy(data)
    state = "on" if enabled else "off"
    return True, f"Unfiltered replies are {state} for {target}."


def match_speech_policy_speech(text: str) -> tuple[str, str] | None:
    value = str(text or "").strip()
    if not value:
        return None
    if _CLEAR_RE.search(value):
        return ("clear_blocked", "")
    age = _AGE_RE.search(value)
    if age:
        return ("age", age.group(1))
    allow = _ALLOW_RE.search(value) or _ALLOW_SHORT_RE.search(value)
    if allow:
        return ("on", str(allow.group(1) or "").strip(" ."))
    deny = _DENY_RE.search(value) or _DENY_SHORT_RE.search(value)
    if deny:
        return ("off", str(deny.group(1) or "").strip(" ."))
    return None


def is_speech_policy_command(text: str) -> bool:
    return match_speech_policy_speech(text) is not None


def handle_speech_policy_speech(assistant, text: str) -> bool:
    parsed = match_speech_policy_speech(text)
    if parsed is None:
        return False
    action, value = parsed
    getter = getattr(assistant, "_user_id", None)
    actor = getter() if callable(getter) else str((get_active_user() or {}).get("id") or "guest")

    if action == "clear_blocked":
        if not is_privileged(actor):
            assistant.say("Only the owner or an admin can clear blocked words.", interruptible=False)
            return True
        from silva.dev.speech_training import clear_blocked_phrases

        count = clear_blocked_phrases()
        assistant.say(f"Cleared {count} blocked phrase(s).", interruptible=False)
        return True

    if action == "age":
        from silva.users.age_verification import handle_age_verification

        ok, message = handle_age_verification(actor, int(value))
        assistant.say(message, interruptible=False)
        return True

    target = resolve_user(value) or _key(actor)
    ok, message = set_unfiltered(target, action == "on", actor_id=actor)
    assistant.say(message, interruptible=False)
    return True
