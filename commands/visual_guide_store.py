"""Persist visual guides and step-by-step progress."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

from silva.config import CONFIG_DIR

GUIDES_DIR = CONFIG_DIR / "captures" / "guides"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def new_guide_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]


def guide_folder(guide_id: str) -> Path:
    path = GUIDES_DIR / guide_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_guide(
    *,
    guide_id: str,
    query: str,
    steps: list[str],
    capture_path: str,
    capture_kind: str,
    search_results: list[dict],
    mouse_log: list[tuple[int, int, float]] | None = None,
    gyazo_url: str | None = None,
) -> Path:
    folder = guide_folder(guide_id)
    payload = {
        "id": guide_id,
        "created_at": _now(),
        "query": query,
        "capture_path": capture_path,
        "capture_kind": capture_kind,
        "gyazo_url": gyazo_url,
        "steps": steps,
        "completed": [],
        "current_step": 0,
        "search_results": search_results,
        "mouse_log": mouse_log or [],
    }
    meta = folder / "guide.json"
    meta.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    write_steps_txt(folder / "steps.txt", steps, completed=set())
    return folder


def load_guide(guide_id: str) -> dict | None:
    meta = GUIDES_DIR / guide_id / "guide.json"
    if not meta.exists():
        return None
    try:
        return json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_latest_guide() -> dict | None:
    if not GUIDES_DIR.exists():
        return None
    folders = sorted(GUIDES_DIR.iterdir(), reverse=True)
    for folder in folders:
        if not folder.is_dir():
            continue
        guide = load_guide(folder.name)
        if guide:
            return guide
    return None


def update_guide(guide: dict) -> None:
    folder = guide_folder(guide["id"])
    (folder / "guide.json").write_text(json.dumps(guide, indent=2), encoding="utf-8")
    write_steps_txt(
        folder / "steps.txt",
        guide.get("steps", []),
        completed=set(guide.get("completed", [])),
    )


def write_steps_txt(path: Path, steps: list[str], *, completed: set[int]) -> None:
    lines: list[str] = []
    for index, step in enumerate(steps):
        mark = "x" if index in completed else " "
        prefix = "[x]" if index in completed else "[ ]"
        lines.append(f"{prefix} Step {index + 1}: {step}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def mark_step_complete(guide: dict, step_index: int, *, done: bool = True) -> dict:
    completed = set(guide.get("completed", []))
    if done:
        completed.add(step_index)
    else:
        completed.discard(step_index)
    guide["completed"] = sorted(completed)
    if done and step_index >= guide.get("current_step", 0):
        guide["current_step"] = min(step_index + 1, len(guide.get("steps", [])) - 1)
    update_guide(guide)
    return guide


def reset_steps(guide: dict) -> dict:
    guide["completed"] = []
    guide["current_step"] = 0
    update_guide(guide)
    return guide
