"""Hidden Tk host so popups share one Tcl thread and sit on the launch monitor."""

from __future__ import annotations

import threading
import tkinter as tk

from silva.gui.display_manager import register, unregister, watch_shutdown
from silva.logger import log_info

_lock = threading.Lock()
_root: tk.Tk | None = None
_started = False


def start_display_host() -> None:
    global _started
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_run, name="silva-display-host", daemon=True).start()


def host_root() -> tk.Tk | None:
    return _root


def _run() -> None:
    global _root
    root = tk.Tk()
    _root = root
    register(root, persistent=True)
    watch_shutdown(root)
    root.overrideredirect(True)
    try:
        root.attributes("-toolwindow", True)
        root.attributes("-alpha", 0.0)
    except tk.TclError:
        pass
    # Keep mapped off-screen. A withdrawn owner hides Toplevel weather popups.
    root.geometry("1x1+-32000+-32000")
    log_info("Silva display host ready (no Chat overlay).")
    root.protocol("WM_DELETE_WINDOW", lambda: None)
    try:
        root.mainloop()
    except Exception as exc:
        log_info(f"Silva display host loop ended: {exc}")
    unregister(root)
    _root = None
    log_info("Silva display host stopped.")
