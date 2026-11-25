"""Detect whether Silva is running on the main owner system or a remote install."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from datetime import datetime, timezone

from silva.config import CONFIG_DIR, CONFIG_FILE, load_config, save_config
from silva.logger import log_info
from silva.users.manager import DEFAULT_OWNER_ID, get_owner, identify_and_set_active, load_store, save_store

SYSTEM_FILE = CONFIG_DIR / "system.json"


def get_machine_fingerprint() -> str:
    if sys.platform == "win32":
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
            )
            guid, _ = winreg.QueryValueEx(key, "MachineGuid")
            winreg.CloseKey(key)
            return hashlib.sha256(str(guid).encode()).hexdigest()[:32]
        except OSError:
            pass

    node = platform.node()
    user = os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"
    raw = f"{platform.system()}:{node}:{user}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _load_local_system() -> dict:
    if not SYSTEM_FILE.exists():
        return {}
    data = json.loads(SYSTEM_FILE.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _save_local_system(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SYSTEM_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _main_system_fingerprint() -> str | None:
    store = load_store()
    fp = store.get("security", {}).get("main_system_fingerprint")
    return fp if fp else None


def _owner_voice_present_locally() -> bool:
    owner = get_owner()
    if owner.get("id") != DEFAULT_OWNER_ID:
        return False
    if not owner.get("voice_enrolled"):
        return False
    from silva.users.voice_id import wav_path

    return wav_path(owner["id"]).exists()


def _should_claim_main_system() -> bool:
    if bool(load_config().get("main_owner_system", False)):
        return True
    if _main_system_fingerprint() is not None:
        return False
    return _owner_voice_present_locally()


def _register_main_system(fingerprint: str) -> None:
    store = load_store()
    security = store.setdefault("security", {})
    security["main_system_fingerprint"] = fingerprint
    security["main_system_registered_at"] = datetime.now(timezone.utc).isoformat()
    save_store(store)

    _save_local_system(
        {
            "role": "main",
            "fingerprint": fingerprint,
            "registered_at": security["main_system_registered_at"],
        }
    )

    from silva.users.access_security import clear_blocks_for_profile

    owner = get_owner()
    clear_blocks_for_profile(owner["id"])
    store = load_store()
    if store.get("active_user_id") == "guest":
        store["active_user_id"] = owner["id"]
        save_store(store)

    if CONFIG_FILE.exists():
        config = load_config()
        if not config.get("main_owner_system"):
            config["main_owner_system"] = True
            save_config(config)

    log_info(
        f"Registered main owner system (fingerprint {fingerprint[:8]}…). "
        f"Cleared profile blocks for {owner['name']}."
    )


def ensure_main_owner_system() -> bool:
    """Register this machine as main when allowed and repair owner access."""
    local_fp = get_machine_fingerprint()
    main_fp = _main_system_fingerprint()

    if main_fp and local_fp == main_fp:
        from silva.users.access_security import clear_main_system_security_history

        clear_main_system_security_history()
        return True

    if main_fp and local_fp != main_fp:
        if bool(load_config().get("main_owner_system", False)):
            log_info(
                "Main owner system is configured for this machine — rebinding the registered fingerprint."
            )
            _register_main_system(local_fp)
            return True
        return False

    if _should_claim_main_system():
        _register_main_system(local_fp)
        return True

    return False


def is_main_owner_system() -> bool:
    """True when this machine is the registered main owner/admin system."""
    return ensure_main_owner_system()


def is_remote_system() -> bool:
    return not is_main_owner_system()


def bypass_security_checks() -> bool:
    """Main owner system runs with full owner access; remote access checks apply later."""
    if not is_main_owner_system():
        return False
    return bool(load_config().get("bypass_security_on_main_system", True))


def owner_auto_profile_on_startup() -> bool:
    if is_main_owner_system():
        return bool(load_config().get("owner_auto_profile_panel_on_main", False))
    return bool(load_config().get("owner_auto_profile_panel", True))


def apply_system_startup_access() -> dict:
    """Set the active profile based on whether this is the main owner system."""
    if is_main_owner_system():
        from silva.users.access_security import clear_main_system_security_history
        from silva.users.owner_biometrics import ensure_owner_biometrics_on_main

        clear_main_system_security_history()
        ensure_owner_biometrics_on_main()
        owner = get_owner()
        identify_and_set_active(owner["id"])
        return owner

    identify_and_set_active(None)
    store = load_store()
    return store["users"].get("guest", store["users"][DEFAULT_OWNER_ID])


def system_role_label() -> str:
    return "main_owner" if is_main_owner_system() else "remote"
