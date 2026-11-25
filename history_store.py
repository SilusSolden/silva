"""Persistent history for Silva conversations, searches, and crafting guides."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from silva.config import CONFIG_DIR

HISTORY_DIR = CONFIG_DIR / "history"
HISTORY_FILE = HISTORY_DIR / "silva_history.json"
GUIDES_FILE = HISTORY_DIR / "active_guides.json"

_MAX_ITEMS = 500


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save(path: Path, data: dict) -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)


def _trim(items: list) -> list:
    if len(items) <= _MAX_ITEMS:
        return items
    return items[-_MAX_ITEMS:]


def _user_key(user_id: str) -> str:
    return user_id or "guest"


def record_conversation_turn(
    user_id: str,
    *,
    user_text: str,
    ai_text: str,
    category: str | None = None,
) -> None:
    data = _load(HISTORY_FILE)
    key = _user_key(user_id)
    bucket = data.setdefault("conversations", {}).setdefault(key, [])
    bucket.append(
        {
            "time": _now(),
            "user": user_text,
            "ai": ai_text,
            "category": category,
        }
    )
    data["conversations"][key] = _trim(bucket)
    _save(HISTORY_FILE, data)


def record_search(user_id: str, *, kind: str, query: str, title: str, summary: str = "") -> None:
    data = _load(HISTORY_FILE)
    key = _user_key(user_id)
    bucket = data.setdefault("searches", {}).setdefault(key, [])
    bucket.append(
        {
            "time": _now(),
            "kind": kind,
            "query": query,
            "title": title,
            "summary": summary[:400],
        }
    )
    data["searches"][key] = _trim(bucket)
    _save(HISTORY_FILE, data)


def record_guide(user_id: str, guide: dict[str, Any]) -> None:
    data = _load(HISTORY_FILE)
    key = _user_key(user_id)
    bucket = data.setdefault("guides", {}).setdefault(key, [])
    entry = {**guide, "time": _now()}
    bucket.append(entry)
    data["guides"][key] = _trim(bucket)
    _save(HISTORY_FILE, data)


def get_recent_conversations(user_id: str, limit: int = 10) -> list[dict]:
    data = _load(HISTORY_FILE)
    items = data.get("conversations", {}).get(_user_key(user_id), [])
    return list(reversed(items[-limit:]))


def get_recent_searches(user_id: str, limit: int = 10) -> list[dict]:
    data = _load(HISTORY_FILE)
    items = data.get("searches", {}).get(_user_key(user_id), [])
    return list(reversed(items[-limit:]))


def get_recent_guides(user_id: str, limit: int = 10) -> list[dict]:
    data = _load(HISTORY_FILE)
    items = data.get("guides", {}).get(_user_key(user_id), [])
    return list(reversed(items[-limit:]))


def find_guide(user_id: str, query_hint: str) -> dict | None:
    hint = query_hint.strip().lower()
    if not hint:
        return None
    for entry in get_recent_guides(user_id, limit=50):
        title = str(entry.get("title", "")).lower()
        q = str(entry.get("query", "")).lower()
        if hint in title or hint in q:
            return entry
    return None


def save_active_guide(user_id: str, guide: dict[str, Any]) -> None:
    data = _load(GUIDES_FILE)
    data[_user_key(user_id)] = {**guide, "updated": _now()}
    _save(GUIDES_FILE, data)


def load_active_guide(user_id: str) -> dict | None:
    data = _load(GUIDES_FILE)
    guide = data.get(_user_key(user_id))
    return guide if isinstance(guide, dict) else None


def clear_active_guide(user_id: str) -> None:
    data = _load(GUIDES_FILE)
    data.pop(_user_key(user_id), None)
    _save(GUIDES_FILE, data)


def record_calculation(
    user_id: str,
    *,
    query: str,
    result: str,
    category: str = "expression",
) -> None:
    data = _load(HISTORY_FILE)
    key = _user_key(user_id)
    bucket = data.setdefault("calculations", {}).setdefault(key, [])
    bucket.append(
        {
            "time": _now(),
            "query": query,
            "result": result,
            "category": category,
        }
    )
    data["calculations"][key] = _trim(bucket)
    _save(HISTORY_FILE, data)


def get_recent_calculations(user_id: str, limit: int = 10) -> list[dict]:
    data = _load(HISTORY_FILE)
    items = data.get("calculations", {}).get(_user_key(user_id), [])
    return list(reversed(items[-limit:]))


def record_measurement(
    user_id: str,
    *,
    query: str,
    source: str,
    summary: str,
    width_px: int,
    height_px: int,
    width_mm: float | None = None,
    height_mm: float | None = None,
    confidence: str = "pixel_only",
    image_path: str | None = None,
) -> None:
    data = _load(HISTORY_FILE)
    key = _user_key(user_id)
    bucket = data.setdefault("measurements", {}).setdefault(key, [])
    bucket.append(
        {
            "time": _now(),
            "query": query,
            "source": source,
            "summary": summary[:800],
            "width_px": width_px,
            "height_px": height_px,
            "width_mm": width_mm,
            "height_mm": height_mm,
            "confidence": confidence,
            "image_path": image_path,
        }
    )
    data["measurements"][key] = _trim(bucket)
    _save(HISTORY_FILE, data)


def get_recent_measurements(user_id: str, limit: int = 10) -> list[dict]:
    data = _load(HISTORY_FILE)
    items = data.get("measurements", {}).get(_user_key(user_id), [])
    return list(reversed(items[-limit:]))
