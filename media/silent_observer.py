"""Silent background camera peek — no app window, no UI."""

from __future__ import annotations

import os

os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")

import cv2

from silva.config import load_config


def peek_user_presence(*, camera_index: int | None = None) -> str:
    """Return clear, absent, or unavailable without opening a camera app."""
    config = load_config()
    if not bool(config.get("silent_camera_peek_enabled", True)):
        return "unavailable"

    try:
        from silva.media.camera import cameras_connected, capture_single_frame

        if not cameras_connected():
            return "unavailable"
        frame = capture_single_frame(index=camera_index, wait_for_plugin=False)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        cascade = cv2.CascadeClassifier(cascade_path)
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(60, 60))
        if len(faces) == 0:
            return "absent"
        return "clear"
    except Exception:
        return "unavailable"
