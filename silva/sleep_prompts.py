"""Varied reminders when users talk to Silva while she is asleep."""

from __future__ import annotations

import random

SLEEP_REMINDERS: tuple[str, ...] = (
    "Silva is sleeping.",
    "I'm asleep.",
    "Sleeping.",
    "I'm in sleep mode.",
    "Still asleep.",
)

REPEAT_REPLIES: tuple[str, ...] = (
    "Sorry, I didn't catch that. Could you repeat that?",
    "I'm sorry, could you say that again?",
    "Sorry, what was that?",
)

IDLE_SLEEP_REMINDERS: tuple[str, ...] = (
    "Just a reminder — I'm still in sleep mode. Say hey Silva when you're back.",
    "Silva is still resting. Wake me with wake up Silva whenever you need help.",
    "I'm here, but still asleep. Say Silva wake up or I'm back Silva to continue.",
    "Still in sleep mode. Say hey Silva or yo Silva when you're ready.",
    "Taking a break — use a wake phrase like wake up Silva when you return.",
)


def next_sleep_reminder(index: int | None = None) -> str:
    if index is None:
        return random.choice(SLEEP_REMINDERS)
    return SLEEP_REMINDERS[index % len(SLEEP_REMINDERS)]


def next_idle_sleep_reminder(index: int | None = None) -> str:
    if index is None:
        return random.choice(IDLE_SLEEP_REMINDERS)
    return IDLE_SLEEP_REMINDERS[index % len(IDLE_SLEEP_REMINDERS)]


def maybe_idle_sleep_reminder(_assistant) -> None:
    """Idle sleep nags are off. Remind only when the user tries to talk."""
    return


def remind_asleep(assistant, *, reason: str = "command", text: str = "") -> None:
    import time

    from silva.config import load_config
    from silva.logger import log_info

    if reason == "idle":
        return
    now = time.time()
    cooldown = float(load_config().get("sleep_reminder_cooldown_seconds", 12))
    last = float(getattr(assistant, "_last_sleep_reminder_at", 0.0) or 0.0)
    if now - last < cooldown:
        return
    assistant._last_sleep_reminder_at = now
    index = int(getattr(assistant, "_sleep_reminder_index", 0) or 0)
    message = next_sleep_reminder(index)
    if reason == "voice" and text.strip():
        message = REPEAT_REPLIES[index % len(REPEAT_REPLIES)]
    assistant._sleep_reminder_index = index + 1
    log_info(f"Sleep reminder ({reason}): {message[:120]}")
    if bool(load_config().get("sleep_reminder_speak", True)):
        assistant._say_while_asleep(message)
    else:
        print(f"Silva: {message}")


def looks_like_user_attempt(text: str) -> bool:
    """True when the user likely tried to talk to Silva, not background noise."""
    stripped = text.strip()
    if len(stripped) < 2:
        return False
    words = stripped.split()
    return len(words) >= 1 and len(stripped) >= 3
