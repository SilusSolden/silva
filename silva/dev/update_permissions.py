from __future__ import annotations

from silva.users.manager import get_active_user, is_owner
from silva.users.tiers import normalize_tier


def can_scan_updates(user: dict | None = None) -> bool:
    return True


def can_request_update(user: dict | None = None) -> bool:
    return True


def can_apply_update(user: dict | None = None) -> bool:
    active = user or get_active_user()
    if is_owner(active):
        return True
    if normalize_tier(active.get("tier")) < 4:
        return False
    from silva.users.admin_access import is_capability_enabled

    return is_capability_enabled(active, "stage_updates") or is_capability_enabled(
        active, "voice_scope_updates"
    )


def can_publish_update(user: dict | None = None) -> bool:
    return is_owner(user or get_active_user())


def update_permission_message(user: dict | None = None) -> str:
    active = user or get_active_user()
    if is_owner(active):
        return "You can apply this update."
    if normalize_tier(active.get("tier")) >= 4:
        return "Ask the owner to approve this update before applying it."
    return "Ask an admin or the owner to update Silva for you."
