"""Unlimited text popup when speech fails for a note or to-do."""

from __future__ import annotations

import threading
import tkinter as tk
import tkinter.font as tkfont
from typing import Callable

from silva.commands.notes_store import add_note, update_todo
from silva.gui.display_manager import register, unregister, watch_shutdown
from silva.gui.monitors import geometry_on_monitor
from silva.logger import log_error, log_info

BG = "#FAFAFA"
ACCENT = "#1A237E"
MUTED = "#78909C"


def _overlay_parent() -> tk.Misc | None:
    try:
        from silva.gui.display_host import host_root

        return host_root()
    except Exception:
        return None


class NotesTypePopup:
    def __init__(
        self,
        parent: tk.Misc,
        *,
        user_id: str,
        kind: str,
        on_saved: Callable[[str], None] | None = None,
        on_closed: Callable[[], None] | None = None,
        replace_id: str | None = None,
    ) -> None:
        self.user_id = user_id
        self.kind = "todo" if kind == "todo" else "note"
        self._on_saved = on_saved
        self._on_closed = on_closed
        self._replace_id = replace_id
        self._closed = False

        self.dialog = tk.Toplevel(parent)
        register(self.dialog, persistent=True)
        watch_shutdown(self.dialog)
        title = "Silva - Type a to-do" if self.kind == "todo" else "Silva - Type a note"
        self.dialog.title(title)
        self.dialog.configure(bg=BG)
        self.dialog.resizable(True, True)
        self.dialog.attributes("-topmost", True)
        self.dialog.protocol("WM_DELETE_WINDOW", self._close)
        self.dialog.geometry(geometry_on_monitor(520, 420, anchor="center"))

        title_font = tkfont.Font(family="Segoe UI", size=13, weight="bold")
        body_font = tkfont.Font(family="Segoe UI", size=10)

        heading = "Type your to-do" if self.kind == "todo" else "Type your note"
        tk.Label(self.dialog, text=heading, font=title_font, fg=ACCENT, bg=BG).pack(
            anchor="w", padx=16, pady=(14, 4)
        )
        tk.Label(
            self.dialog,
            text="No word limit. Press Enter or Save to keep it. Shift+Enter starts a new line.",
            font=body_font,
            fg=MUTED,
            bg=BG,
            wraplength=480,
            justify="left",
        ).pack(anchor="w", padx=16)

        self._text = tk.Text(self.dialog, font=body_font, wrap="word", undo=True)
        self._text.pack(fill="both", expand=True, padx=16, pady=10)
        self._text.bind("<Return>", self._on_return)
        self._text.bind("<KP_Enter>", self._on_return)
        self._text.focus_set()

        self._status = tk.StringVar(value="")
        tk.Label(self.dialog, textvariable=self._status, font=body_font, fg="#1B5E20", bg=BG).pack(
            anchor="w", padx=16
        )

        row = tk.Frame(self.dialog, bg=BG)
        row.pack(fill="x", padx=16, pady=(4, 14))
        tk.Button(row, text="Save", font=body_font, width=12, command=self._save).pack(side="left")
        tk.Button(row, text="Cancel", font=body_font, width=10, command=self._close).pack(side="right")

    def _on_return(self, event) -> str | None:
        if int(getattr(event, "state", 0)) & 0x0001:
            return None
        self._save()
        return "break"

        try:
            self.dialog.deiconify()
            self.dialog.lift()
            self.dialog.focus_force()
        except tk.TclError:
            pass
        log_info(f"{self.kind} type popup shown.")

    def _save(self) -> None:
        body = self._text.get("1.0", "end-1c")
        if not body.strip():
            self._status.set("Type something first.")
            return
        if self.kind == "todo":
            if self._replace_id:
                update_todo(self.user_id, self._replace_id, text=body.strip())
            else:
                from silva.commands.notes_handler import _save_todo

                _save_todo(self.user_id, body)
            try:
                from silva.gui.todo_popup import refresh_todo_popup

                refresh_todo_popup(self.user_id)
            except Exception:
                pass
        else:
            add_note(self.user_id, body)
        if self._on_saved:
            self._on_saved(body.strip())
        self._close()

    def _close(self) -> None:
        if self._closed:
            return
        self._closed = True
        callback = self._on_closed
        if self.dialog.winfo_exists():
            unregister(self.dialog)
            self.dialog.destroy()
        if callback:
            callback()


def show_notes_type_popup(
    user_id: str,
    kind: str = "note",
    *,
    on_saved: Callable[[str], None] | None = None,
    on_closed: Callable[[], None] | None = None,
    replace_id: str | None = None,
) -> None:
    def _build(parent: tk.Misc) -> None:
        try:
            NotesTypePopup(
                parent,
                user_id=user_id,
                kind=kind,
                on_saved=on_saved,
                on_closed=on_closed,
                replace_id=replace_id,
            )
        except Exception as exc:
            log_error("Notes type popup failed", exc=exc)

    parent = _overlay_parent()
    if parent is not None:
        try:
            parent.after(0, lambda: _build(parent))
            return
        except Exception as exc:
            log_error("Notes type popup schedule failed", exc=exc)

    def _run() -> None:
        root = tk.Tk()
        root.withdraw()
        register(root, persistent=True)
        _build(root)
        root.mainloop()

    threading.Thread(target=_run, name="silva-notes-type", daemon=True).start()
