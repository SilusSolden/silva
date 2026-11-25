"""Clickable to-do checklist popup. Circles turn green when completed."""

from __future__ import annotations

import threading
import tkinter as tk
import tkinter.font as tkfont
from typing import Callable

from silva.commands.notes_store import format_due_clock, list_todos, set_todo_done
from silva.gui.display_manager import register, unregister, watch_shutdown
from silva.gui.monitors import geometry_on_monitor
from silva.logger import log_error, log_info

BG = "#FAFAFA"
CARD = "#FFFFFF"
TEXT = "#263238"
MUTED = "#78909C"
GREEN = "#43A047"
GREEN_FILL = "#C8E6C9"
EMPTY = "#FFFFFF"
EMPTY_OUTLINE = "#B0BEC5"
ACCENT = "#1A237E"

_lock = threading.Lock()
_window: tk.Misc | None = None
_panel: "TodoPopup | None" = None


class _CheckCircle(tk.Canvas):
    def __init__(self, master: tk.Misc, *, done: bool, command: Callable[[], None]) -> None:
        super().__init__(master, width=28, height=28, bg=CARD, highlightthickness=0, bd=0)
        self._command = command
        self._oval = self.create_oval(3, 3, 25, 25, width=2)
        self.set_done(done)
        self.bind("<Button-1>", lambda _e: self._command())

    def set_done(self, done: bool) -> None:
        if done:
            self.itemconfig(self._oval, fill=GREEN, outline=GREEN)
        else:
            self.itemconfig(self._oval, fill=EMPTY, outline=EMPTY_OUTLINE)


class TodoPopup:
    def __init__(self, parent: tk.Misc, *, user_id: str) -> None:
        self.user_id = user_id
        self._closed = False
        self.dialog = tk.Toplevel(parent)
        register(self.dialog, persistent=True)
        watch_shutdown(self.dialog)
        self.dialog.title("Silva - To-do list")
        self.dialog.configure(bg=BG)
        self.dialog.resizable(True, True)
        self.dialog.attributes("-topmost", True)
        self.dialog.protocol("WM_DELETE_WINDOW", self.close)
        width, height = 420, 540
        self.dialog.geometry(geometry_on_monitor(width, height, anchor="center"))

        title_font = tkfont.Font(family="Segoe UI", size=13, weight="bold")
        body_font = tkfont.Font(family="Segoe UI", size=10)
        self._body_font = body_font

        header = tk.Frame(self.dialog, bg=BG)
        header.pack(fill="x", padx=16, pady=(14, 6))
        tk.Label(header, text="To-do list", font=title_font, fg=ACCENT, bg=BG).pack(side="left")
        tk.Button(header, text="Close", font=body_font, command=self.close).pack(side="right")

        canvas_host = tk.Frame(self.dialog, bg=BG)
        canvas_host.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self._canvas = tk.Canvas(canvas_host, bg=BG, highlightthickness=0)
        scroll = tk.Scrollbar(canvas_host, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)
        self._list = tk.Frame(self._canvas, bg=BG)
        self._list_id = self._canvas.create_window((0, 0), window=self._list, anchor="nw")
        self._list.bind("<Configure>", self._on_list_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._canvas.bind("<MouseWheel>", self._on_mousewheel)
        self._list.bind("<MouseWheel>", self._on_mousewheel)

        self.reload()
        try:
            self.dialog.deiconify()
            self.dialog.lift()
            self.dialog.focus_force()
        except tk.TclError:
            pass
        log_info("To-do list popup shown.")

    def _on_list_configure(self, _event=None) -> None:
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        self._canvas.itemconfigure(self._list_id, width=event.width)

    def _on_mousewheel(self, event) -> None:
        if not self._window_alive():
            return
        self._canvas.yview_scroll(int(-event.delta / 120), "units")

    def _window_alive(self) -> bool:
        try:
            return bool(self.dialog.winfo_exists())
        except tk.TclError:
            return False

    def reload(self) -> None:
        if not self._window_alive():
            return
        for child in self._list.winfo_children():
            child.destroy()
        items = list_todos(self.user_id)
        if not items:
            tk.Label(
                self._list,
                text="No to-dos yet. Say add this to the to-do list, or type one in.",
                font=self._body_font,
                fg=MUTED,
                bg=BG,
                wraplength=360,
                justify="left",
            ).pack(anchor="w", padx=8, pady=12)
            return
        for index, item in enumerate(items, start=1):
            self._add_row(item, number=index)

    def _add_row(self, item: dict, *, number: int | None = None) -> None:
        done = bool(item.get("done"))
        row = tk.Frame(self._list, bg=GREEN_FILL if done else CARD, padx=8, pady=8)
        row.pack(fill="x", padx=4, pady=4)

        def toggle(item_id: str = str(item.get("id")), frame: tk.Frame = row) -> None:
            current = False
            for existing in list_todos(self.user_id):
                if existing.get("id") == item_id:
                    current = bool(existing.get("done"))
                    break
            updated = set_todo_done(self.user_id, item_id, done=not current)
            if updated is None:
                return
            now_done = bool(updated.get("done"))
            circle.set_done(now_done)
            frame.configure(bg=GREEN_FILL if now_done else CARD)
            label.configure(bg=GREEN_FILL if now_done else CARD, fg=MUTED if now_done else TEXT)

        circle = _CheckCircle(row, done=done, command=toggle)
        circle.pack(side="left", padx=(0, 10))
        caption = str(item.get("text") or "")
        if number is not None:
            caption = f"{number}. {caption}"
        if item.get("repeat") == "daily":
            clock = format_due_clock(item)
            caption += f"  · {clock}" if clock else "  · daily"
        label = tk.Label(
            row,
            text=caption,
            font=self._body_font,
            fg=MUTED if done else TEXT,
            bg=GREEN_FILL if done else CARD,
            wraplength=320,
            justify="left",
            anchor="w",
        )
        label.pack(side="left", fill="x", expand=True)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        global _window, _panel
        if self._window_alive():
            unregister(self.dialog)
            self.dialog.destroy()
        with _lock:
            if _panel is self:
                _panel = None
                _window = None


def _overlay_parent() -> tk.Misc | None:
    try:
        from silva.gui.display_host import host_root

        return host_root()
    except Exception:
        return None


def show_todo_popup(user_id: str) -> None:
    def _build(parent: tk.Misc) -> None:
        global _window, _panel
        with _lock:
            if _panel is not None:
                try:
                    if _panel.dialog.winfo_exists():
                        _panel.user_id = user_id
                        _panel.reload()
                        _panel.dialog.deiconify()
                        _panel.dialog.lift()
                        return
                except tk.TclError:
                    pass
        try:
            panel = TodoPopup(parent, user_id=user_id)
        except Exception as exc:
            log_error("To-do popup failed", exc=exc)
            return
        with _lock:
            _panel = panel
            _window = panel.dialog

    parent = _overlay_parent()
    if parent is not None:
        try:
            parent.after(0, lambda: _build(parent))
            return
        except Exception as exc:
            log_error("To-do popup schedule failed", exc=exc)

    def _run() -> None:
        root = tk.Tk()
        root.withdraw()
        register(root, persistent=True)
        _build(root)
        root.mainloop()

    threading.Thread(target=_run, name="silva-todo-popup", daemon=True).start()


def refresh_todo_popup(user_id: str) -> None:
    with _lock:
        panel = _panel
    if panel is None:
        return

    def _reload() -> None:
        try:
            if panel.dialog.winfo_exists():
                panel.user_id = user_id
                panel.reload()
        except tk.TclError:
            pass

    try:
        panel.dialog.after(0, _reload)
    except tk.TclError:
        pass


def close_todo_popup() -> None:
    with _lock:
        panel = _panel
    if panel is None:
        return
    try:
        panel.dialog.after(0, panel.close)
    except tk.TclError:
        panel.close()
