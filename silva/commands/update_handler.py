"""Handle spoken update questions and live apply — reloadable while Silva runs."""

from __future__ import annotations

import re
import threading

from silva.logger import log_info

_SLEEP_AFTER_RE = re.compile(
    r"\b(?:then|and)\s+(?:go\s+)?(?:back\s+to\s+)?sleep\b|"
    r"\bgo\s+(?:back\s+)?to\s+sleep\b",
    re.I,
)
_UPDATE_CHECK_RE = re.compile(
    r"\b(?:check|scan)\b.{0,24}\bupdates?\b|\bupdate check\b",
    re.I,
)
_YES_RE = re.compile(
    r"^\s*(?:yes|yeah|yep|yup|yea|yah|ya|sure|ok|okay|please|go ahead|do it|check)\b",
    re.I,
)
_NO_RE = re.compile(
    r"^\s*(?:no|nope|nah|negative|cancel|skip|later|not now|no thanks|don't|dont|do not|maybe later)\b",
    re.I,
)


def _speak_update(assistant, text: str) -> None:
    """Speak an update reply without waking Silva if she is asleep."""
    speaker = getattr(assistant, "_speak_now", None)
    if callable(speaker):
        speaker(text)
        return
    assistant.say(text, interruptible=False)


def _sleep_after_update(assistant) -> None:
    sleeper = getattr(assistant, "_enter_sleep", None)
    if callable(sleeper):
        sleeper()


def _is_yes_reply(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(text or "").strip())
    return bool(normalized) and len(normalized.split()) <= 8 and bool(_YES_RE.match(normalized))


def _is_no_reply(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(text or "").strip())
    return bool(normalized) and len(normalized.split()) <= 8 and bool(_NO_RE.match(normalized))


def _status_reason_text(status) -> str:
    if getattr(status, "pending_reload", False):
        return "an applied update is waiting for a reload"
    reasons = {
        "code_changed": "local Silva code files changed since the last applied update",
        "manifest_changed": "a newer release manifest was found",
        "version_only": "a newer version number is present but no file changes were found",
        "current": "the installed copy matches the newest manifest I can find",
    }
    return reasons.get(str(getattr(status, "reason", "") or ""), "the release information did not show a newer applied change")


def _status_help_line(status) -> str:
    current = str(getattr(status, "current_version", "") or "unknown")
    available = str(getattr(status, "available_version", "") or current)
    source = str(getattr(status, "source", "") or "the update manifest")
    if getattr(status, "needs_update", False):
        return (
            f"Version {current} is installed and version {available} is available from {source}; "
            f"{_status_reason_text(status)}."
        )
    return f"Version {current} is installed and that is the newest copy I can find; {_status_reason_text(status)}."


def _handle_update_feature_request(assistant, text: str) -> None:
    from silva.users.feature_requests import submit_feature_request
    from silva.users.manager import get_active_user
    from silva.users.update_help import record_update_help_request

    user = get_active_user() or {}
    allowed, message = record_update_help_request(
        user,
        "missing_from_update",
        f"User asked why this was not in the update: {text}",
        notify=False,
    )
    if not allowed:
        _speak_update(assistant, message)
        return
    submit_feature_request(
        user,
        "include_requested_item_in_update",
        reason=f"User asked why this was not in the update: {text}",
    )
    _speak_update(
        assistant,
        "That wasn't included in the update. I've sent it to the admins and owner as a feature request for review.",
    )


def _handle_update_not_current(assistant, text: str) -> None:
    from silva.dev.update_check import check_update_status
    from silva.users.manager import get_active_user
    from silva.users.update_help import record_update_help_request

    user = get_active_user() or {}
    allowed, message = record_update_help_request(
        user,
        "why_not_updated",
        f"User asked why Silva is not on the right version: {text}",
    )
    status = check_update_status()
    sent = "I've sent an update request to the admins and owner." if allowed else message
    explanation = (
        f"{_status_help_line(status)} I did not apply anything automatically because updates need "
        "owner or admin approval, and I don't want to interrupt you without a clear request."
    )
    setattr(assistant, "_update_help_check_pending", True)
    _speak_update(
        assistant,
        f"{explanation} {sent} Do you want me to check to see if there is an update?",
    )


def _handle_update_help_check(assistant) -> None:
    from silva.dev.update_check import check_update_status
    from silva.dev.update_permissions import can_apply_update, update_permission_message

    status = check_update_status()
    if not status.needs_update:
        version = status.available_version or status.current_version
        _speak_update(assistant, f"Already on the newest update, {version}. No new files were added.")
        return
    setattr(assistant, "_update_offer", {"version": status.available_version, "changes": list(status.changes)})
    changes = [str(item).strip().rstrip(".") for item in status.changes[:3] if str(item).strip()]
    summary = " ".join(changes)
    message = f"Update {status.available_version} is ready. {summary}".strip()
    if can_apply_update():
        setattr(assistant, "_update_help_apply_pending", True)
        message += " Would you like me to update?"
    else:
        message += " " + update_permission_message()
    _speak_update(assistant, message)


def _simple_item(value: object) -> str:
    text = str(value or "").strip().rstrip(".")
    text = re.sub(r"^(?:new feature|feature|patch|bug fix|update)\s*[:\-]\s*", "", text, flags=re.I)
    text = re.sub(r"\s*\([^)]*?\.py[^)]*?\)", "", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip()[:100]


def _number_word(count: int) -> str:
    return {1: "one", 2: "two", 3: "three"}.get(count, str(count))


def _ordinal_word(index: int) -> str:
    return {
        0: "first",
        1: "second",
        2: "third",
        3: "fourth",
        4: "fifth",
        5: "sixth",
        6: "seventh",
        7: "eighth",
        8: "ninth",
        9: "tenth",
    }.get(index, f"number {index + 1}")


def _update_summary_spoken(assistant, report, *, technical: bool) -> str:
    """Speak a simple numbered list and remember it for follow-up expansion."""
    items = [_simple_item(item) for item in (getattr(report, "items", None) or [])]
    items = [item for item in items if item]
    version = str(getattr(report, "version", "") or "").strip()
    shown = items[:3] if not technical and len(items) >= 2 else list(items)
    setattr(assistant, "_update_summary_items", items)
    setattr(assistant, "_update_summary_version", version)
    setattr(assistant, "_update_summary_shown_count", len(shown))
    setattr(assistant, "_update_summary_awaiting_choice", False)
    if technical or len(items) < 2:
        return str(getattr(report, "spoken", "") or "")
    lead = f"Update {version}" if version else "This update"
    parts = [f"{_ordinal_word(index)}, {item}." for index, item in enumerate(shown)]
    extra = len(items) - len(shown)
    if extra > 0:
        parts.append(f"and {extra} more")
    setattr(assistant, "_update_summary_awaiting_choice", True)
    return f"{lead} added {_number_word(len(items))} things: " + " ".join(parts)


def _expansion_detail(topic: str, version: str) -> str:
    from silva.users.manager import get_active_user

    try:
        from silva.commands.help_phrases import _WHICH_FEATURE, feature_detail_reply_for_user

        detail = feature_detail_reply_for_user(
            f"tell me in detail what {topic} does", get_active_user()
        )
        if detail and detail != _WHICH_FEATURE:
            return str(detail).strip()
    except Exception:
        pass
    try:
        from silva.dev.code_assist import explain_script

        detail = str(explain_script(topic) or "").strip()
        if detail:
            return detail
    except Exception:
        pass
    if version:
        return f"I only have the name {topic} from update {version}."
    return f"I only have the name {topic} right now."


def _remaining_update_spoken(assistant) -> str:
    items = [
        str(item)
        for item in (getattr(assistant, "_update_summary_items", None) or [])
        if str(item).strip()
    ]
    if not items:
        return ""
    shown_count = int(getattr(assistant, "_update_summary_shown_count", 0) or 0)
    shown_count = max(0, min(shown_count, len(items)))
    remaining = items[shown_count:]
    if not remaining:
        return ""
    version = str(getattr(assistant, "_update_summary_version", "") or "").strip()
    if len(remaining) == 1:
        lead = "The other one was"
    else:
        lead = f"The {_number_word(len(remaining))} others were"
    parts = [
        f"{_ordinal_word(shown_count + index)}, {item}."
        for index, item in enumerate(remaining)
    ]
    spoken = f"{lead}: " + " ".join(parts)
    if version and f"Version {version}" not in spoken:
        spoken = f"Version {version}. {spoken}"
    return spoken


def handle_update_expansion_speech(assistant, text: str) -> bool:
    """Expand one item from the last simple update list, or ask which one."""
    from silva.commands.update_phrases import (
        is_update_expand_phrase,
        is_update_extra_ask,
        update_expand_index,
    )

    items = [
        str(item)
        for item in (getattr(assistant, "_update_summary_items", None) or [])
        if str(item).strip()
    ]
    if not items:
        return False
    if is_update_extra_ask(text):
        spoken = _remaining_update_spoken(assistant)
        if spoken:
            setattr(assistant, "_update_summary_awaiting_choice", True)
            _speak_update(assistant, spoken)
            return True
    expand_ask = is_update_expand_phrase(text)
    awaiting_choice = bool(getattr(assistant, "_update_summary_awaiting_choice", False))
    index = update_expand_index(text, items) if (expand_ask or awaiting_choice) else None
    if index is None:
        if not expand_ask:
            return False
        setattr(assistant, "_update_summary_awaiting_choice", True)
        names = ", ".join(items[:3])
        _speak_update(assistant, f"Which one? {names}.")
        return True

    topic = items[index]
    version = str(getattr(assistant, "_update_summary_version", "") or "")
    setattr(assistant, "_update_summary_awaiting_choice", False)
    _speak_update(assistant, _expansion_detail(topic, version))
    return True


def handle_update_speech(assistant, text: str) -> bool:
    """Answer what's new or apply the waiting update into the running process."""
    from silva.commands.update_phrases import (
        is_ambiguous_update_confirm,
        is_code_detail_ask,
        is_update_confirm_phrase,
        is_update_decline_phrase,
        is_update_detail_ask,
        is_update_feature_request_phrase,
        is_update_not_current_phrase,
        is_update_status_phrase,
        is_whats_new_update_phrase,
    )

    if getattr(assistant, "_update_help_apply_pending", False) is True:
        setattr(assistant, "_update_help_apply_pending", False)
        if _is_yes_reply(text):
            apply_live_now(assistant)
            return True
        if _is_no_reply(text) or is_update_decline_phrase(text):
            _speak_update(assistant, "Okay, I won't apply that update.")
            return True
        return False

    if getattr(assistant, "_update_help_check_pending", False) is True:
        setattr(assistant, "_update_help_check_pending", False)
        if _is_yes_reply(text):
            _handle_update_help_check(assistant)
            return True
        if _is_no_reply(text) or is_update_decline_phrase(text):
            _speak_update(assistant, "Okay, I won't check right now.")
            return True
        return False

    if is_update_feature_request_phrase(text):
        _handle_update_feature_request(assistant, text)
        return True

    if is_update_not_current_phrase(text):
        _handle_update_not_current(assistant, text)
        return True

    if is_update_status_phrase(text):
        from silva.dev.whats_new_script import verify_update_status

        status = verify_update_status()
        items = [str(item).strip().rstrip(".") for item in status.items[:3]]
        detail = " ".join(item[0].upper() + item[1:] + "." for item in items if item)
        if status.up_to_date:
            message = f"Yes, version {status.current_version} is installed and it is the newest update."
        else:
            message = (
                f"No, version {status.current_version} is installed; "
                f"version {status.newest_version} is the newest update."
            )
        _speak_update(assistant, f"{message} {detail}".strip())
        return True

    if _UPDATE_CHECK_RE.search(str(text or "")):
        from silva.dev.update_check import check_update_status
        from silva.dev.update_permissions import can_apply_update, update_permission_message

        status = check_update_status()
        if not status.needs_update:
            version = status.available_version or status.current_version
            _speak_update(assistant, f"Already on the newest update, {version}. No new files were added.")
            return True
        assistant._update_offer = {
            "version": status.available_version,
            "changes": list(status.changes),
        }
        summary = " ".join(status.changes[:3])
        message = f"Update {status.available_version} is ready. {summary}".strip()
        if can_apply_update():
            message += " Say yes update to confirm."
        else:
            message += " " + update_permission_message()
        _speak_update(assistant, message)
        return True

    if is_update_decline_phrase(text):
        if getattr(assistant, "_update_offer", None):
            assistant._update_offer = None
            _speak_update(assistant, "Okay, I'll remind you later.")
            return True
        return False

    if is_whats_new_update_phrase(text):
        from silva.dev.whats_new_script import run_whats_new_script

        detailed = is_update_detail_ask(text) or not is_code_detail_ask(text)
        technical = is_code_detail_ask(text)
        report = run_whats_new_script(technical=technical, detailed=detailed, mark_told=True)
        spoken = _update_summary_spoken(assistant, report, technical=technical)
        version = str(getattr(report, "version", "") or "").strip()
        if version and f"Version {version}" not in spoken:
            spoken = f"Version {version}. {spoken}".strip()
        _speak_update(assistant, spoken)
        return True

    if is_update_confirm_phrase(text):
        sleep_after = bool(_SLEEP_AFTER_RE.search(str(text or "")))
        apply_live_now(assistant, sleep_after=sleep_after)
        return True

    if is_ambiguous_update_confirm(text) and getattr(assistant, "_update_offer", None):
        if any(
            getattr(assistant, name, None)
            for name in (
                "_notes_flow",
                "_news_flow",
                "_weather_feedback_flow",
                "_weather_forecast_flow",
                "_appointment_flow",
                "_camera_setup_flow",
                "_permission_flow",
            )
        ):
            return False
        apply_live_now(assistant)
        return True

    return False


def apply_live_now(assistant, *, sleep_after: bool = False) -> None:
    """Push folder code into this running Silva process."""
    from silva.dev.panel_update import scan_panel_changes
    from silva.dev.update_check import check_update_status
    from silva.dev.update_permissions import can_apply_update
    from silva.dev.update_scanner import code_file_hashes, load_bundled_manifest, scan_for_updates
    from silva.dev.whats_new_script import applied_hashes, recent_files, record_apply_delta
    from silva.users.manager import get_active_user
    from silva.users.tiers import normalize_tier

    active_user = get_active_user()
    if not can_apply_update(active_user):
        if normalize_tier(active_user.get("tier")) < 4:
            _speak_update(
                assistant,
                "Ask an admin, chat rep, or the owner to update Silva for you.",
            )
        else:
            _speak_update(assistant, "Ask the owner to approve this update before applying it.")
        if sleep_after:
            _sleep_after_update(assistant)
        return

    status = check_update_status()
    if not status.needs_update:
        version = status.available_version or status.current_version
        _speak_update(assistant, f"Already on the newest update, {version}. No new files were added.")
        if sleep_after:
            _sleep_after_update(assistant)
        return

    if getattr(assistant, "_update_apply_in_progress", False):
        if sleep_after:
            assistant._sleep_after_update = True
        _speak_update(assistant, "I'm already applying an update.")
        return

    panel = scan_panel_changes()
    version_scan = scan_for_updates()
    before = applied_hashes()
    pending_files = recent_files(code_file_hashes(), before)
    if (
        not panel.has_changes
        and not pending_files
        and not version_scan.available
        and not version_scan.pending_reload
    ):
        _speak_update(assistant, "Already up to date.")
        if sleep_after:
            _sleep_after_update(assistant)
        return

    assistant._update_apply_in_progress = True
    _speak_update(assistant, "Yes, I will update it now. Please hold on.")

    def worker() -> None:
        try:
            from silva.dev.live_update import apply_code_to_running_assistant

            ok, message = apply_code_to_running_assistant()
            log_info(message)
            printer = getattr(assistant, "_print_terminal_message", None)
            if callable(printer):
                printer(message)
            if ok:
                manifest = load_bundled_manifest()
                version = str(manifest.get("version") or "")
                after = code_file_hashes()
                files = recent_files(after, before)
                changelog = [
                    str(item).strip()
                    for item in (manifest.get("changelog") or [])
                    if str(item).strip()
                ]
                report = record_apply_delta(
                    files=files,
                    version=version,
                    hashes=after,
                    changelog=changelog,
                )
                _speak_update(assistant, report.spoken)
                assistant._update_offer = None
            else:
                _speak_update(assistant, message)
        except Exception as exc:
            detail = str(exc)
            log_info(f"Live update apply failed: {detail}")
            try:
                if type(exc).__name__ == "TclError" or "tcl" in detail.lower():
                    _speak_update(
                        assistant,
                        "The update is on disk. Restart Silva to finish loading the new windows.",
                    )
                else:
                    _speak_update(
                        assistant,
                        "The update did not finish. You can type update in the terminal.",
                    )
            except Exception:
                pass
        finally:
            assistant._update_apply_in_progress = False
            should_sleep = sleep_after or bool(getattr(assistant, "_sleep_after_update", False))
            if should_sleep:
                assistant._sleep_after_update = False
                _sleep_after_update(assistant)

    threading.Thread(target=worker, name="silva-voice-update", daemon=True).start()
