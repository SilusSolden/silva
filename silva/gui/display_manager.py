"""Track and safely close active Silva display windows."""

from __future__ import annotations

import threading
from typing import Any

try:
    import tkinter as tk

    _TCL_ERRORS = (tk.TclError,)
except Exception:  # pragma: no cover - tk unavailable in some test environments
    tk = None  # type: ignore[assignment]
    _TCL_ERRORS = (Exception,)

_lock = threading.Lock()
_windows: list[Any] = []
_persistent: set[int] = set()
_shutting_down = False


def register(window: Any, *, persistent: bool = False) -> None:
    with _lock:
        if _shutting_down:
            return
        if window not in _windows:
            _windows.append(window)
        if persistent:
            _persistent.add(id(window))


def unregister(window: Any) -> None:
    with _lock:
        if window in _windows:
            _windows.remove(window)
        _persistent.discard(id(window))


def _window_alive(window: Any) -> bool:
    try:
        return bool(window.winfo_exists())
    except _TCL_ERRORS:
        return False


def _destroy_now(window: Any) -> None:
    unregister(window)
    if not _window_alive(window):
        return
    try:
        window.destroy()
    except _TCL_ERRORS:
        pass
    except Exception:
        pass


def _safe_destroy(window: Any) -> None:
    """Destroy on the window's Tk thread. Cross-thread destroy causes Tcl_AsyncDelete."""
    try:
        window.after(0, lambda w=window: _destroy_now(w))
        return
    except _TCL_ERRORS:
        pass
    except Exception:
        pass
    _destroy_now(window)


def close_all() -> None:
    with _lock:
        windows = [window for window in _windows if id(window) not in _persistent]

    for window in windows:
        _safe_destroy(window)


def shutdown() -> None:
    """Prepare GUI layers for process exit."""
    global _shutting_down
    _shutting_down = True
    close_all()


def is_shutting_down() -> bool:
    return _shutting_down


def watch_shutdown(root: Any, *, interval_ms: int = 250) -> None:
    """Let daemon Tk popups close themselves on the correct thread."""
    if tk is None:
        return

    def _poll() -> None:
        if not _window_alive(root):
            return
        if is_shutting_down():
            _safe_destroy(root)
            return
        try:
            root.after(interval_ms, _poll)
        except _TCL_ERRORS:
            pass

    try:
        root.after(interval_ms, _poll)
    except _TCL_ERRORS:
        pass
