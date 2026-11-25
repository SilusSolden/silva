from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta

from silva.config import CONFIG_DIR, load_config

TRACKING_FILE = CONFIG_DIR / "update_help_tracking.json"
HISTORY_FILE = CONFIG_DIR / "update_help_request_history.json"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _load_json(path, fallback):
    if not path.exists():
        return fallback
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback
    return data if isinstance(data, type(fallback)) else fallback


def _save_json(path, data) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _cooldown() -> timedelta:
    try:
        minutes = float(load_config().get("update_help_request_cooldown_minutes", 10))
    except (TypeError, ValueError):
        minutes = 10.0
    return timedelta(minutes=max(0.0, minutes))


def record_update_help_request(
    user: dict | None,
    kind: str,
    detail: str = "",
    *,
    notify: bool = True,
) -> tuple[bool, str]:
    user = user or {}
    user_id = str(user.get("id") or "guest")
    name = str(user.get("name") or "Guest")
    now = datetime.now()

    tracking = _load_json(TRACKING_FILE, {})
    bucket = tracking.setdefault(user_id, {})
    entry = bucket.setdefault(kind, {"count": 0, "last_at": ""})
    last_at = str(entry.get("last_at") or "")
    if last_at:
        try:
            previous = datetime.fromisoformat(last_at)
        except ValueError:
            previous = None
        if previous and now - previous < _cooldown():
            return False, "I've already sent that request to admins and the owner."

    entry["count"] = int(entry.get("count", 0)) + 1
    entry["last_at"] = now.isoformat(timespec="seconds")
    tracking[user_id] = bucket
    _save_json(TRACKING_FILE, tracking)

    history = _load_json(HISTORY_FILE, [])
    history.append(
        {
            "id": uuid.uuid4().hex[:12],
            "user_id": user_id,
            "user_name": name,
            "kind": str(kind),
            "detail": str(detail or "").strip()[:500],
            "status": "sent",
            "submitted_at": _now(),
        }
    )
    _save_json(HISTORY_FILE, history[-200:])

    if notify:
        from silva.notifications.dispatch import notify_owner_async

        notify_owner_async(
            f"Update help request from {name} ({user_id}): {kind}. {detail}".strip(),
            reason="update_help_request",
            force=False,
            prefer_telegram=True,
        )
    return True, ""


def list_update_help_requests() -> list[dict]:
    return [dict(item) for item in _load_json(HISTORY_FILE, [])]
