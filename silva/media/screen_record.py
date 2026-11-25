"""Record the primary display to an MP4 file."""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from silva.config import CONFIG_DIR, load_config

VIDEO_DIR = CONFIG_DIR / "captures" / "videos"


def record_screen(
    *,
    seconds: float | None = None,
    fps: int | None = None,
    track_mouse: bool = False,
) -> tuple[Path, list[tuple[int, int, float]]]:
    """Return (video path, mouse samples as x,y,t)."""
    config = load_config()
    duration = float(seconds or config.get("visual_capture_video_seconds", 30))
    duration = max(3.0, min(duration, 120.0))
    frame_rate = int(fps or config.get("visual_capture_fps", 2))
    frame_rate = max(1, min(frame_rate, 10))

    try:
        import cv2
        from PIL import ImageGrab
    except ImportError as exc:
        raise RuntimeError("opencv-python and Pillow are required for screen recording.") from exc

    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    out_path = VIDEO_DIR / f"screen_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
    mouse_log: list[tuple[int, int, float]] = []

    start = time.time()
    first = ImageGrab.grab(all_screens=True)
    width, height = first.size
    writer = cv2.VideoWriter(
        str(out_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        float(frame_rate),
        (width, height),
    )
    if not writer.isOpened():
        raise RuntimeError("Could not open screen video writer.")

    try:
        interval = 1.0 / frame_rate
        next_frame = start
        while time.time() - start < duration:
            now = time.time()
            if now < next_frame:
                time.sleep(min(0.05, next_frame - now))
                continue
            image = ImageGrab.grab(all_screens=True)
            frame = cv2.cvtColor(__import__("numpy").array(image), cv2.COLOR_RGB2BGR)
            if frame.shape[1] != width or frame.shape[0] != height:
                frame = cv2.resize(frame, (width, height))
            writer.write(frame)
            if track_mouse:
                pos = _cursor_pos()
                if pos:
                    mouse_log.append((pos[0], pos[1], now - start))
            next_frame += interval
    finally:
        writer.release()

    return out_path, mouse_log


def _cursor_pos() -> tuple[int, int] | None:
    try:
        import sys

        if sys.platform == "win32":
            import ctypes

            class POINT(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

            pt = POINT()
            if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
                return int(pt.x), int(pt.y)
    except Exception:
        pass
    return None
