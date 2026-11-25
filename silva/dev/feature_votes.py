from __future__ import annotations

import json
import uuid
from datetime import datetime

from silva.dev.dev_branch import prepare_dev_branch
from silva.dev.paths import DEV_DIR, ensure_dev_dir
from silva.users.admin_access import is_capability_enabled
from silva.users.manager import is_owner
from silva.users.profile_access import can_open_control_panel

VOTES_FILE = DEV_DIR / "dev_feature_votes.json"

STATUS_PROPOSED = "proposed"
STATUS_DEV_TESTING = "dev_testing"
STATUS_OWNER_APPROVED = "owner_approved"
STATUS_LIVE = "live"
STATUS_REJECTED = "rejected"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _load_features() -> list[dict]:
    if not VOTES_FILE.exists():
        return []
    try:
        data = json.loads(VOTES_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _save_features(items: list[dict]) -> None:
    ensure_dev_dir()
    VOTES_FILE.write_text(json.dumps(items[-300:], indent=2), encoding="utf-8")


def _can_stage(user: dict | None) -> bool:
    active = user or {}
    return can_open_control_panel(active) and is_capability_enabled(active, "stage_updates")


def propose_dev_feature(
    user: dict | None,
    title: str,
    details: str = "",
    *,
    source_request_id: str = "",
) -> dict:
    if not _can_stage(user):
        raise PermissionError("Only admins with staging access can propose dev features.")
    item = {
        "id": uuid.uuid4().hex[:12],
        "title": str(title or "").strip(),
        "details": str(details or "").strip(),
        "source_request_id": str(source_request_id or ""),
        "status": STATUS_PROPOSED,
        "proposed_by": str((user or {}).get("id") or "guest"),
        "proposed_by_name": str((user or {}).get("name") or "Guest"),
        "proposed_at": _now(),
        "votes": {},
        "dev_branch_path": "",
        "finalized_by": "",
        "finalized_at": "",
        "live_at": "",
        "live_by": "",
        "emergency_push": False,
    }
    items = _load_features()
    items.append(item)
    _save_features(items)
    return dict(item)


def list_dev_features(*, status: str | None = None) -> list[dict]:
    items = _load_features()
    if status:
        return [dict(item) for item in items if item.get("status") == status]
    return [dict(item) for item in items]


def start_dev_testing(feature_id: str, user: dict | None) -> tuple[bool, str]:
    if not _can_stage(user):
        return False, "Only admins with staging access can prepare the dev branch."
    path = prepare_dev_branch()
    items = _load_features()
    for item in items:
        if str(item.get("id")) != str(feature_id):
            continue
        item["status"] = STATUS_DEV_TESTING
        item["dev_branch_path"] = str(path)
        _save_features(items)
        return True, str(path)
    return False, "Dev feature not found."


def vote_totals(item: dict) -> dict:
    votes = item.get("votes") or {}
    yes = sum(1 for value in votes.values() if bool(value.get("approve")))
    no = sum(1 for value in votes.values() if not bool(value.get("approve")))
    return {"yes": yes, "no": no, "total": yes + no}


def cast_dev_vote(feature_id: str, voter: dict | None, approve: bool, note: str = "") -> tuple[bool, str]:
    active = voter or {}
    if not can_open_control_panel(active):
        return False, "Only the owner and tier 4 admins can vote on dev features."
    items = _load_features()
    for item in items:
        if str(item.get("id")) != str(feature_id):
            continue
        if item.get("status") in {STATUS_REJECTED, STATUS_LIVE}:
            return False, "That feature is no longer open for voting."
        votes = item.setdefault("votes", {})
        votes[str(active.get("id") or "guest")] = {
            "voter_name": str(active.get("name") or "Guest"),
            "approve": bool(approve),
            "note": str(note or "").strip()[:300],
            "voted_at": _now(),
        }
        _save_features(items)
        totals = vote_totals(item)
        return True, f"Vote recorded. Yes {totals['yes']}, no {totals['no']}."
    return False, "Dev feature not found."


def owner_finalize(feature_id: str, owner: dict | None, approve: bool, note: str = "") -> tuple[bool, str]:
    if not is_owner(owner):
        return False, "Only the owner can make the final dev feature decision."
    items = _load_features()
    for item in items:
        if str(item.get("id")) != str(feature_id):
            continue
        item["status"] = STATUS_OWNER_APPROVED if approve else STATUS_REJECTED
        item["finalized_by"] = str((owner or {}).get("id") or "owner")
        item["finalized_at"] = _now()
        if note:
            votes = item.setdefault("votes", {})
            votes["owner_note"] = {"approve": bool(approve), "note": str(note).strip()[:300], "voted_at": _now()}
        _save_features(items)
        return True, "Owner approval recorded." if approve else "Feature rejected."
    return False, "Dev feature not found."


def mark_dev_feature_live(
    feature_id: str,
    actor: dict | None,
    *,
    emergency: bool = False,
) -> tuple[bool, str]:
    active = actor or {}
    if emergency:
        if not is_owner(active) and not is_capability_enabled(active, "emergency_publish_updates"):
            return False, "Only the owner or a trusted admin can emergency push."
    elif not is_owner(active):
        return False, "Only the owner can mark a feature live."
    items = _load_features()
    for item in items:
        if str(item.get("id")) != str(feature_id):
            continue
        if item.get("status") != STATUS_OWNER_APPROVED and not emergency:
            return False, "Owner approval is required before a normal live push."
        item["status"] = STATUS_LIVE
        item["live_at"] = _now()
        item["live_by"] = str(active.get("id") or "owner")
        item["emergency_push"] = bool(emergency)
        _save_features(items)
        return True, "Feature marked live as opt-in."
    return False, "Dev feature not found."
