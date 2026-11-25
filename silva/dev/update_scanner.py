"""Detect Silva updates from local files, bundled manifest, and optional remote manifest."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from silva import __version__
from silva.config import load_config
from silva.dev.paths import (
    INSTALLED_MANIFEST_FILE,
    PENDING_UPDATE_FILE,
    PUBLISHED_MANIFEST_FILE,
    RELOAD_FLAG_FILE,
    ensure_dev_dir,
)
from silva.logger import log_error, log_info

SILVA_PACKAGE_DIR = Path(__file__).resolve().parents[1]
BUNDLED_MANIFEST_FILE = SILVA_PACKAGE_DIR / "release_manifest.json"
LOCAL_PUBLISH_MANIFEST = PUBLISHED_MANIFEST_FILE


def _parse_version(value: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", str(value or "0"))
    if not parts:
        return (0,)
    return tuple(int(part) for part in parts)


def version_newer(left: str, right: str) -> bool:
    return _parse_version(left) > _parse_version(right)


@dataclass
class UpdateScanResult:
    available: bool = False
    version: str = __version__
    installed_version: str = "0.0.0"
    source: str = ""
    changes: list[str] = field(default_factory=list)
    features: list[str] = field(default_factory=list)
    pending_reload: bool = False
    manifest: dict = field(default_factory=dict)


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def compute_code_fingerprint(*, root: Path | None = None) -> str:
    base = root or SILVA_PACKAGE_DIR
    digest = hashlib.sha256()
    py_files = sorted(base.rglob("*.py"))
    for path in py_files:
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(base).as_posix().encode("utf-8")
        digest.update(rel)
        try:
            digest.update(path.read_bytes())
        except OSError:
            continue
    return digest.hexdigest()[:16]


def list_code_files(*, root: Path | None = None) -> list[Path]:
    base = root or SILVA_PACKAGE_DIR
    return [
        path
        for path in sorted(base.rglob("*.py"))
        if "__pycache__" not in path.parts
    ]


def code_file_hashes(*, root: Path | None = None) -> dict[str, str]:
    base = root or SILVA_PACKAGE_DIR
    hashes: dict[str, str] = {}
    for path in list_code_files(root=base):
        rel = path.relative_to(base).as_posix()
        try:
            hashes[rel] = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
        except OSError:
            continue
    return hashes


def describe_code_change(rel: str, *, kind: str) -> str | None:
    """Human scan line for a changed Python file. Skips tests."""
    posix = rel.replace("\\", "/")
    if "/test_" in f"/{posix}" or posix.startswith("test_") or "/tests/" in f"/{posix}":
        return None
    stem = Path(posix).stem.replace("_", " ")
    if kind == "added":
        if "phrases" in posix or "handler" in posix or "popup" in posix or "dialog" in posix:
            return f"New feature: {stem} ({posix})"
        return f"New module: {stem} ({posix})"
    if kind == "removed":
        return f"Removed: {stem} ({posix})"
    return f"Patch: {stem} ({posix})"


def diff_code_files(previous: dict | None = None, *, root: Path | None = None) -> dict[str, list[str]]:
    current = code_file_hashes(root=root)
    old = previous if isinstance(previous, dict) else {}
    if not old:
        return {"added": [], "removed": [], "modified": [], "hashes": current}
    added = sorted(set(current) - set(old))
    removed = sorted(set(old) - set(current))
    modified = sorted(path for path in current if path in old and current[path] != old[path])
    return {"added": added, "removed": removed, "modified": modified, "hashes": current}


def load_installed_manifest() -> dict:
    ensure_dev_dir()
    manifest = _read_json(INSTALLED_MANIFEST_FILE)
    if manifest:
        return manifest
    return {
        "version": "0.0.0",
        "applied_at": "",
        "features": [],
        "fingerprint": "",
        "changelog": [],
    }


def save_installed_manifest(manifest: dict) -> None:
    ensure_dev_dir()
    payload = dict(manifest)
    payload["applied_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _write_json(INSTALLED_MANIFEST_FILE, payload)


def load_bundled_manifest() -> dict:
    manifest = _read_json(BUNDLED_MANIFEST_FILE)
    if manifest:
        return manifest
    return {
        "version": __version__,
        "features": load_config().get("universal_features", []),
        "changelog": [],
        "fingerprint": compute_code_fingerprint(),
    }


def fetch_remote_manifest() -> dict:
    url = str(load_config().get("update_manifest_url", "")).strip()
    if not url:
        return {}
    try:
        with urlopen(url, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except (URLError, TimeoutError, json.JSONDecodeError, OSError, ValueError) as exc:
        log_error("Remote update manifest fetch failed", exc=exc)
        return {}


def _manifest_changes(candidate: dict, installed: dict) -> list[str]:
    changes: list[str] = []
    for item in candidate.get("changelog", []):
        text = str(item).strip()
        if text:
            changes.append(text)

    installed_features = set(installed.get("features") or [])
    candidate_features = set(candidate.get("features") or [])
    added = sorted(candidate_features - installed_features)
    if added:
        changes.append("New features: " + ", ".join(added))

    if candidate.get("fingerprint") and candidate.get("fingerprint") != installed.get("fingerprint"):
        if not any("code" in item.lower() for item in changes):
            changes.append("Updated Silva code and command modules.")

    if RELOAD_FLAG_FILE.exists() or PENDING_UPDATE_FILE.exists():
        if not any("live update" in item.lower() for item in changes):
            changes.append("Live update queued by owner or admin.")

    if not changes:
        changes.append("Silva update is ready to install.")
    return changes[:12]


def _pick_candidate_manifests() -> list[tuple[str, dict]]:
    candidates: list[tuple[str, dict]] = []
    bundled = load_bundled_manifest()
    if bundled:
        candidates.append(("bundled", bundled))
    published = _read_json(LOCAL_PUBLISH_MANIFEST)
    if published:
        candidates.append(("published", published))
    remote = fetch_remote_manifest()
    if remote:
        candidates.append(("remote", remote))

    current_fp = compute_code_fingerprint()
    live = {
        "version": bundled.get("version", __version__),
        "features": load_config().get("universal_features", []),
        "changelog": ["Local Silva files changed since last update."],
        "fingerprint": current_fp,
    }
    candidates.append(("local_files", live))
    return candidates


def bootstrap_installed_manifest_if_needed() -> None:
    """First run — record the bundled version so users are not prompted immediately."""
    ensure_dev_dir()
    if INSTALLED_MANIFEST_FILE.exists():
        return
    bundled = load_bundled_manifest()
    save_installed_manifest(
        {
            "version": str(bundled.get("version", __version__)),
            "features": bundled.get("features") or load_config().get("universal_features", []),
            "fingerprint": bundled.get("fingerprint") or compute_code_fingerprint(),
            "changelog": bundled.get("changelog") or [],
        }
    )


def sync_installed_manifest_current() -> None:
    """Mark the running Silva install as current — used on the main owner system."""
    bundled = load_bundled_manifest()
    save_installed_manifest(
        {
            "version": str(bundled.get("version", __version__)),
            "features": bundled.get("features") or load_config().get("universal_features", []),
            "fingerprint": compute_code_fingerprint(),
            "changelog": bundled.get("changelog") or [],
        }
    )


def mark_update_applied(*, manifest: dict | None = None) -> dict:
    """Record the current codebase as fully published/applied after an owner update."""
    from silva.dev.paths import APPLIED_UPDATE_FILE
    from silva.dev.speech_training import load_speech_training

    ensure_dev_dir()
    bundled = manifest or load_bundled_manifest()
    current_fp = compute_code_fingerprint()
    files = code_file_hashes()
    payload = {
        "version": str(bundled.get("version", __version__)),
        "features": bundled.get("features") or load_config().get("universal_features", []),
        "fingerprint": current_fp,
        "files": files,
        "changelog": bundled.get("changelog") or [],
        "speech_training": load_speech_training(),
    }
    save_installed_manifest(payload)
    applied = {
        "applied_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "features": payload["features"],
        "fingerprint": payload["fingerprint"],
        "files": files,
        "speech_training": payload["speech_training"],
    }
    _write_json(APPLIED_UPDATE_FILE, applied)
    return payload


def scan_for_updates() -> UpdateScanResult:
    bootstrap_installed_manifest_if_needed()
    installed = load_installed_manifest()
    installed_version = str(installed.get("version", "0.0.0"))
    pending_reload = RELOAD_FLAG_FILE.exists() or PENDING_UPDATE_FILE.exists()

    best_source = ""
    best_manifest: dict = {}
    best_version = installed_version

    for source, manifest in _pick_candidate_manifests():
        if source == "local_files":
            continue
        version = str(manifest.get("version", __version__))
        newer = version_newer(version, best_version)
        if newer:
            best_source = source
            best_manifest = manifest
            best_version = version

    if pending_reload and not best_manifest:
        bundled = load_bundled_manifest()
        best_source = "pending"
        best_manifest = bundled
        best_version = str(bundled.get("version", __version__))

    available = pending_reload or version_newer(best_version, installed_version)

    if not available:
        return UpdateScanResult(
            available=False,
            version=installed_version,
            installed_version=installed_version,
            source="",
            changes=[],
            features=list(installed.get("features") or []),
            pending_reload=pending_reload,
        )

    changes = _manifest_changes(best_manifest, installed)
    features = best_manifest.get("features")
    if not isinstance(features, list):
        features = installed.get("features") or load_config().get("universal_features", [])

    return UpdateScanResult(
        available=True,
        version=str(best_manifest.get("version", best_version)),
        installed_version=installed_version,
        source=best_source or "pending",
        changes=changes,
        features=[str(item) for item in features],
        pending_reload=pending_reload,
        manifest=best_manifest,
    )


def publish_update_manifest(
    *,
    features: list[str] | None = None,
    changelog: list[str] | None = None,
    bump_patch: bool = True,
) -> dict:
    """Owner/admin push — record a release other Silva installs can detect."""
    ensure_dev_dir()
    current = load_bundled_manifest()
    version = str(current.get("version", __version__))
    live_fingerprint = compute_code_fingerprint()
    installed = load_installed_manifest()
    if bump_patch and installed.get("fingerprint") == live_fingerprint:
        log_info(f"No update published; Silva is already current at {version}.")
        return current
    if bump_patch:
        parts = list(_parse_version(version))
        if not parts:
            parts = [0, 1, 0]
        parts[-1] += 1
        version = ".".join(str(part) for part in parts)

    config = load_config()
    manifest = {
        "version": version,
        "released_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "features": features or config.get("universal_features", []),
        "changelog": changelog
        or [
            "Owner pushed a live update.",
            "Speech training and feature access refreshed.",
        ],
        "fingerprint": live_fingerprint,
    }

    _write_json(LOCAL_PUBLISH_MANIFEST, manifest)
    try:
        _write_json(BUNDLED_MANIFEST_FILE, manifest)
    except OSError:
        pass

    try:
        from silva.dev.whats_new_script import write_release_note

        write_release_note(
            version,
            changelog=[str(item) for item in (manifest.get("changelog") or [])],
            features=[str(item) for item in (manifest.get("features") or [])],
            fingerprint=str(manifest.get("fingerprint") or ""),
            released_at=str(manifest.get("released_at") or ""),
        )
    except Exception as exc:
        log_error("Could not record release notes", exc=exc)

    log_info(f"Published Silva update manifest {version}")
    return manifest
