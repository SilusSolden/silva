"""Apply a saved voice panel result to the user store."""

from __future__ import annotations

from silva.gui.voice_panel import SetVoiceResult
from silva.users.manager import (
    ensure_user,
    get_owner,
    identify_and_set_active,
    is_owner,
    load_store,
    save_store,
    update_user_profile,
)
from silva.users.tiers import MAX_TIER


def apply_voice_enrollment(result: SetVoiceResult) -> dict | None:
    if not result.saved or not result.user_id:
        return None

    owner = get_owner()
    tier = MAX_TIER if result.user_id == owner["id"] else 1
    if result.user_id not in load_store()["users"]:
        if not is_owner():
            return None
        ensure_user(result.user_id, result.name, tier=tier)

    update_user_profile(
        result.user_id,
        name=result.name,
        voice_enrolled=True,
        face_recognition_future=result.face_recognition_future,
    )
    try:
        from silva.users.voice_id import invalidate_voice_cache

        invalidate_voice_cache(result.user_id)
    except Exception:
        pass
    user = identify_and_set_active(result.user_id)

    if result.face_recognition_future:
        store = load_store()
        store.setdefault("future_features", {})["face_recognition_saved"] = True
        save_store(store)

    return user
