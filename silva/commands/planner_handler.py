"""Open the 3D planner window from speech."""

from __future__ import annotations

import inspect
from typing import Any, Callable

from silva.config import load_config
from silva.logger import log_command, log_error, log_info
from silva.users.features import FEATURE_PLANNER, feature_allowed
from silva.users.manager import get_active_user


def is_planner_enabled() -> bool:
    return bool(load_config().get("planner_enabled", True))


def _planner_window() -> Any:
    """Use the live window module. Live updates skip GUI reloads to avoid Tcl crashes."""
    live = None
    try:
        from silva.gui import planner_window as live
    except Exception as exc:
        log_error("Planner window module unavailable", exc=exc)
        return None
    if bool(getattr(live, "planner_is_open", lambda: False)()):
        return live
    try:
        from silva.dev.live_update import load_gui_module_from_disk

        fresh = load_gui_module_from_disk("silva.gui.planner_window")
        if fresh is not None and hasattr(fresh, "show_planner_window"):
            return fresh
    except Exception:
        pass
    return live


def _call_show_planner(show_fn: Callable[..., None], **kwargs: Any) -> None:
    try:
        params = inspect.signature(show_fn).parameters
        has_var = any(item.kind == inspect.Parameter.VAR_KEYWORD for item in params.values())
        filtered = {key: value for key, value in kwargs.items() if has_var or key in params}
        show_fn(**filtered)
    except TypeError:
        show_fn(user_id=kwargs.get("user_id") or "guest", view_mode=kwargs.get("view_mode"))


def handle_planner_speech(assistant, text: str) -> bool:
    if not text or not str(text).strip():
        return False

    from silva.commands.planner_phrases import (
        is_planner_close_ask,
        is_planner_command,
        is_planner_map_ask,
        is_planner_site_ask,
        match_planner_draw_tool,
        match_planner_view,
    )

    pw = _planner_window()
    is_open = bool(getattr(pw, "planner_is_open", lambda: False)()) if pw is not None else False
    apply_fn = getattr(pw, "apply_planner_speech", None) if pw is not None else None
    if is_planner_close_ask(text):
        log_command("planner", query=text[:120])
        if is_open:
            close_fn = getattr(pw, "close_planner_window", None)
            if callable(close_fn):
                close_fn()
            elif callable(apply_fn):
                apply_fn(text)
            assistant.say("I closed the planner.", interruptible=True)
        else:
            assistant.say("The planner is already closed.", interruptible=True)
        return True
    if is_open and callable(apply_fn):
        try:
            spoken = apply_fn(text) or ""
        except Exception as exc:
            log_error("Planner edit failed", exc=exc)
            spoken = ""
        if spoken:
            log_command("planner-edit", query=text[:120])
            assistant.say(spoken, interruptible=True)
            return True

    if not is_planner_command(text) and not is_planner_map_ask(text):
        return False
    if not is_planner_enabled():
        return False

    user = get_active_user()
    if not feature_allowed(user, FEATURE_PLANNER):
        assistant.say("The 3D planner is not enabled for your profile.", interruptible=False)
        return True

    show_fn = getattr(pw, "show_planner_window", None) if pw is not None else None
    if not callable(show_fn):
        assistant.say("I couldn't open the planner window.", interruptible=False)
        return True

    view = match_planner_view(text)
    log_command("planner", query=text[:120])
    map_ask = is_planner_map_ask(text)
    site_ask = is_planner_site_ask(text)
    detailed = map_ask and len(str(text).split()) >= 5
    _call_show_planner(
        show_fn,
        user_id=str(user.get("id") or "guest"),
        view_mode=view,
        apply_text=text if detailed or site_ask else None,
        open_map=map_ask and not detailed,
        map_text=text if map_ask else None,
    )
    log_info(f"Opened planner ({view or '2d'}).")
    if detailed:
        spoken = "I mapped that building in the planner."
    elif map_ask:
        spoken = "I opened the planner."
    elif site_ask:
        spoken = "I turned on the lot."
    elif view == "3d":
        spoken = "I opened the 3D planner."
    elif view == "2d":
        spoken = "I opened the 2D planner."
    else:
        spoken = "I opened the planner."
    assistant.say(spoken, interruptible=True)
    return True
