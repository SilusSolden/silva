"""Track repeated feature requests, admin approval, and user nag limits."""

from __future__ import annotations

import json
from datetime import datetime

from silva.config import CONFIG_DIR, load_config

TRACKING_FILE = CONFIG_DIR / "feature_request_tracking.json"
REQUESTS_FILE = CONFIG_DIR / "feature_access_requests.json"

STATUS_NONE = "none"
STATUS_REQUESTED = "requested"
STATUS_APPROVED = "approved_pending_patch"
STATUS_DENIED = "denied"
STATUS_BLOCKED = "blocked"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _load_tracking() -> dict:
    if not TRACKING_FILE.exists():
        return {}
    try:
        data = json.loads(TRACKING_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_tracking(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    TRACKING_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _load_requests() -> list:
    if not REQUESTS_FILE.exists():
        return []
    try:
        data = json.loads(REQUESTS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_requests(items: list) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    REQUESTS_FILE.write_text(json.dumps(items, indent=2), encoding="utf-8")


def _entry(data: dict, user_id: str, feature: str) -> dict:
    user_bucket = data.setdefault(user_id, {})
    return user_bucket.setdefault(
        feature,
        {
            "status": STATUS_NONE,
            "ask_count": 0,
            "last_ask_at": "",
            "warned": False,
            "offered": False,
        },
    )


def _warn_threshold() -> int:
    return int(load_config().get("feature_request_warn_count", 4))


def _block_threshold() -> int:
    return int(load_config().get("feature_request_block_count", 7))


def get_feature_status(user_id: str, feature: str) -> dict:
    data = _load_tracking()
    return dict(_entry(data, user_id, feature))


def mark_feature_offer_made(user_id: str, feature: str = "general_feature_request") -> None:
    data = _load_tracking()
    entry = _entry(data, user_id, feature)
    entry["offered"] = True
    _save_tracking(data)


def feature_offer_pending(user_id: str, feature: str = "general_feature_request") -> bool:
    data = _load_tracking()
    return not bool(_entry(data, user_id, feature).get("offered"))


def record_feature_ask(user_id: str, feature: str) -> tuple[str, bool]:
    """Record a denied feature ask. Returns (message, should_offer_request)."""
    from silva.conversation.response_bank import (
        BLOCKED_FEATURE_REPLIES,
        NAG_WARNING_REPLIES,
        PENDING_FEATURE_REPLIES,
    )

    import random

    data = _load_tracking()
    entry = _entry(data, user_id, feature)
    entry["ask_count"] = int(entry.get("ask_count", 0)) + 1
    entry["last_ask_at"] = _now()
    status = entry.get("status", STATUS_NONE)

    if status == STATUS_BLOCKED:
        _save_tracking(data)
        return random.choice(BLOCKED_FEATURE_REPLIES), False

    if status == STATUS_APPROVED:
        _save_tracking(data)
        return (
            "Admins approved that feature. Please wait for the next Silva patch to install it.",
            False,
        )

    if status == STATUS_REQUESTED:
        _save_tracking(data)
        if entry["ask_count"] >= _block_threshold():
            entry["status"] = STATUS_BLOCKED
            entry["warned"] = True
            _save_tracking(data)
            return random.choice(BLOCKED_FEATURE_REPLIES), False
        if entry["ask_count"] >= _warn_threshold() and not entry.get("warned"):
            entry["warned"] = True
            _save_tracking(data)
            return random.choice(NAG_WARNING_REPLIES), False
        _save_tracking(data)
        return random.choice(PENDING_FEATURE_REPLIES), False

    _save_tracking(data)
    offer = entry["ask_count"] <= 2
    return (
        "I'm sorry, I'm not able to do that on your profile. "
        "You can ask an admin to enable it or add that feature.",
        offer,
    )


def submit_feature_request(user: dict, feature: str, *, reason: str = "") -> None:
    user_id = user.get("id", "guest")
    data = _load_tracking()
    entry = _entry(data, user_id, feature)
    entry["status"] = STATUS_REQUESTED
    entry["last_ask_at"] = _now()
    _save_tracking(data)

    requests = _load_requests()
    requests.append(
        {
            "user_id": user_id,
            "user_name": user.get("name", "Guest"),
            "feature": feature,
            "reason": reason.strip(),
            "status": "pending",
            "submitted_at": _now(),
        }
    )
    _save_requests(requests)

    from silva.notifications.dispatch import notify_owner_async

    name = str(user.get("name") or "Guest").strip()
    detail = reason.strip() or "No extra detail given."
    notify_owner_async(
        f"New feature request from {name} ({user_id}): {feature}. {detail}",
        reason="feature_request",
        force=False,
        prefer_telegram=True,
    )


def approve_feature_request(user_id: str, feature: str, *, approver_id: str) -> bool:
    data = _load_tracking()
    entry = _entry(data, user_id, feature)
    entry["status"] = STATUS_APPROVED
    entry["approved_at"] = _now()
    entry["approved_by"] = approver_id
    _save_tracking(data)

    requests = _load_requests()
    updated = False
    for item in requests:
        if (
            item.get("user_id") == user_id
            and item.get("feature") == feature
            and item.get("status") == "pending"
        ):
            item["status"] = "approved"
            item["approved_at"] = _now()
            item["approved_by"] = approver_id
            updated = True
    if updated:
        _save_requests(requests)
    return True


def block_feature_requests(user_id: str, feature: str, *, by: str) -> None:
    data = _load_tracking()
    entry = _entry(data, user_id, feature)
    entry["status"] = STATUS_BLOCKED
    entry["blocked_at"] = _now()
    entry["blocked_by"] = by
    _save_tracking(data)

    requests = _load_requests()
    updated = False
    for item in requests:
        if (
            item.get("user_id") == user_id
            and item.get("feature") == feature
            and item.get("status") == "pending"
        ):
            item["status"] = "blocked"
            item["blocked_at"] = _now()
            item["blocked_by"] = by
            updated = True
    if updated:
        _save_requests(requests)


def list_pending_feature_requests() -> list[dict]:
    return [r for r in _load_requests() if r.get("status") == "pending"]
