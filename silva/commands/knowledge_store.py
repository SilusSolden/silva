"""Save skimmed knowledge on the main NVMe with Silva's other files. Never spill onto extra disks."""

from __future__ import annotations

import json
import re
from pathlib import Path

from silva.config import CONFIG_DIR
from silva.logger import log_error, log_info
from silva.storage.drives import (
    StorageRefused,
    pick_data_drive,
    silva_data_root,
)

KNOWLEDGE_DIR = CONFIG_DIR / "knowledge"
INDEX_FILE = CONFIG_DIR / "knowledge_index.json"
DATA_FOLDER = "knowledge"
MAX_FILE_CHARS = 400_000
STORAGE_REFUSAL = (
    "I couldn't save that on the drive that's in use. "
    "Extra files stay on the main drive unless you pick another one yourself."
)

_LAST: dict[str, dict[str, str]] = {}
_STOP = {
    "a", "an", "the", "of", "on", "in", "for", "to", "and", "all", "information",
    "info", "about", "wikipedia", "please", "me", "my", "this", "that",
}


def _slug(topic: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", (topic or "").strip().lower())
    text = text.strip("-")[:72]
    return text or "topic"


def category_for(topic: str) -> str:
    words = [w for w in re.findall(r"[a-z0-9]+", (topic or "").lower()) if w not in _STOP]
    if not words:
        return "general"
    if words[0] in {"how", "make", "build", "craft"} or "how" in words[:2]:
        rest = [w for w in words if w not in {"how", "to", "make", "build", "do", "i"}]
        return _slug("how-to " + " ".join(rest[:3] or words[:3]))
    return _slug(" ".join(words[:4]))


def knowledge_dir() -> Path:
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    return KNOWLEDGE_DIR


def remember_result(user_id: str, topic: str, body: str, *, category: str = "") -> None:
    _LAST[user_id or "guest"] = {
        "topic": (topic or "").strip(),
        "body": (body or "").strip(),
        "category": category or category_for(topic),
    }


def last_result(user_id: str) -> dict[str, str] | None:
    item = _LAST.get(user_id or "guest")
    if not item or not item.get("body"):
        return None
    return dict(item)


def _using_test_dir() -> bool:
    return Path(KNOWLEDGE_DIR) != CONFIG_DIR / "knowledge"


def _load_index() -> dict:
    if not INDEX_FILE.exists():
        return {"items": []}
    try:
        data = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("items", [])
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return {"items": []}


def _save_index(data: dict) -> None:
    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _clip_body(body: str) -> str:
    text = (body or "").strip()
    if len(text) <= MAX_FILE_CHARS:
        return text
    return text[:MAX_FILE_CHARS].rsplit(" ", 1)[0] + "\n\n[trimmed to keep the drive safe]\n"


def _pick_root(needed: int) -> Path:
    del needed
    if _using_test_dir():
        knowledge_dir()
        return Path(KNOWLEDGE_DIR)
    drive = pick_data_drive()
    if drive is None or drive.is_system:
        root = knowledge_dir()
    else:
        root = silva_data_root(drive) / DATA_FOLDER
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise StorageRefused(STORAGE_REFUSAL) from exc
    return root


def save_knowledge(topic: str, body: str, *, category: str | None = None) -> Path:
    text = _clip_body(body)
    if not text:
        raise RuntimeError("There was nothing to save.")
    cat = category or category_for(topic)
    needed = len(text.encode("utf-8")) + 256
    root = _pick_root(needed)
    folder = root / cat
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{_slug(topic)}.txt"
    header = f"{topic.strip()}\nCategory: {cat}\n{'=' * min(40, max(8, len(topic.strip())))}\n\n"
    path.write_text(header + text + "\n", encoding="utf-8")
    _index_item(topic, cat, path)
    log_info(f"Knowledge saved ({cat}): {path}")
    return path


def _index_item(topic: str, category: str, path: Path) -> None:
    if _using_test_dir():
        return
    data = _load_index()
    items = [row for row in data.get("items", []) if str(row.get("path") or "") != str(path)]
    items.append(
        {
            "topic": topic,
            "category": category,
            "path": str(path),
            "drive": str(path.drive or ""),
        }
    )
    data["items"] = items[-400:]
    try:
        _save_index(data)
    except OSError as exc:
        log_error("Knowledge index save failed", exc=exc)


def _scan_live_files() -> list[Path]:
    files: list[Path] = []
    if _using_test_dir():
        files.extend(Path(KNOWLEDGE_DIR).rglob("*.txt"))
        return files
    from silva.storage.drives import list_drives

    seen: set[str] = set()
    try:
        for path in knowledge_dir().rglob("*.txt"):
            key = str(path).lower()
            if key in seen:
                continue
            seen.add(key)
            files.append(path)
    except OSError:
        pass
    for drive in list_drives():
        folder = silva_data_root(drive) / DATA_FOLDER
        if not folder.exists():
            continue
        try:
            for path in folder.rglob("*.txt"):
                key = str(path).lower()
                if key in seen:
                    continue
                seen.add(key)
                files.append(path)
        except OSError:
            continue
    for row in _load_index().get("items", []):
        path = Path(str(row.get("path") or ""))
        key = str(path).lower()
        if key and path.exists() and key not in seen:
            seen.add(key)
            files.append(path)
    return files


def list_saved(*, query: str = "") -> list[dict]:
    needle = (query or "").strip().lower()
    rows: list[dict] = []
    for path in _scan_live_files():
        category = path.parent.name
        topic = path.stem.replace("-", " ")
        blob = f"{category} {topic} {path.name}".lower()
        if needle and needle not in blob:
            try:
                head = path.read_text(encoding="utf-8")[:400].lower()
            except OSError:
                head = ""
            if needle not in head:
                continue
        rows.append(
            {
                "topic": topic,
                "category": category,
                "path": path,
                "missing": False,
            }
        )
    if needle:
        for row in _load_index().get("items", []):
            topic = str(row.get("topic") or "")
            category = str(row.get("category") or "")
            path = Path(str(row.get("path") or ""))
            if needle not in f"{topic} {category}".lower():
                continue
            if any(existing["path"] == path for existing in rows):
                continue
            rows.append(
                {
                    "topic": topic,
                    "category": category,
                    "path": path,
                    "missing": not path.exists(),
                }
            )
    return rows


def read_saved(query: str) -> tuple[str, Path] | None:
    rows = list_saved(query=query)
    live = [row for row in rows if not row.get("missing")]
    if not live:
        return None
    path = Path(live[0]["path"])
    try:
        return path.read_text(encoding="utf-8"), path
    except OSError:
        return None


def format_saved_list(query: str = "") -> str:
    rows = list_saved(query=query)
    if not rows:
        if query:
            return f"I don't have stored knowledge about {query} on any plugged-in drive."
        return "I don't have any stored knowledge files yet."
    missing = [row for row in rows if row.get("missing")]
    live = [row for row in rows if not row.get("missing")]
    lines = []
    if live:
        lines.append("Stored knowledge:")
        for row in live[:12]:
            lines.append(f"- {row['category']}: {row['topic']} on {Path(row['path']).drive}")
        if len(live) > 12:
            lines.append(f"That's 12 of {len(live)} files.")
    if missing:
        drives = sorted({Path(row["path"]).drive or "?" for row in missing})
        lines.append(
            "Some files are on a drive that isn't plugged in: " + ", ".join(drives) + "."
        )
    return " ".join(lines) if len(lines) <= 3 else "\n".join(lines)
