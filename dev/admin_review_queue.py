"""Owner-review queue for updates and code snippets staged by admins."""

from __future__ import annotations

import json
import uuid
from datetime import datetime

from silva.dev.paths import DEV_DIR, ensure_dev_dir
from silva.users.manager import is_owner
from silva.users.profile_access import can_open_control_panel

QUEUE_FILE = DEV_DIR / "admin_review_queue.json"

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_APPLIED = "applied"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _load_queue() -> list[dict]:
    if not QUEUE_FILE.exists():
        return []
    try:
        data = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _save_queue(items: list[dict]) -> None:
    ensure_dev_dir()
    QUEUE_FILE.write_text(json.dumps(items, indent=2), encoding="utf-8")


def _clean_lines(values) -> list[str]:
    result: list[str] = []
    for value in values or []:
        item = str(value).strip()
        if item and item not in result:
            result.append(item)
    return result


def queue_admin_update(
    user: dict,
    *,
    features=None,
    changelog=None,
    code: str = "",
    checks: dict | None = None,
) -> dict:
    """Stage a typed update or code snippet for owner review. No code is executed."""
    from silva.users.admin_access import is_capability_enabled

    if not can_open_control_panel(user or {}) or not is_capability_enabled(user or {}, "stage_updates"):
        raise PermissionError("Only the owner and admins with staging access can stage updates.")

    feature_list = _clean_lines(features)
    note_list = _clean_lines(changelog)
    snippet = str(code or "")
    item = {
        "id": uuid.uuid4().hex[:12],
        "kind": "code" if snippet and not feature_list else "update",
        "status": STATUS_PENDING,
        "submitted_by": str(user.get("id") or "guest"),
        "submitted_by_name": str(user.get("name") or "Guest"),
        "submitted_at": _now(),
        "features": feature_list,
        "changelog": note_list,
        "code": snippet,
        "checks": dict(checks or {}),
        "reviewed_by": "",
        "reviewed_at": "",
        "review_note": "",
        "applied_at": "",
    }
    items = _load_queue()
    items.append(item)
    _save_queue(items)
    return dict(item)


def list_admin_reviews(*, status: str | None = None) -> list[dict]:
    items = _load_queue()
    if status:
        return [dict(item) for item in items if item.get("status") == status]
    return [dict(item) for item in items]


def list_pending_admin_reviews() -> list[dict]:
    return list_admin_reviews(status=STATUS_PENDING)


def review_admin_review(
    item_id: str,
    *,
    reviewer: dict,
    approve: bool,
    note: str = "",
) -> tuple[bool, dict | None, str]:
    """Approve or reject a staged item. Owner-only, checked here as well as in the UI."""
    if not is_owner(reviewer):
        return False, None, "Only the owner can review staged updates."

    items = _load_queue()
    for item in items:
        if str(item.get("id")) != str(item_id):
            continue
        if item.get("status") != STATUS_PENDING:
            return False, dict(item), "That item was already reviewed."
        item["status"] = STATUS_APPROVED if approve else STATUS_REJECTED
        item["reviewed_by"] = str(reviewer.get("id") or "owner")
        item["reviewed_at"] = _now()
        item["review_note"] = str(note or "")
        _save_queue(items)
        return True, dict(item), ""
    return False, None, "Staged item not found."


def mark_admin_review_applied(item_id: str, *, owner: dict) -> tuple[bool, str]:
    if not is_owner(owner):
        return False, "Only the owner can mark a staged update as applied."
    items = _load_queue()
    for item in items:
        if str(item.get("id")) != str(item_id):
            continue
        item["status"] = STATUS_APPLIED
        item["applied_at"] = _now()
        _save_queue(items)
        return True, ""
    return False, "Staged item not found."
