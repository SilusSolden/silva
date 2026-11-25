"""Temporary clean-language guest demo sessions started by the owner."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from silva.config import CONFIG_DIR
from silva.logger import log_info

STATE_FILE = CONFIG_DIR / "guest_demo_state.json"
GUEST_USER_ID = "demo_guest"

_GUEST_TARGET = (
    r"(?:someone|somebody|them|him|her|another person|my friend|a friend|this person|the guest|guests?)"
)
_START_RE = re.compile(
    rf"\b(?:let|allow|permit|enable)\s+{_GUEST_TARGET}\b.{{0,48}}"
    r"\b(?:try|test|talk|speak|use|see|check|demo|ask|show)\b"
    r"|\b(?:guest|demo) mode\s+on\b"
    r"|\bshow\s+(?:them|him|her|someone|somebody)\s+(?:what|how)\b"
    r"|\b(?:they|he|she|someone|somebody)\s+(?:can|could|will)\s+(?:talk|speak|use|try)\b",
    re.I,
)
_RETURN_RE = re.compile(
    r"\b(?:i'm|i am|im)\s+back\b"
    r"|\bback\s+again\b"
    r"|\b(?:i'm|i am|im)\s+(?:here|here again)\b"
    r"|\bthe\s+owner\s+is\s+back\b"
    r"|\bowner\s+back\b",
    re.I,
)


def _normalize(text: str) -> str:
    value = str(text or "").strip().lower().replace("'", "")
    return re.sub(r"\s+", " ", value)


def _load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def is_guest_demo_start_command(text: str) -> bool:
    return bool(_START_RE.search(_normalize(text)))


def is_owner_return_command(text: str) -> bool:
    return bool(_RETURN_RE.search(_normalize(text)))


def guest_demo_active() -> bool:
    return bool(_load_state().get("active"))


def guest_demo_owner_id() -> str | None:
    owner_id = _load_state().get("owner_id")
    return str(owner_id) if owner_id else None


def is_guest_demo_user(user_id: str | None) -> bool:
    if not user_id or not guest_demo_active():
        return False
    return str(_load_state().get("guest_user_id") or "") == str(user_id)


def start_guest_demo(owner: dict) -> dict:
    from silva.users.manager import ensure_user, load_store, save_store
    from silva.users.tiers import permissions_for_tier

    owner_id = str(owner.get("id") or "")
    if not owner_id:
        from silva.users.manager import get_owner

        owner_id = str(get_owner().get("id") or "kevin")

    guest = ensure_user(GUEST_USER_ID, "Demo Guest", 1)
    store = load_store()
    target = store["users"][GUEST_USER_ID]
    target["tier"] = 1
    target["role"] = "guest"
    target["permissions"] = permissions_for_tier(1)
    target["voice_enrolled"] = False
    save_store(store)
    _save_state(
        {
            "active": True,
            "owner_id": owner_id,
            "guest_user_id": GUEST_USER_ID,
            "guest_active": False,
            "started_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    log_info(f"Guest demo mode started by {owner_id}")
    return guest


def activate_guest_for_unknown_voice() -> dict | None:
    from silva.users.manager import identify_and_set_active

    state = _load_state()
    if not state.get("active") or state.get("guest_active"):
        return None
    guest_id = str(state.get("guest_user_id") or GUEST_USER_ID)
    guest = identify_and_set_active(guest_id)
    state["guest_active"] = True
    state["activated_at"] = datetime.now().isoformat(timespec="seconds")
    _save_state(state)
    log_info(f"Unrecognized guest voice detected; switched to {guest_id} demo profile")
    return guest


def end_guest_demo(*, reason: str = "owner_return") -> dict | None:
    from silva.users.manager import get_owner, identify_and_set_active

    state = _load_state()
    if not state.get("active"):
        return None
    owner_id = str(state.get("owner_id") or get_owner().get("id") or "kevin")
    owner = identify_and_set_active(owner_id)
    _save_state({})
    log_info(f"Guest demo ended ({reason}); restored {owner_id}")
    return owner


def handle_guest_demo_speech(assistant, text: str, user: dict) -> bool:
    from silva.users.manager import is_owner

    state = _load_state()
    if state.get("active") and is_owner_return_command(text):
        owner = end_guest_demo(reason="owner_return_phrase")
        name = str((owner or {}).get("name") or "Owner")
        assistant.say(
            f"Welcome back, {name}. Owner profile restored. Guest demo is off.",
            interruptible=False,
        )
        return True

    if not is_guest_demo_start_command(text):
        return False
    if not is_owner(user):
        assistant.say("Only the owner can start guest demo mode.", interruptible=False)
        return True
    if state.get("active"):
        assistant.say(
            "Guest demo mode is already on. I will switch back when you say I'm back.",
            interruptible=False,
        )
        return True
    start_guest_demo(user)
    assistant.say(
        "Guest demo mode is on. I will use clean replies and limited guest access "
        "until you say I'm back.",
        interruptible=False,
    )
    return True
