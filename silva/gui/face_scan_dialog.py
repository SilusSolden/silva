"""Face scan dialog — uses Silva camera capture (no conflicting system camera app)."""

from __future__ import annotations

import threading
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass
from typing import Callable

from silva.gui.display_manager import register, unregister
from silva.users.face_id import enroll_face, face_scan_available, verify_face


@dataclass
class FaceScanResult:
    passed: bool
    message: str
    enroll_mode: bool = False


class FaceScanPanel:
    def __init__(
        self,
        parent: tk.Misc,
        *,
        user_id: str,
        user_name: str,
        enroll: bool = True,
        on_done: Callable[[FaceScanResult], None] | None = None,
    ) -> None:
        self.user_id = user_id
        self.user_name = user_name
        self.enroll = enroll
        self._on_done = on_done
        self._closed = False

        self.dialog = tk.Toplevel(parent)
        register(self.dialog)
        self.dialog.title("Silva - Face Scan")
        self.dialog.resizable(False, False)
        self.dialog.attributes("-topmost", True)
        self.dialog.transient(parent)
        self.dialog.protocol("WM_DELETE_WINDOW", self._cancel)

        width, height = 420, 200
        px = parent.winfo_rootx() + max(0, (parent.winfo_width() - width) // 2)
        py = parent.winfo_rooty() + max(0, (parent.winfo_height() - height) // 2)
        self.dialog.geometry(f"{width}x{height}+{px}+{py}")

        body = tkfont.Font(family="Segoe UI", size=10)
        title = tkfont.Font(family="Segoe UI", size=11, weight="bold")

        tk.Label(
            self.dialog,
            text=f"{'Enroll' if enroll else 'Verify'} face: {user_name}",
            font=title,
            fg="#1A237E",
        ).pack(pady=(14, 6))

        self._status = tk.Label(self.dialog, text="Preparing camera...", font=body, fg="#455A64", wraplength=380)
        self._status.pack(pady=(0, 10))

        self._close_btn = tk.Button(
            self.dialog,
            text="Close",
            font=body,
            width=12,
            state="disabled",
            command=self._cancel,
        )
        self._close_btn.pack(pady=(0, 12))

        threading.Thread(target=self._run_scan, daemon=True).start()

    def _set_status(self, message: str) -> None:
        if self._closed or not self.dialog.winfo_exists():
            return
        self.dialog.after(0, lambda: self._status.config(text=message))

    def _run_scan(self) -> None:
        if not face_scan_available():
            self._finish(False, "opencv-python is required for face scan.")
            return
        try:
            if self.enroll:
                ok, message = enroll_face(self.user_id, self.user_name, on_progress=self._set_status)
            else:
                ok, message = verify_face(self.user_id, on_progress=self._set_status)
            self._finish(ok, message)
        except Exception as exc:
            self._finish(False, str(exc))

    def _finish(self, passed: bool, message: str) -> None:
        if self._closed or not self.dialog.winfo_exists():
            return

        def update() -> None:
            self._status.config(text=message, fg="#1B5E20" if passed else "#C62828")
            self._close_btn.config(state="normal")
            if passed:
                self.dialog.after(800, self._close_ok)
            result = FaceScanResult(passed=passed, message=message, enroll_mode=self.enroll)
            if self._on_done:
                self._on_done(result)

        self.dialog.after(0, update)

    def _close_ok(self) -> None:
        self._close(FaceScanResult(passed=True, message="OK", enroll_mode=self.enroll))

    def _cancel(self) -> None:
        self._close(FaceScanResult(passed=False, message="Cancelled.", enroll_mode=self.enroll))

    def _close(self, result: FaceScanResult) -> None:
        if self._closed:
            return
        self._closed = True
        if self.dialog.winfo_exists():
            unregister(self.dialog)
            self.dialog.destroy()


def _run_face_panel_blocking(
    user_id: str,
    user_name: str,
    *,
    enroll: bool,
) -> FaceScanResult:
    holder: dict = {
        "value": FaceScanResult(False, "Cancelled.", enroll_mode=enroll),
    }

    def _run() -> None:
        root = tk.Tk()
        root.withdraw()
        done = threading.Event()

        def on_done(result: FaceScanResult) -> None:
            holder["value"] = result
            done.set()
            root.quit()

        FaceScanPanel(root, user_id=user_id, user_name=user_name, enroll=enroll, on_done=on_done)
        root.mainloop()
        try:
            root.destroy()
        except tk.TclError:
            pass
        done.wait(timeout=90)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=95)
    default = FaceScanResult(
        False,
        "Face scan timed out." if enroll else "Face verify timed out.",
        enroll_mode=enroll,
    )
    return holder.get("value", default)


def run_face_verify(user_id: str, user_name: str) -> FaceScanResult:
    return _run_face_panel_blocking(user_id, user_name, enroll=False)


def run_face_enroll(user_id: str, user_name: str) -> FaceScanResult:
    return _run_face_panel_blocking(user_id, user_name, enroll=True)
