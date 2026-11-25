from __future__ import annotations

import json

from silva.config import CONFIG_DIR
from silva.users.manager import get_active_user, is_owner
from silva.users.profile_access import can_open_control_panel

CHANNEL_FILE = CONFIG_DIR / "update_channels.json"
CHANNEL_STABLE = "stable"
CHANNEL_DEV = "dev"
_ALIASES = {
    "stable": CHANNEL_STABLE,
    "production": CHANNEL_STABLE,
    "normal": CHANNEL_STABLE,
    "dev": CHANNEL_DEV,
    "development": CHANNEL_DEV,
    "beta": CHANNEL_DEV,
    "prerelease": CHANNEL_DEV,
}


def _load_channels() -> dict:
    if not CHANNEL_FILE.exists():
        return {}
    try:
        data = json.loads(CHANNEL_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_channels(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CHANNEL_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_update_channel(user_id: str) -> str:
    value = str(_load_channels().get(str(user_id) or "guest") or CHANNEL_STABLE)
    return _ALIASES.get(value.lower(), CHANNEL_STABLE)


def set_update_channel(user_id: str, channel: str) -> tuple[bool, str]:
    normalized = _ALIASES.get(str(channel or "").strip().lower(), "")
    if not normalized:
        return False, "Choose stable or dev updates."
    data = _load_channels()
    data[str(user_id or "guest")] = normalized
    _save_channels(data)
    return True, f"Update channel set to {normalized}."


def can_use_dev_channel(user: dict | None = None) -> bool:
    active = user or get_active_user() or {}
    return is_owner(active) or can_open_control_panel(active)


def should_offer_dev_update(user: dict | None = None) -> bool:
    active = user or get_active_user() or {}
    if not can_use_dev_channel(active):
        return False
    return get_update_channel(str(active.get("id") or "guest")) == CHANNEL_DEV
