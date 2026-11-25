"""Custom camera test-run window — light preview, then save or skip."""

from __future__ import annotations

import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from typing import Callable

import cv2

from silva.gui.display_manager import register, unregister, watch_shutdown
from silva.gui.monitors import geometry_on_monitor
from silva.logger import log_error, log_info
from silva.media.camera import (
    COMBO_HEAT_WARNING,
    grab_frame,
    open_camera,
    save_chosen_camera,
    select_camera_index,
)
from silva.media.perf_guard import camera_test_too_heavy, sample_perf

BG = "#121212"
TEXT = "#F5F5F5"
MUTED = "#B0BEC5"
ACCENT = "#FFB74D"

PREVIEW_W = 320
PREVIEW_H = 180
TICK_MS = 250
CAPTURE_SLEEP = 0.12

_lock = threading.Lock()
_popup: "CameraPreviewPopup | None" = None

try:
    from PIL import Image, ImageTk
except Exception:  # pragma: no cover - Pillow is in requirements
    Image = None  # type: ignore[assignment]
    ImageTk = None  # type: ignore[assignment]


def _overlay_parent() -> tk.Misc | None:
    try:
        from silva.gui.display_host import host_root

        return host_root()
    except Exception:
        return None


def _frame_to_photo(frame, width: int = PREVIEW_W, height: int = PREVIEW_H):
    if Image is None or ImageTk is None or frame is None:
        return None
    try:
        resized = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        return ImageTk.PhotoImage(Image.fromarray(rgb))
    except Exception:
        return None


class CameraPreviewPopup:
    def __init__(
        self,
        parent: tk.Misc,
        *,
        camera_name: str,
        seconds: int,
        combo: bool,
        on_finished: Callable[[str], None] | None = None,
    ) -> None:
        self.camera_name = camera_name
        self.seconds = 60 if int(seconds) >= 45 else 30
        self.combo = combo
        self._on_finished = on_finished
        self._closed = False
        self._stop = threading.Event()
        self._camera = None
        self._index = 0
        self._latest = None
        self._photo = None
        self._started = 0.0
        self._heavy_hits = 0

        self.dialog = tk.Toplevel(parent)
        register(self.dialog, persistent=True)
        watch_shutdown(self.dialog)
        self.dialog.title("Silva - Camera test")
        self.dialog.configure(bg=BG)
        self.dialog.resizable(False, False)
        self.dialog.attributes("-topmost", True)
        self.dialog.protocol("WM_DELETE_WINDOW", self._skip)
        self.dialog.geometry(geometry_on_monitor(360, 360, anchor="center"))

        title_font = tkfont.Font(family="Segoe UI", size=13, weight="bold")
        body_font = tkfont.Font(family="Segoe UI", size=10)
        self._body_font = body_font

        tk.Label(self.dialog, text="Camera test", font=title_font, fg=TEXT, bg=BG).pack(
            anchor="w", padx=16, pady=(12, 2)
        )
        tk.Label(
            self.dialog,
            text=camera_name,
            font=body_font,
            fg=MUTED,
            bg=BG,
            wraplength=320,
            justify="left",
        ).pack(anchor="w", padx=16)
        if combo:
            tk.Label(
                self.dialog,
                text=COMBO_HEAT_WARNING,
                font=body_font,
                fg=ACCENT,
                bg=BG,
                wraplength=320,
                justify="left",
            ).pack(anchor="w", padx=16, pady=(6, 0))

        self._video = tk.Label(self.dialog, bg="#000000", width=PREVIEW_W, height=PREVIEW_H)
        self._video.pack(padx=16, pady=10)

        self._status = tk.StringVar(value="Checking quietly whether this PC can run the test...")
        tk.Label(self.dialog, textvariable=self._status, font=body_font, fg=TEXT, bg=BG).pack(
            anchor="w", padx=16
        )

        self._buttons = tk.Frame(self.dialog, bg=BG)
        self._buttons.pack(fill="x", padx=16, pady=(8, 14))
        tk.Button(self._buttons, text="Finish test", font=body_font, command=self._finish_preview).pack(
            side="left"
        )

        threading.Thread(target=self._start_camera, name="silva-camera-test-open", daemon=True).start()

    def _ui(self, fn) -> None:
        if self._closed:
            return
        try:
            self.dialog.after(0, fn)
        except tk.TclError:
            pass

    def _start_camera(self) -> None:
        try:
            index = select_camera_index()
            camera, first = open_camera(index=index, wait_for_plugin=False)
            camera.set(cv2.CAP_PROP_FRAME_WIDTH, PREVIEW_W)
            camera.set(cv2.CAP_PROP_FRAME_HEIGHT, PREVIEW_H)
            camera.set(cv2.CAP_PROP_FPS, 10)
        except Exception as exc:
            log_error("Camera test could not open", exc=exc)
            self._ui(lambda: self._fail_open(str(exc)))
            return

        t0 = time.perf_counter()
        _frame_to_photo(first)
        frame_ms = (time.perf_counter() - t0) * 1000.0
        snap = sample_perf(interval=0.25)
        if camera_test_too_heavy(process_cpu=snap.process_cpu, frame_ms=frame_ms):
            try:
                camera.release()
            except Exception:
                pass
            self._ui(self._fail_heavy)
            return

        self._camera = camera
        self._index = index
        self._latest = first
        self._started = time.time()
        threading.Thread(target=self._capture_loop, name="silva-camera-test", daemon=True).start()
        self._ui(self._begin_preview)
        log_info(f"Camera test popup started ({self.seconds}s) for {self.camera_name}.")

    def _fail_open(self, message: str) -> None:
        self._status.set(message or "I couldn't open that camera.")
        for child in self._buttons.winfo_children():
            child.destroy()
        tk.Button(self._buttons, text="Close", font=self._body_font, command=self._skip).pack(side="right")

    def _fail_heavy(self) -> None:
        self._done("too_heavy")

    def _begin_preview(self) -> None:
        if self._closed or not self.dialog.winfo_exists():
            self._release_camera()
            return
        if self._latest is not None:
            self._show_frame(self._latest)
        self._tick()

    def _show_frame(self, frame) -> None:
        t0 = time.perf_counter()
        photo = _frame_to_photo(frame)
        frame_ms = (time.perf_counter() - t0) * 1000.0
        if frame_ms >= 180:
            self._heavy_hits += 1
        if photo is None:
            return
        self._photo = photo
        self._video.configure(image=photo)

    def _capture_loop(self) -> None:
        next_sample = time.time() + 2.0
        while not self._stop.is_set() and self._camera is not None:
            frame = grab_frame(self._camera, retries=1)
            if frame is not None:
                self._latest = frame
            now = time.time()
            if now >= next_sample:
                next_sample = now + 2.0
                snap = sample_perf(interval=0.2)
                if camera_test_too_heavy(process_cpu=snap.process_cpu, frame_ms=0):
                    self._ui(self._fail_heavy)
                    return
            time.sleep(CAPTURE_SLEEP)

    def _tick(self) -> None:
        if self._closed or not self.dialog.winfo_exists():
            return
        if self._heavy_hits >= 4:
            self._fail_heavy()
            return
        frame = self._latest
        if frame is not None:
            self._show_frame(frame)
        remaining = self.seconds - int(time.time() - self._started)
        if remaining <= 0:
            self._finish_preview()
            return
        self._status.set(f"{remaining} seconds left in the test.")
        self.dialog.after(TICK_MS, self._tick)

    def _release_camera(self) -> None:
        self._stop.set()
        camera = self._camera
        self._camera = None
        if camera is not None:
            try:
                camera.release()
            except Exception:
                pass

    def _finish_preview(self) -> None:
        self._release_camera()
        if self._closed or not self.dialog.winfo_exists():
            return
        self._status.set("Test finished. Save this camera if you like the picture.")
        for child in self._buttons.winfo_children():
            child.destroy()
        tk.Button(
            self._buttons,
            text="Save and use this camera",
            font=self._body_font,
            command=self._save,
        ).pack(side="left")
        tk.Button(self._buttons, text="Don't save", font=self._body_font, command=self._skip).pack(
            side="right"
        )

    def _save(self) -> None:
        save_chosen_camera(self.camera_name, self._index, combo=self.combo)
        self._done("saved")

    def _skip(self) -> None:
        self._done("skipped")

    def _done(self, result: str) -> None:
        if self._closed:
            return
        self._closed = True
        self._release_camera()
        callback = self._on_finished
        self._close()
        if callback:
            callback(result)

    def _close(self) -> None:
        global _popup
        if self.dialog.winfo_exists():
            unregister(self.dialog)
            self.dialog.destroy()
        with _lock:
            if _popup is self:
                _popup = None


def show_camera_preview_popup(
    camera_name: str,
    *,
    seconds: int,
    combo: bool,
    on_finished: Callable[[str], None] | None = None,
) -> None:
    def _build(parent: tk.Misc) -> None:
        global _popup
        try:
            popup = CameraPreviewPopup(
                parent,
                camera_name=camera_name,
                seconds=seconds,
                combo=combo,
                on_finished=on_finished,
            )
        except Exception as exc:
            log_error("Camera preview popup failed", exc=exc)
            if on_finished:
                on_finished("error")
            return
        with _lock:
            _popup = popup

    parent = _overlay_parent()
    if parent is not None:
        try:
            parent.after(0, lambda: _build(parent))
            return
        except Exception as exc:
            log_error("Camera preview schedule failed", exc=exc)

    def _run() -> None:
        root = tk.Tk()
        root.withdraw()
        register(root, persistent=True)
        _build(root)
        root.mainloop()

    threading.Thread(target=_run, name="silva-camera-preview", daemon=True).start()


def close_camera_preview_popup() -> None:
    with _lock:
        popup = _popup
    if popup is None:
        return
    try:
        popup.dialog.after(0, popup._skip)
    except tk.TclError:
        popup._skip()
