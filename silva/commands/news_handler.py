"""Assistant-facing news briefing flows."""

from __future__ import annotations

from silva.commands.news_briefing import (
    briefing_summary_speech,
    format_briefing_text,
    generate_and_store_briefing,
    load_latest_briefing,
)
from silva.commands.news_display import open_briefing_txt
from silva.commands.news_monitor import (
    can_use_news_briefing,
    clear_pending_prompt,
    display_minutes,
    mark_prompt_offered,
    refresh_daily_briefing,
)
from silva.commands.news_phrases import (
    is_news_no,
    is_news_open_file,
    is_news_refresh_command,
    is_news_yes,
)


def deny_message() -> str:
    return "The daily news briefing is only available for the owner and admins."


def handle_news_speech(text: str, user: dict) -> tuple[str | None, dict | None]:
    if not can_use_news_briefing(user):
        return deny_message(), None

    user_id = user.get("id", "guest")
    user_name = user.get("name", "Admin")

    if is_news_refresh_command(text):
        briefing = generate_and_store_briefing(user_id=user_id, user_name=user_name)
        if is_news_open_file(text):
            return _open_saved_briefing(briefing, user_id)
        return _speak_saved_briefing(briefing)

    briefing = load_latest_briefing()
    if briefing is None:
        if refresh_daily_briefing(user_id=user_id, user_name=user_name, force=True):
            briefing = load_latest_briefing()
        if briefing is None:
            return "I could not build a news briefing right now. Check your internet connection and try again.", None

    if is_news_open_file(text):
        return _open_saved_briefing(briefing, user_id)
    return _speak_saved_briefing(briefing)


def start_daily_prompt(user: dict) -> tuple[str, dict]:
    briefing = load_latest_briefing()
    summary = briefing_summary_speech(briefing) if briefing else "Your daily news briefing is ready."
    return (
        f"{summary} Would you like to see it now? Say yes or no.",
        {"phase": "await_show_choice", "user_id": user.get("id", "guest")},
    )


def continue_news_flow(text: str, flow: dict, *, is_yes: bool, is_no: bool) -> tuple[str | None, dict | None]:
    phase = flow.get("phase")
    user_id = flow.get("user_id", "guest")

    if phase == "await_show_choice":
        yes = is_yes or is_news_yes(text)
        no = is_no or is_news_no(text)
        if yes and not no:
            briefing = load_latest_briefing()
            if briefing is None:
                return "I do not have a saved briefing yet.", None
            clear_pending_prompt()
            msg, _ = _open_saved_briefing(briefing, user_id)
            return msg, None
        if no:
            clear_pending_prompt()
            return (
                "Okay. I saved today's briefing. Ask me to show the news briefing whenever you want it.",
                None,
            )
        # Already asked once — keep listening silently for yes/no.
        return None, flow

    return None, None


def _speak_saved_briefing(briefing: dict) -> tuple[str, None]:
    clear_pending_prompt()
    summary = briefing_summary_speech(briefing)
    from silva.tts_pronunciation import prefetch_text_async

    prefetch_text_async(summary)
    return summary, None


def _open_saved_briefing(briefing: dict, user_id: str) -> tuple[str, None]:
    del user_id
    clear_pending_prompt()
    day = briefing.get("date", "today")
    from silva.commands.news_paths import BRIEFINGS_DIR, ensure_news_dir, prune_old_briefing_files

    ensure_news_dir()
    txt_path = BRIEFINGS_DIR / f"{day}.txt"
    txt_path.write_text(format_briefing_text(briefing), encoding="utf-8")
    prune_old_briefing_files(txt_path)
    open_briefing_txt(txt_path, auto_close_minutes=display_minutes())
    summary = briefing_summary_speech(briefing)
    from silva.tts_pronunciation import prefetch_text_async

    prefetch_text_async(summary)
    return (
        f"{summary} I opened the briefing in a text file. It will close automatically after "
        f"{display_minutes()} minutes.",
        None,
    )


def offer_prompt_if_ready(user: dict) -> tuple[str, dict] | None:
    from silva.commands.news_monitor import pending_prompt_for_user

    user_id = user.get("id", "guest")
    if not can_use_news_briefing(user):
        return None
    if not pending_prompt_for_user(user_id):
        return None
    mark_prompt_offered(user_id)
    return start_daily_prompt(user)
