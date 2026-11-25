"""Latest yes/no question wins. Older prompts do not keep a queue."""

from __future__ import annotations

import re

from silva.logger import log_info

KIND_NEWS = "news"
KIND_CAMERA_TEST = "camera_test"
KIND_PROFILE = "profile"

_SHORT_REPLY = re.compile(
    r"^(yes|yeah|yep|yup|yea|yah|ya|sure|ok|okay|please|"
    r"no|nope|nah|negative|cancel|skip|later|"
    r"not now|not right now|no thanks|don't|dont|do not|"
    r"show it|open it|go ahead|i do|do it|bring it up|"
    r"save (it|for later)|maybe later)\b",
    re.I,
)


def claim(assistant, kind: str) -> None:
    previous = getattr(assistant, "_yes_no_owner", None)
    if previous == KIND_CAMERA_TEST and kind != KIND_CAMERA_TEST:
        flow = getattr(assistant, "_camera_setup_flow", None)
        if isinstance(flow, dict):
            flow["yes_no"] = False
    assistant._yes_no_owner = kind
    if previous and previous != kind:
        log_info(f"Yes/no prompt switched from {previous} to {kind}")


def clear(assistant, kind: str | None = None) -> None:
    current = getattr(assistant, "_yes_no_owner", None)
    if kind is None or current == kind:
        assistant._yes_no_owner = None


def owner(assistant) -> str | None:
    return getattr(assistant, "_yes_no_owner", None)


def is_yes_no_reply(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", (text or "").strip())
    if not normalized:
        return False
    if len(normalized.split()) > 6:
        return False
    return bool(_SHORT_REPLY.match(normalized))


def dispatch(assistant, text: str) -> bool:
    """Send a short yes/no to the question that was asked last."""
    if not text:
        return False
    kind = owner(assistant)
    if kind == KIND_NEWS and getattr(assistant, "_news_flow", None):
        from silva.commands.news_phrases import is_news_no, is_news_yes

        if is_yes_no_reply(text) or is_news_no(text) or is_news_yes(text):
            return handle_news_flow(assistant, text)
    if not is_yes_no_reply(text):
        return False
    if kind == KIND_NEWS:
        if not getattr(assistant, "_news_flow", None):
            clear(assistant, KIND_NEWS)
            return False
        return handle_news_flow(assistant, text)
    if kind == KIND_CAMERA_TEST:
        flow = getattr(assistant, "_camera_setup_flow", None)
        if not flow or flow.get("yes_no") is False:
            clear(assistant, KIND_CAMERA_TEST)
            return False
        return handle_camera_setup_flow(assistant, text)
    if kind == KIND_PROFILE:
        return bool(assistant._handle_profile_switch_reply(text))
    return False


def check_news_briefing(assistant) -> None:
    if assistant._scheduled_alerts_paused() or assistant._asleep or assistant._news_flow:
        return
    from silva.commands.news_handler import offer_prompt_if_ready
    from silva.commands.news_monitor import can_use_news_briefing, refresh_daily_briefing
    from silva.config import load_config
    from silva.users.manager import get_active_user

    user = get_active_user()
    if not can_use_news_briefing(user):
        return
    refresh_daily_briefing(
        user_id=user.get("id", "guest"),
        user_name=user.get("name", "Admin"),
    )
    offer = offer_prompt_if_ready(user)
    if offer is None:
        return
    import time

    msg, flow = offer
    assistant._news_flow = flow
    claim(assistant, KIND_NEWS)
    assistant.say(msg, interruptible=False)
    settle = float(load_config().get("tts_post_speak_delay_seconds", 0.35))
    if settle > 0:
        time.sleep(settle)


def handle_news_flow(assistant, text: str) -> bool:
    flow = assistant._news_flow
    if flow is None:
        clear(assistant, KIND_NEWS)
        return False

    from silva.commands.news_handler import continue_news_flow
    from silva.commands.news_monitor import clear_pending_prompt
    from silva.commands.news_phrases import is_news_no, is_news_yes
    from silva.stt_quick_commands import is_complete_command

    yes = assistant._is_yes(text) or is_news_yes(text)
    no = assistant._is_no(text) or is_news_no(text)
    msg, next_flow = continue_news_flow(
        text,
        flow,
        is_yes=yes,
        is_no=no,
    )
    if next_flow is None:
        assistant._news_flow = None
        clear(assistant, KIND_NEWS)
        if msg:
            assistant.say(msg, interruptible=True)
        return True

    if is_complete_command(text) and not yes and not no:
        clear_pending_prompt()
        assistant._news_flow = None
        clear(assistant, KIND_NEWS)
        return False

    assistant._news_flow = next_flow
    return True


def offer_plugged_in_camera(assistant) -> None:
    if assistant._camera_setup_flow is not None:
        return
    from silva.commands.camera_setup_handler import offer_for_camera
    from silva.media.camera import take_camera_plug_events

    events = take_camera_plug_events()
    if not events:
        return
    event = events[-1]
    msg, flow = offer_for_camera(str(event.get("name") or "this camera"), is_combo=bool(event.get("is_combo")))
    assistant._apply_camera_setup_flow(msg, flow)
    if assistant._camera_setup_flow:
        claim(assistant, KIND_CAMERA_TEST)


def handle_camera_setup_flow(assistant, text: str) -> bool:
    flow = assistant._camera_setup_flow
    if flow is None:
        return False
    from silva.commands.camera_setup_handler import continue_camera_setup_flow
    from silva.commands.camera_setup_phrases import (
        is_camera_cancel_speech,
        is_camera_setup_command,
        parse_test_duration,
    )
    from silva.commands.intent import is_action_command
    from silva.interrupt import is_interrupt_command

    if is_yes_no_reply(text):
        if flow.get("yes_no") is False:
            return False
        if owner(assistant) not in (None, KIND_CAMERA_TEST):
            return False

    if is_interrupt_command(text) and not is_camera_cancel_speech(text):
        return False
    if (
        is_action_command(text)
        and not is_camera_setup_command(text)
        and parse_test_duration(text) is None
        and not assistant._is_yes(text)
        and not is_camera_cancel_speech(text)
    ):
        return False
    msg, next_flow = continue_camera_setup_flow(text, flow)
    if next_flow is None:
        clear(assistant, KIND_CAMERA_TEST)
    assistant._apply_camera_setup_flow(msg, next_flow)
    return True


def handle_camera_setup_command(assistant, text: str) -> bool:
    from silva.commands.camera_setup_handler import handle_camera_setup_speech
    from silva.commands.camera_setup_phrases import is_camera_setup_command

    if not is_camera_setup_command(text):
        return False
    msg, flow = handle_camera_setup_speech(text)
    if msg is None and flow is None:
        return False
    if flow is None:
        assistant.say(msg or "", interruptible=False)
        return True
    result = assistant._apply_camera_setup_flow(msg, flow)
    if assistant._camera_setup_flow:
        claim(assistant, KIND_CAMERA_TEST)
    return result
