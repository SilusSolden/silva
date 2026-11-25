"""Live camera window for profile face photos — wait until you see yourself, then capture."""

from __future__ import annotations

import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from typing import Callable

import cv2

from silva.gui.display_manager import register, unregister
from silva.logger import log_error, log_info
from silva.media.camera import (
    frame_brightness,
    grab_frame,
    open_camera,
    select_rgb_camera_index,
)
from silva.users.face_id import add_live_preview_photo

try:
    from PIL import Image, ImageTk
except Exception:  # pragma: no cover
    Image = None  # type: ignore[assignment]
    ImageTk = None  # type: ignore[assignment]

PREVIEW_W = 480
PREVIEW_H = 360


def _frame_to_photo(frame, width: int = PREVIEW_W, height: int = PREVIEW_H):
    if Image is None or ImageTk is None or frame is None:
        return None
    try:
        resized = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        return ImageTk.PhotoImage(Image.fromarray(rgb))
    except Exception:
        return None


class FaceCaptureDialog:
    def __init__(
        self,
        parent: tk.Misc,
        *,
        user_id: str,
        user_name: str,
        on_done: Callable[[bool, str], None] | None = None,
    ) -> None:
        self.user_id = user_id
        self.user_name = user_name
        self._on_done = on_done
        self._closed = False
        self._stop = threading.Event()
        self._camera = None
        self._latest = None
        self._photo = None

        self.dialog = tk.Toplevel(parent)
        register(self.dialog)
        self.dialog.title(f"Silva - Take photo ({user_name})")
        self.dialog.resizable(False, False)
        self.dialog.attributes("-topmost", True)
        self.dialog.transient(parent)
        self.dialog.protocol("WM_DELETE_WINDOW", self._close)

        width, height = 520, 520
        px = parent.winfo_rootx() + max(0, (parent.winfo_width() - width) // 2)
        py = parent.winfo_rooty() + max(0, (parent.winfo_height() - height) // 2)
        self.dialog.geometry(f"{width}x{height}+{px}+{py}")

        title = tkfont.Font(family="Segoe UI", size=12, weight="bold")
        body = tkfont.Font(family="Segoe UI", size=10)

        tk.Label(self.dialog, text=f"Face photo: {user_name}", font=title, fg="#1A237E").pack(
            pady=(12, 4)
        )
        tk.Label(
            self.dialog,
            text="Wait until you see yourself clearly, look at the lens, then click Capture Photo.",
            font=body,
            fg="#455A64",
            wraplength=480,
        ).pack(pady=(0, 6))

        self._video = tk.Label(self.dialog, bg="#000000", width=PREVIEW_W, height=PREVIEW_H)
        self._video.pack(padx=16, pady=6)

        self._status = tk.Label(
            self.dialog,
            text="Opening camera...",
            font=body,
            fg="#455A64",
            wraplength=480,
        )
        self._status.pack(pady=(0, 8))

        row = tk.Frame(self.dialog)
        row.pack(pady=(0, 12))
        self._capture_btn = tk.Button(
            row,
            text="Capture Photo",
            font=body,
            width=14,
            state="disabled",
            bg="#1B5E20",
            fg="white",
            command=self._capture,
        )
        self._capture_btn.pack(side="left", padx=6)
        tk.Button(row, text="Cancel", font=body, width=10, command=self._close).pack(side="left", padx=6)

        threading.Thread(target=self._start_camera, daemon=True, name="silva-face-preview").start()

    def _ui(self, fn) -> None:
        if self._closed:
            return
        try:
            self.dialog.after(0, fn)
        except tk.TclError:
            pass

    def _set_status(self, text: str, *, error: bool = False) -> None:
        def update() -> None:
            if self._closed or not self.dialog.winfo_exists():
                return
            self._status.config(text=text, fg="#C62828" if error else "#37474F")

        self._ui(update)

    def _start_camera(self) -> None:
        last_error = "Could not open a camera."
        camera = None
        first = None
        chosen = select_rgb_camera_index()
        tried = []
        for index in [chosen, *[i for i in range(6) if i != chosen]]:
            tried.append(index)
            try:
                camera, first = open_camera(index=index, wait_for_plugin=index == chosen)
            except Exception as exc:
                last_error = str(exc)
                camera = None
                first = None
                continue
            if first is not None and frame_brightness(first) >= 14:
                log_info(f"Face photo preview opened on camera index {index}.")
                break
            if camera is not None:
                try:
                    camera.release()
                except Exception:
                    pass
            camera = None
            first = None
        if camera is None or first is None:
            log_error("Face photo camera could not open", exc=RuntimeError(last_error))
            self._set_status(last_error, error=True)
            return
        self._camera = camera
        self._latest = first
        self._ui(self._enable_capture)
        threading.Thread(target=self._capture_loop, daemon=True, name="silva-face-preview-loop").start()
        self._ui(self._tick)

    def _enable_capture(self) -> None:
        if self._closed or not self.dialog.winfo_exists():
            return
        self._capture_btn.config(state="normal")
        self._status.config(text="Camera is live. Look at the lens, then capture.")

    def _capture_loop(self) -> None:
        while not self._stop.is_set() and self._camera is not None:
            frame = grab_frame(self._camera, retries=1)
            if frame is not None:
                self._latest = frame
            time.sleep(0.08)

    def _tick(self) -> None:
        if self._closed or not self.dialog.winfo_exists():
            return
        frame = self._latest
        if frame is not None:
            photo = _frame_to_photo(frame)
            if photo is not None:
                self._photo = photo
                self._video.configure(image=photo)
            bright = frame_brightness(frame)
            if bright < 16:
                self._status.config(
                    text="This picture is still dark — waiting for auto-exposure. Stay in the light.",
                    fg="#E65100",
                )
            elif self._capture_btn["state"] == "normal":
                self._status.config(
                    text="Camera is live. Look at the lens, then capture.",
                    fg="#37474F",
                )
        self.dialog.after(120, self._tick)

    def _capture(self) -> None:
        frame = self._latest
        if frame is None:
            self._set_status("No picture yet — wait a second for the preview.", error=True)
            return
        ok, message = add_live_preview_photo(self.user_id, self.user_name, frame)
        if self._on_done:
            self._on_done(ok, message)
        if ok:
            self._close()
        else:
            self._set_status(message, error=True)

    def _release(self) -> None:
        self._stop.set()
        camera = self._camera
        self._camera = None
        if camera is not None:
            try:
                camera.release()
            except Exception:
                pass

    def _close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._release()
        if self.dialog.winfo_exists():
            unregister(self.dialog)
            self.dialog.destroy()
