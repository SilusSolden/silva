"""Background daily news refresh and prompt state for owner/admin users."""

from __future__ import annotations

import threading
import time
from datetime import date, datetime

from silva.config import load_config
from silva.location import is_wifi_connected
from silva.logger import log_error, log_info

_state = {
    "last_attempt": 0.0,
    "in_flight": False,
}
_lock = threading.Lock()


def news_enabled() -> bool:
    return bool(load_config().get("news_briefing_enabled", True))


def news_manual_only() -> bool:
    return bool(load_config().get("news_briefing_manual_only", True))


def display_minutes() -> int:
    try:
        return max(1, int(load_config().get("news_briefing_display_minutes", 3)))
    except (TypeError, ValueError):
        return 3


def daily_hour() -> int:
    try:
        return max(0, min(23, int(load_config().get("news_briefing_daily_hour", 7))))
    except (TypeError, ValueError):
        return 7


def can_use_news_briefing(user: dict) -> bool:
    from silva.users.manager import is_owner
    from silva.users.tiers import normalize_tier

    if not news_enabled():
        return False
    tier = normalize_tier(user.get("tier", 1))
    return is_owner(user) or tier >= 4


def _already_built_today() -> bool:
    from silva.commands.news_briefing import load_news_state

    state = load_news_state()
    return state.get("last_briefing_date") == date.today().isoformat()


def _after_daily_hour() -> bool:
    return datetime.now().hour >= daily_hour()


def should_refresh_today() -> bool:
    if not news_enabled() or news_manual_only():
        return False
    if not is_wifi_connected():
        return False
    if _already_built_today():
        return False
    return _after_daily_hour()


def news_refresh_in_flight() -> bool:
    return bool(_state.get("in_flight"))


def refresh_daily_briefing(*, user_id: str, user_name: str, force: bool = False) -> bool:
    """Build today's briefing once per day. Returns True when a new briefing was saved."""
    if not news_enabled() or (news_manual_only() and not force):
        return False
    if not force and not should_refresh_today():
        return False
    if not is_wifi_connected() and not force:
        return False

    now = time.time()
    with _lock:
        if not force and now - _state["last_attempt"] < 300:
            return False
        if _state["in_flight"]:
            return False
        if not force and _already_built_today():
            return False
        _state["in_flight"] = True
        _state["last_attempt"] = now

    try:
        from silva.commands.news_briefing import generate_and_store_briefing

        generate_and_store_briefing(user_id=user_id, user_name=user_name)
        log_info("Daily news briefing generated in background.")
        return True
    except Exception as exc:
        log_error("Daily news briefing refresh failed", exc=exc)
        return False
    finally:
        with _lock:
            _state["in_flight"] = False


def pending_prompt_for_user(user_id: str) -> bool:
    from silva.commands.news_briefing import load_latest_briefing, load_news_state

    if not news_enabled() or news_manual_only():
        return False
    state = load_news_state()
    if not state.get("pending_prompt"):
        return False
    if state.get("prompted_user_id") == user_id:
        return False
    if load_latest_briefing() is None:
        return False
    return state.get("last_briefing_date") == date.today().isoformat()


def mark_prompt_offered(user_id: str) -> None:
    from silva.commands.news_briefing import load_news_state, save_news_state

    state = load_news_state()
    state["prompted_user_id"] = user_id
    save_news_state(state)


def clear_pending_prompt() -> None:
    from silva.commands.news_briefing import load_news_state, save_news_state

    state = load_news_state()
    state["pending_prompt"] = False
    save_news_state(state)


def latest_txt_path() -> str | None:
    from silva.commands.news_briefing import load_news_state

    state = load_news_state()
    path = state.get("last_txt_path")
    return str(path) if path else None
