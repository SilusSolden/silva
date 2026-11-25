"""Speech phrases that open Silva profile panels."""

from __future__ import annotations

import re

from silva.config import load_config

# Exact or substring matches (normalized).
MY_PROFILE_PHRASES: tuple[str, ...] = (
    "my profile",
    "setup my profile",
    "set up my profile",
    "open my profile",
    "show my profile",
    "edit my profile",
    "my account profile",
    "my voice profile",
    "my face profile",
    "configure my profile",
    "profile setup",
    "setup profile",
    "set up profile",
)

PANEL_PHRASES: tuple[str, ...] = (
    "profiles",
    "profile",
    "profile panel",
    "profile page",
    "profile manager",
    "profile settings",
    "user profiles",
    "user profile",
    "all profiles",
    "manage profiles",
    "manage users",
    "user management",
    "open profiles",
    "open profile",
    "open profile panel",
    "open profile page",
    "open profile settings",
    "open user profiles",
    "show profiles",
    "show profile",
    "show profile panel",
    "show user profiles",
    "launch profiles",
    "launch profile panel",
    "go to profiles",
    "go to profile",
    "go to profile panel",
    "take me to profiles",
    "take me to profile panel",
    "silva profiles",
    "silva profile",
    "silva open profiles",
    "silva open profile",
    "silva profile panel",
    "silva show profiles",
    "silva user profiles",
    "control panel",
    "open control panel",
    "show control panel",
    "silva control panel",
    "admin panel",
    "open admin panel",
    "admin profiles",
    "owner profiles",
    "owner profile panel",
    "account profiles",
    "accounts panel",
)


def normalize(text: str) -> str:
    text = text.strip().lower()
    text = text.replace("'", "")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _custom_phrases() -> tuple[str, ...]:
    items = load_config().get("profile_phrases", [])
    if isinstance(items, list):
        return tuple(str(item).strip().lower() for item in items if str(item).strip())
    return ()


def _matches_any(normalized: str, phrases: tuple[str, ...]) -> bool:
    for phrase in phrases:
        if not phrase:
            continue
        if normalized == phrase:
            return True
        if normalized.startswith(phrase + " "):
            return True
        if phrase in normalized:
            return True
    return False


def classify_profile_speech(text: str) -> str | None:
    """Return 'self', 'panel', or 'any' when text opens profiles."""
    normalized = normalize(text)
    if not normalized:
        return None

    all_custom = _custom_phrases()
    if _matches_any(normalized, all_custom):
        return "any"

    if _matches_any(normalized, MY_PROFILE_PHRASES):
        return "self"
    if _matches_any(normalized, PANEL_PHRASES):
        return "panel"
    return None


def is_profile_open_phrase(text: str) -> bool:
    return classify_profile_speech(text) is not None
