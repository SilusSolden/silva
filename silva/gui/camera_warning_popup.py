"""Simple warning popup for camera + mic combo devices."""

from __future__ import annotations

import threading
import tkinter as tk
import tkinter.font as tkfont
from typing import Callable

from silva.gui.display_manager import register, unregister, watch_shutdown
from silva.gui.monitors import geometry_on_monitor
from silva.logger import log_error, log_info
from silva.media.camera import COMBO_HEAT_WARNING

BG = "#FAFAFA"
ACCENT = "#E65100"
TEXT = "#263238"
MUTED = "#78909C"

_lock = threading.Lock()
_dialog: tk.Misc | None = None


def _overlay_parent() -> tk.Misc | None:
    try:
        from silva.gui.display_host import host_root

        return host_root()
    except Exception:
        return None


class CameraWarningPopup:
    def __init__(
        self,
        parent: tk.Misc,
        *,
        camera_name: str,
        on_choice: Callable[[str], None] | None = None,
    ) -> None:
        self._on_choice = on_choice
        self._closed = False
        self.dialog = tk.Toplevel(parent)
        register(self.dialog, persistent=True)
        watch_shutdown(self.dialog)
        self.dialog.title("Silva - Camera warning")
        self.dialog.configure(bg=BG)
        self.dialog.resizable(False, False)
        self.dialog.attributes("-topmost", True)
        self.dialog.protocol("WM_DELETE_WINDOW", lambda: self._choose("skip"))
        self.dialog.geometry(geometry_on_monitor(460, 280, anchor="center"))

        title_font = tkfont.Font(family="Segoe UI", size=13, weight="bold")
        body_font = tkfont.Font(family="Segoe UI", size=10)

        tk.Label(
            self.dialog,
            text="Camera with a built-in mic",
            font=title_font,
            fg=ACCENT,
            bg=BG,
        ).pack(anchor="w", padx=18, pady=(16, 6))
        tk.Label(
            self.dialog,
            text=camera_name,
            font=body_font,
            fg=TEXT,
            bg=BG,
            wraplength=420,
            justify="left",
        ).pack(anchor="w", padx=18)
        tk.Label(
            self.dialog,
            text=COMBO_HEAT_WARNING + " You can still use it if you want.",
            font=body_font,
            fg=MUTED,
            bg=BG,
            wraplength=420,
            justify="left",
        ).pack(anchor="w", padx=18, pady=(10, 14))

        row = tk.Frame(self.dialog, bg=BG)
        row.pack(fill="x", padx=18, pady=(0, 16))
        tk.Button(row, text="Test 30 seconds", font=body_font, command=lambda: self._choose("30")).pack(
            side="left", padx=(0, 8)
        )
        tk.Button(row, text="Test 1 minute", font=body_font, command=lambda: self._choose("60")).pack(
            side="left", padx=(0, 8)
        )
        tk.Button(row, text="Not now", font=body_font, command=lambda: self._choose("skip")).pack(side="right")

        try:
            self.dialog.deiconify()
            self.dialog.lift()
            self.dialog.focus_force()
        except tk.TclError:
            pass
        log_info("Camera combo warning popup shown.")

    def _choose(self, choice: str) -> None:
        if self._closed:
            return
        self._closed = True
        callback = self._on_choice
        self._close()
        if callback:
            callback(choice)

    def _close(self) -> None:
        global _dialog
        if self.dialog.winfo_exists():
            unregister(self.dialog)
            self.dialog.destroy()
        with _lock:
            if _dialog is self.dialog:
                _dialog = None


def show_camera_warning_popup(camera_name: str, on_choice: Callable[[str], None] | None = None) -> None:
    def _build(parent: tk.Misc) -> None:
        global _dialog
        try:
            popup = CameraWarningPopup(parent, camera_name=camera_name, on_choice=on_choice)
        except Exception as exc:
            log_error("Camera warning popup failed", exc=exc)
            return
        with _lock:
            _dialog = popup.dialog

    parent = _overlay_parent()
    if parent is not None:
        try:
            parent.after(0, lambda: _build(parent))
            return
        except Exception as exc:
            log_error("Camera warning popup schedule failed", exc=exc)

    def _run() -> None:
        root = tk.Tk()
        root.withdraw()
        register(root, persistent=True)
        _build(root)
        root.mainloop()

    threading.Thread(target=_run, name="silva-camera-warning", daemon=True).start()


def close_camera_warning_popup() -> None:
    with _lock:
        dialog = _dialog
    if dialog is None:
        return
    try:
        dialog.after(0, dialog.destroy)
    except tk.TclError:
        pass
