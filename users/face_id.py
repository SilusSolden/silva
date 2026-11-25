"""Face gallery enrollment — multiple photos per user for robust matching."""

from __future__ import annotations

import json
import shutil
import uuid
from collections.abc import Callable
from pathlib import Path

import numpy as np

from silva.config import CONFIG_DIR, load_config
from silva.logger import log_info
from silva.media.camera import (
    capture_frames,
    capture_single_frame,
    frame_brightness,
    frame_is_too_dark,
    open_camera,
    select_rgb_camera_index,
    grab_frame,
)

FACES_DIR = CONFIG_DIR / "faces"
FACE_SIZE = (128, 128)

ProgressCallback = Callable[[str], None]


def face_scan_available() -> bool:
    try:
        import cv2  # noqa: F401

        return True
    except ImportError:
        return False


def _legacy_face_path(user_id: str) -> Path:
    return FACES_DIR / f"{user_id}.npy"


def _user_dir(user_id: str) -> Path:
    return FACES_DIR / user_id


def photos_dir(user_id: str) -> Path:
    return _user_dir(user_id) / "photos"


def _gallery_index_path(user_id: str) -> Path:
    return _user_dir(user_id) / "gallery.json"


def _meta_path(user_id: str) -> Path:
    return _user_dir(user_id) / "meta.json"


def video_path(user_id: str) -> Path:
    for ext in (".avi", ".mp4"):
        path = _user_dir(user_id) / f"profile{ext}"
        if path.exists():
            return path
    legacy = FACES_DIR / f"{user_id}.avi"
    return legacy if legacy.exists() else _user_dir(user_id) / "profile.avi"


def reference_image_path(user_id: str) -> Path:
    for ext in (".jpg", ".jpeg", ".png"):
        path = _user_dir(user_id) / f"reference{ext}"
        if path.exists():
            return path
    legacy = FACES_DIR / f"{user_id}_reference.jpg"
    return legacy


def has_face_enrolled(user_id: str) -> bool:
    return photo_count(user_id) > 0 or _legacy_face_path(user_id).exists()


def photo_count(user_id: str) -> int:
    return len(list_gallery_photos(user_id))


def requires_face_for_tier(tier: int) -> bool:
    minimum = int(load_config().get("face_scan_min_tier", 4))
    return tier >= minimum or tier >= 5


def _extract_face_gray(frame, *, min_size: tuple[int, int] = (40, 40)) -> np.ndarray | None:
    import cv2

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame
    try:
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
    except Exception:
        enhanced = cv2.equalizeHist(gray)

    cascade_files = (
        "haarcascade_frontalface_default.xml",
        "haarcascade_frontalface_alt2.xml",
    )
    images = (enhanced, gray)
    sizes = (min_size, (24, 24), (16, 16))
    for cascade_file in cascade_files:
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + cascade_file)
        if cascade.empty():
            continue
        for image in images:
            for size in sizes:
                for neighbors in (4, 3, 2):
                    faces = cascade.detectMultiScale(
                        image,
                        scaleFactor=1.05,
                        minNeighbors=neighbors,
                        minSize=size,
                    )
                    if len(faces) == 0:
                        continue
                    x, y, w, h = max(faces, key=lambda item: item[2] * item[3])
                    face = gray[y : y + h, x : x + w]
                    return cv2.resize(face, FACE_SIZE)
    return None


def _center_face_fallback(frame) -> np.ndarray:
    import cv2

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame
    height, width = gray.shape[:2]
    side = min(height, width)
    x = max(0, (width - side) // 2)
    y = max(0, int(height * 0.12))
    crop = gray[y : min(height, y + side), x : x + side]
    return cv2.resize(crop, FACE_SIZE)


def _compare_faces(stored: np.ndarray, probe: np.ndarray) -> float:
    stored = stored.astype(np.float32)
    probe = probe.astype(np.float32)
    stored = (stored - stored.mean()) / (stored.std() + 1e-6)
    probe = (probe - probe.mean()) / (probe.std() + 1e-6)
    return float(np.mean(stored * probe))


def _load_gallery_index(user_id: str) -> list[dict]:
    path = _gallery_index_path(user_id)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def _save_gallery_index(user_id: str, items: list[dict]) -> None:
    _user_dir(user_id).mkdir(parents=True, exist_ok=True)
    _gallery_index_path(user_id).write_text(json.dumps(items, indent=2), encoding="utf-8")


def list_gallery_photos(user_id: str) -> list[dict]:
    items = _load_gallery_index(user_id)
    return [item for item in items if Path(item.get("image", "")).exists()]


def load_gallery_embeddings(user_id: str) -> list[np.ndarray]:
    embeddings: list[np.ndarray] = []
    for item in list_gallery_photos(user_id):
        emb_path = Path(item.get("embedding", ""))
        if emb_path.exists():
            embeddings.append(np.load(emb_path))
    legacy = _legacy_face_path(user_id)
    if legacy.exists():
        embeddings.append(np.load(legacy))
    return embeddings


def _migrate_legacy_profile(user_id: str, name: str) -> None:
    legacy = _legacy_face_path(user_id)
    if not legacy.exists():
        return
    ref = reference_image_path(user_id)
    image_path = photos_dir(user_id) / "legacy_migrated.jpg"
    photos_dir(user_id).mkdir(parents=True, exist_ok=True)
    emb_path = photos_dir(user_id) / "legacy_migrated.npy"
    if not emb_path.exists():
        shutil.copy2(legacy, emb_path)
    if ref.exists() and not image_path.exists():
        shutil.copy2(ref, image_path)
    items = _load_gallery_index(user_id)
    if not any(item.get("id") == "legacy_migrated" for item in items):
        items.append(
            {
                "id": "legacy_migrated",
                "image": str(image_path if image_path.exists() else ref),
                "embedding": str(emb_path),
                "source": "legacy",
            }
        )
        _save_gallery_index(user_id, items)


def add_face_photo_from_frame(
    user_id: str,
    name: str,
    frame,
    *,
    source: str = "camera",
    allow_fallback: bool = False,
) -> tuple[bool, str]:
    if frame is None:
        return False, "The camera did not return a picture."
    if frame_is_too_dark(frame, minimum=12.0):
        log_info(
            f"Face capture too dark (brightness {frame_brightness(frame):.1f}) for {name}."
        )
        return (
            False,
            "That camera picture is nearly black — I likely opened the IR camera, not your Elgato. "
            "Close Camera Hub if it is locking the Facecam, then take the photo again from the live preview.",
        )
    face = _extract_face_gray(frame)
    if face is None and allow_fallback:
        face = _center_face_fallback(frame)
        log_info(f"Face box missed for {name}; saved a center crop from the live preview.")
    if face is None:
        log_info(f"No face detected for {name} (brightness {frame_brightness(frame):.1f}).")
        return False, "I couldn't find a face in that still. Use Take Photo on the live preview and look at the lens."

    import cv2

    photo_id = uuid.uuid4().hex[:10]
    photos_dir(user_id).mkdir(parents=True, exist_ok=True)
    image_path = photos_dir(user_id) / f"{photo_id}.jpg"
    emb_path = photos_dir(user_id) / f"{photo_id}.npy"
    cv2.imwrite(str(image_path), frame)
    np.save(emb_path, face)

    items = _load_gallery_index(user_id)
    items.append(
        {
            "id": photo_id,
            "image": str(image_path),
            "embedding": str(emb_path),
            "source": source,
        }
    )
    _save_gallery_index(user_id, items)
    _meta_path(user_id).write_text(
        json.dumps({"user_id": user_id, "name": name, "photo_count": len(items)}, indent=2),
        encoding="utf-8",
    )
    _rebuild_primary_embedding(user_id)
    return True, f"Photo saved ({len(items)} total for {name})."


def add_face_photo_from_file(user_id: str, name: str, image_path: Path | str) -> tuple[bool, str]:
    import cv2

    path = Path(image_path)
    if not path.exists():
        return False, f"Image not found: {path}"
    frame = cv2.imread(str(path))
    if frame is None:
        return False, "Could not read image."
    return add_face_photo_from_frame(user_id, name, frame, source="file")


def remove_gallery_photo(user_id: str, photo_id: str) -> bool:
    items = _load_gallery_index(user_id)
    kept: list[dict] = []
    removed = False
    for item in items:
        if item.get("id") == photo_id:
            for key in ("image", "embedding"):
                p = Path(item.get(key, ""))
                if p.exists():
                    p.unlink()
            removed = True
            continue
        kept.append(item)
    if removed:
        _save_gallery_index(user_id, kept)
        _rebuild_primary_embedding(user_id)
    return removed


def _rebuild_primary_embedding(user_id: str) -> None:
    embeddings = load_gallery_embeddings(user_id)
    if not embeddings:
        legacy = _legacy_face_path(user_id)
        if legacy.exists():
            legacy.unlink()
        return
    np.save(_legacy_face_path(user_id), embeddings[0])


def enroll_face_from_image(user_id: str, name: str, image_path: Path | str) -> tuple[bool, str]:
    _migrate_legacy_profile(user_id, name)
    ok, message = add_face_photo_from_file(user_id, name, image_path)
    if ok:
        ref = reference_image_path(user_id)
        ref.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(image_path), ref)
    return ok, message


def enroll_face(
    user_id: str,
    name: str,
    *,
    on_progress: ProgressCallback | None = None,
) -> tuple[bool, str]:
    if not face_scan_available():
        return False, "Face scan requires opencv-python."

    duration = min(6.0, float(load_config().get("profile_capture_seconds", 10)))
    try:
        if on_progress:
            on_progress("Opening camera — speak naturally and look at the lens.")

        frames = capture_frames(
            duration=duration,
            on_tick=on_progress,
            index=select_rgb_camera_index(),
        )
        saved = 0
        for index, frame in enumerate(frames[:: max(1, len(frames) // 3)]):
            ok, _msg = add_face_photo_from_frame(user_id, name, frame, source="camera_burst")
            if ok:
                saved += 1
        if saved == 0:
            ok, msg = add_face_photo_from_frame(user_id, name, frames[-1], source="camera")
            if not ok:
                return False, msg
            saved = 1
        return True, f"Saved {saved} face photo(s) for {name}."
    except RuntimeError as exc:
        return False, str(exc)


def verify_face(
    user_id: str,
    *,
    on_progress: ProgressCallback | None = None,
) -> tuple[bool, str]:
    return verify_face_silent(user_id, on_progress=on_progress, partial_ok=False)


def verify_face_silent(
    user_id: str,
    *,
    on_progress: ProgressCallback | None = None,
    partial_ok: bool = False,
) -> tuple[bool, str]:
    _migrate_legacy_profile(user_id, user_id)
    gallery = load_gallery_embeddings(user_id)
    if not gallery:
        return False, "owner_face_not_enrolled"
    if not face_scan_available():
        return False, "camera_unavailable"

    if partial_ok:
        threshold = float(load_config().get("protection_face_match_threshold", 0.42))
        min_sizes = ((24, 24), (40, 40))
    else:
        threshold = float(load_config().get("face_match_threshold", 0.55))
        min_sizes = ((40, 40),)

    try:
        if on_progress:
            on_progress("Capturing for face match...")
        frame = capture_single_frame(index=select_rgb_camera_index(), wait_for_plugin=True)
        probe = None
        for min_size in min_sizes:
            probe = _extract_face_gray(frame, min_size=min_size)
            if probe is not None:
                break
        if probe is None:
            return False, "no_face_detected"

        best = max(_compare_faces(stored, probe) for stored in gallery)
        if best >= threshold:
            return True, f"face_verified_{best:.2f}"
        return False, f"face_mismatch_{best:.2f}"
    except RuntimeError as exc:
        text = str(exc)
        if "camera" in text.lower() and "plug" in text.lower():
            return False, text
        return False, "camera_unavailable"
    except Exception:
        return False, "camera_unavailable"



def capture_and_add_photo(
    user_id: str,
    name: str,
    *,
    on_progress: ProgressCallback | None = None,
) -> tuple[bool, str]:
    if not face_scan_available():
        return False, "opencv-python is required."
    try:
        if on_progress:
            on_progress("Opening your camera preview...")
        index = select_rgb_camera_index()
        camera, first = open_camera(index=index, wait_for_plugin=True)
        try:
            best = first
            best_bright = frame_brightness(first) if first is not None else 0.0
            for _ in range(18):
                frame = grab_frame(camera, retries=2)
                if frame is None:
                    continue
                bright = frame_brightness(frame)
                if bright > best_bright:
                    best = frame
                    best_bright = bright
                if _extract_face_gray(frame) is not None and bright >= 18:
                    best = frame
                    break
        finally:
            camera.release()
        if best is None:
            return False, "Could not capture a frame from the webcam."
        return add_face_photo_from_frame(user_id, name, best, source="camera", allow_fallback=True)
    except RuntimeError as exc:
        return False, str(exc)


def add_live_preview_photo(user_id: str, name: str, frame) -> tuple[bool, str]:
    """Save a still the user chose from the live camera window."""
    return add_face_photo_from_frame(user_id, name, frame, source="live_preview", allow_fallback=True)
