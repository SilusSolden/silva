"""Protection protocol — face/voice gate, verification challenges, owner privacy."""

from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path

from silva.config import CONFIG_DIR, load_config
from silva.logger import log_info
from silva.users.manager import get_owner, is_owner, load_store
from silva.users.tiers import normalize_tier

STATE_FILE = CONFIG_DIR / "protection_protocol.json"

ACTIVATE_PHRASES = (
    "silva activate protection",
    "activate protection",
    "activate protection protocol",
    "protection protocol",
    "protection protocol on",
    "silva protection on",
    "enable protection",
    "enable protection protocol",
)

DEACTIVATE_PHRASES = (
    "silva deactivate protection",
    "deactivate protection",
    "disable protection",
    "protection off",
    "silva protection off",
    "turn off protection",
    "turn off protection protocol",
)

OWNER_OVERRIDE_PHRASES = (
    "owner override",
    "owner bypass",
    "kevin override",
    "main owner override",
)


@dataclass
class ProtectionCheck:
    allowed: bool
    reason: str
    needs_verification: bool = False
    camera_unavailable: bool = False
    owner_verified: bool = False


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {"users": {}, "sessions": {}}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("users", {})
            data.setdefault("sessions", {})
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"users": {}, "sessions": {}}


def _save_state(state: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _user_entry(user_id: str) -> dict:
    state = _load_state()
    users = state.setdefault("users", {})
    entry = users.setdefault(
        user_id,
        {
            "enabled": False,
            "telegram_chat_id": "",
            "alert_phone": "",
            "weather_city": "",
            "activated_at": None,
        },
    )
    return entry


def can_enable_protection(user: dict) -> bool:
    tier = normalize_tier(user.get("tier", 1))
    return is_owner(user) or tier >= 4


def is_protection_enabled_for_user(user_id: str) -> bool:
    entry = _load_state().get("users", {}).get(user_id, {})
    return bool(entry.get("enabled"))


def is_protection_active() -> bool:
    """True when owner or any admin has protection enabled on this system."""
    state = _load_state()
    for entry in state.get("users", {}).values():
        if entry.get("enabled"):
            return True
    return False


def protection_enabled_for_monitor_user() -> str | None:
    """User id whose protection rules apply on the main system (owner first)."""
    owner = get_owner()
    if is_protection_enabled_for_user(owner["id"]):
        return owner["id"]
    store = load_store()
    for uid, user in store["users"].items():
        if uid == owner["id"]:
            continue
        if normalize_tier(user.get("tier", 1)) >= 4 and is_protection_enabled_for_user(uid):
            return uid
    return None


def activate_protection(user_id: str, *, telegram_chat_id: str = "", alert_phone: str = "") -> bool:
    state = _load_state()
    entry = state.setdefault("users", {}).setdefault(user_id, {})
    entry["enabled"] = True
    entry["activated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    if telegram_chat_id:
        entry["telegram_chat_id"] = telegram_chat_id.strip()
    if alert_phone:
        entry["alert_phone"] = alert_phone.strip()
    _save_state(state)
    log_info(f"Protection protocol activated for user {user_id}.")
    return True


def deactivate_protection(user_id: str) -> bool:
    state = _load_state()
    entry = state.get("users", {}).get(user_id)
    if not entry:
        return False
    entry["enabled"] = False
    sessions = state.setdefault("sessions", {})
    sessions.pop(user_id, None)
    _save_state(state)
    log_info(f"Protection protocol deactivated for user {user_id}.")
    return True


def protection_contact_for_user(user_id: str) -> dict:
    from silva.notifications.owner_secrets import owner_phone, telegram_chat_id

    entry = _user_entry(user_id)
    owner = get_owner()
    chat = str(entry.get("telegram_chat_id", "")).strip()
    phone = str(entry.get("alert_phone", "")).strip()
    if is_owner({"id": user_id, "tier": 5}):
        if not chat:
            chat = telegram_chat_id() or ""
        if not phone:
            phone = owner_phone() or ""
    return {
        "telegram_chat_id": chat or None,
        "alert_phone": phone or None,
        "weather_city": str(entry.get("weather_city", "")).strip() or None,
    }


def classify_protection_command(text: str) -> str | None:
    normalized = re.sub(r"\s+", " ", text.strip().lower())
    if any(normalized == p or normalized.startswith(p + " ") for p in ACTIVATE_PHRASES):
        return "activate"
    if any(normalized == p or normalized.startswith(p + " ") for p in DEACTIVATE_PHRASES):
        return "deactivate"
    if any(normalized == p or normalized.startswith(p + " ") for p in OWNER_OVERRIDE_PHRASES):
        return "owner_override"
    return None


def session_verified(user_id: str) -> bool:
    state = _load_state()
    session = state.get("sessions", {}).get(user_id)
    if not session:
        return False
    expires = float(session.get("expires_at", 0))
    return time.time() < expires


def mark_session_verified(user_id: str, *, minutes: int | None = None) -> None:
    if minutes is None:
        minutes = int(load_config().get("protection_session_minutes", 45))
    state = _load_state()
    state.setdefault("sessions", {})[user_id] = {
        "verified_at": time.time(),
        "expires_at": time.time() + max(5, minutes) * 60,
    }
    _save_state(state)


def clear_session(user_id: str) -> None:
    state = _load_state()
    sessions = state.get("sessions", {})
    if user_id in sessions:
        del sessions[user_id]
        _save_state(state)


def generate_verification_code(*, length: int = 8) -> list[int]:
    count = int(load_config().get("protection_verification_digits", 8))
    count = max(4, min(count, length))
    return [random.randint(1, 10) for _ in range(count)]


def format_verification_code(digits: list[int]) -> str:
    return " ".join(str(d) for d in digits)


def parse_verification_entry(text: str, expected: list[int]) -> bool:
    cleaned = re.sub(r"[^0-9]", " ", text.strip())
    parts = [p for p in cleaned.split() if p]
    try:
        entered = [int(p) for p in parts]
    except ValueError:
        return False
    return entered == expected


def owner_may_reveal_private(user: dict, topic: str) -> bool:
    """Owner-only sensitive topics; never reveal to others even if protection is off."""
    if not is_owner(user):
        return False
    topic = topic.strip().lower()
    allowed = (
        "phone",
        "number",
        "telegram",
        "address",
        "location",
        "protection",
        "security",
        "contact",
    )
    return any(word in topic for word in allowed)
