"""Chat overlay is disabled so it cannot cover games or other windows."""

from __future__ import annotations

from collections.abc import Callable

from silva.logger import log_info

CommandCallback = Callable[[str], None]


def start_command_overlay(*, on_command: CommandCallback) -> None:
    del on_command
    log_info("Silva chat overlay is disabled.")


def show_command_box() -> bool:
    return False


def hide_command_box() -> bool:
    return False


def overlay_root():
    try:
        from silva.gui.display_host import host_root

        return host_root()
    except Exception:
        return None
