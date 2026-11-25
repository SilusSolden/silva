"""Capture the primary display as a PNG image."""

from __future__ import annotations

from pathlib import Path

from silva.config import CONFIG_DIR

SCREENSHOT_DIR = CONFIG_DIR / "measurements" / "screenshots"


def capture_screen(*, save: bool = True) -> tuple[object, Path | None]:
    """Return (BGR numpy frame, saved path or None)."""
    try:
        from PIL import ImageGrab
    except ImportError as exc:
        raise RuntimeError("Pillow is required for screen capture. Install with: pip install pillow") from exc

    import numpy as np

    image = ImageGrab.grab(all_screens=True)
    frame = np.array(image)
    if frame.ndim == 3 and frame.shape[2] >= 3:
        import cv2

        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

    saved_path = None
    if save:
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        saved_path = SCREENSHOT_DIR / f"screen_{_timestamp()}.png"
        import cv2

        cv2.imwrite(str(saved_path), frame)
    return frame, saved_path


def _timestamp() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y%m%d_%H%M%S")
