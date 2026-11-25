"""Always-on background task loop for Silva."""

from __future__ import annotations

import threading
import time

from silva.config import load_config
from silva.logger import log_error


def background_task_interval() -> float:
    try:
        return max(0.5, float(load_config().get("background_task_interval_seconds", 1.0)))
    except (TypeError, ValueError):
        return 1.0


def stt_poll_timeout() -> float:
    try:
        return max(0.2, float(load_config().get("stt_background_poll_timeout", 0.4)))
    except (TypeError, ValueError):
        return 0.4


def stt_listen_timeout() -> float:
    """How long to wait for the user to start speaking during active listening."""
    try:
        return max(2.0, float(load_config().get("stt_listen_timeout", 12.0)))
    except (TypeError, ValueError):
        return 8.0


def wake_listen_timeout() -> float:
    try:
        return max(2.0, float(load_config().get("wake_listen_timeout_seconds", 8.0)))
    except (TypeError, ValueError):
        return 8.0


class BackgroundRunner:
    """Run Silva maintenance tasks on a timer, independent of voice input."""

    def __init__(self, tick) -> None:
        self._tick = tick
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="silva-background", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as exc:
                log_error("Background task tick failed", exc=exc)
            self._stop.wait(background_task_interval())
