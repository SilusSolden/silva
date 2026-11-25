"""Voice access with safe user scopes and owner-approved admin scopes."""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from silva.config import CONFIG_DIR, load_config
from silva.users.admin_access import is_capability_enabled
from silva.users.features import FEATURE_VOICE_CONTROL_ACCESS, save_user_feature_overrides
from silva.users.manager import is_owner, load_store
from silva.users.profile_access import can_open_control_panel
from silva.users.tiers import normalize_tier

REQUESTS_FILE = CONFIG_DIR / "voice_control_access_requests.json"
DOWNLOADS_DIR = Path.home() / "Downloads"
REFERENCE_IMAGE = Path(r"c:\Users\klevo\Downloads\c41632086db272d9b1171e27ff7f51c0.png")
_GYAZO_NAME_RE = re.compile(r"^[0-9a-f]{32}\.(?:png|jpe?g|gif)$", re.I)
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif"}

VOICE_SCOPES: dict[str, str] = {
    "conversation": "Normal conversation",
    "images": "Images and visual guides",
    "math": "Math and calculations",
    "weather_news": "Weather and news",
    "notes": "Notes and to-do",
    "appointments": "Appointments",
    "audio": "Audio controls",
    "media": "Playback and media",
    "system": "System controls",
    "updates": "Live updates and restart",
    "users": "User management",
    "security": "Security panel",
    "logs": "View logs",
    "settings": "Change settings",
    "camera": "Camera controls",
    "planner": "3D planner",
    "room_audio": "Room voice gating",
}

BASIC_VOICE_SCOPES = frozenset(
    {
        "conversation",
        "images",
        "math",
        "weather_news",
        "notes",
        "appointments",
        "audio",
        "media",
    }
)
ADMIN_VOICE_SCOPES = frozenset(set(VOICE_SCOPES) - BASIC_VOICE_SCOPES)

_SCOPE_ALIASES: dict[str, str] = {
    "normal conversation": "conversation",
    "talking": "conversation",
    "chat": "conversation",
    "image": "images",
    "images": "images",
    "visual guides": "images",
    "math": "math",
    "calculations": "math",
    "system controls": "system",
    "live updates": "updates",
    "update": "updates",
    "user management": "users",
    "security panel": "security",
    "view logs": "logs",
    "change settings": "settings",
    "camera controls": "camera",
    "3d planner": "planner",
    "audio controls": "audio",
    "playback and media": "media",
    "media": "media",
    "notes and to-do": "notes",
    "weather and news": "weather_news",
    "room audio": "room_audio",
    "room voice": "room_audio",
    "room voice gating": "room_audio",
}

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_DENIED = "denied"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def normalize_scope(raw: str) -> str | None:
    key = str(raw or "").strip().lower()
    if not key:
        return None
    key = _SCOPE_ALIASES.get(key, key.replace(" ", "_"))
    return key if key in VOICE_SCOPES else None


def scope_label(scope: str) -> str:
    key = normalize_scope(scope) or str(scope)
    return VOICE_SCOPES.get(key, key.replace("_", " ").title())


def _load_requests() -> list[dict]:
    if not REQUESTS_FILE.exists():
        return []
    try:
        data = json.loads(REQUESTS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _save_requests(items: list[dict]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    REQUESTS_FILE.write_text(json.dumps(items, indent=2), encoding="utf-8")


def _stamp(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def can_request_voice_control(user: dict | None, scope: str | None = None) -> tuple[bool, str]:
    user = user or {}
    if is_owner(user):
        return True, ""
    if not user.get("voice_enrolled"):
        return False, "Your voice must be enrolled before using voice access."
    key = normalize_scope(scope) if scope else None
    if scope is None or key in BASIC_VOICE_SCOPES:
        return True, ""
    if key and key in ADMIN_VOICE_SCOPES and is_capability_enabled(user, f"voice_scope_{key}"):
        return True, ""
    if normalize_tier(user.get("tier", 1)) < 4 or not can_open_control_panel(user):
        return False, (
            "Basic voice access is already on after voice enrollment. "
            "Major system controls require a tier 4 admin request."
        )
    if key and key not in ADMIN_VOICE_SCOPES:
        return False, "That voice-control area is not recognized."
    wait_days = int(load_config().get("voice_access_request_wait_days", 0) or 0)
    if wait_days <= 0:
        return True, ""
    ready_at = _stamp(user.get("voice_enrolled_at") or user.get("admin_approved_at") or "")
    if ready_at and datetime.now() - ready_at < timedelta(days=wait_days):
        return False, f"Voice-control requests unlock after {wait_days} day(s) of approved access."
    return True, ""


def submit_voice_access_request(user: dict, scope: str, reason: str) -> tuple[bool, dict | None, str]:
    key = normalize_scope(scope)
    if not key:
        return False, None, "That voice-control area is not recognized."
    if key in BASIC_VOICE_SCOPES and not is_owner(user):
        return False, None, "Basic voice access is already enabled after voice enrollment."
    allowed, message = can_request_voice_control(user, key)
    if not allowed:
        return False, None, message
    detail = str(reason or "").strip()
    if len(detail) < 8:
        return False, None, "Please explain why you need that voice-control area."

    items = _load_requests()
    user_id = str(user.get("id") or "guest")
    for item in items:
        if (
            item.get("from_id") == user_id
            and item.get("scope") == key
            and item.get("status") == STATUS_PENDING
        ):
            return False, None, "You already have a pending request for that area."

    entry = {
        "id": uuid.uuid4().hex[:12],
        "from_user": str(user.get("name") or "Guest"),
        "from_id": user_id,
        "tier": user.get("tier", 1),
        "scope": key,
        "scope_label": VOICE_SCOPES[key],
        "reason": detail,
        "status": STATUS_PENDING,
        "submitted_at": _now(),
        "reviewed_at": "",
        "reviewed_by": "",
        "reference_image": str(REFERENCE_IMAGE),
    }
    items.append(entry)
    _save_requests(items)
    return True, entry, ""


def list_voice_access_requests(status: str | None = None) -> list[dict]:
    items = _load_requests()
    if status:
        return [dict(item) for item in items if item.get("status") == status]
    return [dict(item) for item in items]


def list_pending_voice_access_requests() -> list[dict]:
    return list_voice_access_requests(status=STATUS_PENDING)


def review_voice_access_request(
    request_id: str,
    *,
    reviewer: dict,
    approve: bool,
) -> tuple[bool, dict | None, str]:
    if not is_owner(reviewer):
        return False, None, "Only the owner can approve or deny voice-control access."

    items = _load_requests()
    for item in items:
        if str(item.get("id")) != str(request_id):
            continue
        if item.get("status") != STATUS_PENDING:
            return False, dict(item), "That request was already reviewed."
        item["status"] = STATUS_APPROVED if approve else STATUS_DENIED
        item["reviewed_at"] = _now()
        item["reviewed_by"] = str(reviewer.get("id") or "owner")
        _save_requests(items)

        if approve:
            user_id = str(item.get("from_id") or "")
            store = load_store()
            if user_id and user_id in store.get("users", {}):
                overrides = dict(store["users"][user_id].get("feature_overrides") or {})
                overrides[FEATURE_VOICE_CONTROL_ACCESS] = True
                save_user_feature_overrides(user_id, overrides)
        return True, dict(item), ""
    return False, None, "Voice-control request not found."


def approved_scopes_for_user(user_id: str) -> set[str]:
    return {
        str(item.get("scope"))
        for item in list_voice_access_requests(status=STATUS_APPROVED)
        if item.get("from_id") == user_id and item.get("scope")
    }


def can_use_voice_control(user: dict | None, scope: str) -> bool:
    user = user or {}
    if is_owner(user):
        return True
    key = normalize_scope(scope)
    if not key or not user.get("voice_enrolled"):
        return False
    if key in BASIC_VOICE_SCOPES:
        return True
    if key in ADMIN_VOICE_SCOPES and is_capability_enabled(user, f"voice_scope_{key}"):
        return True
    if not can_open_control_panel(user):
        return False
    return key in approved_scopes_for_user(str(user.get("id") or "guest"))


def requestable_voice_scopes(user: dict | None) -> dict[str, str]:
    user = user or {}
    if is_owner(user) or not user.get("voice_enrolled") or not can_open_control_panel(user):
        return {}
    return {key: label for key, label in VOICE_SCOPES.items() if key in ADMIN_VOICE_SCOPES}


def reference_image_path() -> Path:
    configured = os.environ.get("SILVA_REFERENCE_IMAGE") or load_config().get("reference_image_path")
    if configured:
        path = Path(str(configured))
        if path.exists():
            return path

    candidates: list[Path] = []
    try:
        for path in DOWNLOADS_DIR.iterdir():
            if path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES:
                candidates.append(path)
    except OSError:
        candidates = []

    gyazo = [path for path in candidates if _GYAZO_NAME_RE.match(path.name)]
    pool = gyazo or candidates
    if pool:
        try:
            return max(pool, key=lambda path: path.stat().st_mtime)
        except OSError:
            pass
    return REFERENCE_IMAGE
