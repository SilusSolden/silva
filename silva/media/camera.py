"""Reliable webcam access on Windows (avoids MSMF grab failures when camera is busy)."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from contextlib import contextmanager

os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")

import cv2

from silva.config import load_config, save_config
from silva.logger import log_info

COMBO_HEAT_WARNING = (
    "This camera has a built-in microphone. Using the camera and mic together "
    "for a long time can overheat it and freeze."
)

DEDICATED_CAMERA_HINTS: tuple[str, ...] = (
    "elgato",
    "facecam",
    "cam link",
    "capture",
    "obsbot",
    "insta360",
    "dslr",
    "mirrorless",
    "virtual camera",
)

COMBO_CAMERA_HINTS: tuple[str, ...] = (
    "onn",
    "webcam",
    "web cam",
    "usb camera",
    "hd webcam",
    "hd camera",
    "integrated webcam",
    "integrated camera",
    "lifecam",
    "life cam",
)

CAMERA_MISSING_MESSAGE = (
    "I don't see a camera connected, so I can't do that just yet. "
    "Please plug one in and try that command again whenever you're ready."
)

_IR_CAMERA_HINTS: tuple[str, ...] = (
    "infrared",
    "ir camera",
    "windows hello",
    "rgb ir",
)

_camera_name_cache: tuple[float, list[str]] = (0.0, [])
_CAMERA_NAME_TTL = 6.0
_seen_camera_names: set[str] | None = None
_camera_events: list[dict] = []
_event_lock = threading.Lock()

PREFERRED_CAMERA_HINTS: tuple[str, ...] = (
    "elgato",
    "facecam",
    "mk.2",
    "mk2",
    "cam link",
    "4k cam",
)


def _backend_candidates() -> list[int | None]:
    if sys.platform == "win32":
        return [cv2.CAP_DSHOW, cv2.CAP_MSMF, None]
    return [None]


def list_camera_names(*, force: bool = False) -> list[str]:
    """Windows PnP camera names. Cached so background code does not keep waking devices."""
    global _camera_name_cache
    now = time.time()
    cached_at, cached_names = _camera_name_cache
    if not force and now - cached_at < _CAMERA_NAME_TTL and cached_at > 0:
        return list(cached_names)
    names = _query_camera_names()
    _camera_name_cache = (now, names)
    return list(names)


def _query_camera_names() -> list[str]:
    if sys.platform != "win32":
        return []
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-PnpDevice -Class Camera,Image -Status OK -ErrorAction SilentlyContinue "
                "| Select-Object -ExpandProperty FriendlyName",
            ],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    names = []
    for line in result.stdout.splitlines():
        name = line.strip()
        if name:
            names.append(name)
    return names


def usable_camera_names(*, force: bool = False) -> list[str]:
    names = []
    for name in list_camera_names(force=force):
        lowered = name.lower()
        if any(hint in lowered for hint in _IR_CAMERA_HINTS):
            continue
        names.append(name)
    return names


def cameras_connected(*, force: bool = False) -> bool:
    return bool(usable_camera_names(force=force))


def is_dedicated_camera(name: str) -> bool:
    lowered = name.lower()
    return any(hint in lowered for hint in DEDICATED_CAMERA_HINTS)


def is_combo_camera(name: str) -> bool:
    """True for webcam + built-in mic combos like the Onn camera, not Elgato-style cams."""
    if not name or is_dedicated_camera(name):
        return False
    lowered = name.lower()
    return any(hint in lowered for hint in COMBO_CAMERA_HINTS)


def poll_camera_devices() -> None:
    """PnP-only camera plug-in watch. Does not open the camera."""
    global _seen_camera_names
    if not bool(load_config().get("device_auto_detect", True)):
        return
    names = usable_camera_names()
    current = set(names)
    with _event_lock:
        if _seen_camera_names is None:
            _seen_camera_names = current
            return
        appeared = [name for name in names if name not in _seen_camera_names]
        _seen_camera_names = current
        for name in appeared:
            event = {"name": name, "is_combo": is_combo_camera(name)}
            _camera_events.append(event)
            log_info(f"Camera plugged in: {name} (combo={event['is_combo']})")


def take_camera_plug_events() -> list[dict]:
    with _event_lock:
        events = list(_camera_events)
        _camera_events.clear()
    return events


def save_chosen_camera(name: str, index: int, *, combo: bool = False) -> None:
    config = load_config()
    config["camera_index"] = max(0, int(index))
    config["saved_camera_name"] = name
    if combo:
        approved = [str(item) for item in (config.get("approved_combo_cameras") or [])]
        if name not in approved:
            approved.append(name)
        config["approved_combo_cameras"] = approved
    save_config(config)
    log_info(f"Saved camera '{name}' at index {index} (combo={combo}).")


def reset_camera_watch() -> None:
    global _seen_camera_names
    with _event_lock:
        _seen_camera_names = None
        _camera_events.clear()


def camera_wait_seconds() -> float:
    try:
        return max(2.0, float(load_config().get("camera_wait_seconds", 6.0)))
    except (TypeError, ValueError):
        return 6.0


def ensure_camera_ready(*, wait_seconds: float | None = None) -> str | None:
    """Silent wait for a camera plug-in. Returns a polite message if none appears."""
    if cameras_connected(force=True):
        return None
    timeout = camera_wait_seconds() if wait_seconds is None else max(0.0, float(wait_seconds))
    if timeout <= 0:
        return CAMERA_MISSING_MESSAGE
    log_info("Camera command requested — waiting briefly for a camera to be plugged in.")
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(0.6)
        if cameras_connected(force=True):
            log_info("Camera detected after wait.")
            return None
    log_info("No camera found after wait.")
    return CAMERA_MISSING_MESSAGE


def _score_camera_name(name: str) -> int:
    lowered = name.lower()
    score = 0
    for hint in PREFERRED_CAMERA_HINTS:
        if hint in lowered:
            score += 10
    if "elgato" in lowered and ("mk.2" in lowered or "mk2" in lowered):
        score += 20
    return score


def _probe_index(index: int) -> tuple[int, int] | None:
    for backend in _backend_candidates():
        camera = None
        try:
            camera = cv2.VideoCapture(index) if backend is None else cv2.VideoCapture(index, backend)
            if not camera.isOpened():
                continue
            frame = _warmup(camera, max_attempts=6)
            if frame is None:
                continue
            height, width = frame.shape[:2]
            return width, height
        except Exception:
            continue
        finally:
            if camera is not None:
                camera.release()
    return None


def _probe_index_light(index: int) -> tuple[int, int] | None:
    backends = [cv2.CAP_DSHOW] if sys.platform == "win32" else [None]
    for backend in backends:
        camera = None
        try:
            camera = cv2.VideoCapture(index) if backend is None else cv2.VideoCapture(index, backend)
            if not camera.isOpened():
                continue
            camera.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
            camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 180)
            frame = _warmup(camera, max_attempts=3)
            if frame is None:
                continue
            height, width = frame.shape[:2]
            return width, height
        except Exception:
            continue
        finally:
            if camera is not None:
                camera.release()
    return None


def detect_preferred_camera_index() -> int:
    """Light probe of the first few indexes. Does not scan every camera on the PC."""
    names = usable_camera_names()
    preferred_names = [name for name in names if _score_camera_name(name) > 0]
    if preferred_names:
        log_info(f"Preferred camera device(s): {', '.join(preferred_names)}")

    best_index = 0
    best_score = -1
    found = False
    for index in range(0, 4):
        probed = _probe_index_light(index)
        if probed is None:
            continue
        found = True
        width, height = probed
        score = width * height
        if preferred_names and index < len(names):
            score += _score_camera_name(names[index]) * 100000
        elif preferred_names:
            score += min(width * height, 640 * 360)
        if score > best_score:
            best_score = score
            best_index = index
    return best_index if found else 0


def select_camera_index() -> int:
    """Saved camera first so a test does not re-probe every device."""
    config = load_config()
    saved = config.get("camera_index")
    if saved is not None and str(saved).strip() != "":
        try:
            return max(0, int(saved))
        except (TypeError, ValueError):
            pass
    return detect_preferred_camera_index()


def preferred_camera_index() -> int:
    index = select_camera_index()
    log_info(f"Using camera index {index}.")
    return index


def open_camera(*, index: int | None = None, wait_for_plugin: bool = False):
    if wait_for_plugin:
        missing = ensure_camera_ready()
        if missing:
            raise RuntimeError(missing)
    elif not cameras_connected():
        raise RuntimeError(CAMERA_MISSING_MESSAGE)
    if index is None:
        index = preferred_camera_index()
    last_error: Exception | None = None
    for backend in _backend_candidates():
        try:
            if backend is None:
                camera = cv2.VideoCapture(index)
            else:
                camera = cv2.VideoCapture(index, backend)
            if not camera.isOpened():
                camera.release()
                continue
            try:
                camera.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)
            except Exception:
                pass
            warmed = _warmup(camera, max_attempts=24, min_brightness=16.0)
            if warmed is not None:
                return camera, warmed
            camera.release()
        except Exception as exc:
            last_error = exc
    raise RuntimeError(
        "Webcam not available. Close other camera apps and check Windows camera privacy settings."
    ) from last_error


def frame_brightness(frame) -> float:
    if frame is None or getattr(frame, "size", 0) == 0:
        return 0.0
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame
    return float(gray.mean())


def frame_is_too_dark(frame, *, minimum: float = 18.0) -> bool:
    return frame_brightness(frame) < minimum


def is_ir_camera_name(name: str) -> bool:
    lowered = (name or "").lower()
    return any(hint in lowered for hint in _IR_CAMERA_HINTS)


def select_rgb_camera_index() -> int:
    """Pick a real RGB camera for photos — skip IR / Windows Hello and nearly-black sensors."""
    config = load_config()
    names = list_camera_names(force=True)
    saved_name = str(config.get("saved_camera_name") or "").lower()
    try:
        saved_index = max(0, int(config.get("camera_index") if config.get("camera_index") is not None else 0))
    except (TypeError, ValueError):
        saved_index = 0

    best_index = saved_index
    best_score = -1.0
    for index in range(0, 6):
        name = names[index] if index < len(names) else ""
        if is_ir_camera_name(name):
            log_info(f"Skipping IR camera at index {index}: {name}")
            continue
        probed = _probe_index_light(index)
        if probed is None:
            continue
        width, height = probed
        score = float(width * height)
        lowered = name.lower()
        if saved_name and saved_name in lowered:
            score += 20_000_000
        if any(hint in lowered for hint in PREFERRED_CAMERA_HINTS):
            score += 10_000_000
        if index == saved_index:
            score += 1_000_000
        if score > best_score:
            best_score = score
            best_index = index
    log_info(f"RGB camera index {best_index} (saved was {saved_index}).")
    return best_index if best_score >= 0 else saved_index


def _warmup(camera, *, max_attempts: int = 12, min_brightness: float = 0.0):
    last = None
    for _ in range(max_attempts):
        ok, frame = camera.read()
        if ok and frame is not None:
            last = frame
            if min_brightness <= 0 or frame_brightness(frame) >= min_brightness:
                return frame
        time.sleep(0.05)
    return last


def grab_frame(camera, *, retries: int = 8):
    for _ in range(retries):
        ok, frame = camera.read()
        if ok and frame is not None:
            return frame
        time.sleep(0.04)
    return None


@contextmanager
def camera_session(*, index: int | None = None, wait_for_plugin: bool = False):
    camera, _first = open_camera(index=index, wait_for_plugin=wait_for_plugin)
    try:
        yield camera
    finally:
        camera.release()


def capture_single_frame(*, index: int | None = None, wait_for_plugin: bool = False):
    with camera_session(index=index, wait_for_plugin=wait_for_plugin) as camera:
        frame = grab_frame(camera, retries=15)
        if frame is None:
            raise RuntimeError("Could not capture a frame from the webcam.")
        return frame


def capture_frames(*, duration: float, on_tick=None, index: int | None = None) -> list:
    frames: list = []
    end_at = time.time() + duration
    seconds_left = int(duration)
    next_tick = time.time()

    with camera_session(index=index, wait_for_plugin=True) as camera:
        while time.time() < end_at:
            frame = grab_frame(camera, retries=3)
            if frame is not None:
                frames.append(frame)
            now = time.time()
            if on_tick and now >= next_tick:
                remaining = max(0, int(end_at - now) + 1)
                if remaining != seconds_left:
                    seconds_left = remaining
                    on_tick(f"Capturing... {seconds_left}s remaining")
                next_tick = now + 1.0

    if not frames:
        raise RuntimeError("Could not capture from webcam.")
    return frames
