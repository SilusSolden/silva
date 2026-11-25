"""Backup and restore Silva codebase for safe terminal updates."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from silva.config import CONFIG_DIR
from silva.dev.update_scanner import SILVA_PACKAGE_DIR
from silva.logger import log_info

PROJECT_ROOT = SILVA_PACKAGE_DIR.parent
BACKUP_ROOT = CONFIG_DIR / "backups" / "codebase"
PRODUCTION_DIR = BACKUP_ROOT / "production"
STAGING_DIR = BACKUP_ROOT / "staging"
SNAPSHOTS_DIR = BACKUP_ROOT / "snapshots"
META_FILE = BACKUP_ROOT / "backup_meta.json"

PROJECT_ITEMS = ("silva", "tests", "main.py", "requirements.txt", "run.bat", "silva-system-panel.bat")


def _ignore(_dir: str, names: list[str]) -> set[str]:
    ignored = {"__pycache__", ".git", ".pytest_cache", ".mypy_cache"}
    return {name for name in names if name in ignored or name.endswith(".pyc")}


def _remove_path(path: Path) -> None:
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


def _copy_item(src: Path, dest: Path) -> None:
    if src.is_dir():
        _remove_path(dest)
        shutil.copytree(src, dest, ignore=_ignore)
    elif src.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        _remove_path(dest)
        shutil.copy2(src, dest)


def copy_project_to(target: Path) -> None:
    """Copy the Silva project into target, replacing any previous backup safely on Windows."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    temp = target.parent / f".{target.name}.tmp-{stamp}"
    _remove_path(temp)
    temp.mkdir(parents=True, exist_ok=True)
    try:
        for item in PROJECT_ITEMS:
            _copy_item(PROJECT_ROOT / item, temp / item)
        _remove_path(target)
        temp.rename(target)
    except Exception:
        _remove_path(temp)
        raise
    finally:
        if temp.exists():
            _remove_path(temp)


def create_snapshot(*, label: str = "pre-update") -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    snapshot = SNAPSHOTS_DIR / f"{stamp}-{label}"
    copy_project_to(snapshot)
    meta = _load_meta()
    meta["latest_snapshot"] = str(snapshot)
    meta["snapshots"] = ([str(snapshot)] + meta.get("snapshots", []))[:10]
    _save_meta(meta)
    log_info(f"Codebase snapshot saved: {snapshot}")
    return snapshot


def sync_production_backup() -> Path:
    copy_project_to(PRODUCTION_DIR)
    meta = _load_meta()
    meta["production_updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _save_meta(meta)
    log_info("Production codebase backup refreshed.")
    return PRODUCTION_DIR


def sync_staging_copy() -> Path:
    copy_project_to(STAGING_DIR)
    meta = _load_meta()
    meta["staging_updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _save_meta(meta)
    log_info("Staging codebase copy refreshed.")
    return STAGING_DIR


def restore_from_path(source: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(f"Backup not found: {source}")
    for item in PROJECT_ITEMS:
        src = source / item
        dest = PROJECT_ROOT / item
        if src.is_dir():
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            shutil.copytree(src, dest, ignore=_ignore)
        elif src.exists():
            _copy_item(src, dest)


def restore_production() -> Path:
    restore_from_path(PRODUCTION_DIR)
    log_info("Restored Silva codebase from production backup.")
    return PRODUCTION_DIR


def restore_latest_snapshot() -> Path:
    meta = _load_meta()
    latest = str(meta.get("latest_snapshot", "")).strip()
    if not latest:
        raise FileNotFoundError("No snapshot backup found.")
    path = Path(latest)
    restore_from_path(path)
    log_info(f"Restored Silva codebase from snapshot {path.name}.")
    return path


def backup_paths_summary() -> str:
    meta = _load_meta()
    lines = [
        f"Production backup: {PRODUCTION_DIR}",
        f"Staging copy: {STAGING_DIR}",
    ]
    latest = meta.get("latest_snapshot")
    if latest:
        lines.append(f"Latest snapshot: {latest}")
    return "\n".join(lines)


def _load_meta() -> dict:
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    if not META_FILE.exists():
        return {}
    try:
        data = json.loads(META_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_meta(meta: dict) -> None:
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    META_FILE.write_text(json.dumps(meta, indent=2), encoding="utf-8")
