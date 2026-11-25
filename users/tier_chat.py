"""Tier-based chat actions for Silva."""

from __future__ import annotations

import re

from silva.users.manager import submit_request
from silva.users.permissions import (
    PERM_BUG_CHECK,
    PERM_BUG_FIX,
    PERM_SELF_HELP,
    PERM_SUBMIT_REQUESTS,
    has_permission,
)


def _normalize(text: str) -> str:
    text = text.strip().lower()
    text = text.replace("'", "")
    return re.sub(r"\s+", " ", text)


def try_tier_conversation(text: str, user: dict) -> str | None:
    normalized = _normalize(text)

    if has_permission(user, PERM_SUBMIT_REQUESTS):
        triggers = (
            "submit request",
            "send request",
            "forward to owner",
            "forward this to kevin",
            "tell the owner",
            "report issue",
            "i need help fixing",
            "request help",
        )
        if any(t in normalized for t in triggers):
            submit_request(user, text)
            return "I sent your request to the owner for review."

    if has_permission(user, PERM_SELF_HELP):
        triggers = (
            "help me figure out",
            "help me find the issue",
            "something is wrong",
            "having trouble with",
            "can you help me troubleshoot",
            "what could be wrong",
        )
        if any(t in normalized for t in triggers):
            return (
                "Let's walk through it together. Tell me what happened, "
                "what you expected, and what you see instead."
            )

    if has_permission(user, PERM_BUG_CHECK):
        if "check for bugs" in normalized or "run a check" in normalized or "diagnose" in normalized:
            return "I'll help you check for issues. Tell me what system or feature seems wrong."

    if has_permission(user, PERM_BUG_FIX):
        if "fix this" in normalized or "bug fix" in normalized or "repair this" in normalized:
            if user.get("tier", 1) >= 4:
                return "I can start a fix, but tier 4 actions may need owner approval first."
            return "Describe the bug and what you already tried, and I'll help you fix it."

    return None
