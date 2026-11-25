"""Short notice when a command is too heavy for the PC."""

from __future__ import annotations

import threading
import tkinter as tk
import tkinter.font as tkfont

from silva.gui.display_manager import register, unregister, watch_shutdown
from silva.gui.monitors import geometry_on_monitor
from silva.logger import log_error, log_info

BG = "#FAFAFA"
ACCENT = "#C62828"
TEXT = "#263238"


def _overlay_parent() -> tk.Misc | None:
    try:
        from silva.gui.display_host import host_root

        return host_root()
    except Exception:
        return None


def show_perf_notice_popup(message: str, *, seconds: int = 10) -> None:
    text = (message or "").strip() or "This command was too heavy for the PC, so I stopped it."

    def _build(parent: tk.Misc) -> None:
        dialog = tk.Toplevel(parent)
        register(dialog)
        watch_shutdown(dialog)
        dialog.title("Silva")
        dialog.configure(bg=BG)
        dialog.resizable(False, False)
        dialog.attributes("-topmost", True)
        dialog.geometry(geometry_on_monitor(440, 210, anchor="center"))
        title_font = tkfont.Font(family="Segoe UI", size=12, weight="bold")
        body_font = tkfont.Font(family="Segoe UI", size=10)
        tk.Label(dialog, text="I had to stop that", font=title_font, fg=ACCENT, bg=BG).pack(
            anchor="w", padx=16, pady=(14, 6)
        )
        tk.Label(
            dialog,
            text=text,
            font=body_font,
            fg=TEXT,
            bg=BG,
            wraplength=400,
            justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 10))
        tk.Button(dialog, text="OK", font=body_font, command=dialog.destroy).pack(pady=(0, 12))

        def _close() -> None:
            if dialog.winfo_exists():
                unregister(dialog)
                dialog.destroy()

        dialog.protocol("WM_DELETE_WINDOW", _close)
        dialog.after(max(4, int(seconds)) * 1000, _close)
        try:
            dialog.deiconify()
            dialog.lift()
        except tk.TclError:
            pass
        log_info("Performance notice popup shown.")

    parent = _overlay_parent()
    if parent is not None:
        try:
            parent.after(0, lambda: _build(parent))
            return
        except Exception as exc:
            log_error("Performance notice schedule failed", exc=exc)

    def _run() -> None:
        root = tk.Tk()
        root.withdraw()
        register(root)
        _build(root)
        root.mainloop()

    threading.Thread(target=_run, name="silva-perf-notice", daemon=True).start()
