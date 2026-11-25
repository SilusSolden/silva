"""Run face/voice checks when protection protocol is active."""

from __future__ import annotations

from silva.alerts.category_log import log_category_alert
from silva.config import load_config
from silva.logger import log_info
from silva.notifications.dispatch import notify_user_protection_async
from silva.security.protection_protocol import (
    ProtectionCheck,
    format_verification_code,
    generate_verification_code,
    mark_session_verified,
    protection_enabled_for_monitor_user,
    session_verified,
)
from silva.users.face_id import has_face_enrolled, verify_face_silent
from silva.users.manager import get_owner, load_store
from silva.users.voice_id import rank_voice_matches


def _owner_voice_match(audio, owner_id: str, enrolled: dict) -> tuple[bool, float]:
    if audio is None or owner_id not in enrolled:
        return False, 0.0
    ranked = rank_voice_matches(audio, {owner_id: enrolled[owner_id]})
    if not ranked:
        return False, 0.0
    user_id, score = ranked[0]
    threshold = float(load_config().get("voice_match_threshold", 0.72))
    return user_id == owner_id and score >= threshold, score


def _intruder_voice(audio, owner_id: str, enrolled: dict) -> tuple[str | None, float]:
    if audio is None:
        return None, 0.0
    ranked = rank_voice_matches(audio, enrolled)
    if not ranked:
        return None, 0.0
    user_id, score = ranked[0]
    if user_id == owner_id:
        return None, score
    threshold = float(load_config().get("voice_match_threshold", 0.72))
    if score >= threshold:
        name = enrolled[user_id].get("name", user_id)
        return name, score
    return None, score


def check_protection_access(*, audio=None, asleep: bool = False) -> ProtectionCheck:
    monitor_id = protection_enabled_for_monitor_user()
    if not monitor_id:
        return ProtectionCheck(allowed=True, reason="protection_off")

    if session_verified(monitor_id):
        return ProtectionCheck(allowed=True, reason="session_verified", owner_verified=True)

    owner = get_owner()
    store = load_store()
    enrolled = {uid: u for uid, u in store["users"].items() if u.get("voice_enrolled")}

    voice_ok, voice_score = _owner_voice_match(audio, owner["id"], enrolled)
    if voice_ok:
        mark_session_verified(owner["id"])
        log_category_alert(
            "protection",
            f"Owner verified by voice (score {voice_score:.2f})",
            asleep=asleep,
        )
        return ProtectionCheck(
            allowed=True,
            reason="owner_voice",
            owner_verified=True,
        )

    intruder_name, intruder_score = _intruder_voice(audio, owner["id"], enrolled)
    if intruder_name:
        log_category_alert(
            "security",
            f"Unauthorized voice detected: {intruder_name} (score {intruder_score:.2f})",
            detail="Protection protocol blocked access.",
            asleep=asleep,
        )
        digits = generate_verification_code()
        notify_user_protection_async(
            owner,
            f"Silva protection alert: {intruder_name} tried to use the system. "
            f"Verification code: {format_verification_code(digits)}",
            reason="intruder_voice",
            force=True,
        )
        return ProtectionCheck(
            allowed=False,
            reason=f"intruder_voice:{intruder_name}",
            needs_verification=True,
        )

    if audio is not None and enrolled and not voice_ok:
        log_info("Protection voice inconclusive — skipping camera to avoid blocking replies.")

    if asleep:
        return ProtectionCheck(allowed=True, reason="sleep_monitor_only")

    return ProtectionCheck(allowed=True, reason="inconclusive")


def check_protection_camera(*, asleep: bool = False) -> ProtectionCheck:
    """Slower camera check — use only when verification is already required."""
    owner = get_owner()
    if not has_face_enrolled(owner["id"]):
        return ProtectionCheck(
            allowed=False,
            reason="owner_face_not_enrolled",
            needs_verification=True,
            camera_unavailable=True,
        )

    face_ok, face_reason = verify_face_silent(owner["id"], partial_ok=True)
    if face_ok:
        mark_session_verified(owner["id"])
        log_category_alert("protection", "Owner verified by face", asleep=asleep)
        return ProtectionCheck(allowed=True, reason="owner_face", owner_verified=True)

    if face_reason in {"camera_unavailable", "no_camera"}:
        log_category_alert(
            "protection",
            "Camera unavailable during protection check",
            detail=face_reason,
            asleep=asleep,
        )
        notify_user_protection_async(
            owner,
            "Silva protection: camera not detected. Say owner override at the machine, "
            "or confirm on Telegram.",
            reason="camera_unavailable",
            force=True,
        )
        return ProtectionCheck(
            allowed=False,
            reason=face_reason,
            needs_verification=True,
            camera_unavailable=True,
        )

    return ProtectionCheck(
        allowed=False,
        reason=face_reason,
        needs_verification=True,
    )
