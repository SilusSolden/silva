"""User permission helpers - backed by the 5-tier system."""

from __future__ import annotations

from silva.users.tiers import (
    PERM_ALL,
    PERM_APPROVE_ACTIONS,
    PERM_BUG_CHECK,
    PERM_BUG_FIX,
    PERM_CHANGE_SETTINGS,
    PERM_CONVERSATION,
    PERM_ENROLL_VOICE,
    PERM_MANAGE_USERS,
    PERM_ROOM_AUDIO,
    PERM_RUN_COMMANDS,
    PERM_SELF_HELP,
    PERM_SUBMIT_REQUESTS,
    PERM_USE_NEW_FEATURES,
    PERM_VIEW_LOGS,
    has_tier_permission,
    permissions_for_tier,
)

__all__ = [
    "PERM_ALL",
    "PERM_APPROVE_ACTIONS",
    "PERM_BUG_CHECK",
    "PERM_BUG_FIX",
    "PERM_CHANGE_SETTINGS",
    "PERM_CONVERSATION",
    "PERM_ENROLL_VOICE",
    "PERM_MANAGE_USERS",
    "PERM_ROOM_AUDIO",
    "PERM_RUN_COMMANDS",
    "PERM_SELF_HELP",
    "PERM_SUBMIT_REQUESTS",
    "PERM_USE_NEW_FEATURES",
    "PERM_VIEW_LOGS",
    "has_permission",
    "permissions_for_tier",
]


def has_permission(user: dict, permission: str) -> bool:
    from silva.users.manager import is_owner
    from silva.users.system_identity import bypass_security_checks

    if bypass_security_checks() and is_owner(user):
        return True
    return has_tier_permission(user, permission)
