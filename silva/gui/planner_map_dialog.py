"""Popup so you can type or paste a building for Silva to map in the planner."""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from typing import Callable

from silva.gui.display_manager import register, unregister, watch_shutdown
from silva.gui.monitors import geometry_on_monitor
from silva.logger import log_error

BG = "#FAFAFA"
ACCENT = "#1A237E"
MUTED = "#607D8B"


def _parent() -> tk.Misc | None:
    try:
        from silva.gui.display_host import host_root

        return host_root()
    except Exception:
        return None


class PlannerMapDialog:
    def __init__(self, parent: tk.Misc, *, initial: str = "", on_map: Callable[[str], None] | None = None) -> None:
        self._on_map = on_map
        self._closed = False
        self.dialog = tk.Toplevel(parent)
        register(self.dialog, persistent=True)
        watch_shutdown(self.dialog)
        self.dialog.title("Silva - Map a building")
        self.dialog.configure(bg=BG)
        self.dialog.geometry(geometry_on_monitor(520, 340, anchor="center"))
        self.dialog.protocol("WM_DELETE_WINDOW", self.close)
        title = tkfont.Font(family="Segoe UI", size=12, weight="bold")
        body = tkfont.Font(family="Segoe UI", size=10)
        tk.Label(self.dialog, text="Tell Silva what to map", font=title, fg=ACCENT, bg=BG).pack(anchor="w", padx=16, pady=(14, 6))
        tk.Label(
            self.dialog,
            text="Example: two bedroom house with a kitchen, bathroom, and garage, two stories.",
            font=body,
            fg=MUTED,
            bg=BG,
            wraplength=480,
            justify="left",
        ).pack(anchor="w", padx=16)
        self.text = tk.Text(self.dialog, height=8, wrap="word", font=body)
        self.text.pack(fill="both", expand=True, padx=16, pady=10)
        if initial:
            self.text.insert("1.0", initial)
        row = tk.Frame(self.dialog, bg=BG)
        row.pack(fill="x", padx=16, pady=(0, 14))
        tk.Button(row, text="Map it", font=body, command=self._submit).pack(side="right")
        tk.Button(row, text="Cancel", font=body, command=self.close).pack(side="right", padx=8)
        try:
            self.dialog.lift()
            self.text.focus_set()
        except tk.TclError:
            pass

    def _submit(self) -> None:
        body = self.text.get("1.0", "end").strip()
        callback = self._on_map
        self.close()
        if body and callback:
            callback(body)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self.dialog.winfo_exists():
                unregister(self.dialog)
                self.dialog.destroy()
        except tk.TclError:
            pass


def show_planner_map_dialog(initial: str = "", on_map: Callable[[str], None] | None = None) -> None:
    parent = _parent()
    if parent is None:
        log_error("Planner map popup needs the Silva display.")
        return

    def _open() -> None:
        PlannerMapDialog(parent, initial=initial, on_map=on_map)

    try:
        parent.after(0, _open)
    except Exception as exc:
        log_error("Planner map popup failed", exc=exc)
