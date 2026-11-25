"""Windows-style Yes/No camera access prompt for one Silva feature."""

from __future__ import annotations

import threading
import tkinter as tk
import tkinter.font as tkfont
from typing import Callable

from silva.gui.display_manager import register, unregister, watch_shutdown
from silva.gui.monitors import geometry_on_monitor
from silva.logger import log_error, log_info

BG = "#FAFAFA"
ACCENT = "#1565C0"
TEXT = "#263238"
MUTED = "#607D8B"

_lock = threading.Lock()
_dialog: tk.Misc | None = None


def _overlay_parent() -> tk.Misc | None:
    try:
        from silva.gui.display_host import host_root

        return host_root()
    except Exception:
        return None


class CameraAccessPopup:
    def __init__(
        self,
        parent: tk.Misc,
        *,
        purpose: str,
        on_choice: Callable[[bool], None] | None = None,
    ) -> None:
        self._on_choice = on_choice
        self._closed = False
        self.dialog = tk.Toplevel(parent)
        register(self.dialog, persistent=True)
        watch_shutdown(self.dialog)
        self.dialog.title("Silva - Camera access")
        self.dialog.configure(bg=BG)
        self.dialog.resizable(False, False)
        try:
            self.dialog.attributes("-topmost", True)
        except tk.TclError:
            pass
        self.dialog.protocol("WM_DELETE_WINDOW", lambda: self._choose(False))
        self.dialog.geometry(geometry_on_monitor(440, 220, anchor="center"))

        title_font = tkfont.Font(family="Segoe UI", size=13, weight="bold")
        body_font = tkfont.Font(family="Segoe UI", size=10)

        tk.Label(
            self.dialog,
            text="Allow camera access?",
            font=title_font,
            fg=ACCENT,
            bg=BG,
        ).pack(anchor="w", padx=18, pady=(16, 8))
        tk.Label(
            self.dialog,
            text=f"Silva wants to use your camera for {purpose}.",
            font=body_font,
            fg=TEXT,
            bg=BG,
            wraplength=400,
            justify="left",
        ).pack(anchor="w", padx=18)
        tk.Label(
            self.dialog,
            text="Choose Yes to turn the camera on for this feature, or No to keep it off.",
            font=body_font,
            fg=MUTED,
            bg=BG,
            wraplength=400,
            justify="left",
        ).pack(anchor="w", padx=18, pady=(8, 16))

        row = tk.Frame(self.dialog, bg=BG)
        row.pack(fill="x", padx=18, pady=(0, 16))
        tk.Button(
            row,
            text="Yes",
            font=body_font,
            width=10,
            command=lambda: self._choose(True),
        ).pack(side="left")
        tk.Button(
            row,
            text="No",
            font=body_font,
            width=10,
            command=lambda: self._choose(False),
        ).pack(side="left", padx=(8, 0))

        try:
            self.dialog.deiconify()
            self.dialog.lift()
            self.dialog.focus_force()
        except tk.TclError:
            pass
        log_info(f"Camera access popup shown ({purpose}).")

    def _choose(self, allowed: bool) -> None:
        if self._closed:
            return
        self._closed = True
        callback = self._on_choice
        self._close()
        if callback:
            callback(allowed)

    def _close(self) -> None:
        global _dialog
        if self.dialog.winfo_exists():
            unregister(self.dialog)
            self.dialog.destroy()
        with _lock:
            if _dialog is self.dialog:
                _dialog = None


def show_camera_access_popup(
    purpose: str,
    *,
    parent: tk.Misc | None = None,
    on_choice: Callable[[bool], None] | None = None,
) -> None:
    def _build(host: tk.Misc) -> None:
        global _dialog
        try:
            popup = CameraAccessPopup(host, purpose=purpose, on_choice=on_choice)
        except Exception as exc:
            log_error("Camera access popup failed", exc=exc)
            if on_choice:
                on_choice(False)
            return
        with _lock:
            _dialog = popup.dialog

    host = parent or _overlay_parent()
    if host is not None:
        try:
            host.after(0, lambda: _build(host))
            return
        except Exception as exc:
            log_error("Camera access popup schedule failed", exc=exc)

    def _run() -> None:
        root = tk.Tk()
        root.withdraw()
        register(root, persistent=True)
        _build(root)
        root.mainloop()

    threading.Thread(target=_run, name="silva-camera-access", daemon=True).start()
