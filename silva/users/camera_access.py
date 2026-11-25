"""Per-feature camera permission, like Windows camera access prompts."""

from __future__ import annotations

import re
from typing import Callable

from silva.logger import log_info
from silva.users.manager import get_active_user, load_store, save_store

FEATURE_PROFILE_FACE = "profile_face"
FEATURE_CAMERA_TEST = "camera_test"
FEATURE_MEASUREMENT = "measurement"
FEATURE_AGE_VERIFICATION = "age_verification"

CAMERA_FEATURE_LABELS: dict[str, str] = {
    FEATURE_PROFILE_FACE: "profile face setup and auto switching",
    FEATURE_CAMERA_TEST: "testing the camera",
    FEATURE_MEASUREMENT: "measuring something with the camera",
    FEATURE_AGE_VERIFICATION: "age verification for unfiltered replies",
}

_ACCESS_PHRASES: tuple[str, ...] = (
    "camera access",
    "allow camera",
    "allow the camera",
    "give camera access",
    "camera permission",
    "permission for the camera",
    "permission for camera",
    "let silva use the camera",
    "let you use the camera",
)


def camera_feature_label(feature: str) -> str:
    return CAMERA_FEATURE_LABELS.get(feature, "this feature")


def _access_map(user: dict) -> dict:
    access = user.get("camera_access")
    return access if isinstance(access, dict) else {}


def is_camera_granted(user_id: str, feature: str) -> bool:
    store = load_store()
    user = store.get("users", {}).get(user_id) or {}
    return bool(_access_map(user).get(feature))


def set_camera_access(user_id: str, feature: str, allowed: bool) -> None:
    store = load_store()
    user = store.get("users", {}).get(user_id)
    if user is None:
        return
    access = dict(_access_map(user))
    access[feature] = bool(allowed)
    user["camera_access"] = access
    save_store(store)
    state = "allowed" if allowed else "denied"
    log_info(f"Camera access {state} for {user.get('name', user_id)} ({feature})")


def is_camera_access_phrase(text: str) -> bool:
    normalized = re.sub(r"[^\w\s]", " ", (text or "").strip().lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        return False
    return any(phrase in normalized for phrase in _ACCESS_PHRASES)


def request_camera_access(
    user_id: str,
    feature: str,
    *,
    parent=None,
    on_result: Callable[[bool], None] | None = None,
) -> None:
    """Show a Yes/No camera popup unless this feature was already allowed."""
    if is_camera_granted(user_id, feature):
        if on_result:
            on_result(True)
        return

    def _done(allowed: bool) -> None:
        set_camera_access(user_id, feature, allowed)
        if on_result:
            on_result(allowed)

    from silva.gui.camera_access_popup import show_camera_access_popup

    show_camera_access_popup(
        camera_feature_label(feature),
        parent=parent,
        on_choice=_done,
    )


def ensure_camera_access(user_id: str, feature: str, *, parent=None, timeout: float = 120.0) -> bool:
    """Block until the user answers the camera popup. True if they allowed it."""
    import threading

    if is_camera_granted(user_id, feature):
        return True
    done = threading.Event()
    holder = {"ok": False}

    def _done(allowed: bool) -> None:
        holder["ok"] = bool(allowed)
        done.set()

    request_camera_access(user_id, feature, parent=parent, on_result=_done)
    done.wait(timeout=timeout)
    return bool(holder["ok"])


def active_user_id() -> str:
    return str(get_active_user().get("id") or "guest")
