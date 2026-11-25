"""Full terminal update flow — backup, scan, apply, verify, finish message."""

from __future__ import annotations

from dataclasses import dataclass, field

from silva.cache.refresh import refresh_all_caches
from silva.config import load_config
from silva.dev.auto_update import apply_available_update
from silva.dev.codebase_backup import (
    backup_paths_summary,
    create_snapshot,
    restore_production,
    sync_production_backup,
    sync_staging_copy,
)
from silva.dev.live_update import apply_pending_update, queue_live_update
from silva.dev.panel_update import (
    can_publish_system_update,
    format_scan_report,
    panel_update_user,
    scan_panel_changes,
)
from silva.dev.test_runner import run_all_tests
from silva.dev.update_scanner import mark_update_applied
from silva.logger import log_error, log_info
from silva.users.manager import get_owner
from silva.users.system_identity import is_main_owner_system


FINISH_MESSAGE = (
    "Update finished. Please check that everything is working.\n"
    "If something is wrong, type revert in this terminal to restore the last stable copy,\n"
    "or contact the owner. If the owner is unavailable, contact an admin."
)


@dataclass
class TerminalUpdateResult:
    ok: bool
    message: str
    steps: list[str] = field(default_factory=list)


def _owner_contact_line() -> str:
    from silva.dev.github_updates import repo_web_url, support_email_url

    support = support_email_url()
    page = repo_web_url()
    question_line = f" Project page: {page}." if page else ""
    if support:
        question_line += f" Questions or update paths: {support}"
    if is_main_owner_system():
        return (
            "You are on the main owner system. Type revert to restore the last production backup if needed."
            + question_line
        )
    owner = get_owner()
    name = owner.get("name", "Owner")
    return f"Contact {name} (owner) or a tier 4 admin if you need help." + question_line


def run_terminal_scan() -> TerminalUpdateResult:
    if not can_publish_system_update(panel_update_user()):
        return TerminalUpdateResult(
            ok=False,
            message="Terminal update is only available for the owner or admins.",
        )
    from silva.dev.update_check import check_update_status, format_status_message

    scan = scan_panel_changes()
    report = format_scan_report(scan)
    status = check_update_status()
    if not status.needs_update:
        return TerminalUpdateResult(
            ok=True,
            message=report + "\n\n" + format_status_message(status),
            steps=["scan"],
        )
    return TerminalUpdateResult(
        ok=True,
        message=report + "\n\n" + format_status_message(status),
        steps=["scan"],
    )


def run_terminal_update(*, force: bool = False) -> TerminalUpdateResult:
    user = panel_update_user()
    if not can_publish_system_update(user):
        return TerminalUpdateResult(
            ok=False,
            message="Terminal update is only available for the owner or admins.",
        )

    steps: list[str] = []
    lines: list[str] = ["=== Silva terminal update ==="]

    try:
        from silva.dev.update_check import check_update_status, format_status_message

        steps.append("scan")
        scan = scan_panel_changes()
        lines.append(format_scan_report(scan))
        status = check_update_status()
        lines.append("\n" + format_status_message(status))
        if not status.needs_update and not force:
            return TerminalUpdateResult(ok=True, message="\n".join(lines), steps=steps)

        if bool(load_config().get("terminal_update_backup_enabled", True)):
            steps.append("backup")
            snapshot = create_snapshot(label="pre-update")
            sync_production_backup()
            lines.append(f"\nBackup saved: {snapshot.name}")
            lines.append("Production copy preserved for normal use / revert.")

            steps.append("staging")
            staging = sync_staging_copy()
            lines.append(f"Staging copy ready for testing: {staging}")

        steps.append("apply")
        features = list(load_config().get("universal_features", []))
        from silva.dev.live_update import apply_code_to_running_assistant
        from silva.dev.update_scanner import load_bundled_manifest

        ok, apply_message = apply_code_to_running_assistant()
        if not ok:
            queue_live_update(features=features)
            ok, apply_message = apply_pending_update()
        if not ok:
            ok, apply_message, _ = apply_available_update(
                publish=True,
                features=features,
                skip_tests=True,
            )
        try:
            from silva.dev.runtime_hooks import safe_install_runtime_hooks

            safe_install_runtime_hooks()
        except Exception as exc:
            log_error("Terminal update could not rebind live command handlers", exc=exc)
        manifest = load_bundled_manifest()
        lines.append(f"\nLive update: {apply_message}")
        lines.append(f"Published version: {manifest.get('version', 'unknown')}")

        steps.append("verify")
        lines.append("\nRe-scanning and running checks...")
        verify_scan = scan_panel_changes(features=features)
        test_result = run_all_tests(include_unit_tests=True)
        lines.append(format_scan_report(verify_scan))
        if test_result.passed:
            lines.append(f"\nChecks passed ({test_result.tests_run} unit tests).")
        else:
            lines.append("\nChecks failed after update:")
            lines.extend(f"- {item}" for item in test_result.broken_items[:8])
            lines.append("\nYou can type revert to restore the last production backup.")
            lines.append(_owner_contact_line())
            return TerminalUpdateResult(ok=False, message="\n".join(lines), steps=steps)

        steps.append("promote")
        if bool(load_config().get("terminal_update_backup_enabled", True)):
            sync_production_backup()
            lines.append("\nProduction backup updated to the new stable version.")

        mark_update_applied(manifest=manifest)

        try:
            refresh_all_caches(force=True)
            lines.append("Caches refreshed.")
        except Exception as exc:
            log_error("Cache refresh after terminal update failed", exc=exc)

        steps.append("done")
        lines.append("\n" + FINISH_MESSAGE)
        lines.append(_owner_contact_line())
        if scan.code_changed:
            lines.append(
                "\nCode patches were loaded into the running assistant. Keep talking — no restart needed unless voice still sounds off."
            )
        log_info("Terminal update completed successfully.")
        return TerminalUpdateResult(ok=True, message="\n".join(lines), steps=steps)
    except Exception as exc:
        log_error("Terminal update failed", exc=exc)
        lines.append(f"\nUpdate failed: {exc}")
        lines.append("Type revert to restore the last production backup if needed.")
        lines.append(_owner_contact_line())
        return TerminalUpdateResult(ok=False, message="\n".join(lines), steps=steps)


def run_terminal_revert() -> TerminalUpdateResult:
    if not can_publish_system_update(panel_update_user()):
        return TerminalUpdateResult(
            ok=False,
            message="Revert is only available for the owner or admins.",
        )
    try:
        path = restore_production()
        queue_live_update()
        apply_pending_update()
        refresh_all_caches(force=True)
        message = (
            "Reverted Silva codebase to the last production backup.\n"
            f"Restored from: {path}\n"
            "Restart Silva to fully reload code changes.\n"
            + _owner_contact_line()
        )
        return TerminalUpdateResult(ok=True, message=message, steps=["revert"])
    except Exception as exc:
        log_error("Terminal revert failed", exc=exc)
        return TerminalUpdateResult(
            ok=False,
            message=f"Revert failed: {exc}\n{backup_paths_summary()}",
        )
