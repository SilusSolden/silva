"""Bug reports with tier escalation."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path

from silva.config import CONFIG_DIR
from silva.users.manager import get_owner, load_store
from silva.users.tiers import MAX_TIER, normalize_tier

REPORTS_FILE = CONFIG_DIR / "bug_reports.json"

_SILVA_BUG_RE = re.compile(
    r"\b(bug|glitch|broken|error|crash(?:ed)?|issue|problem|not working)\b",
    re.I,
)
_AI_CONTEXT_RE = re.compile(r"\b(silva|ai|assistant|this app|the app)\b", re.I)


def _load_reports() -> list[dict]:
    if not REPORTS_FILE.exists():
        return []
    data = json.loads(REPORTS_FILE.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def _save_reports(items: list[dict]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_FILE.write_text(json.dumps(items[-300:], indent=2), encoding="utf-8")


def is_silva_bug_report(text: str) -> bool:
    text = text.strip()
    if not text:
        return False
    if not _SILVA_BUG_RE.search(text):
        return False
    return bool(_AI_CONTEXT_RE.search(text))


def create_report(*, user: dict, message: str, source: str = "typed") -> dict:
    report = {
        "id": uuid.uuid4().hex[:10],
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "reporter_id": user.get("id", "guest"),
        "reporter_name": user.get("name", "Guest"),
        "reporter_tier": normalize_tier(user.get("tier", 1)),
        "message": message.strip(),
        "source": source,
        "status": "submitted",
        "assigned_tier": _next_review_tier(normalize_tier(user.get("tier", 1))),
        "history": [],
    }
    items = _load_reports()
    items.append(report)
    _save_reports(items)
    return report


def _next_review_tier(reporter_tier: int) -> int:
    return min(MAX_TIER, reporter_tier + 1)


def list_reports_for_reviewer(user: dict) -> list[dict]:
    tier = normalize_tier(user.get("tier", 1))
    owner_id = get_owner()["id"]
    if user.get("id") == owner_id or tier >= MAX_TIER:
        return [item for item in _load_reports() if item.get("status") != "resolved"][-20:]
    return [
        item
        for item in _load_reports()
        if item.get("status") == "submitted" and normalize_tier(item.get("assigned_tier", 1)) <= tier
    ][-20:]


def forward_report(report_id: str, *, actor: dict, note: str = "") -> bool:
    items = _load_reports()
    for item in items:
        if item.get("id") != report_id:
            continue
        current = normalize_tier(item.get("assigned_tier", 1))
        item.setdefault("history", []).append(
            {
                "at": datetime.now().isoformat(timespec="seconds"),
                "by": actor.get("name", "Admin"),
                "action": "forward",
                "note": note,
            }
        )
        if current >= MAX_TIER:
            item["status"] = "escalated_owner"
        else:
            item["assigned_tier"] = min(MAX_TIER, current + 1)
            item["status"] = "forwarded"
        _save_reports(items)
        return True
    return False


def resolve_report(report_id: str, *, actor: dict, note: str = "") -> bool:
    items = _load_reports()
    for item in items:
        if item.get("id") != report_id:
            continue
        item["status"] = "resolved"
        item.setdefault("history", []).append(
            {
                "at": datetime.now().isoformat(timespec="seconds"),
                "by": actor.get("name", "Admin"),
                "action": "resolved",
                "note": note,
            }
        )
        _save_reports(items)
        return True
    return False


def list_user_reports(user_id: str) -> list[dict]:
    return [item for item in _load_reports() if item.get("reporter_id") == user_id][-10:]
