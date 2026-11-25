"""Weekly permission / access request tracking."""

from __future__ import annotations

import json
from datetime import datetime

from silva.config import CONFIG_DIR, load_config

USAGE_FILE = CONFIG_DIR / "permission_request_usage.json"
REQUESTS_FILE = CONFIG_DIR / "permission_access_requests.json"


def _week_key() -> str:
    return datetime.now().strftime("%Y-W%W")


def _max_per_week() -> int:
    return int(load_config().get("permission_requests_per_week", 3))


def _load_usage() -> dict:
    if not USAGE_FILE.exists():
        return {}
    data = json.loads(USAGE_FILE.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _save_usage(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    USAGE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def requests_remaining(user_id: str) -> int:
    usage = _load_usage()
    entry = usage.get(user_id, {})
    if entry.get("week") != _week_key():
        return _max_per_week()
    used = int(entry.get("count", 0))
    return max(0, _max_per_week() - used)


def can_submit_request(user_id: str) -> bool:
    return requests_remaining(user_id) > 0


def record_request(user_id: str) -> None:
    usage = _load_usage()
    week = _week_key()
    entry = usage.get(user_id, {})
    if entry.get("week") != week:
        entry = {"week": week, "count": 0}
    entry["count"] = int(entry.get("count", 0)) + 1
    entry["week"] = week
    usage[user_id] = entry
    _save_usage(usage)


def submit_access_request(
    user: dict,
    *,
    reason: str,
    requested_action: str,
    permission: str,
) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    requests = []
    if REQUESTS_FILE.exists():
        data = json.loads(REQUESTS_FILE.read_text(encoding="utf-8"))
        requests = data if isinstance(data, list) else []

    requests.append(
        {
            "from_user": user.get("name", "Unknown"),
            "from_id": user.get("id", "guest"),
            "tier": user.get("tier", 1),
            "reason": reason.strip(),
            "requested_action": requested_action.strip(),
            "permission": permission,
            "submitted_at": datetime.now().isoformat(timespec="seconds"),
            "week": _week_key(),
        }
    )
    REQUESTS_FILE.write_text(json.dumps(requests, indent=2), encoding="utf-8")
    record_request(user.get("id", "guest"))
