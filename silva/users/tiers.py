"""Five-tier access system for Silva users."""

from __future__ import annotations

MAX_TIER = 5

TIER_LABELS: dict[int, str] = {
    1: "Conversation only",
    2: "Requests and self-help",
    3: "Head checklist — helps tier 2 and below",
    4: "Owner assistance — helps lower tiers when needed",
    5: "Owner — full control",
}

PERM_ALL = "all"
PERM_CONVERSATION = "conversation"
PERM_SUBMIT_REQUESTS = "submit_requests"
PERM_SELF_HELP = "self_help"
PERM_BUG_CHECK = "bug_check"
PERM_BUG_FIX = "bug_fix"
PERM_RUN_COMMANDS = "run_commands"
PERM_USE_NEW_FEATURES = "use_new_features"
PERM_VIEW_LOGS = "view_logs"
PERM_MANAGE_USERS = "manage_users"
PERM_CHANGE_SETTINGS = "change_settings"
PERM_ENROLL_VOICE = "enroll_voice"
PERM_APPROVE_ACTIONS = "approve_actions"
PERM_ASSIST_LOWER_TIERS = "assist_lower_tiers"
PERM_HEAD_CHECKLIST = "head_checklist"
PERM_ROOM_AUDIO = "room_audio"

TIER_GRANTS: dict[int, set[str]] = {
    1: {PERM_CONVERSATION},
    2: {PERM_SUBMIT_REQUESTS, PERM_SELF_HELP},
    3: {PERM_BUG_CHECK, PERM_BUG_FIX, PERM_RUN_COMMANDS, PERM_HEAD_CHECKLIST},
    4: {
        PERM_USE_NEW_FEATURES,
        PERM_VIEW_LOGS,
        PERM_ASSIST_LOWER_TIERS,
        PERM_APPROVE_ACTIONS,
        PERM_ROOM_AUDIO,
    },
    5: {
        PERM_ALL,
        PERM_MANAGE_USERS,
        PERM_CHANGE_SETTINGS,
        PERM_ENROLL_VOICE,
        PERM_APPROVE_ACTIONS,
    },
}


def normalize_tier(tier: int | None) -> int:
    if tier is None:
        return 1
    return max(1, min(MAX_TIER, int(tier)))


def permissions_for_tier(tier: int) -> list[str]:
    from silva.users.tier_grants import permissions_for_tier as _merged_permissions

    return _merged_permissions(tier)


def has_tier_permission(user: dict, permission: str) -> bool:
    tier = normalize_tier(user.get("tier", 1))
    if tier >= MAX_TIER:
        return True
    perms = set(permissions_for_tier(tier))
    if PERM_ALL in perms:
        return True
    return permission in perms


def tier_description(tier: int) -> str:
    return TIER_LABELS.get(normalize_tier(tier), TIER_LABELS[1])


def can_help_tier(helper_tier: int, target_tier: int) -> bool:
    helper_tier = normalize_tier(helper_tier)
    target_tier = normalize_tier(target_tier)
    if helper_tier >= MAX_TIER:
        return True
    if helper_tier == 4:
        return target_tier <= 3
    if helper_tier == 3:
        return target_tier <= 2
    return helper_tier == target_tier
