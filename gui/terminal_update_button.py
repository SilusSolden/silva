"""Clickable Update Silva button while the assistant is running."""

from __future__ import annotations

import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox
from typing import Callable

from silva.gui.display_manager import register, unregister, watch_shutdown
from silva.gui.monitors import geometry_on_monitor
from silva.logger import log_error, log_info

UpdateCallback = Callable[[], None]


def start_terminal_update_button(*, on_update: UpdateCallback) -> None:
    threading.Thread(
        target=_attach_when_host_ready,
        args=(on_update,),
        name="silva-terminal-update-btn",
        daemon=True,
    ).start()


def _attach_when_host_ready(on_update: UpdateCallback) -> None:
    try:
        from silva.gui.display_host import host_root

        parent = None
        for _ in range(80):
            parent = host_root()
            if parent is not None:
                break
            time.sleep(0.1)
        if parent is None:
            log_info("Update button skipped — display host was not ready.")
            return
        parent.after(0, lambda: _build_button(on_update, parent))
    except Exception as exc:
        log_error("Update button could not open", exc=exc)


def _build_button(on_update: UpdateCallback, parent: tk.Misc) -> None:
    window = tk.Toplevel(parent)
    register(window)
    watch_shutdown(window)
    window.title("Silva Update")
    window.resizable(False, False)
    window.transient(parent)

    width, height = 150, 42
    window.geometry(geometry_on_monitor(width, height, anchor="sw", margin=16))

    font = tkfont.Font(family="Segoe UI", size=9, weight="bold")

    def _click() -> None:
        if not messagebox.askyesno(
            "Update Silva",
            "Scan for changes, back up the current codebase, apply the update, and run checks?",
            parent=window,
        ):
            return
        on_update()

    def _hide() -> None:
        try:
            window.withdraw()
        except tk.TclError:
            pass

    tk.Button(
        window,
        text="Update Silva",
        font=font,
        command=_click,
        bg="#1A237E",
        fg="white",
        activebackground="#283593",
        activeforeground="white",
        relief="flat",
        padx=8,
        pady=4,
    ).pack(fill="both", expand=True, padx=4, pady=4)

    # Closing this button must not quit Silva.
    window.protocol("WM_DELETE_WINDOW", _hide)
    window.bind("<Destroy>", lambda _event: unregister(window))
