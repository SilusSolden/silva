"""Access security: attempts, blocks, temporary grants, owner alerts."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from silva.config import CONFIG_DIR, load_config
from silva.users.manager import get_owner, load_store, save_store
from silva.users.tiers import MAX_TIER, normalize_tier

ATTEMPTS_FILE = CONFIG_DIR / "access_attempts.json"
BLOCKS_FILE = CONFIG_DIR / "blocked_access.json"
GRANTS_FILE = CONFIG_DIR / "temporary_access_grants.json"
ALERTS_FILE = CONFIG_DIR / "security_alerts.json"


def _now() -> datetime:
    return datetime.now()


def _load_json(path: Path, default):
    if not path.exists():
        return default
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if data is not None else default


def _save_json(path: Path, data) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def max_owner_slots() -> int:
    return int(load_config().get("max_owner_slots", 1))


def list_co_owners() -> list[str]:
    store = load_store()
    owner_id = store["owner_id"]
    slots = store.setdefault("security", {}).setdefault("co_owner_ids", [])
    return [owner_id] + [uid for uid in slots if uid != owner_id][: max_owner_slots() - 1]


def can_promote_to_owner() -> bool:
    return len(list_co_owners()) < max_owner_slots()


def is_blocked(actor_id: str, target_user_id: str) -> bool:
    blocks = _load_json(BLOCKS_FILE, {})
    blocked_targets = blocks.get(actor_id, [])
    return target_user_id in blocked_targets


def block_actor(actor_id: str, target_user_id: str, *, reason: str = "") -> None:
    from silva.users.system_identity import is_main_owner_system

    if is_main_owner_system() and target_user_id == get_owner()["id"]:
        return
    blocks = _load_json(BLOCKS_FILE, {})
    entries = set(blocks.get(actor_id, []))
    entries.add(target_user_id)
    blocks[actor_id] = sorted(entries)
    _save_json(BLOCKS_FILE, blocks)
    log_attempt_event(
        target_user_id,
        actor_id=actor_id,
        reason=reason or "blocked_by_owner",
        status="blocked",
    )


def unblock_actor(actor_id: str, target_user_id: str) -> None:
    blocks = _load_json(BLOCKS_FILE, {})
    entries = [item for item in blocks.get(actor_id, []) if item != target_user_id]
    if entries:
        blocks[actor_id] = entries
    elif actor_id in blocks:
        del blocks[actor_id]
    _save_json(BLOCKS_FILE, blocks)


def clear_blocks_for_profile(target_user_id: str) -> None:
    """Remove all actor blocks against a profile (used when reclaiming main owner system)."""
    blocks = _load_json(BLOCKS_FILE, {})
    changed = False
    for actor_id in list(blocks.keys()):
        if target_user_id not in blocks.get(actor_id, []):
            continue
        entries = [item for item in blocks[actor_id] if item != target_user_id]
        if entries:
            blocks[actor_id] = entries
        else:
            del blocks[actor_id]
        changed = True
    if changed:
        _save_json(BLOCKS_FILE, blocks)


def clear_main_system_security_history() -> None:
    """Reset failed checks, blocks, and alerts on the main owner system."""
    owner = get_owner()
    clear_blocks_for_profile(owner["id"])
    _save_json(BLOCKS_FILE, {})
    _save_json(ATTEMPTS_FILE, [])
    _save_json(ALERTS_FILE, [])


def _load_attempts() -> list[dict]:
    return _load_json(ATTEMPTS_FILE, [])


def _save_attempts(items: list[dict]) -> None:
    _save_json(ATTEMPTS_FILE, items[-200:])


def log_access_attempt(
    *,
    target_user_id: str,
    target_name: str,
    target_tier: int,
    actor_id: str,
    actor_name: str,
    reason: str,
    voice_score: float = 0.0,
    face_passed: bool | None = None,
    status: str = "pending",
) -> str:
    attempt_id = f"{_now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    entry = {
        "id": attempt_id,
        "timestamp": _now().isoformat(timespec="seconds"),
        "target_user_id": target_user_id,
        "target_name": target_name,
        "target_tier": target_tier,
        "actor_id": actor_id,
        "actor_name": actor_name,
        "reason": reason,
        "voice_score": round(voice_score, 3),
        "face_passed": face_passed,
        "status": status,
        "expires_at": None,
        "allowed_minutes": None,
    }
    attempts = _load_attempts()
    attempts.append(entry)
    _save_attempts(attempts)

    if normalize_tier(target_tier) >= 4 or target_tier >= MAX_TIER:
        _push_owner_alert(entry)
    return attempt_id


def log_attempt_event(
    target_user_id: str,
    *,
    actor_id: str,
    reason: str,
    status: str,
) -> None:
    store = load_store()
    target = store["users"].get(target_user_id, {})
    actor = store["users"].get(actor_id, {"name": actor_id, "tier": 1})
    log_access_attempt(
        target_user_id=target_user_id,
        target_name=target.get("name", target_user_id),
        target_tier=normalize_tier(target.get("tier", 1)),
        actor_id=actor_id,
        actor_name=actor.get("name", actor_id),
        reason=reason,
        status=status,
    )


def _push_owner_alert(entry: dict) -> None:
    alerts = _load_json(ALERTS_FILE, [])
    alerts.append(
        {
            "attempt_id": entry["id"],
            "timestamp": entry["timestamp"],
            "message": (
                f"{entry['actor_name']} tried to access {entry['target_name']} "
                f"(tier {entry['target_tier']}) — {entry['reason']}"
            ),
            "read": False,
        }
    )
    _save_json(ALERTS_FILE, alerts[-100:])


def list_pending_attempts() -> list[dict]:
    return [item for item in _load_attempts() if item.get("status") == "pending"]


def list_unread_alerts() -> list[dict]:
    return [item for item in _load_json(ALERTS_FILE, []) if not item.get("read")]


def mark_alerts_read() -> None:
    alerts = _load_json(ALERTS_FILE, [])
    for item in alerts:
        item["read"] = True
    _save_json(ALERTS_FILE, alerts)


def update_attempt_status(attempt_id: str, status: str, **extra) -> dict | None:
    attempts = _load_attempts()
    for item in attempts:
        if item.get("id") == attempt_id:
            item["status"] = status
            item.update(extra)
            _save_attempts(attempts)
            return item
    return None


def grant_temporary_access(
    attempt_id: str,
    *,
    actor_id: str,
    target_user_id: str,
    minutes: int,
    approver_id: str,
) -> dict | None:
    minutes = max(1, min(int(minutes), 240))
    expires = _now() + timedelta(minutes=minutes)
    grants = _load_json(GRANTS_FILE, {})
    grants[actor_id] = {
        "target_user_id": target_user_id,
        "expires_at": expires.isoformat(timespec="seconds"),
        "minutes": minutes,
        "approved_by": approver_id,
        "attempt_id": attempt_id,
    }
    _save_json(GRANTS_FILE, grants)
    return update_attempt_status(
        attempt_id,
        "allowed",
        expires_at=expires.isoformat(timespec="seconds"),
        allowed_minutes=minutes,
        approved_by=approver_id,
    )


def get_active_grant(actor_id: str, target_user_id: str) -> dict | None:
    grants = _load_json(GRANTS_FILE, {})
    entry = grants.get(actor_id)
    if not entry or entry.get("target_user_id") != target_user_id:
        return None
    expires = datetime.fromisoformat(entry["expires_at"])
    if _now() >= expires:
        revoke_grant(actor_id, block_after=True, target_user_id=target_user_id)
        return None
    return entry


def revoke_grant(actor_id: str, *, block_after: bool = False, target_user_id: str | None = None) -> None:
    grants = _load_json(GRANTS_FILE, {})
    entry = grants.pop(actor_id, None)
    _save_json(GRANTS_FILE, grants)
    if block_after:
        target = target_user_id or (entry or {}).get("target_user_id")
        if target:
            block_actor(actor_id, target, reason="temporary_access_expired")


def expire_sessions() -> list[dict]:
    """Return expired sessions that were revoked."""
    grants = _load_json(GRANTS_FILE, {})
    expired: list[dict] = []
    for actor_id, entry in list(grants.items()):
        expires = datetime.fromisoformat(entry["expires_at"])
        if _now() >= expires:
            expired.append({"actor_id": actor_id, **entry})
            revoke_grant(actor_id, block_after=True, target_user_id=entry.get("target_user_id"))
    return expired


def tier_can_assist(helper_tier: int, target_tier: int) -> bool:
    helper_tier = normalize_tier(helper_tier)
    target_tier = normalize_tier(target_tier)
    if helper_tier >= MAX_TIER:
        return True
    if helper_tier == 4:
        return target_tier <= 3
    if helper_tier == 3:
        return target_tier <= 2
    return False


def notify_owner_message() -> str:
    owner = get_owner()
    pending = list_pending_attempts()
    alerts = list_unread_alerts()
    if not pending and not alerts:
        return "No security alerts right now."
    parts = [f"{len(alerts)} unread alert(s)", f"{len(pending)} pending access attempt(s)"]
    return f"Security notice for {owner['name']}: " + ", ".join(parts) + ". Say security panel to review."
