"""Session logging for Silva."""

from __future__ import annotations

import traceback
from datetime import datetime
from enum import Enum
from pathlib import Path

from silva.config import CONFIG_DIR, load_config, save_config

LOG_DIR = CONFIG_DIR / "logs"
LOG_FILE = LOG_DIR / "silva.log"


class LogKind(str, Enum):
    INPUT = "INPUT"
    RESPONSE = "RESPONSE"
    COMMAND = "COMMAND"
    ERROR = "ERROR"
    INFO = "INFO"


def _timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _write(line: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as handle:
        handle.write(line)


def log_event(kind: LogKind, message: str, *, detail: str = "") -> None:
    entry = f"[{_timestamp()}] {kind.value}: {message}"
    if detail:
        entry = f"{entry}\n{detail.rstrip()}"
    _write(entry + "\n")


def log_input(text: str, *, mode: str) -> None:
    log_event(LogKind.INPUT, f"({mode}) {text}")


def log_response(text: str) -> None:
    log_event(LogKind.RESPONSE, text)


def log_command(name: str, *, query: str | None = None) -> None:
    if query:
        log_event(LogKind.COMMAND, f"{name} | query: {query}")
    else:
        log_event(LogKind.COMMAND, name)


def _exception_detail(exc: BaseException | None) -> str:
    if exc is None:
        return ""
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))


def log_error(message: str, *, exc: BaseException | None = None) -> None:
    log_event(LogKind.ERROR, message, detail=_exception_detail(exc))
    try:
        from silva.console_view import print_error

        print_error(message)
    except Exception:
        print(f"Error: {message}")


def update_check_errors_enabled() -> bool:
    return bool(load_config().get("show_update_check_errors", False))


def set_update_check_errors_enabled(enabled: bool) -> bool:
    config = load_config()
    value = bool(enabled)
    config["show_update_check_errors"] = value
    save_config(config)
    return value


def log_update_check_error(message: str, *, exc: BaseException | None = None) -> None:
    if update_check_errors_enabled():
        log_error(message, exc=exc)
        return
    log_event(LogKind.ERROR, message, detail=_exception_detail(exc))


def log_info(message: str) -> None:
    log_event(LogKind.INFO, message)


def log_path() -> Path:
    return LOG_FILE
