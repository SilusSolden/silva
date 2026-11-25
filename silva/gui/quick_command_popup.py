"""Tiny type box from the background hotkey — does not stay over games."""

from __future__ import annotations

import threading
import tkinter as tk
import tkinter.font as tkfont
from collections.abc import Callable

from silva.gui.display_manager import register, unregister, watch_shutdown
from silva.gui.monitors import geometry_on_monitor
from silva.logger import log_error, log_info

_lock = threading.Lock()
_open = False


def _parent() -> tk.Misc | None:
    try:
        from silva.gui.display_host import host_root

        return host_root()
    except Exception:
        return None


def show_quick_command_popup(on_command: Callable[[str], None]) -> None:
    parent = _parent()
    if parent is None:
        log_error("Quick command box skipped — display host not ready")
        return
    try:
        parent.after(0, lambda: _open_box(parent, on_command))
    except Exception as exc:
        log_error("Quick command box schedule failed", exc=exc)


def _open_box(parent: tk.Misc, on_command: Callable[[str], None]) -> None:
    global _open
    with _lock:
        if _open:
            return
        _open = True
    try:
        dialog = tk.Toplevel(parent)
    except tk.TclError as exc:
        log_error("Quick command box failed", exc=exc)
        _open = False
        return
    register(dialog)
    watch_shutdown(dialog)
    dialog.title("Silva")
    dialog.configure(bg="#FAFAFA")
    dialog.resizable(False, False)
    dialog.attributes("-topmost", True)
    dialog.geometry(geometry_on_monitor(420, 92, anchor="se"))
    body = tkfont.Font(family="Segoe UI", size=10)
    tk.Label(
        dialog,
        text="Type a command for Silva, then Enter. Esc closes.",
        font=body,
        bg="#FAFAFA",
        fg="#546E7A",
    ).pack(anchor="w", padx=12, pady=(10, 4))
    entry = tk.Entry(dialog, font=body, width=42)
    entry.pack(fill="x", padx=12, pady=(0, 12))
    entry.focus_set()

    def close() -> None:
        global _open
        try:
            unregister(dialog)
            dialog.destroy()
        except tk.TclError:
            pass
        _open = False

    def submit(_event=None) -> str:
        text = entry.get().strip()
        close()
        if text:
            log_info(f"Quick command typed: {text[:80]}")
            on_command(text)
        return "break"

    dialog.bind("<Escape>", lambda _e: close())
    dialog.protocol("WM_DELETE_WINDOW", close)
    entry.bind("<Return>", submit)
    try:
        dialog.lift()
        dialog.focus_force()
        entry.focus_set()
    except tk.TclError:
        pass
