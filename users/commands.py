"""User management command phrases for Silva."""

from __future__ import annotations

import json
import re

from silva.users.manager import (
    REQUESTS_FILE,
    add_user,
    get_active_user,
    get_owner,
    list_users,
    remove_user,
    user_can,
)
from silva.users.permissions import PERM_ENROLL_VOICE, PERM_MANAGE_USERS, PERM_VIEW_LOGS
from silva.users.tiers import MAX_TIER, normalize_tier, tier_description

import speech_recognition as sr


def _normalize(text: str) -> str:
    text = text.strip().lower()
    text = text.replace("'", "")
    return re.sub(r"\s+", " ", text)


def try_user_command(text: str, *, audio: sr.AudioData | None = None) -> str | None:
    normalized = _normalize(text)
    user = get_active_user()
    tier = normalize_tier(user.get("tier", 1))

    if normalized in {"who am i", "who is speaking", "who is this", "identify me"}:
        if user.get("id") == "guest":
            return "I don't recognize your voice yet."
        enrolled = "Voice enrolled." if user.get("voice_enrolled") else "Voice not enrolled yet."
        return (
            f"You are {user['name']}, tier {tier}, {tier_description(tier)}. {enrolled}"
        )

    if normalized in {"list users", "show users", "who has access"}:
        if not user_can(user, PERM_MANAGE_USERS):
            return None
        names = [
            f"{u['name']} (tier {normalize_tier(u.get('tier', 1))})"
            for u in list_users()
            if u["id"] != "guest"
        ]
        return "Registered users: " + ", ".join(names)

    if normalized.startswith("add user "):
        if not user_can(user, PERM_MANAGE_USERS):
            return None
        remainder = normalized.replace("add user ", "", 1).strip()
        tier = 1
        for n in range(1, MAX_TIER):
            token = f" tier {n}"
            if token in remainder:
                tier = n
                remainder = remainder.replace(token, "").strip()
                break
        if not remainder:
            return "Say add user Sarah tier 2."
        new_user = add_user(remainder, tier=tier)
        return f"Added {new_user['name']} at tier {tier}."

    if normalized.startswith("remove user "):
        if not user_can(user, PERM_MANAGE_USERS):
            return None
        name = normalized.replace("remove user ", "", 1).strip()
        target = next(
            (u for u in list_users() if u["name"].lower() == name or u["id"] == name.replace(" ", "_")),
            None,
        )
        if target is None:
            return f"I couldn't find a user named {name.title()}."
        if normalize_tier(target.get("tier")) >= MAX_TIER:
            return "The owner account cannot be removed."
        remove_user(target["id"])
        return f"Removed {target['name']} from Silva."

    if normalized in {"show requests", "pending requests", "list requests"}:
        if not user_can(user, PERM_MANAGE_USERS):
            return None
        if not REQUESTS_FILE.exists():
            return "There are no pending requests."
        requests = json.loads(REQUESTS_FILE.read_text(encoding="utf-8"))
        if not requests:
            return "There are no pending requests."
        latest = requests[-3:]
        parts = [f"{r['from_user']}: {r['message'][:80]}" for r in latest]
        return "Pending requests: " + " | ".join(parts)

    if normalized in {"who is the owner", "who owns silva"}:
        owner = get_owner()
        return f"The owner is {owner['name']}, tier {MAX_TIER}."

    return None
