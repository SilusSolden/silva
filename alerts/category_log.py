"""Per-category alert logs — each section gets its own folder under ~/.silva/logs/alerts/."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from silva.config import CONFIG_DIR
from silva.logger import log_info

ALERTS_ROOT = CONFIG_DIR / "logs" / "alerts"
VALID_CATEGORIES = frozenset({"weather", "news", "security", "protection"})


def _category_dir(category: str) -> Path:
    safe = category.strip().lower()
    if safe not in VALID_CATEGORIES:
        safe = "general"
    path = ALERTS_ROOT / safe
    path.mkdir(parents=True, exist_ok=True)
    return path


def _timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log_category_alert(
    category: str,
    title: str,
    *,
    detail: str = "",
    metadata: dict | None = None,
    asleep: bool = False,
) -> None:
    """Append one alert to the category daily log and JSONL index."""
    category = category.strip().lower()
    entry = {
        "timestamp": _timestamp(),
        "category": category,
        "title": title.strip(),
        "detail": detail.strip(),
        "asleep": bool(asleep),
        "metadata": metadata or {},
    }
    day = datetime.now().strftime("%Y-%m-%d")
    folder = _category_dir(category)
    text_path = folder / f"{day}.log"
    jsonl_path = folder / f"{day}.jsonl"

    line = f"[{entry['timestamp']}] {entry['title']}"
    if detail:
        line = f"{line}\n  {detail.strip()}"
    if asleep:
        line = f"{line}\n  (logged during sleep mode)"
    with text_path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")

    with jsonl_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    log_info(f"Alert logged [{category}]: {title[:120]}")


def list_recent_alerts(category: str, *, limit: int = 20) -> list[dict]:
    folder = _category_dir(category)
    files = sorted(folder.glob("*.jsonl"), reverse=True)
    items: list[dict] = []
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue
            if len(items) >= limit:
                return items
    return items
