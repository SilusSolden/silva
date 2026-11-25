"""Background terminal input while Silva runs."""

from __future__ import annotations

import json
import sys
import threading
from typing import Callable

from silva.dev.paths import DEV_STATE_FILE, ensure_dev_dir
from silva.dev.terminal_update import run_terminal_revert, run_terminal_scan, run_terminal_update
from silva.dev.test_runner import run_all_tests
from silva.dev.typed_command_access import (
    is_dev_terminal_command,
    normalize_typed_command,
    typed_command_help_for_user,
)

_listener_started = False
_lock = threading.Lock()

TypedCommandCallback = Callable[[str], None]


def _load_state() -> dict:
    ensure_dev_dir()
    if not DEV_STATE_FILE.exists():
        return {}
    try:
        data = json.loads(DEV_STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(state: dict) -> None:
    ensure_dev_dir()
    DEV_STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def last_test_passed() -> bool:
    return bool(_load_state().get("last_test_passed"))


def set_last_test_passed(passed: bool) -> bool:
    state = _load_state()
    state["last_test_passed"] = bool(passed)
    _save_state(state)


def run_check(*, apply_update: bool = False) -> tuple[bool, str]:
    result = run_all_tests(include_unit_tests=True)
    set_last_test_passed(result.passed)
    if result.passed:
        summary = f"All checks passed ({result.tests_run} unit tests)."
    else:
        broken = "\n".join(result.broken_items[:12])
        summary = f"Checks failed — {len(result.broken_items)} issue(s).\n{broken}"
    if apply_update:
        update_result = run_terminal_update()
        return update_result.ok, summary + "\n\n" + update_result.message
    return result.passed, summary + "\n\n" + result.output


def _can_run_dev_commands(user: dict) -> bool:
    from silva.users.manager import is_owner
    from silva.users.profile_access import can_open_control_panel

    return is_owner(user) or can_open_control_panel(user)


def handle_terminal_command(line: str) -> tuple[bool, str]:
    """Return (handled, message) for dev-only terminal commands."""
    cmd = line.strip().lower()
    if not cmd:
        return False, ""

    if cmd in {"help", "commands", "?"}:
        from silva.users.manager import get_active_user

        return True, typed_command_help_for_user(get_active_user())

    if cmd in {"chat", "open chat", "textbox", "open textbox", "open chat box", "command box"}:
        return True, "The on-screen chat box is turned off. Type commands in this terminal instead."

    if cmd in {"requests", "feature requests", "pending requests", "list requests", "show requests"}:
        from silva.users.feature_requests import list_pending_feature_requests
        from silva.users.manager import get_active_user, is_owner
        from silva.users.profile_access import can_open_control_panel

        user = get_active_user()
        if not (is_owner(user) or can_open_control_panel(user)):
            return True, "Only the owner and admins can view feature requests."
        pending = list_pending_feature_requests()
        if not pending:
            return True, "No pending feature requests."
        lines = ["Pending feature requests:"]
        for item in pending[:20]:
            name = str(item.get("user_name") or item.get("user_id") or "Guest")
            feature = str(item.get("feature") or "feature")
            reason = str(item.get("reason") or "").strip()
            suffix = f" - {reason}" if reason else ""
            lines.append(f"- {name}: {feature}{suffix}")
        return True, "\n".join(lines)

    if cmd in {"crosschat on", "crosschat off", "streamdeck on", "streamdeck off", "screenmonitor on", "screenmonitor off"}:
        from silva.config import load_config, save_config
        from silva.users.manager import get_active_user

        user = get_active_user()
        if not _can_run_dev_commands(user):
            return True, "Only the owner and admins can change these features."
        key, value = cmd.split()
        config_key = {
            "crosschat": "crosschat_memory_enabled",
            "streamdeck": "stream_deck_enabled",
            "screenmonitor": "screen_monitor_enabled",
        }[key]
        if key == "screenmonitor" and value == "on":
            from silva.dev.screen_monitor import approved

            if not approved():
                return True, "Approve screen monitoring first with: screenmonitor approve"
        config = load_config()
        config[config_key] = value == "on"
        save_config(config)
        return True, f"{key} turned {value}."

    if cmd in {"codeassist on", "codeassist off"}:
        from silva.dev.code_assist import set_enabled

        value = cmd.endswith(" on")
        ok = set_enabled(value)
        return True, f"Code assist turned {'on' if value else 'off'}." if ok else "Only the owner can change code assist."

    if cmd == "screenmonitor approve":
        from silva.dev.screen_monitor import approve
        from silva.users.manager import get_active_user, is_owner

        user = get_active_user()
        if not is_owner(user):
            return True, "Only the owner can approve screen monitoring."
        ok = approve(str(user.get("id") or ""))
        return True, "Screen monitoring approved." if ok else "Approval failed."

    if not is_dev_terminal_command(line):
        return False, ""

    from silva.users.manager import get_active_user

    user = get_active_user()
    if not _can_run_dev_commands(user):
        return True, "Dev commands are only available to the owner and admins."

    if cmd == "status":
        passed = last_test_passed()
        return True, "Last check: PASSED" if passed else "Last check: FAILED or not run yet."

    if cmd == "scan":
        result = run_terminal_scan()
        return True, result.message

    if cmd in {"check", "test"}:
        passed, message = run_check(apply_update=False)
        return True, message

    if cmd == "update check":
        from silva.dev.update_check import format_status_message

        return True, format_status_message()

    if cmd == "update":
        from silva.dev.terminal_update import run_terminal_update as run_update

        result = run_update()
        set_last_test_passed(result.ok)
        return True, result.message

    if cmd == "revert":
        result = run_terminal_revert()
        return True, result.message

    return False, ""


def terminal_banner() -> str:
    from silva.console_view import is_clean_console
    from silva.users.manager import get_active_user, is_owner
    from silva.users.profile_access import can_open_control_panel

    if is_clean_console():
        lines = [
            "Type a command and press Enter — same as speaking.",
            "Close this window or say goodbye to stop Silva.",
        ]
    else:
        lines = [
            "=== Silva terminal ===",
            "Type any command and press Enter — same as speaking to Silva.",
            "Examples: weather   open voice recorder   pause the video",
            "Type help for more.",
        ]
    user = get_active_user()
    if is_owner(user) or can_open_control_panel(user):
        lines.append("Owner/admin: scan | update | revert | requests | codeassist on/off | crosschat on/off")
        lines.append("Owner: screenmonitor approve | streamdeck on/off | screenmonitor on/off")
    return "\n".join(lines)


def start_terminal_listener(
    *,
    on_message: Callable[[str], None],
    on_typed_command: TypedCommandCallback | None = None,
) -> None:
    """Read typed input from stdin in a daemon thread."""
    from silva.config import load_config

    if not bool(load_config().get("terminal_commands_enabled", True)):
        return
    global _listener_started
    with _lock:
        if _listener_started:
            return
        _listener_started = True

    def _loop() -> None:
        from silva.console_view import is_clean_console

        if bool(load_config().get("terminal_commands_show_banner", True)) and not is_clean_console():
            print(terminal_banner())
        while True:
            try:
                line = sys.stdin.readline()
            except (KeyboardInterrupt, EOFError):
                break
            if not line:
                break
            if not line.strip():
                continue

            handled, message = handle_terminal_command(line)
            if handled:
                on_message(message)
                continue

            if on_typed_command is not None:
                command = normalize_typed_command(line)
                if command:
                    on_typed_command(line)
                continue

            on_message("Typed commands are not enabled.")

    threading.Thread(target=_loop, name="silva-terminal-cmds", daemon=True).start()
