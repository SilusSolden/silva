"""Silent owner face confirmation for uncertain privileged voice access."""

from __future__ import annotations

from silva.config import load_config
from silva.logger import log_info

_STATE: dict[str, object] = {
    "assessed": False,
    "owner_confident": False,
    "owner_id": None,
    "matched_id": None,
}


def reset_voice_identity() -> None:
    _STATE.update(
        {
            "assessed": False,
            "owner_confident": False,
            "owner_id": None,
            "matched_id": None,
        }
    )


def record_voice_identity(owner_id: str, ranked: list[tuple[str, float]], owner_matched: bool) -> None:
    _STATE["assessed"] = True
    _STATE["owner_id"] = owner_id
    _STATE["owner_confident"] = bool(owner_matched)
    _STATE["matched_id"] = ranked[0][0] if ranked else None


def voice_identity_state() -> dict[str, object]:
    return dict(_STATE)


def needs_owner_reconfirmation() -> bool:
    if not _STATE["assessed"] or _STATE["owner_confident"]:
        return False
    return bool(load_config().get("owner_camera_fallback_enabled", True))


def confirm_owner_with_camera() -> tuple[bool, str]:
    from silva.users.face_id import verify_face_silent
    from silva.users.manager import get_owner

    owner = get_owner()
    ok, detail = verify_face_silent(owner["id"], partial_ok=False)
    if ok:
        log_info(f"Owner face fallback confirmed for {owner.get('name', owner['id'])} ({detail}).")
    else:
        log_info(f"Owner face fallback failed ({detail}).")
    return ok, detail


def require_owner_confirmation(assistant=None, action: str = "admin access") -> bool:
    if not needs_owner_reconfirmation():
        return True
    log_info(f"Owner face fallback requested for {action}.")
    ok, detail = confirm_owner_with_camera()
    if ok:
        return True
    if assistant is not None:
        assistant.say(
            "I could not confirm you are the owner with the camera, so that admin access stays locked.",
            interruptible=False,
        )
    return False
