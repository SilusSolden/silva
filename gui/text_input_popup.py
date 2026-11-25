"""Small typed-input popup used when the microphone is not available."""

from __future__ import annotations

import threading
import tkinter as tk
import tkinter.font as tkfont
from collections.abc import Callable

from silva.gui.display_manager import register, unregister, watch_shutdown
from silva.gui.monitors import geometry_on_monitor
from silva.logger import log_error

_lock = threading.Lock()
_open = False


def _parent() -> tk.Misc | None:
    try:
        from silva.gui.display_host import host_root

        return host_root()
    except Exception:
        return None


def show_text_input_popup(
    title: str,
    prompt: str,
    on_submit: Callable[[str], None],
    *,
    initial_value: str = "",
    width: int = 520,
) -> None:
    parent = _parent()
    if parent is None:
        log_error(f"{title} box skipped — display host not ready")
        return
    try:
        parent.after(0, lambda: _open_box(parent, title, prompt, on_submit, initial_value, width))
    except Exception as exc:
        log_error(f"{title} box schedule failed", exc=exc)


def _open_box(
    parent: tk.Misc,
    title: str,
    prompt: str,
    on_submit: Callable[[str], None],
    initial_value: str,
    width: int,
) -> None:
    global _open
    with _lock:
        if _open:
            return
        _open = True
    try:
        dialog = tk.Toplevel(parent)
    except tk.TclError as exc:
        log_error(f"{title} box failed", exc=exc)
        _open = False
        return
    register(dialog)
    watch_shutdown(dialog)
    dialog.title(title)
    dialog.configure(bg="#FAFAFA")
    dialog.resizable(False, False)
    dialog.attributes("-topmost", True)
    dialog.geometry(geometry_on_monitor(width, 124, anchor="center"))
    font = tkfont.Font(family="Segoe UI", size=10)
    tk.Label(dialog, text=str(prompt or ""), font=font, bg="#FAFAFA", fg="#546E7A").pack(
        anchor="w", padx=12, pady=(10, 4)
    )
    entry = tk.Entry(dialog, font=font, width=max(24, width // 10))
    entry.insert(0, str(initial_value or ""))
    entry.pack(fill="x", padx=12, pady=(0, 10))
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
            on_submit(text)
        return "break"

    dialog.bind("<Escape>", lambda _event: close())
    dialog.protocol("WM_DELETE_WINDOW", close)
    entry.bind("<Return>", submit)
    try:
        dialog.lift()
        dialog.focus_force()
        entry.focus_set()
    except tk.TclError:
        pass
