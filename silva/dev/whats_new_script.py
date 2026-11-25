"""Scan recently added Silva files so what's-new and update speak the current delta."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from silva.dev.paths import (
    APPLIED_UPDATE_FILE,
    RELEASE_NOTES_DIR,
    WHATS_NEW_STATE_FILE,
    ensure_dev_dir,
)
from silva.dev.update_scanner import (
    code_file_hashes,
    load_bundled_manifest,
    load_installed_manifest,
    version_newer,
)


@dataclass
class WhatsNewReport:
    spoken: str
    version: str = ""
    files: list[str] = field(default_factory=list)
    items: list[str] = field(default_factory=list)
    pending: bool = False
    nothing_new: bool = False
    hashes: dict[str, str] = field(default_factory=dict)


@dataclass
class UpdateStatusReport:
    current_version: str = ""
    newest_version: str = ""
    up_to_date: bool = False
    items: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    applied_version: str = ""
    applied_at: str = ""


def _is_test_path(posix: str) -> bool:
    posix = str(posix or "").replace("\\", "/")
    return (
        "/test_" in f"/{posix}"
        or posix.startswith("test_")
        or "/tests/" in posix
        or posix.endswith("/conftest.py")
    )


def _normalize(posix: str) -> str:
    posix = str(posix or "").replace("\\", "/").lstrip("/")
    if posix.startswith("silva/"):
        posix = posix[len("silva/") :]
    return posix


def _read_json(path: Path) -> dict:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return {}


_SEEDED_RELEASE_NOTES: dict[str, dict] = {
    "0.1.99": {
        "released_at": "2026-11-24 00:33:55",
        "features": ["weather", "math"],
        "changelog": [
            "quiet sleep-mode daily routines that wait after wake before showing news and weather",
            "reply attitudes that shift from shy and skittish to sassy and blunt while still doing the work",
        ],
        "fingerprint": "9c5981c062b0db2c",
        "applied": True,
    },
    "0.1.101": {
        "released_at": "2026-11-24 19:35:00",
        "features": ["weather", "math", "image_generation"],
        "changelog": [
            "GPU image generation with automatic CUDA detection and RTX VRAM checks",
            "image generation status, test, and popup controls driven by voice and GUI",
        ],
        "fingerprint": "d79c87d4f2453c00",
        "applied": False,
    },
    "0.1.102": {
        "released_at": "2026-11-24 20:46:42",
        "features": ["weather", "math", "image_generation"],
        "changelog": [
            "Phrase recorder now opens on the shared display host without blocking the command loop",
            "centered the phrase recorder on the launch monitor and added non-blocking open logging",
        ],
        "fingerprint": "e15d0241551917a3",
        "applied": False,
    },
}


def _release_notes_dir() -> Path:
    path = Path(RELEASE_NOTES_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _release_note_path(version: str) -> Path:
    safe = re.sub(r"[^0-9A-Za-z_.-]+", "_", str(version or "").strip())
    return _release_notes_dir() / f"{safe or 'unknown'}.json"


def write_release_note(
    version: str,
    *,
    changelog: list[str] | None = None,
    features: list[str] | None = None,
    fingerprint: str = "",
    files: list[str] | dict | None = None,
    applied: bool = False,
    released_at: str = "",
) -> dict:
    version = str(version or "").strip()
    if not version:
        return {}
    path = _release_note_path(version)
    existing = _read_json(path)
    items = _display_items([str(item) for item in (changelog or [])])
    old_items = [str(item) for item in (existing.get("changelog") or [])]
    payload = {
        **existing,
        "version": version,
        "released_at": released_at or str(existing.get("released_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        "features": list(dict.fromkeys([str(item) for item in (features or existing.get("features") or [])])),
        "changelog": list(dict.fromkeys(old_items + items)),
        "fingerprint": str(fingerprint or existing.get("fingerprint") or ""),
        "files": dict(files) if isinstance(files, dict) else list(dict.fromkeys([str(item) for item in (files or existing.get("files") or [])])),
        "applied": bool(applied or existing.get("applied", False)),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if applied:
        payload["applied_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def seed_release_notes() -> None:
    for version, payload in _SEEDED_RELEASE_NOTES.items():
        path = _release_note_path(version)
        if path.exists():
            continue
        write_release_note(
            version,
            changelog=list(payload.get("changelog") or []),
            features=list(payload.get("features") or []),
            fingerprint=str(payload.get("fingerprint") or ""),
            released_at=str(payload.get("released_at") or ""),
            applied=bool(payload.get("applied", False)),
        )


def load_release_note(version: str) -> dict:
    version = str(version or "").strip()
    if not version:
        return {}
    return _read_json(_release_note_path(version))


def list_release_notes() -> list[dict]:
    seed_release_notes()
    notes: list[dict] = []
    for path in sorted(_release_notes_dir().glob("*.json")):
        data = _read_json(path)
        if str(data.get("version") or "").strip():
            notes.append(data)
    return notes


def newest_release_note() -> dict:
    best: dict = {}
    for note in list_release_notes():
        version = str(note.get("version") or "")
        if not version:
            continue
        if not best or version_newer(version, str(best.get("version") or "")):
            best = note
    return best


def newest_update_version() -> str:
    bundled = str(load_bundled_manifest().get("version") or "").strip()
    if bundled:
        return bundled
    installed = str(load_installed_manifest().get("version") or "").strip()
    notes = newest_release_note().get("version") or ""
    if installed and notes:
        return installed if version_newer(installed, notes) else notes
    return installed or notes


def verify_update_status() -> UpdateStatusReport:
    seed_release_notes()
    installed = load_installed_manifest()
    current = str(installed.get("version") or "").strip()
    newest = newest_update_version() or current
    note = load_release_note(newest)
    bundled = load_bundled_manifest()
    items = _display_items([str(item) for item in (note.get("changelog") or bundled.get("changelog") or [])])
    files = note.get("files")
    if isinstance(files, dict):
        file_list = [str(item) for item in files]
    else:
        file_list = [str(item) for item in (files or [])]
    applied = _read_json(APPLIED_UPDATE_FILE)
    applied_version = str(applied.get("version") or "").strip()
    return UpdateStatusReport(
        current_version=current,
        newest_version=newest,
        up_to_date=bool(current and current == newest),
        items=items,
        files=file_list,
        applied_version=applied_version,
        applied_at=str(applied.get("applied_at") or installed.get("applied_at") or ""),
    )


def load_state() -> dict:
    ensure_dev_dir()
    return _read_json(WHATS_NEW_STATE_FILE)


def save_state(payload: dict) -> None:
    ensure_dev_dir()
    payload = dict(payload)
    payload["saved_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    WHATS_NEW_STATE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def applied_hashes() -> dict[str, str]:
    data = _read_json(APPLIED_UPDATE_FILE)
    files = data.get("files")
    return dict(files) if isinstance(files, dict) else {}


def current_version() -> str:
    installed = load_installed_manifest()
    bundled = load_bundled_manifest()
    return str(installed.get("version") or bundled.get("version") or "").strip()


def _manifest_changelog_items(version: str = "") -> list[str]:
    wanted = str(version or "").strip()
    note_items = _display_items(
        [str(item) for item in (load_release_note(wanted).get("changelog") or [])]
    )
    if note_items:
        return note_items
    installed = load_installed_manifest()
    bundled = load_bundled_manifest()
    if wanted and str(installed.get("version") or "").strip() == wanted:
        manifest = installed
    elif wanted and str(bundled.get("version") or "").strip() == wanted:
        manifest = bundled
    else:
        manifest = installed or bundled
    changelog = manifest.get("changelog") or []
    return _display_items([str(item) for item in changelog])


def recent_files(current: dict[str, str], baseline: dict[str, str]) -> list[str]:
    """Return added or modified Python files vs a hash snapshot. Empty baseline is not the whole tree."""
    if not baseline:
        return []
    added = sorted(set(current) - set(baseline))
    modified = sorted(path for path in current if path in baseline and current[path] != baseline[path])
    return [_normalize(path) for path in added + modified if not _is_test_path(path)]


def items_for_files(files: list[str], *, limit: int = 1) -> list[str]:
    from silva.dev.auto_update import _feature_items_from_files, _normalize_rel, _why_for_path

    rels = [_normalize_rel(path) for path in files if not _is_test_path(path)]
    items = _display_items(_feature_items_from_files(rels))
    if items:
        return items[:limit]
    extras: list[str] = []
    for path in rels:
        why = _why_for_path(path)
        extras.append(why or Path(path).stem.replace("_", " "))
        if len(extras) >= limit:
            break
    return _display_items(extras)


_ITEM_REPLACEMENTS = (
    ("a shorter update summary", "clearer answers about what changed in the newest update"),
    ("shorter update summary", "clearer answers about what changed in the newest update"),
)


def _display_item(item: str) -> str:
    text = str(item or "").strip().rstrip(".")
    lowered = text.lower()
    for old, new in _ITEM_REPLACEMENTS:
        if lowered == old or lowered == f"i updated {old}":
            return new
    return text


def _display_items(items: list[str]) -> list[str]:
    cleaned = [_display_item(item) for item in items]
    return [item for item in cleaned if item]


def _one(items: list[str]) -> str:
    return _display_item(str(items[0])) if items else ""


def _signature(version: str, items: list[str], files: list[str]) -> str:
    return json.dumps({"v": version, "i": list(items), "f": list(files)[:16]}, sort_keys=True)


def _speak(
    version: str,
    items: list[str],
    files: list[str],
    *,
    pending: bool,
    technical: bool,
    detailed: bool,
    nothing_new: bool,
) -> str:
    if nothing_new:
        return f"Already on {version}." if version else "Nothing new."
    bit = _one(items)
    if bit:
        bit = bit[0].upper() + bit[1:]
    if technical:
        label = files[0].replace(".py", "").replace("/", " ") if files else "silva"
        if version:
            return f"Update {version}. Python: {label}."
        return f"Python: {label}."
    if detailed and len(items) > 1:
        extra = str(items[1]).strip().rstrip(".")
        extra = extra[0].upper() + extra[1:] if extra else ""
        body = f"{bit}. {extra}." if extra else f"{bit}."
        if pending:
            return f"Update {version} is ready. {body}".strip()
        return f"Update {version}. {body}".strip() if version else body
    if pending:
        if version and bit:
            return f"Update {version} is ready. {bit}."
        if version:
            return f"Update {version} is ready."
        return f"{bit}." if bit else "An update is ready."
    if version and bit:
        return f"Update {version}. {bit}."
    if version:
        return f"Update {version}."
    return f"{bit}." if bit else "No update notes."


def spoken_after_apply(version: str, items: list[str]) -> str:
    bit = _one(items)
    if bit:
        bit = bit[0].upper() + bit[1:]
    if version and bit:
        return f"Update {version} is live. {bit}."
    if version:
        return f"Update {version} is live."
    if bit:
        return f"The update is live. {bit}."
    return "The update is live."


def _persist(
    *,
    current: dict[str, str],
    version: str,
    files: list[str],
    items: list[str],
    last_apply: dict | None,
) -> None:
    payload = {
        "version": version,
        "hashes": current,
        "files": files,
        "items": items,
        "told_signature": _signature(version, items, files),
        "told_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "last_apply": last_apply
        or {
            "version": version,
            "files": files,
            "items": items,
        },
    }
    save_state(payload)


def record_apply_delta(
    *,
    files: list[str],
    version: str = "",
    hashes: dict[str, str] | None = None,
    changelog: list[str] | None = None,
    items: list[str] | None = None,
) -> WhatsNewReport:
    """Save the files that just went live so later what's-new asks match this apply."""
    current = dict(hashes) if hashes is not None else code_file_hashes()
    files = [_normalize(path) for path in files if not _is_test_path(path)]
    explicit = _display_items(
        [str(item) for item in (list(items or []) + list(changelog or []))]
    )
    chosen_items = explicit or items_for_files(files, limit=1)
    version = str(version or current_version()).strip()
    last_apply = {"version": version, "files": files, "items": chosen_items}
    _persist(
        current=current,
        version=version,
        files=files,
        items=chosen_items,
        last_apply=last_apply,
    )
    write_release_note(
        version,
        changelog=chosen_items,
        files=files,
        applied=True,
    )
    spoken = spoken_after_apply(version, chosen_items)
    return WhatsNewReport(
        spoken=spoken,
        version=version,
        files=files,
        items=chosen_items,
        pending=False,
        nothing_new=not bool(chosen_items),
        hashes=current,
    )


def run_whats_new_script(
    *,
    technical: bool = False,
    detailed: bool = False,
    mark_told: bool = True,
    for_apply: bool = False,
    current_hashes: dict[str, str] | None = None,
    baseline_hashes: dict[str, str] | None = None,
    version: str | None = None,
    changelog: list[str] | None = None,
) -> WhatsNewReport:
    """Diff disk hashes against the last applied / last spoken snapshot and describe only that delta."""
    current = dict(current_hashes) if current_hashes is not None else code_file_hashes()
    applied = dict(baseline_hashes) if baseline_hashes is not None else applied_hashes()
    state = load_state()
    last_apply = state.get("last_apply") if isinstance(state.get("last_apply"), dict) else {}
    from_notes = (
        not for_apply
        and current_hashes is None
        and baseline_hashes is None
        and version is None
    )
    if from_notes:
        status = verify_update_status()
        version = status.newest_version or current_version()
        note = load_release_note(version)
        items = _display_items([str(item) for item in (status.items or note.get("changelog") or [])])
        files = list(status.files)
        spoken = _speak(
            version,
            items,
            files,
            pending=not status.up_to_date,
            technical=technical,
            detailed=detailed,
            nothing_new=not bool(items),
        )
        if mark_told:
            _persist(
                current=current,
                version=version,
                files=files,
                items=items,
                last_apply=last_apply or None,
            )
        return WhatsNewReport(
            spoken=spoken,
            version=version,
            files=files,
            items=items,
            pending=not status.up_to_date,
            nothing_new=not bool(items),
            hashes=current,
        )

    version = str(version if version is not None else current_version()).strip()
    pending_files = recent_files(current, applied)
    pending = bool(pending_files)

    if for_apply or pending:
        files = pending_files
        explicit = _display_items([str(item) for item in (changelog or [])])
        items = explicit or items_for_files(files, limit=2 if detailed else 1)
        if for_apply:
            spoken = spoken_after_apply(version, items)
            if mark_told or for_apply:
                _persist(
                    current=current,
                    version=version,
                    files=files,
                    items=items,
                    last_apply={"version": version, "files": files, "items": items},
                )
        else:
            spoken = _speak(
                version,
                items,
                files,
                pending=True,
                technical=technical,
                detailed=detailed,
                nothing_new=False,
            )
            if mark_told:
                _persist(
                    current=current,
                    version=version,
                    files=files,
                    items=items,
                    last_apply=last_apply or None,
                )
        return WhatsNewReport(
            spoken=spoken,
            version=version,
            files=files,
            items=items,
            pending=pending,
            nothing_new=False,
            hashes=current,
        )

    apply_files = [_normalize(path) for path in (last_apply.get("files") or []) if str(path).strip()]
    apply_items = _display_items([str(item) for item in (last_apply.get("items") or [])])[:2]
    apply_version = str(last_apply.get("version") or version).strip()
    manifest_items = _manifest_changelog_items(apply_version or version)[:2]
    if apply_version != version:
        apply_version = version
        apply_files = []
        apply_items = manifest_items
    elif manifest_items and apply_items and not any(item in manifest_items for item in apply_items):
        apply_items = manifest_items
    elif not apply_items:
        apply_items = manifest_items
    told_hashes = state.get("hashes") if isinstance(state.get("hashes"), dict) else {}
    since_told = recent_files(current, told_hashes) if told_hashes else []
    if since_told:
        items = items_for_files(since_told, limit=2 if detailed else 1)
        spoken = _speak(
            version,
            items,
            since_told,
            pending=False,
            technical=technical,
            detailed=detailed,
            nothing_new=False,
        )
        if mark_told:
            _persist(
                current=current,
                version=version,
                files=since_told,
                items=items,
                last_apply=last_apply or {"version": version, "files": since_told, "items": items},
            )
        return WhatsNewReport(
            spoken=spoken,
            version=version,
            files=since_told,
            items=items,
            pending=False,
            nothing_new=False,
            hashes=current,
        )

    if detailed or technical:
        spoken = _speak(
            apply_version or version,
            apply_items,
            apply_files,
            pending=False,
            technical=technical,
            detailed=detailed,
            nothing_new=not bool(apply_items),
        )
        return WhatsNewReport(
            spoken=spoken,
            version=apply_version or version,
            files=apply_files,
            items=apply_items,
            pending=False,
            nothing_new=not bool(apply_items),
            hashes=current,
        )

    spoken = _speak(
        apply_version or version,
        apply_items,
        apply_files,
        pending=False,
        technical=False,
        detailed=False,
        nothing_new=not bool(apply_items),
    )
    return WhatsNewReport(
        spoken=spoken,
        version=apply_version or version,
        files=apply_files,
        items=apply_items,
        pending=False,
        nothing_new=not bool(apply_items),
        hashes=current,
    )
