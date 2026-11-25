"""Ensure owner voice and face profiles are ready on the main system."""

from __future__ import annotations

from pathlib import Path

from silva.logger import log_info
from silva.users.manager import get_owner, update_user_profile
from silva.users.system_identity import is_main_owner_system

_BUNDLED_OWNER_PHOTO = Path(__file__).resolve().parents[1] / "assets" / "owner_kevin.png"


def ensure_owner_biometrics_on_main() -> None:
    if not is_main_owner_system():
        return

    owner = get_owner()
    owner_id = owner["id"]
    owner_name = owner.get("name", "Kevin")

    _ensure_owner_face(owner_id, owner_name)
    _ensure_owner_voice(owner_id, owner_name)


def _ensure_owner_face(user_id: str, name: str) -> None:
    from silva.users.face_id import enroll_face_from_image

    if not _BUNDLED_OWNER_PHOTO.exists():
        log_info("Owner face photo not bundled; use Record Face in the profile panel.")
        return

    ok, message = enroll_face_from_image(user_id, name, _BUNDLED_OWNER_PHOTO)
    if ok:
        update_user_profile(user_id, face_recognition_future=True)
        log_info(message)
    else:
        log_info(f"Owner face enrollment skipped: {message}")


def _ensure_owner_voice(user_id: str, name: str) -> None:
    from silva.audio_recorder import VoiceRecorder
    from silva.users.voice_id import save_voice_profile, wav_path

    wav = wav_path(user_id)
    if not wav.exists():
        log_info("Owner voice not recorded yet; use Record Voice in the profile panel.")
        return

    audio = VoiceRecorder.load_wav(wav)
    save_voice_profile(user_id, audio, name=name, queue_pending=False)
    update_user_profile(user_id, voice_enrolled=True)
    log_info(f"Owner voice profile loaded from {wav.name}.")
