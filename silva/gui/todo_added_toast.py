"""Short visual confirmation when a to-do is added — no extra speech."""

from __future__ import annotations

import threading
import tkinter as tk
import tkinter.font as tkfont

from silva.gui.display_manager import register, unregister, watch_shutdown
from silva.gui.monitors import geometry_on_monitor
from silva.logger import log_error

BG = "#1A237E"
TEXT = "#FFFFFF"
MUTED = "#C5CAE9"


def _overlay_parent() -> tk.Misc | None:
    try:
        from silva.gui.display_host import host_root

        return host_root()
    except Exception:
        return None


def show_todo_added_toast(number: int, title: str, when: str = "") -> None:
    heading = f"{number}. {title}".strip()
    detail = when.strip()

    def _build(parent: tk.Misc) -> None:
        dialog = tk.Toplevel(parent)
        register(dialog)
        watch_shutdown(dialog)
        dialog.overrideredirect(True)
        dialog.configure(bg=BG)
        dialog.attributes("-topmost", True)
        dialog.geometry(geometry_on_monitor(340, 92, anchor="ne"))
        title_font = tkfont.Font(family="Segoe UI", size=11, weight="bold")
        body_font = tkfont.Font(family="Segoe UI", size=9)
        tk.Label(dialog, text="•  Saved", font=title_font, fg=TEXT, bg=BG).pack(
            anchor="w", padx=14, pady=(10, 0)
        )
        tk.Label(dialog, text=heading, font=body_font, fg=TEXT, bg=BG, wraplength=310, justify="left").pack(
            anchor="w", padx=14
        )
        if detail:
            tk.Label(dialog, text=detail, font=body_font, fg=MUTED, bg=BG).pack(anchor="w", padx=14, pady=(0, 8))

        def _close() -> None:
            if dialog.winfo_exists():
                unregister(dialog)
                dialog.destroy()

        dialog.after(4000, _close)
        try:
            dialog.deiconify()
            dialog.lift()
        except tk.TclError:
            pass

    parent = _overlay_parent()
    if parent is not None:
        try:
            parent.after(0, lambda: _build(parent))
            return
        except Exception as exc:
            log_error("To-do toast schedule failed", exc=exc)

    def _run() -> None:
        root = tk.Tk()
        root.withdraw()
        register(root)
        _build(root)
        root.mainloop()

    threading.Thread(target=_run, name="silva-todo-toast", daemon=True).start()
