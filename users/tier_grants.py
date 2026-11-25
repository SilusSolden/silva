"""Owner-editable permission grants per tier."""

from __future__ import annotations

import json

from silva.config import CONFIG_DIR
from silva.users.tiers import MAX_TIER, TIER_GRANTS, normalize_tier

TIER_GRANTS_FILE = CONFIG_DIR / "tier_grants.json"

# Permissions owner can assign to each tier (tier 5 always has all).
EDITABLE_PERMISSIONS: list[tuple[str, str]] = [
    ("conversation", "Conversation"),
    ("submit_requests", "Submit requests"),
    ("self_help", "Self-help"),
    ("bug_check", "Bug check"),
    ("bug_fix", "Bug fix"),
    ("run_commands", "Run commands"),
    ("head_checklist", "Head checklist"),
    ("use_new_features", "Advanced features"),
    ("view_logs", "View logs"),
    ("assist_lower_tiers", "Assist lower tiers"),
    ("approve_actions", "Approve actions"),
    ("manage_users", "Manage users"),
    ("change_settings", "Change settings"),
    ("enroll_voice", "Enroll voice"),
    ("room_audio", "Room voice gating"),
    ("weather", "Weather"),
    ("wikipedia", "Wikipedia"),
    ("bug_report", "Bug reports"),
]


def _load_overrides() -> dict[str, list[str]]:
    if not TIER_GRANTS_FILE.exists():
        return {}
    data = json.loads(TIER_GRANTS_FILE.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _save_overrides(data: dict[str, list[str]]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    TIER_GRANTS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def grants_for_level(tier: int) -> set[str]:
    tier = normalize_tier(tier)
    overrides = _load_overrides()
    key = str(tier)
    if key in overrides:
        return set(overrides[key])
    return set(TIER_GRANTS.get(tier, set()))


def permissions_for_tier(tier: int) -> list[str]:
    tier = normalize_tier(tier)
    if tier >= MAX_TIER:
        return ["all"]
    perms: set[str] = set()
    for level in range(1, tier + 1):
        perms.update(grants_for_level(level))
    return sorted(perms)


def get_tier_permission_set(tier: int) -> set[str]:
    """Direct grants for one tier level (for editor UI)."""
    tier = normalize_tier(tier)
    if tier >= MAX_TIER:
        return {key for key, _label in EDITABLE_PERMISSIONS}
    return grants_for_level(tier)


def save_tier_permission_set(tier: int, permissions: set[str]) -> None:
    tier = normalize_tier(tier)
    if tier >= MAX_TIER:
        return
    overrides = _load_overrides()
    overrides[str(tier)] = sorted(permissions)
    _save_overrides(overrides)


def apply_tier_permissions_to_all_users() -> None:
    """Refresh stored permission lists on every user after tier grant edits."""
    from silva.users.manager import load_store, save_store

    store = load_store()
    for user in store["users"].values():
        user["permissions"] = permissions_for_tier(user.get("tier", 1))
    save_store(store)
