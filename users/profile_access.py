"""Who may open Silva profile / control panels."""

from __future__ import annotations

from silva.users.admin_access import is_capability_enabled
from silva.users.manager import get_owner, is_owner
from silva.users.system_identity import owner_auto_profile_on_startup
from silva.users.tiers import normalize_tier

ADMIN_TIER = 4


def owner_auto_profile_enabled() -> bool:
    return owner_auto_profile_on_startup()


def can_open_control_panel(user: dict) -> bool:
    """Owner or tier 4+ admin assistance panel."""
    return is_capability_enabled(user, "open_control_panel")


def can_open_self_profile(user: dict) -> bool:
    return user.get("id") not in {None, "", "guest"}


def profile_mode_for_user(user: dict) -> str | None:
    if is_owner(user):
        return "owner"
    if normalize_tier(user.get("tier", 1)) >= ADMIN_TIER:
        return "admin"
    if can_open_self_profile(user):
        return "self"
    return None


def startup_owner_user() -> dict:
    return get_owner()
