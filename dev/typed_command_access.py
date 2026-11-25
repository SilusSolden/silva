"""Permission checks for typed Silva commands in the terminal."""

from __future__ import annotations

import re

from silva.users.manager import is_owner
from silva.users.profile_access import can_open_control_panel

_OPTIONAL_PREFIXES: tuple[str, ...] = ("run:", "cmd:", "say:")

# Exact single-word terminal dev tools — not routed as voice commands.
DEV_TERMINAL_COMMANDS: frozenset[str] = frozenset(
    {"help", "commands", "?", "status", "scan", "check", "test", "update", "update check", "revert"}
)

# Non-owner/admin users cannot type these in the terminal.
_BLOCKED_TYPED_PATTERNS: tuple[str, ...] = (
    "add user",
    "remove user",
    "delete user",
    "manage users",
    "security panel",
    "show security",
    "show logs",
    "open logs",
    "view logs",
    "change settings",
    "silva settings",
    "update silva",
    "owner override",
    "protection protocol",
    "approve actions",
    "tier 4",
    "control panel",
)


def is_dev_terminal_command(line: str) -> bool:
    return line.strip().lower() in DEV_TERMINAL_COMMANDS


def normalize_typed_command(line: str) -> str:
    """Return the Silva command text from a terminal line (optional run:/cmd:/say: prefix)."""
    text = line.strip()
    lowered = text.lower()
    for prefix in _OPTIONAL_PREFIXES:
        if lowered.startswith(prefix):
            return text[len(prefix) :].strip()
    return text


def is_typed_silva_command(line: str) -> bool:
    """True when line uses the optional run:/cmd:/say: prefix (backward compatible)."""
    normalized = line.strip().lower()
    return any(normalized.startswith(prefix) for prefix in _OPTIONAL_PREFIXES)


def extract_typed_command(line: str) -> str:
    return normalize_typed_command(line)


def typed_command_help_for_user(user: dict) -> str:
    lines = [
        "Type any command and press Enter — same as speaking to Silva.",
        "Type chat to open the on-screen command box (or click Chat, bottom-right).",
        "",
        "Examples:",
        "  weather",
        "  next few days weather",
        "  pause the video",
        "  silva wake up",
        "  mute chrome",
        "  open the phrase recorder",
        "  open voice recorder",
    ]
    if is_owner(user) or can_open_control_panel(user):
        lines.extend(
            [
                "",
                "Dev commands (owner/admin only, single word):",
                "  scan | update check | update | revert | check | test | status",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "Note: admin-only commands cannot be typed here.",
                "Use voice or ask an owner/admin if you need help.",
            ]
        )
    return "\n".join(lines)


def validate_typed_command(user: dict, text: str) -> tuple[bool, str]:
    command = text.strip()
    if not command:
        return False, "Type a command and press Enter — for example: weather"

    if is_owner(user) or can_open_control_panel(user):
        return True, ""

    normalized = re.sub(r"\s+", " ", command.lower())
    for pattern in _BLOCKED_TYPED_PATTERNS:
        if pattern in normalized:
            return False, (
                f'You cannot type "{pattern}" from the terminal. '
                "Try help, weather, pause the video, or open the phrase recorder."
            )
    return True, ""
