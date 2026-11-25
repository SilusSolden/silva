"""Persistent daily to-do reminder. Stays up until the user closes it."""

from __future__ import annotations

import threading
import tkinter as tk
import tkinter.font as tkfont
from typing import Callable

from silva.commands.notes_store import (
    complete_todo_by_query,
    dismiss_todo_nag,
    format_due_clock,
    mark_todo_nag_popup,
    set_todo_done,
)
from silva.gui.display_manager import register, unregister, watch_shutdown
from silva.gui.monitors import geometry_on_monitor
from silva.logger import log_error, log_info

BG = "#FFF8E1"
ACCENT = "#E65100"
TEXT = "#263238"
MUTED = "#6D4C41"
GREEN = "#2E7D32"

_lock = threading.Lock()
_popups: dict[str, "TodoReminderPopup"] = {}


def _overlay_parent() -> tk.Misc | None:
    try:
        from silva.gui.display_host import host_root

        return host_root()
    except Exception:
        return None


class TodoReminderPopup:
    def __init__(
        self,
        parent: tk.Misc,
        *,
        user_id: str,
        item: dict,
        message: str,
        on_closed: Callable[[str, str], None] | None = None,
    ) -> None:
        self.user_id = user_id
        self.item_id = str(item.get("id") or "")
        self._on_closed = on_closed
        self._closed = False
        self.dialog = tk.Toplevel(parent)
        register(self.dialog, persistent=True)
        watch_shutdown(self.dialog)
        self.dialog.title("Silva - To-do reminder")
        self.dialog.configure(bg=BG)
        self.dialog.resizable(False, False)
        self.dialog.attributes("-topmost", True)
        self.dialog.protocol("WM_DELETE_WINDOW", self._dismiss)
        self.dialog.geometry(geometry_on_monitor(420, 230, anchor="ne"))

        title_font = tkfont.Font(family="Segoe UI", size=13, weight="bold")
        body_font = tkfont.Font(family="Segoe UI", size=10)
        clock = format_due_clock(item)
        heading = str(item.get("text") or "To-do")
        if clock:
            heading = f"{heading}  ·  {clock}"

        tk.Label(self.dialog, text=heading, font=title_font, fg=ACCENT, bg=BG, wraplength=380, justify="left").pack(
            anchor="w", padx=16, pady=(14, 6)
        )
        tk.Label(
            self.dialog,
            text=message + " This stays up until you close it or mark it done.",
            font=body_font,
            fg=TEXT,
            bg=BG,
            wraplength=380,
            justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 8))
        tk.Label(
            self.dialog,
            text="Say I no longer need that if you want it off the list, or bring it back later.",
            font=body_font,
            fg=MUTED,
            bg=BG,
            wraplength=380,
            justify="left",
        ).pack(anchor="w", padx=16)

        buttons = tk.Frame(self.dialog, bg=BG)
        buttons.pack(fill="x", padx=16, pady=(12, 14))
        tk.Button(buttons, text="Done for today", font=body_font, fg=GREEN, command=self._done).pack(side="left")
        tk.Button(buttons, text="Close reminder", font=body_font, command=self._dismiss).pack(side="right")

        try:
            self.dialog.deiconify()
            self.dialog.lift()
        except tk.TclError:
            pass
        mark_todo_nag_popup(user_id, self.item_id, is_open=True)
        log_info(f"To-do reminder popup shown for {heading[:80]}.")

    def _finish(self, result: str) -> None:
        if self._closed:
            return
        self._closed = True
        mark_todo_nag_popup(self.user_id, self.item_id, is_open=False)
        callback = self._on_closed
        if self.dialog.winfo_exists():
            unregister(self.dialog)
            self.dialog.destroy()
        with _lock:
            _popups.pop(self.item_id, None)
        if callback:
            callback(self.item_id, result)

    def _dismiss(self) -> None:
        dismiss_todo_nag(self.user_id, self.item_id)
        self._finish("dismissed")

    def _done(self) -> None:
        if not set_todo_done(self.user_id, self.item_id, done=True):
            complete_todo_by_query(self.user_id, self.item_id, done=True)
        dismiss_todo_nag(self.user_id, self.item_id)
        try:
            from silva.gui.todo_popup import refresh_todo_popup

            refresh_todo_popup(self.user_id)
        except Exception:
            pass
        self._finish("done")


def show_todo_reminder_popup(
    user_id: str,
    item: dict,
    message: str,
    *,
    on_closed: Callable[[str, str], None] | None = None,
) -> None:
    item_id = str(item.get("id") or "")
    if not item_id:
        return

    def _build(parent: tk.Misc) -> None:
        with _lock:
            existing = _popups.get(item_id)
            if existing is not None:
                try:
                    if existing.dialog.winfo_exists():
                        existing.dialog.deiconify()
                        existing.dialog.lift()
                        mark_todo_nag_popup(user_id, item_id, is_open=True)
                        return
                except tk.TclError:
                    _popups.pop(item_id, None)
        try:
            popup = TodoReminderPopup(
                parent,
                user_id=user_id,
                item=item,
                message=message,
                on_closed=on_closed,
            )
        except Exception as exc:
            log_error("To-do reminder popup failed", exc=exc)
            return
        with _lock:
            _popups[item_id] = popup

    parent = _overlay_parent()
    if parent is None:
        log_info("To-do reminder skipped — display host is not ready.")
        return
    try:
        parent.after(0, lambda: _build(parent))
    except Exception as exc:
        log_error("To-do reminder schedule failed", exc=exc)


def close_todo_reminder_popup(item_id: str | None = None) -> None:
    with _lock:
        if item_id:
            targets = [_popups[item_id]] if item_id in _popups else []
        else:
            targets = list(_popups.values())
    for popup in targets:
        try:
            popup.dialog.after(0, popup._dismiss)
        except tk.TclError:
            popup._dismiss()
