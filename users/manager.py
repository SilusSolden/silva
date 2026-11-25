"""User profile management for Silva."""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from datetime import datetime
from pathlib import Path

from silva.config import CONFIG_DIR
from silva.users.permissions import PERM_ALL
from silva.users.tiers import MAX_TIER, normalize_tier, permissions_for_tier
from silva.users.voice_id import wav_path

USERS_FILE = CONFIG_DIR / "users.json"
USERS_BACKUP_FILE = CONFIG_DIR / "users.json.bak"
REQUESTS_FILE = CONFIG_DIR / "pending_requests.json"
DEFAULT_OWNER_ID = "kevin"
DEFAULT_OWNER_NAME = "Kevin"
_STORE_LOCK = threading.RLock()


def _default_store() -> dict:
    return {
        "owner_id": DEFAULT_OWNER_ID,
        "active_user_id": DEFAULT_OWNER_ID,
        "future_features": {
            "face_recognition_enabled": False,
        },
        "security": {
            "co_owner_ids": [],
            "main_system_fingerprint": None,
        },
        "users": {
            DEFAULT_OWNER_ID: {
                "id": DEFAULT_OWNER_ID,
                "name": DEFAULT_OWNER_NAME,
                "tier": MAX_TIER,
                "role": "owner",
                "permissions": [PERM_ALL],
                "voice_enrolled": False,
                "onboarding_done": False,
                "admin_onboarding_done": False,
                "future_features": {"face_recognition": False},
            }
        },
    }


def _read_json_object(path: Path) -> dict | None:
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _enrich_owner_voice(store: dict) -> None:
    owner_id = store.get("owner_id", DEFAULT_OWNER_ID)
    users = store.setdefault("users", {})
    owner = users.setdefault(owner_id, _default_store()["users"][DEFAULT_OWNER_ID])
    voice_file = wav_path(owner_id)
    if voice_file.exists():
        owner["voice_enrolled"] = True
        owner["voice_wav"] = str(voice_file)


def _migrate_user(user: dict) -> dict:
    if "tier" not in user:
        role = user.get("role", "guest")
        tier_map = {"owner": 5, "admin": 4, "user": 3, "guest": 1}
        user["tier"] = tier_map.get(role, 1)
    user["tier"] = normalize_tier(user["tier"])
    user["permissions"] = permissions_for_tier(user["tier"])
    user.setdefault("onboarding_done", False)
    user.setdefault("admin_onboarding_done", False)
    user.setdefault("setup_seen_build", "")
    user.setdefault("role_request", "")
    user.setdefault("update_notifications", True)
    user.setdefault("future_features", {"face_recognition": False})
    return user


def _merge_store(data: dict) -> dict:
    store = _default_store()
    store.update(
        {k: data[k] for k in ("owner_id", "active_user_id", "future_features", "security") if k in data}
    )
    merged = {**_default_store()["users"], **data.get("users", {})}
    store["users"] = {uid: _migrate_user(dict(u)) for uid, u in merged.items() if isinstance(u, dict)}
    if store["owner_id"] not in store["users"]:
        store["users"][store["owner_id"]] = _default_store()["users"][DEFAULT_OWNER_ID]
    store["users"][store["owner_id"]]["tier"] = MAX_TIER
    _enrich_owner_voice(store)
    return store


def load_store() -> dict:
    with _STORE_LOCK:
        data = _read_json_object(USERS_FILE) if USERS_FILE.exists() else None
        recovered = False
        if data is None:
            data = _read_json_object(USERS_BACKUP_FILE) if USERS_BACKUP_FILE.exists() else None
            recovered = data is not None
        if data is None:
            store = _default_store()
            _enrich_owner_voice(store)
            _write_store_unlocked(store)
            return store
        store = _merge_store(data)
        if recovered or not USERS_FILE.exists() or not USERS_FILE.read_text(encoding="utf-8").strip():
            _write_store_unlocked(store)
        return store


def _write_store_unlocked(store: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(store, indent=2)
    fd, tmp_name = tempfile.mkstemp(prefix="users.", suffix=".tmp", dir=str(CONFIG_DIR))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, USERS_FILE)
        USERS_BACKUP_FILE.write_text(payload, encoding="utf-8")
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def save_store(store: dict) -> None:
    with _STORE_LOCK:
        _write_store_unlocked(store)


def needs_onboarding(user: dict | None, *, admin: bool = False) -> bool:
    user = user or get_active_user()
    if admin:
        return normalize_tier(user.get("tier")) >= 4 and not bool(user.get("admin_onboarding_done"))
    return not bool(user.get("onboarding_done"))


def mark_onboarding_done(user_id: str, *, admin: bool = False) -> None:
    store = load_store()
    user = store.get("users", {}).get(user_id)
    if not user:
        return
    user["admin_onboarding_done" if admin else "onboarding_done"] = True
    save_store(store)


def current_build_version() -> str:
    manifest = Path(__file__).resolve().parents[1] / "release_manifest.json"
    try:
        import json as _json

        data = _json.loads(manifest.read_text(encoding="utf-8"))
        return str(data.get("version") or "") if isinstance(data, dict) else ""
    except (OSError, ValueError):
        return ""


def needs_first_run_setup(user: dict | None = None) -> bool:
    active = user or get_active_user()
    return not bool(active.get("onboarding_done"))


def mark_first_run_setup_done(user_id: str) -> None:
    store = load_store()
    user = store.get("users", {}).get(user_id)
    if not user:
        return
    user["setup_seen_build"] = current_build_version()
    user["onboarding_done"] = True
    save_store(store)


def record_first_run_choices(
    user_id: str,
    *,
    profile_name: str = "",
    requested_role: str = "guest",
    update_notifications: bool = True,
) -> dict:
    store = load_store()
    role = str(requested_role or "guest").strip().lower()
    target_id = user_id
    name = str(profile_name or "").strip()
    if name and user_id == "guest":
        created = add_user(name, tier=2)
        target_id = created["id"]
        store = load_store()
    if target_id == store.get("owner_id"):
        role = "owner"
    user = store.get("users", {}).get(target_id)
    if not user:
        return get_active_user()
    user["update_notifications"] = bool(update_notifications)
    user["setup_seen_build"] = current_build_version()
    user["onboarding_done"] = True
    if role == "admin":
        user["role_request"] = "admin_pending_owner_approval"
    elif role == "owner":
        user["role_request"] = "owner"
    else:
        user["role_request"] = role if role in {"basic", "guest"} else "guest"
        tier = 1 if user["role_request"] == "guest" else 2
        if normalize_tier(user.get("tier")) < 4 and target_id != store.get("owner_id"):
            user["tier"] = tier
            user["permissions"] = permissions_for_tier(tier)
    save_store(store)
    return identify_and_set_active(target_id)


def get_active_user() -> dict:
    store = load_store()
    user_id = store.get("active_user_id", DEFAULT_OWNER_ID)
    return store["users"].get(user_id, store["users"][DEFAULT_OWNER_ID])


def get_owner() -> dict:
    store = load_store()
    return store["users"][store["owner_id"]]


def is_owner(user: dict | None = None) -> bool:
    user = user or get_active_user()
    store = load_store()
    return user.get("id") == store.get("owner_id") or normalize_tier(user.get("tier")) >= MAX_TIER


def user_can(user: dict, permission: str) -> bool:
    from silva.users.permissions import has_permission

    return has_permission(user, permission)


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return slug or "user"


def add_user(name: str, tier: int = 1) -> dict:
    store = load_store()
    tier = normalize_tier(tier)
    if tier >= MAX_TIER and not is_owner():
        tier = 1
    if tier >= MAX_TIER:
        from silva.users.access_security import can_promote_to_owner

        if not can_promote_to_owner():
            tier = MAX_TIER - 1

    user_id = _slug(name)
    base_id = user_id
    counter = 2
    while user_id in store["users"]:
        user_id = f"{base_id}_{counter}"
        counter += 1

    user = _new_user_dict(user_id, name, tier)
    store["users"][user_id] = user
    save_store(store)
    return user


def _new_user_dict(user_id: str, name: str, tier: int) -> dict:
    tier = normalize_tier(tier)
    return {
        "id": user_id,
        "name": name.strip().title(),
        "tier": tier,
        "role": "guest" if tier == 1 else "user",
        "permissions": permissions_for_tier(tier),
        "voice_enrolled": False,
        "onboarding_done": False,
        "admin_onboarding_done": False,
        "setup_seen_build": "",
        "role_request": "",
        "update_notifications": True,
        "future_features": {"face_recognition": False},
        "age_band": "",
        "age_verified": False,
        "age_attempts": 0,
    }


def ensure_user(user_id: str, name: str, tier: int = 1) -> dict:
    """Create a user with a stable ID if they do not exist yet."""
    store = load_store()
    if user_id in store["users"]:
        return store["users"][user_id]
    tier = normalize_tier(tier)
    if tier >= MAX_TIER and not is_owner():
        tier = 1
    user = _new_user_dict(user_id, name, tier)
    store["users"][user_id] = user
    save_store(store)
    return user


def update_user_profile(
    user_id: str,
    *,
    name: str | None = None,
    tier: int | None = None,
    voice_enrolled: bool | None = None,
    face_recognition_future: bool | None = None,
    age_band: str | None = None,
    age_verified: bool | None = None,
) -> dict | None:
    store = load_store()
    if user_id not in store["users"]:
        return None
    user = store["users"][user_id]
    if user_id == store["owner_id"]:
        if tier is not None and normalize_tier(tier) < MAX_TIER:
            tier = None
        if name and name.strip().lower() != user.get("name", "").strip().lower():
            name = user.get("name")
    if name:
        user["name"] = name.strip().title()
    if tier is not None:
        previous_tier = normalize_tier(user.get("tier", 1))
        user["tier"] = normalize_tier(tier)
        user["permissions"] = permissions_for_tier(user["tier"])
        user.setdefault("admin_onboarding_done", False)
        if previous_tier < 4 and user["tier"] >= 4:
            user["admin_approved_at"] = datetime.now().isoformat(timespec="seconds")
    if voice_enrolled is not None:
        user["voice_enrolled"] = voice_enrolled
        if voice_enrolled:
            user["voice_enrolled_at"] = datetime.now().isoformat(timespec="seconds")
    if voice_enrolled:
        user["voice_wav"] = str(wav_path(user_id))
    if face_recognition_future is not None:
        user.setdefault("future_features", {})["face_recognition"] = face_recognition_future
    if age_band is not None:
        user["age_band"] = str(age_band)
    if age_verified is not None:
        user["age_verified"] = bool(age_verified)
        if age_verified:
            user["age_verified_at"] = datetime.now().isoformat(timespec="seconds")
    save_store(store)
    return user


def remove_user(user_id: str) -> bool:
    store = load_store()
    if user_id == store["owner_id"]:
        return False
    if user_id not in store["users"]:
        return False
    del store["users"][user_id]
    if store["active_user_id"] == user_id:
        store["active_user_id"] = store["owner_id"]
    save_store(store)

    fp = CONFIG_DIR / "voices" / f"{user_id}.fingerprint.json"
    if fp.exists():
        fp.unlink()
    return True


def list_users() -> list[dict]:
    return list(load_store()["users"].values())


def mark_voice_enrolled(user_id: str, enrolled: bool = True) -> None:
    update_user_profile(user_id, voice_enrolled=enrolled)


def identify_and_set_active(user_id: str | None) -> dict:
    store = load_store()
    if user_id and user_id in store["users"]:
        store["active_user_id"] = user_id
        save_store(store)
        return store["users"][user_id]

    if "guest" not in store["users"]:
        store["users"]["guest"] = {
            "id": "guest",
            "name": "Guest",
            "tier": 1,
            "role": "guest",
            "permissions": permissions_for_tier(1),
            "voice_enrolled": False,
            "future_features": {"face_recognition": False},
        }
    store["active_user_id"] = "guest"
    save_store(store)
    return store["users"]["guest"]


def submit_request(user: dict, message: str) -> None:
    REQUESTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    requests: list = []
    if REQUESTS_FILE.exists():
        try:
            raw = REQUESTS_FILE.read_text(encoding="utf-8").strip()
            loaded = json.loads(raw) if raw else []
            if isinstance(loaded, list):
                requests = loaded
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            requests = []
    requests.append(
        {
            "from_user": user.get("name", "Unknown"),
            "from_id": user.get("id", "guest"),
            "tier": user.get("tier", 1),
            "message": message,
        }
    )
    REQUESTS_FILE.write_text(json.dumps(requests, indent=2), encoding="utf-8")
