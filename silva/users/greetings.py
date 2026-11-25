"""Startup and session greetings for Silva."""

from __future__ import annotations

STARTUP_GREETING = (
    "Hello, I'm Silva, your personal AI assistant. How can I help you today?"
)
LISTENING_PROMPT = "Listening."


def startup_greeting() -> str:
    return STARTUP_GREETING


def listening_prompt() -> str:
    return LISTENING_PROMPT


def wake_greeting_for_user(user: dict | None = None) -> str:
    from silva.users.manager import get_active_user

    user = user or get_active_user()
    name = user.get("name", "")
    if not name or name == "Guest":
        return "I'm awake. Listening."
    return f"I'm awake, {name}. Listening."
