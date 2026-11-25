from __future__ import annotations

import importlib
import re
from datetime import datetime
from pathlib import Path

from silva.config import load_config
from silva.logger import log_error, log_info
from silva.users.manager import load_store, save_store

AGE_RE = re.compile(
    r"\b(?:my age is|i am|i'm|verify my age|age verification)\s+(\d{1,3})\b",
    re.I,
)


def age_band_for_age(age: int) -> str:
    value = max(0, min(120, int(age)))
    width = max(2, int(load_config().get("age_verification_band_years", 10) or 10))
    if value >= 100:
        return f"{100 // width * width}+"
    lower = value // width * width
    return f"{lower}-{lower + width - 1}"


def _user(user_id: str) -> dict:
    return (load_store().get("users") or {}).get(str(user_id or "")) or {}


def _save_fields(user_id: str, **fields) -> None:
    store = load_store()
    user = store.get("users", {}).get(str(user_id or ""))
    if user is None:
        return
    user.update(fields)
    save_store(store)


def _frame_has_face(frame) -> bool:
    from silva.users import face_id

    probe = face_id._extract_face_gray(frame) or face_id._center_face_fallback(frame)
    return probe is not None


def _face_matches_profile(user_id: str, frame) -> tuple[bool, str]:
    from silva.users import face_id

    if not face_id.has_face_enrolled(user_id):
        return True, "face_presence"
    probe = face_id._extract_face_gray(frame) or face_id._center_face_fallback(frame)
    if probe is None:
        return False, "no_face"
    embeddings = face_id.load_gallery_embeddings(user_id)
    if not embeddings:
        return True, "face_presence"
    threshold = float(load_config().get("face_match_threshold", 0.55))
    best = max(face_id._compare_faces(item, probe) for item in embeddings)
    return (best >= threshold), f"score_{best:.2f}"


def estimate_band_from_frame(frame) -> str | None:
    module_name = str(load_config().get("age_verification_estimator_module") or "").strip()
    if not module_name or frame is None:
        return None
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        log_error("Age estimator import failed", exc=exc)
        return None
    estimator = getattr(module, "estimate_age", None) or getattr(module, "estimate_age_band", None)
    if estimator is None:
        return None
    try:
        result = estimator(frame)
    except Exception as exc:
        log_error("Age estimator failed", exc=exc)
        return None
    if isinstance(result, str):
        return result.strip() or None
    if isinstance(result, (int, float)):
        return age_band_for_age(int(result))
    return None


def capture_age_frame(user_id: str) -> tuple[object | None, str]:
    from silva.media.camera import capture_frames, select_rgb_camera_index
    from silva.users.camera_access import (
        FEATURE_AGE_VERIFICATION,
        ensure_camera_access,
    )

    if not ensure_camera_access(user_id, FEATURE_AGE_VERIFICATION):
        return None, "Camera access was not granted."
    try:
        frames = capture_frames(duration=0.8, index=select_rgb_camera_index())
    except Exception as exc:
        log_error("Age verification camera capture failed", exc=exc)
        return None, "I could not open the camera for age verification."
    if not frames:
        return None, "I did not get a camera frame."
    return frames[-1], ""


def verify_age_claim(
    user_id: str,
    stated_age: int,
    *,
    frame: object | None = None,
    voice_used: bool = False,
) -> tuple[bool, str]:
    config = load_config()
    if not bool(config.get("age_verification_enabled", True)):
        return False, "Age verification is disabled."
    try:
        age = int(stated_age)
    except (TypeError, ValueError):
        return False, "I need a whole-number age first."
    if age < 1 or age > 120:
        return False, "That age does not look right."
    band = age_band_for_age(age)

    if frame is None:
        frame, error = capture_age_frame(user_id)
        if frame is None:
            return False, error

    attempts = int(_user(user_id).get("age_attempts") or 0) + 1
    limit = max(1, int(config.get("age_verification_attempts", 3)))
    if attempts > limit:
        return False, "No age-verification attempts remain. Ask an admin to reset it."

    if not _frame_has_face(frame):
        _save_fields(user_id, age_attempts=attempts)
        remaining = limit - attempts
        return False, f"I could not see a clear face. Try again ({remaining} left)."

    matches, detail = _face_matches_profile(user_id, frame)
    if not matches:
        _save_fields(user_id, age_attempts=attempts)
        remaining = limit - attempts
        return False, f"That face did not match the profile. Try again ({remaining} left)."

    estimated = estimate_band_from_frame(frame)
    if estimated and estimated != band:
        _save_fields(user_id, age_attempts=attempts)
        remaining = limit - attempts
        return False, (
            f"The face looks closer to {estimated} than {band}. Try again "
            f"({remaining} left)."
        )

    _save_fields(
        user_id,
        age_band=band,
        age_verified=True,
        age_verified_at=datetime.now().isoformat(timespec="seconds"),
        age_verified_by="face" if not voice_used else "face_and_voice_hint",
        age_face_detail=detail,
        age_attempts=0,
    )
    from silva.conversation.speech_policy import mark_age_verified

    mark_age_verified(user_id, band=band, verified_by="face_age_check")
    log_info(f"Age verification passed for {user_id}: {band} ({detail})")
    return True, f"Age verified in the {band} range. Unfiltered replies are enabled."


def handle_age_verification(user_id: str, stated_age: int) -> tuple[bool, str]:
    from silva.conversation.speech_policy import allows_unfiltered, is_privileged

    if is_privileged(user_id):
        return True, "Owner and admin replies are already unfiltered."
    if allows_unfiltered(user_id) and _user(user_id).get("age_verified"):
        return True, "Your age is already verified."
    return verify_age_claim(user_id, stated_age)
