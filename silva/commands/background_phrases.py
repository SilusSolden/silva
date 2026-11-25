"""Speech for hiding the console so Silva can stay in the background."""

from __future__ import annotations

import re


def _normalize(text: str) -> str:
    text = text.strip().lower()
    text = text.replace("'", "")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_HIDE = (
    "hide the console",
    "hide the terminal",
    "hide cmd",
    "hide the command window",
    "run in the background",
    "go to the background",
    "background mode",
    "stay in the background",
    "dont make me click the terminal",
    "i dont want to click the console",
    "minimize the console",
    "minimize the terminal",
)

_SHOW = (
    "show the console",
    "show the terminal",
    "show cmd",
    "bring up the console",
    "bring up the terminal",
    "open the command window",
    "show the command window",
    "restore the console",
    "show silva",
    "show the silva window",
    "open the silva window",
    "bring silva up",
    "bring up silva",
)


def is_hide_console_command(text: str) -> bool:
    return _normalize(text) in _HIDE


def is_show_console_command(text: str) -> bool:
    return _normalize(text) in _SHOW


def is_background_command(text: str) -> bool:
    return is_hide_console_command(text) or is_show_console_command(text)
