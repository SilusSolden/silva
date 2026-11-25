"""Object measurement from camera frames and screenshots."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from silva.config import CONFIG_DIR
from silva.logger import log_info

MEASUREMENT_DIR = CONFIG_DIR / "measurements"
IMAGE_DIR = MEASUREMENT_DIR / "images"

# Typical real-world sizes for scale detection and lookup guesses (millimeters).
REFERENCE_OBJECTS: dict[str, dict[str, float | str]] = {
    "quarter": {"width_mm": 24.26, "height_mm": 24.26, "shape": "circle"},
    "dime": {"width_mm": 17.91, "height_mm": 17.91, "shape": "circle"},
    "nickel": {"width_mm": 21.21, "height_mm": 21.21, "shape": "circle"},
    "penny": {"width_mm": 19.05, "height_mm": 19.05, "shape": "circle"},
    "credit card": {"width_mm": 85.6, "height_mm": 53.98, "shape": "rect"},
    "business card": {"width_mm": 88.9, "height_mm": 50.8, "shape": "rect"},
    "iphone": {"width_mm": 71.5, "height_mm": 146.7, "shape": "rect"},
    "a4 paper": {"width_mm": 210.0, "height_mm": 297.0, "shape": "rect"},
    "letter paper": {"width_mm": 215.9, "height_mm": 279.4, "shape": "rect"},
}

COMMON_OBJECT_GUESSES: dict[str, dict[str, float]] = {
    "book": {"width_mm": 150.0, "height_mm": 230.0, "depth_mm": 25.0},
    "phone": {"width_mm": 71.5, "height_mm": 146.7, "depth_mm": 8.0},
    "laptop": {"width_mm": 310.0, "height_mm": 220.0, "depth_mm": 20.0},
    "cup": {"width_mm": 80.0, "height_mm": 100.0, "depth_mm": 80.0},
    "bottle": {"width_mm": 70.0, "height_mm": 250.0, "depth_mm": 70.0},
    "box": {"width_mm": 200.0, "height_mm": 150.0, "depth_mm": 100.0},
    "remote": {"width_mm": 50.0, "height_mm": 200.0, "depth_mm": 25.0},
    "keyboard": {"width_mm": 440.0, "height_mm": 140.0, "depth_mm": 30.0},
    "mouse": {"width_mm": 65.0, "height_mm": 110.0, "depth_mm": 40.0},
}


@dataclass
class ObjectMeasurement:
    width_px: int
    height_px: int
    width_mm: float | None = None
    height_mm: float | None = None
    depth_mm: float | None = None
    scale_note: str = ""
    object_hint: str = ""
    confidence: str = "pixel_only"
    image_path: str | None = None


def save_frame(frame, *, prefix: str = "capture") -> Path:
    import cv2

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    path = IMAGE_DIR / f"{prefix}_{uuid.uuid4().hex[:10]}.png"
    cv2.imwrite(str(path), frame)
    return path


def _largest_contour_bbox(frame) -> tuple[int, int, int, int] | None:
    import cv2

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    best = None
    best_area = 0
    height, width = gray.shape[:2]
    min_area = width * height * 0.002
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = w * h
        if area < min_area:
            continue
        if area > best_area:
            best_area = area
            best = (x, y, w, h)
    return best


def _find_reference_scale(frame, reference_key: str) -> float | None:
    """Return millimeters per pixel if a reference object is detected."""
    import cv2

    ref = REFERENCE_OBJECTS.get(reference_key)
    if ref is None:
        return None

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    if ref.get("shape") == "circle":
        circles = cv2.HoughCircles(
            gray,
            cv2.HOUGH_GRADIENT,
            dp=1.2,
            minDist=30,
            param1=100,
            param2=30,
            minRadius=8,
            maxRadius=min(frame.shape[0], frame.shape[1]) // 3,
        )
        if circles is None:
            return None
        target_mm = float(ref["width_mm"])
        best = None
        best_diff = float("inf")
        for circle in circles[0]:
            radius_px = float(circle[2])
            diameter_px = radius_px * 2.0
            mm_per_px = target_mm / diameter_px
            diff = abs(diameter_px - target_mm)
            if diff < best_diff:
                best_diff = diff
                best = mm_per_px
        return best

    bbox = _largest_contour_bbox(frame)
    if bbox is None:
        return None
    _, _, width_px, height_px = bbox
    ref_w = float(ref["width_mm"])
    ref_h = float(ref["height_mm"])
    ratio = ref_w / ref_h if ref_h else 1.0
    object_ratio = width_px / height_px if height_px else 1.0
    if abs(ratio - object_ratio) > 0.35:
        return None
    return ref_w / width_px


def _extract_reference_hint(text: str) -> str | None:
    normalized = text.lower()
    for key in REFERENCE_OBJECTS:
        if key in normalized:
            return key
    if "coin" in normalized:
        return "quarter"
    if "card" in normalized:
        return "credit card"
    return None


def _extract_object_hint(text: str) -> str | None:
    normalized = text.lower()
    for key in COMMON_OBJECT_GUESSES:
        if key in normalized:
            return key
    return None


def measure_frame(frame, *, query: str = "", source: str = "camera") -> ObjectMeasurement:
    bbox = _largest_contour_bbox(frame)
    if bbox is None:
        height, width = frame.shape[:2]
        bbox = (0, 0, width, height)
        confidence = "full_frame"
    else:
        confidence = "detected_object"

    _, _, width_px, height_px = bbox
    image_path = save_frame(frame, prefix=source)
    reference = _extract_reference_hint(query)
    object_hint = _extract_object_hint(query) or query.strip()

    width_mm = None
    height_mm = None
    scale_note = ""

    if reference:
        mm_per_px = _find_reference_scale(frame, reference)
        if mm_per_px:
            width_mm = round(width_px * mm_per_px, 1)
            height_mm = round(height_px * mm_per_px, 1)
            scale_note = f"Scaled using a {reference} as reference."
            confidence = "reference_scaled"

    if width_mm is None and object_hint:
        guess = COMMON_OBJECT_GUESSES.get(object_hint)
        if guess:
            width_mm = guess.get("width_mm")
            height_mm = guess.get("height_mm")
            depth_mm = guess.get("depth_mm")
            scale_note = (
                f"Estimated typical size for a {object_hint}. "
                "Hold a known object like a credit card or quarter for a more exact measurement."
            )
            confidence = "typical_guess"
            return ObjectMeasurement(
                width_px=width_px,
                height_px=height_px,
                width_mm=width_mm,
                height_mm=height_mm,
                depth_mm=depth_mm,
                scale_note=scale_note,
                object_hint=object_hint,
                confidence=confidence,
                image_path=str(image_path),
            )

    if width_mm is None:
        scale_note = (
            "I measured the object in pixels. "
            "For real-world size, say measure this with a credit card or quarter in view."
        )

    return ObjectMeasurement(
        width_px=width_px,
        height_px=height_px,
        width_mm=width_mm,
        height_mm=height_mm,
        scale_note=scale_note,
        object_hint=object_hint,
        confidence=confidence,
        image_path=str(image_path),
    )


def format_measurement(result: ObjectMeasurement) -> str:
    parts = []
    if result.object_hint:
        parts.append(f"Looking at {result.object_hint}.")

    parts.append(f"Detected area is about {result.width_px} by {result.height_px} pixels.")

    if result.width_mm is not None and result.height_mm is not None:
        parts.append(
            f"Estimated size is about {result.width_mm} millimeters wide "
            f"by {result.height_mm} millimeters tall."
        )
        width_in = round(result.width_mm / 25.4, 2)
        height_in = round(result.height_mm / 25.4, 2)
        parts.append(f"That is roughly {width_in} by {height_in} inches.")
        if result.depth_mm is not None:
            parts.append(f"Typical depth estimate: {result.depth_mm} millimeters.")

    if result.scale_note:
        parts.append(result.scale_note)

    if result.image_path:
        parts.append(f"I saved the image for later reference.")

    return " ".join(parts)


def capture_and_measure(*, source: str = "camera", query: str = "") -> ObjectMeasurement:
    if source == "screen":
        from silva.media.screenshot import capture_screen

        frame, _path = capture_screen(save=True)
        log_info("Measurement screenshot captured.")
        return measure_frame(frame, query=query, source="screen")

    from silva.media.camera import capture_single_frame, usable_camera_names
    from silva.media.perf_guard import guard_camera_command

    names = usable_camera_names()
    refusal = guard_camera_command(names[0] if names else "")
    if refusal:
        raise RuntimeError(refusal)

    frame = capture_single_frame(wait_for_plugin=True)
    log_info("Measurement camera frame captured.")
    return measure_frame(frame, query=query, source="camera")
