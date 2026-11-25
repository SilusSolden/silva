from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from silva.dev.github_updates import latest_release_manifest
from silva.dev.paths import APPLIED_UPDATE_FILE, PENDING_UPDATE_FILE, RELOAD_FLAG_FILE, ensure_dev_dir
from silva.dev.update_scanner import (
    compute_code_fingerprint,
    describe_code_change,
    diff_code_files,
    fetch_remote_manifest,
    load_bundled_manifest,
    load_installed_manifest,
    version_newer,
)


@dataclass
class UpdateStatus:
    needs_update: bool = False
    current_version: str = "0.0.0"
    available_version: str = "0.0.0"
    source: str = ""
    reason: str = "current"
    changes: list[str] = field(default_factory=list)
    features: list[str] = field(default_factory=list)
    fingerprint_changed: bool = False
    pending_reload: bool = False
    manifest: dict = field(default_factory=dict)


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _candidate_manifests() -> list[tuple[str, dict]]:
    from silva.dev.paths import PUBLISHED_MANIFEST_FILE

    candidates: list[tuple[str, dict]] = []
    bundled = load_bundled_manifest()
    if bundled:
        candidates.append(("bundled", bundled))
    published = _read_json(PUBLISHED_MANIFEST_FILE)
    if published:
        candidates.append(("published", published))
    remote = fetch_remote_manifest()
    if remote:
        candidates.append(("remote", remote))
    github = latest_release_manifest()
    if github:
        candidates.append(("github", github))
    return candidates


def _best_manifest(candidates: list[tuple[str, dict]], installed_version: str) -> tuple[str, dict, str]:
    best_source = ""
    best_manifest: dict = {}
    best_version = installed_version
    for source, manifest in candidates:
        version = str(manifest.get("version") or "").strip()
        if not version or not version_newer(version, best_version):
            continue
        best_source = source
        best_manifest = manifest
        best_version = version
    if not best_manifest:
        for source, manifest in candidates:
            if manifest:
                return source, manifest, str(manifest.get("version") or installed_version)
    return best_source, best_manifest, best_version


def check_update_status() -> UpdateStatus:
    ensure_dev_dir()
    installed = load_installed_manifest()
    current_version = str(installed.get("version") or load_bundled_manifest().get("version") or "0.0.0")
    current_fp = compute_code_fingerprint()
    installed_fp = str(installed.get("fingerprint") or "")
    applied = _read_json(APPLIED_UPDATE_FILE)
    previous_files = applied.get("files") or installed.get("files") or {}
    file_diff = diff_code_files(previous_files) if previous_files else {}
    changed_files = [
        item for key in ("added", "removed", "modified") for item in (file_diff.get(key) or [])
    ]
    source, manifest, candidate_version = _best_manifest(_candidate_manifests(), current_version)
    candidate_fp = str(manifest.get("fingerprint") or "")
    fingerprint_changed = bool(
        (installed_fp and current_fp != installed_fp)
        or (candidate_fp and current_fp != candidate_fp)
        or changed_files
    )
    version_newer_available = version_newer(candidate_version, current_version)
    manifest_changed = bool(
        candidate_fp != installed_fp
        or (manifest.get("changelog") or []) != (installed.get("changelog") or [])
        or set(manifest.get("features") or []) != set(installed.get("features") or [])
    )
    pending = RELOAD_FLAG_FILE.exists() or PENDING_UPDATE_FILE.exists()

    changes: list[str] = []
    for item in manifest.get("changelog") or []:
        text = str(item).strip()
        if text:
            changes.append(text)
    for rel in changed_files:
        kind = "modified"
        for key in ("added", "removed"):
            if rel in (file_diff.get(key) or []):
                kind = key
                break
        line = describe_code_change(rel, kind=kind)
        if line:
            changes.append(line)
    changes = list(dict.fromkeys(changes))[:12]

    if fingerprint_changed:
        return UpdateStatus(
            needs_update=True,
            current_version=current_version,
            available_version=candidate_version or current_version,
            source=source or "local_files",
            reason="code_changed",
            changes=changes or ["Silva code files changed since the last update."],
            features=[str(item) for item in (manifest.get("features") or installed.get("features") or [])],
            fingerprint_changed=True,
            pending_reload=pending,
            manifest=manifest,
        )
    if version_newer_available and manifest_changed:
        return UpdateStatus(
            needs_update=True,
            current_version=current_version,
            available_version=candidate_version,
            source=source or "manifest",
            reason="manifest_changed",
            changes=changes or ["Updated Silva features and patches."],
            features=[str(item) for item in (manifest.get("features") or [])],
            pending_reload=pending,
            manifest=manifest,
        )

    return UpdateStatus(
        needs_update=False,
        current_version=current_version,
        available_version=candidate_version or current_version,
        source=source,
        reason="version_only" if version_newer_available else "current",
        changes=[],
        features=[str(item) for item in (installed.get("features") or [])],
        pending_reload=pending,
        manifest=manifest,
    )


def needs_update() -> bool:
    return check_update_status().needs_update


def format_status_message(status: UpdateStatus | None = None) -> str:
    status = status or check_update_status()
    if status.needs_update:
        lead = f"Update {status.available_version} is ready."
        if status.changes:
            lead += " " + " ".join(status.changes[:3])
        return lead + " Say yes update to confirm."
    if status.reason == "version_only":
        return f"Already on the newest update, {status.available_version}. No new files were added."
    return f"Already on the newest update, {status.current_version}."


def main() -> None:
    status = check_update_status()
    print(format_status_message(status))
    print(f"installed={status.current_version} available={status.available_version} source={status.source or 'none'}")
    print(f"needs_update={str(status.needs_update).lower()} reason={status.reason}")


if __name__ == "__main__":
    main()
