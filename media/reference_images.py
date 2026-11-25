"""Reference images kept outside the codebase and catalogued for later lookup."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from silva.config import CONFIG_DIR

STORE_DIR = CONFIG_DIR / "reference_images"
INDEX_FILE = STORE_DIR / "index.json"
BLOCKED_NAME = "blocked.json"
DOWNLOADS_DIR = Path.home() / "Downloads"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
CATEGORY_FOLDERS = {
    "object": "objects",
    "information": "information",
    "ai_issue": "ai_issues",
}
CATEGORY_LABELS = {
    "object": "Object",
    "information": "Information",
    "ai_issue": "AI issue",
}
_GYAZO_NAME_RE = re.compile(r"^[0-9a-f]{32}\.(?:png|jpe?g|gif|webp)$", re.I)
_AI_WORDS_RE = re.compile(
    r"\b(bug|glitch|error|crash|issue|problem|silva|ai|assistant|failed|failure|traceback|warning)\b",
    re.I,
)
_INFORMATION_WORDS_RE = re.compile(
    r"\b(info|information|informational|chart|graph|diagram|document|doc|docs|text|article|"
    r"receipt|note|notes|table|screenshot|screen|code|tutorial|guide|web|website|page)\b",
    re.I,
)


def _read_json(path: Path, fallback):
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, type(fallback)) else fallback
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return fallback


def ensure_store() -> Path:
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    for folder in CATEGORY_FOLDERS.values():
        (STORE_DIR / folder).mkdir(parents=True, exist_ok=True)
    return STORE_DIR


def load_index() -> list[dict]:
    ensure_store()
    data = _read_json(INDEX_FILE, {"records": []})
    records = data.get("records") or []
    return [record for record in records if isinstance(record, dict)]


def save_index(records: list[dict]) -> None:
    ensure_store()
    temp = INDEX_FILE.with_suffix(".json.tmp")
    temp.write_text(
        json.dumps({"records": records}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temp, INDEX_FILE)


def blocked_file() -> Path:
    return STORE_DIR / BLOCKED_NAME


def load_blocked_hashes() -> set[str]:
    data = _read_json(blocked_file(), {"hashes": []})
    return {
        str(item).strip().lower()
        for item in (data.get("hashes") or [])
        if str(item or "").strip()
    }


def save_blocked_hashes(hashes: set[str]) -> None:
    ensure_store()
    path = blocked_file()
    temp = path.with_suffix(".json.tmp")
    temp.write_text(
        json.dumps({"hashes": sorted(item for item in hashes if item)}, indent=2),
        encoding="utf-8",
    )
    os.replace(temp, path)


def normalize_category(value: str) -> str:
    text = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    if text in {"ai", "bug", "issue", "issues", "ai_issue", "ai_issues", "problem"}:
        return "ai_issue"
    if text in {"info", "info_image", "informational", "information", "text"}:
        return "information"
    if text in {"obj", "object", "objects", "photo", "picture"}:
        return "object"
    return "object"


def categorize(*texts: str) -> str:
    joined = " ".join(str(text or "") for text in texts)
    if _AI_WORDS_RE.search(joined):
        return "ai_issue"
    if _INFORMATION_WORDS_RE.search(joined):
        return "information"
    return "object"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _label_from_name(name: str) -> str:
    stem = Path(name or "").stem
    if _GYAZO_NAME_RE.fullmatch(Path(name or "").name):
        return "Gyazo image"
    cleaned = re.sub(r"[_\-]+", " ", stem)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:80] or "Reference image"


def _safe_original_name(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name or "image").name)
    return safe[:80] or "image"


def reference_path(reference: dict | str) -> Path | None:
    record = reference
    if isinstance(record, str):
        record = next((item for item in load_index() if item.get("id") == record), None)
    if not isinstance(record, dict):
        return None
    raw = str(record.get("path") or "")
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = STORE_DIR / path
    return path if path.is_file() else None


def add_reference(
    path: str | Path,
    *,
    category: str = "",
    label: str = "",
    notes: str = "",
    source: str = "manual",
    added_by: str = "",
) -> dict | None:
    source_path = Path(path).expanduser()
    if not source_path.is_file() or source_path.suffix.lower() not in IMAGE_SUFFIXES:
        return None

    records = load_index()
    try:
        digest = _sha256(source_path)
    except OSError:
        return None
    existing = next((record for record in records if record.get("sha256") == digest), None)
    if existing is not None:
        return existing
    if digest in load_blocked_hashes():
        return None

    chosen_category = normalize_category(
        category or categorize(source_path.name, label, notes)
    )
    folder = ensure_store() / CATEGORY_FOLDERS[chosen_category]
    reference_id = uuid.uuid4().hex[:12]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = folder / f"{stamp}_{reference_id}_{_safe_original_name(source_path.name)}"
    try:
        shutil.copy2(source_path, target)
    except OSError:
        return None

    record = {
        "id": reference_id,
        "name": source_path.name,
        "label": str(label or "").strip() or _label_from_name(source_path.name),
        "notes": str(notes or "").strip(),
        "category": chosen_category,
        "source": str(source or "manual"),
        "added_by": str(added_by or ""),
        "added_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "size": target.stat().st_size,
        "sha256": digest,
        "path": str(target),
    }
    records.append(record)
    save_index(records)
    return record


def scan_downloads(*, limit: int | None = None, added_by: str = "") -> list[dict]:
    ensure_store()
    try:
        candidates = [
            path
            for path in DOWNLOADS_DIR.iterdir()
            if path.is_file()
            and path.suffix.lower() in IMAGE_SUFFIXES
            and not path.name.startswith(".")
        ]
    except OSError:
        return []

    candidates.sort(
        key=lambda path: (
            0 if _GYAZO_NAME_RE.fullmatch(path.name) else 1,
            -path.stat().st_mtime,
        )
    )
    known = {str(record.get("sha256") or "") for record in load_index()}
    known |= load_blocked_hashes()
    added: list[dict] = []
    for candidate in candidates:
        try:
            digest = _sha256(candidate)
        except OSError:
            continue
        if digest in known:
            continue
        record = add_reference(
            candidate,
            label=_label_from_name(candidate.name),
            source="downloads",
            added_by=added_by,
        )
        if record is not None:
            added.append(record)
            known.add(str(record.get("sha256") or ""))
        if limit is not None and len(added) >= limit:
            break
    return added


def get_reference(reference_id: str) -> dict | None:
    return next(
        (
            record
            for record in load_index()
            if record.get("id") == reference_id and reference_path(record) is not None
        ),
        None,
    )


def grouped_references(limit: int = 500) -> dict[str, list[dict]]:
    records = find_references(limit=limit)
    groups = {category: [] for category in CATEGORY_LABELS}
    for record in records:
        category = str(record.get("category") or "object")
        groups.setdefault(category, []).append(record)
    return groups


def find_references(
    query: str = "",
    *,
    category: str = "",
    limit: int = 20,
) -> list[dict]:
    records = [record for record in load_index() if reference_path(record) is not None]
    wanted = normalize_category(category) if category else ""
    if wanted:
        records = [record for record in records if record.get("category") == wanted]
    tokens = [token for token in re.findall(r"[a-z0-9]+", str(query or "").lower()) if token]
    if tokens:
        scored: list[tuple[int, dict]] = []
        for record in records:
            haystack = " ".join(
                str(record.get(key) or "")
                for key in ("label", "notes", "name", "category", "source")
            ).lower()
            score = sum(1 for token in tokens if token in haystack)
            if score:
                scored.append((score, record))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        records = [record for _, record in scored]
    return records[: max(1, int(limit))]


def update_reference(
    reference_id: str,
    *,
    category: str | None = None,
    label: str | None = None,
    notes: str | None = None,
) -> dict | None:
    records = load_index()
    record = next((item for item in records if item.get("id") == reference_id), None)
    if record is None:
        return None

    if category is not None:
        chosen = normalize_category(category)
        old_path = reference_path(record)
        if old_path is not None:
            target_dir = ensure_store() / CATEGORY_FOLDERS[chosen]
            target = target_dir / old_path.name
            if old_path.parent != target_dir:
                try:
                    shutil.move(str(old_path), str(target))
                    record["path"] = str(target)
                except OSError:
                    pass
        record["category"] = chosen
    if label is not None:
        record["label"] = str(label).strip() or _label_from_name(str(record.get("name") or ""))
    if notes is not None:
        record["notes"] = str(notes).strip()
    record["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_index(records)
    return record


def delete_reference(reference_id: str) -> bool:
    records = load_index()
    record = next((item for item in records if item.get("id") == reference_id), None)
    if record is None:
        return False
    path = reference_path(record)
    if path is not None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    save_index([item for item in records if item.get("id") != reference_id])
    digest = str(record.get("sha256") or "").strip().lower()
    if digest:
        blocked = load_blocked_hashes()
        blocked.add(digest)
        save_blocked_hashes(blocked)
    return True
