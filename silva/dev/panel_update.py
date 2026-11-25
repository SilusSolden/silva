"""Scan and publish manual changes from the Silva System Panel."""

from __future__ import annotations

from dataclasses import dataclass, field

from silva.config import load_config
from silva.dev.paths import APPLIED_UPDATE_FILE, SPEECH_TRAINING_FILE
from silva.dev.speech_training import load_speech_training
from silva.dev.update_scanner import (
    compute_code_fingerprint,
    load_installed_manifest,
    publish_update_manifest,
)
from silva.users.manager import get_active_user
from silva.users.profile_access import can_open_control_panel


@dataclass
class PanelChangeScan:
    has_changes: bool = False
    changes: list[str] = field(default_factory=list)
    features: list[str] = field(default_factory=list)
    code_changed: bool = False
    features_changed: bool = False
    training_changed: bool = False
    config_changed: bool = False


def panel_update_user() -> dict:
    return get_active_user()


def can_publish_system_update(user: dict | None = None) -> bool:
    from silva.users.admin_access import is_capability_enabled

    user = user or panel_update_user()
    return can_open_control_panel(user) and is_capability_enabled(user, "publish_updates")


def owner_quick_update_enabled() -> bool:
    return bool(load_config().get("system_panel_owner_quick_update", True))


def _training_signature(training: dict | None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    data = training if isinstance(training, dict) else {}
    say = tuple(
        sorted(
            str(item).strip().lower()
            for item in data.get("say_phrases", [])
            if str(item).strip()
        )
    )
    dont = tuple(
        sorted(
            str(item).strip().lower()
            for item in data.get("dont_say_phrases", [])
            if str(item).strip()
        )
    )
    return say, dont


def scan_panel_changes(*, features: list[str] | None = None) -> PanelChangeScan:
    """Compare local edits against the last applied Silva update."""
    config = load_config()
    feature_list = features or list(config.get("universal_features", []))
    installed = load_installed_manifest()
    applied: dict = {}
    if APPLIED_UPDATE_FILE.exists():
        try:
            import json

            applied = json.loads(APPLIED_UPDATE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            applied = {}

    scan = PanelChangeScan(features=feature_list)
    current_fp = compute_code_fingerprint()
    installed_fp = str(installed.get("fingerprint") or applied.get("fingerprint") or "")
    if current_fp and current_fp != installed_fp:
        scan.code_changed = True
        from silva.dev.update_scanner import describe_code_change, diff_code_files

        previous_files = applied.get("files") or installed.get("files") or {}
        diff = diff_code_files(previous_files if isinstance(previous_files, dict) else {})
        code_lines: list[str] = []
        for rel in diff["added"]:
            line = describe_code_change(rel, kind="added")
            if line:
                code_lines.append(line)
        for rel in diff["modified"]:
            line = describe_code_change(rel, kind="modified")
            if line:
                code_lines.append(line)
        if not code_lines:
            code_lines.append("Silva code was patched (bug fixes and command updates).")
        if len(code_lines) > 12:
            extra = len(code_lines) - 12
            code_lines = code_lines[:12]
            code_lines.append(f"Plus {extra} more code files.")
        scan.changes.extend(code_lines)

    from silva.users.features import normalize_feature_key

    def _norm_feature_names(items: list) -> set[str]:
        names: set[str] = set()
        for item in items:
            key = normalize_feature_key(str(item))
            names.add(key or str(item).strip().lower())
        return names

    installed_features = [str(item) for item in (installed.get("features") or applied.get("features") or [])]
    current_names = _norm_feature_names(feature_list)
    installed_names = _norm_feature_names(installed_features)
    if current_names != installed_names:
        scan.features_changed = True
        added = sorted(current_names - installed_names)
        removed = sorted(installed_names - current_names)
        if added:
            scan.changes.append("Features added: " + ", ".join(added))
        if removed:
            scan.changes.append("Features removed: " + ", ".join(removed))
        if not added and not removed:
            scan.changes.append("Feature list reordered or edited.")

    current_training = load_speech_training()
    applied_training = applied.get("speech_training") if isinstance(applied.get("speech_training"), dict) else {}
    if SPEECH_TRAINING_FILE.exists() and _training_signature(current_training) != _training_signature(
        applied_training
    ):
        say_count = len(current_training.get("say_phrases", []))
        dont_count = len(current_training.get("dont_say_phrases", []))
        scan.training_changed = True
        scan.changes.append(f"Speech training updated ({say_count} say / {dont_count} don't-say phrases).")

    config_features = list(config.get("universal_features", []))
    if _norm_feature_names(config_features) != installed_names and not scan.features_changed:
        scan.config_changed = True
        scan.changes.append("Config feature flags differ from the last live update.")

    scan.has_changes = bool(scan.changes) or scan.code_changed or scan.features_changed or scan.training_changed
    if not scan.changes and scan.has_changes:
        scan.changes.append("Manual changes detected and ready to publish.")
    if not scan.has_changes:
        scan.changes.append("No manual changes detected since the last update.")
    return scan


def format_scan_report(scan: PanelChangeScan) -> str:
    lines = ["=== Silva change scan ==="]
    for item in scan.changes:
        lines.append(f"- {item}")
    if scan.has_changes:
        lines.append("")
        if scan.code_changed:
            lines.append("These are patches and features already in the folder. Click Update Silva to load them while Silva keeps running.")
        else:
            lines.append("Ready to publish with Update Silva.")
    return "\n".join(lines)


def publish_panel_update(
    *,
    features: list[str],
    changelog: list[str] | None = None,
) -> tuple[dict, PanelChangeScan]:
    scan = scan_panel_changes(features=features)
    merged = list(changelog or [])
    for item in scan.changes:
        if item not in merged and not item.startswith("No manual"):
            merged.append(item)
    if not merged:
        merged = ["Manual update pushed from the Silva System Panel."]

    manifest = publish_update_manifest(features=features, changelog=merged)
    return manifest, scan
