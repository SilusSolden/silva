"""Owner-editable per-user System Panel access controls."""

from __future__ import annotations

import json

from silva.config import CONFIG_DIR
from silva.users.manager import get_active_user, is_owner, load_store
from silva.users.tiers import normalize_tier

ADMIN_ACCESS_FILE = CONFIG_DIR / "admin_access_grants.json"

CAPABILITIES: tuple[tuple[str, str, str], ...] = (
    ("open_control_panel", "Open System Panel", "Panel"),
    ("stage_updates", "Stage Updates", "Updates"),
    ("publish_updates", "Publish Updates", "Updates"),
    ("emergency_publish_updates", "Emergency Push Updates", "Updates"),
    ("open_security_panel", "Security Panel", "Security"),
    ("view_logs", "View Logs", "Security"),
    ("manage_users", "Manage Users", "Users"),
    ("change_settings", "Change Settings", "Settings"),
    ("open_camera", "Camera Features", "Camera"),
    ("voice_scope_system", "Voice: System", "Voice"),
    ("voice_scope_updates", "Voice: Updates", "Voice"),
    ("voice_scope_users", "Voice: Users", "Voice"),
    ("voice_scope_security", "Voice: Security", "Voice"),
    ("voice_scope_logs", "Voice: Logs", "Voice"),
    ("voice_scope_settings", "Voice: Settings", "Voice"),
    ("voice_scope_camera", "Voice: Camera", "Voice"),
    ("voice_scope_planner", "Voice: Planner", "Voice"),
    ("voice_scope_room_audio", "Voice: Room Audio", "Voice"),
    ("view_image_library", "View Image Library", "Media"),
    ("live_chat_reply", "Live Chat Reply", "Chat"),
    ("live_chat_moderation", "Live Chat Moderation", "Chat"),
)

CAPABILITY_KEYS = tuple(key for key, _label, _group in CAPABILITIES)
VOICE_SCOPE_CAPABILITY_KEYS = frozenset(
    key for key, _label, group in CAPABILITIES if group == "Voice"
)


def _load_grants() -> dict[str, dict[str, bool]]:
    if not ADMIN_ACCESS_FILE.exists():
        return {}
    try:
        data = json.loads(ADMIN_ACCESS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    cleaned: dict[str, dict[str, bool]] = {}
    for user_id, grants in data.items():
        if not isinstance(grants, dict):
            continue
        cleaned[str(user_id)] = {
            str(key): bool(value) for key, value in grants.items() if key in CAPABILITY_KEYS
        }
    return cleaned


def _save_grants(grants: dict[str, dict[str, bool]]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    ADMIN_ACCESS_FILE.write_text(json.dumps(grants, indent=2, sort_keys=True), encoding="utf-8")


def load_admin_grants() -> dict[str, dict[str, bool]]:
    return _load_grants()


def set_capability(reviewer: dict | None, user_id: str, key: str, enabled: bool) -> tuple[bool, str]:
    reviewer_user = reviewer or get_active_user()
    if not is_owner(reviewer_user):
        return False, "Only the owner can change admin access."
    if key not in CAPABILITY_KEYS:
        return False, "Unknown admin access."
    if key == "view_image_library" and str(user_id) != str(reviewer_user.get("id") or ""):
        return False, "Image library access is owner-only."
    target = load_store()["users"].get(str(user_id))
    if target is None:
        return False, "User not found."
    grants = _load_grants()
    entry = grants.setdefault(str(user_id), {})
    entry[key] = bool(enabled)
    _save_grants(grants)
    label = next(label for item, label, _group in CAPABILITIES if item == key)
    state = "enabled" if enabled else "disabled"
    message = f"{label} {state} for {target.get('name', user_id)}."
    if is_owner(target):
        message += " Owner access stays available for recovery."
    return True, message


def reset_user_capabilities(reviewer: dict | None, user_id: str) -> tuple[bool, str]:
    if not is_owner(reviewer or get_active_user()):
        return False, "Only the owner can change admin access."
    grants = _load_grants()
    if not grants.pop(str(user_id), None):
        return True, "No saved overrides for that user."
    _save_grants(grants)
    return True, "Saved admin access overrides cleared."


def is_capability_enabled(user: dict | None, key: str) -> bool:
    if not user or key not in CAPABILITY_KEYS:
        return False
    if key == "view_image_library":
        return is_owner(user)
    if is_owner(user):
        return True
    explicit = _load_grants().get(str(user.get("id")), {}).get(key)
    if explicit is not None:
        return bool(explicit)
    if key == "emergency_publish_updates":
        return False
    if key in VOICE_SCOPE_CAPABILITY_KEYS:
        return False
    return normalize_tier(user.get("tier")) >= 4


def capability_states(user: dict | None) -> dict[str, bool]:
    if not user:
        return {key: False for key in CAPABILITY_KEYS}
    explicit = _load_grants().get(str(user.get("id")), {})
    states: dict[str, bool] = {}
    for key in CAPABILITY_KEYS:
        if key in explicit:
            states[key] = bool(explicit[key])
        else:
            states[key] = is_capability_enabled(user, key)
    return states
