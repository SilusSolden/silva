"""Automatic Silva update checks, apply, and user notifications."""

from __future__ import annotations

import threading
from typing import Callable

from silva.cache.refresh import refresh_all_caches
from silva.config import load_config, save_config
from silva.dev.live_update import apply_pending_update, queue_live_update
from silva.dev.paths import PENDING_UPDATE_FILE, RELOAD_FLAG_FILE
from silva.dev.speech_training import load_speech_training
from silva.dev.test_runner import run_all_tests
from silva.dev.update_scanner import (
    UpdateScanResult,
    load_bundled_manifest,
    publish_update_manifest,
    save_installed_manifest,
    scan_for_updates,
)
from silva.logger import log_error, log_info
from silva.notifications.dispatch import notify_owner_async


ApplyCallback = Callable[[bool, str, UpdateScanResult | None], None]


def auto_update_enabled() -> bool:
    return bool(load_config().get("auto_update_enabled", True))


def update_check_interval_seconds() -> float:
    try:
        minutes = float(load_config().get("auto_update_check_interval_minutes", 15))
    except (TypeError, ValueError):
        minutes = 15.0
    return max(60.0, minutes * 60.0)


def desktop_update_notify_enabled() -> bool:
    return bool(load_config().get("auto_update_notify_desktop", True))


def skips_desktop_update_ui(user: dict | None = None) -> bool:
    """Owner and admins use terminal updates — never show desktop update popups."""
    if not bool(load_config().get("auto_update_skip_main_owner", True)):
        return False

    from silva.users.manager import get_active_user, is_owner
    from silva.users.profile_access import can_open_control_panel
    from silva.users.system_identity import is_main_owner_system

    active = user or get_active_user()

    if is_owner(active):
        return True

    if can_open_control_panel(active):
        return True

    # Voice ID can briefly leave the main dev machine on guest between turns.
    if is_main_owner_system() and active.get("id") in {"", "guest"}:
        return True

    return False


def owner_uses_terminal_update_only(user: dict | None = None) -> bool:
    """Alias kept for older call sites."""
    return skips_desktop_update_ui(user)


def should_show_desktop_update_popup(user: dict | None = None) -> bool:
    if not desktop_update_notify_enabled():
        return False
    return not skips_desktop_update_ui(user)


def should_speak_update_offer(user: dict | None = None) -> bool:
    return not skips_desktop_update_ui(user)


def should_notify_update_available(user: dict | None = None) -> bool:
    """Remote/non-owner users trigger owner alerts; owner/admins on dev do not."""
    return not skips_desktop_update_ui(user)


def should_show_terminal_update_button(user: dict | None = None) -> bool:
    """Floating Update Silva button — hidden for owner/admin; terminal commands are enough."""
    if not bool(load_config().get("terminal_update_button_enabled", True)):
        return False
    return not skips_desktop_update_ui(user)


def notify_users_update_available(scan: UpdateScanResult) -> None:
    if not scan.available:
        return
    summary = "; ".join(scan.changes[:3])
    message = (
        f"Silva update {scan.version} is available. "
        f"{summary} Open the update notification on your desktop to install it."
    )
    notify_owner_async(message, reason="silva_update", force=False, prefer_telegram=True)


def notify_users_update_complete(version: str, changes: list[str]) -> None:
    summary = changes[0] if changes else "New features are ready."
    notify_owner_async(
        f"Silva updated to {version}. {summary}",
        reason="silva_update_complete",
        force=False,
        prefer_telegram=True,
    )


def apply_available_update(
    scan: UpdateScanResult | None = None,
    *,
    skip_tests: bool = False,
    publish: bool = False,
    features: list[str] | None = None,
    changelog: list[str] | None = None,
) -> tuple[bool, str, UpdateScanResult | None]:
    """Install the latest Silva update while the assistant keeps running."""
    from silva.dev.panel_update import scan_panel_changes
    from silva.dev.update_check import check_update_status
    from silva.dev.update_scanner import compute_code_fingerprint

    status = check_update_status()
    if not status.needs_update and not publish:
        version = status.available_version or status.current_version
        return False, f"Silva is already up to date at {version}.", scan

    scan = scan or scan_for_updates()
    panel = scan_panel_changes()
    if not scan.available and not publish and not panel.has_changes:
        return False, "Silva is already up to date.", scan
    if not scan.available and not publish and panel.has_changes:
        from silva.dev.live_update import apply_code_to_running_assistant

        ok, message = apply_code_to_running_assistant()
        return ok, message, scan

    if not skip_tests and bool(load_config().get("auto_update_run_tests_before_apply", False)):
        result = run_all_tests(include_unit_tests=True)
        if not result.passed:
            return False, "Update blocked until checks pass.", scan

    if publish:
        manifest = publish_update_manifest(features=features, changelog=changelog)
        scan = scan_for_updates()
        scan.manifest = manifest
        scan.version = str(manifest.get("version", scan.version))
        scan.changes = [str(item) for item in manifest.get("changelog", [])]

    if not PENDING_UPDATE_FILE.exists() and not RELOAD_FLAG_FILE.exists():
        config = load_config()
        queue_live_update(
            features=features or scan.features or config.get("universal_features", []),
        )

    ok, message = apply_pending_update()
    if not ok:
        return False, message, scan

    try:
        refresh_all_caches(force=True)
    except Exception as exc:
        log_error("Cache refresh after update failed", exc=exc)

    manifest = scan.manifest or load_bundled_manifest()
    installed = {
        "version": scan.version or str(manifest.get("version", "0.0.0")),
        "features": features or scan.features or manifest.get("features") or [],
        "fingerprint": compute_code_fingerprint(),
        "changelog": scan.changes or manifest.get("changelog") or [],
        "speech_training": load_speech_training(),
    }
    save_installed_manifest(installed)

    feature_list = installed.get("features")
    if isinstance(feature_list, list) and feature_list:
        config = load_config()
        config["universal_features"] = feature_list
        save_config(config)

    summary = scan.changes[0] if scan.changes else "Silva is now up to date."
    return True, f"Silva updated to {installed['version']}. {summary}", scan


def run_update_check_async(*, on_result: Callable[[UpdateScanResult], None]) -> None:
    def worker() -> None:
        try:
            scan = scan_for_updates()
        except Exception as exc:
            log_error("Update scan failed", exc=exc)
            scan = UpdateScanResult(available=False)
        on_result(scan)

    threading.Thread(target=worker, name="silva-update-scan", daemon=True).start()


def apply_update_async(
    scan: UpdateScanResult,
    *,
    skip_tests: bool = True,
    publish: bool = False,
    features: list[str] | None = None,
    on_done: ApplyCallback | None = None,
) -> None:
    def worker() -> None:
        try:
            ok, message, applied_scan = apply_available_update(
                scan,
                skip_tests=skip_tests,
                publish=publish,
                features=features,
            )
        except Exception as exc:
            log_error("Update apply failed", exc=exc)
            ok, message, applied_scan = False, str(exc), scan
        if on_done is not None:
            on_done(ok, message, applied_scan)

    threading.Thread(target=worker, name="silva-update-apply", daemon=True).start()


def format_update_offer(scan: UpdateScanResult) -> str:
    lines = [
        f"Silva update {scan.version} is available.",
        f"You have version {scan.installed_version}.",
    ]
    for item in scan.changes[:5]:
        lines.append(f"- {item}")
    lines.append("Would you like to update now?")
    return " ".join(lines)


def is_whats_new_update_phrase(text: str) -> bool:
    from silva.commands.update_phrases import is_whats_new_update_phrase as _match

    return _match(text)


_GENERIC_CHANGE = (
    "silva code was patched",
    "bug fixes and command updates",
    "owner pushed a live update",
    "speech training and feature access refreshed",
    "no manual changes detected",
    "manual changes detected",
    "manual update pushed",
    "shorter update summary",
)

_MODULE_WHY = {
    "commands/planner_handler.py": "how the planner opens from speech, including a short I-opened-it reply with no extra how-to",
    "commands/planner_phrases.py": "more spoken ways to open the planner, map a building, or turn on the lot",
    "gui/planner_map_dialog.py": "the popup where you can type a building for me to map",
    "planner/layout.py": "turning drawn lines into rooms and mapping a house from what you say",
    "planner/geometry.py": "measuring lines and finding closed rooms so I can show square footage",
    "commands/crash_report_phrases.py": "asking why I crashed or why commands failed",
    "commands/crash_report_handler.py": "speaking a short reason for a crash or failed commands, then opening a text file for the technical part",
    "crash_record.py": "saving the last crash and last command error from the logs",
    "commands/update_phrases.py": "more ways to ask what was in an update, including the type of code that was added",
    "commands/update_handler.py": "answering those update questions and keeping voice live-apply owner-only",
    "dev/auto_update.py": "reading the last file list and explaining the modules, not only the log line",
    "commands/help_phrases.py": "not treating what's-in-the-update as a help question",
    "stt_quick_commands.py": "finishing update questions as soon as you say them",
    "dev/runtime_hooks.py": "keeping other commands working even if the planner window is still an old version",
    "assistant.py": "the main listen loop, including catching command errors so I can explain them later",
    "interrupt_listen.py": "hearing stop while I talk, including when you type it in the console",
    "tts_interrupt.py": "cutting pyttsx3 off in the middle of a sentence when you say stop",
    "commands/wikipedia.py": "short Wikipedia answers instead of reading a whole article",
    "commands/registry.py": "not treating what's-new-in-the-update as a Wikipedia search",
    "planner/catalog.py": "planner objects you can add, including wires, water, gas, and drain lines",
    "planner/icons.py": "pictures on the planner object list so clicks match what you add",
    "planner/paint_tools.py": "Paint-style tool pictures on the planner ribbon",
    "planner/import_media.py": "importing a photo or video onto the planner with pause and play",
    "planner/store.py": "saving planner walls, rooms, wires, and custom objects",
    "gui/planner_window.py": "click to select objects, delete all, right-click delete or rotate, and 3D photos on the plan",
    "dev/whats_new_script.py": "checking which files were actually added since the last update I told you about",
    "sleep_prompts.py": "short sleep replies and a simple repeat prompt when I miss part of what you said",
    "wake_context.py": "waking from phrases like I said wake up, even when the mic hears break up",
    "conversation/engine.py": "treating a correction like that is not what I said as a request to repeat",
    "commands/notes_phrases.py": "not treating a correction as undoing your last to-do",
    "commands/help_phrases.py": "answering to-do list questions instead of showing help",
    "users/manager.py": "one-time setup notes for new and promoted accounts",
    "users/onboarding.py": "the first-run summary and example phrases popup",
    "users/feature_requests.py": "sending feature requests to the owner and admins",
    "gui/feature_request_popup.py": "a text box for feature requests when you cannot speak them",
    "gui/onboarding_popup.py": "the popup that shows what I can do and how to ask",
    "dev/terminal_commands.py": "showing pending feature requests in the terminal",
    "gui/panel_security_tabs.py": "System Panel tabs for requests, staged updates, live progress, Code Lab, and voice access",
    "dev/admin_review_queue.py": "a staging queue where admins submit updates and only you approve them",
    "dev/code_lab.py": "static code checks that never run pasted code",
    "dev/panel_update.py": "not treating a guest as the owner when publishing from the System Panel",
    "commands/system_panel_commands.py": "opening the System Panel and its tabs by voice",
    "dev/panel_instance.py": "focusing the right System Panel tab when a voice request opens it",
    "users/voice_access.py": "basic voice access for everyone after enrollment, with major controls still owner-approved",
    "users/features.py": "a voice access feature for enrolled users, with major controls kept behind owner approval",
    "gui/media_library_popup.py": "a standalone owner-only image viewer with folders, single-click viewing, and delete control",
    "gui/panel_showcase_popup.py": "a popup to mark System Panel features and link appearance notes to stored images",
    "gui/image_generator_popup.py": "Image Studio for typed or spoken prompts, edits, descriptions, and saving",
    "media/image_generator.py": "a local lightweight image generator that stays within system load limits",
    "media/image_generator_handler.py": "voice commands for building, editing, describing, and saving generated images",
    "dev/panel_showcase.py": "saved marks and appearance notes for System Panel features",
}

_MODULE_TECH = {
    "planner/geometry.py": (
        "planner geometry.py is Python wall math: the closed polygons function walks wall endpoints, "
        "split walls at junctions cuts T junctions, and lengths are labeled in US feet and inches"
    ),
    "planner/layout.py": (
        "planner layout.py rebuilds rooms from those lines, and generate building lays out a house from a spoken spec"
    ),
    "planner/store.py": (
        "planner store.py saves walls, rooms, floors, and the site lot as JSON with the rest of Silva"
    ),
    "gui/planner_window.py": (
        "gui planner window.py is the Tk planner with a Paint-style tool ribbon, object pictures, "
        "and drag-to-route electrical and plumbing lines"
    ),
    "gui/planner_map_dialog.py": (
        "gui planner map dialog.py is the Map a building popup that takes typed text"
    ),
    "commands/planner_handler.py": (
        "commands planner handler.py routes voice to the planner with getattr so a stale GUI cannot crash other commands"
    ),
    "commands/planner_phrases.py": (
        "commands planner phrases.py matches open planner, 2D, 3D, map a building, and site lot speech"
    ),
    "crash_record.py": (
        "crash record.py writes last crash.txt and last command error.txt from logs and Unexpected assistant error"
    ),
    "commands/crash_report_handler.py": (
        "commands crash report handler.py speaks a short why, then opens the crash or command-error text file"
    ),
    "commands/crash_report_phrases.py": (
        "commands crash report phrases.py matches why did you crash and why commands were not working"
    ),
    "commands/update_phrases.py": (
        "commands update phrases.py matches what's-in-the-update and technical codebase questions"
    ),
    "commands/update_handler.py": (
        "commands update handler.py answers those questions instead of sending them to chat"
    ),
    "dev/auto_update.py": (
        "dev auto update.py builds the spoken changelog from Python module lists, not only the log line"
    ),
    "dev/runtime_hooks.py": (
        "dev runtime hooks.py wraps command handling so a planner import error cannot take down every command"
    ),
    "assistant.py": (
        "assistant.py is the listen loop; it records command errors so you can ask why a command failed"
    ),
    "interrupt_listen.py": (
        "interrupt listen.py hears stop on the microphone and from the typed console while pyttsx3 is talking"
    ),
    "tts_interrupt.py": (
        "tts interrupt.py stops the current pyttsx3 engine as soon as the stop event is set"
    ),
    "commands/wikipedia.py": (
        "commands wikipedia.py speaks a short extract instead of the full article"
    ),
    "commands/registry.py": (
        "commands registry.py yields Wikipedia when the phrase is a Silva update question"
    ),
    "planner/catalog.py": (
        "planner catalog.py lists furniture, fixtures, copper wire, water, gas, drain, and custom objects"
    ),
    "planner/icons.py": (
        "planner icons.py draws the object pictures used on the left of the planner"
    ),
    "planner/paint_tools.py": (
        "planner paint tools.py writes the Paint-style ribbon glyphs used on the planner"
    ),
    "planner/import_media.py": (
        "planner import media.py turns a photo or video into planner objects and can pause the render"
    ),
    "dev/whats_new_script.py": (
        "dev whats new script.py diffs current file hashes against the last spoken update"
    ),
}

_DEFAULT_STORY_FILES = (
    "planner/geometry.py",
    "planner/layout.py",
    "planner/store.py",
    "gui/planner_window.py",
    "gui/planner_map_dialog.py",
    "commands/planner_handler.py",
    "commands/planner_phrases.py",
    "crash_record.py",
    "commands/crash_report_handler.py",
    "commands/crash_report_phrases.py",
    "commands/update_phrases.py",
    "commands/update_handler.py",
    "dev/auto_update.py",
    "dev/runtime_hooks.py",
    "assistant.py",
)


def _clean_changelog_item(item: str) -> str:
    import re

    text = re.sub(r"\s*\([^)]*\)", "", str(item)).strip()
    text = re.sub(r"^(Patch:|New feature:|New module:|Removed:)\s*", "", text, flags=re.I)
    return text.strip(" .")


def _is_generic_change(item: str) -> bool:
    lower = str(item or "").strip().lower()
    if not lower:
        return True
    return any(token in lower for token in _GENERIC_CHANGE)


def _normalize_rel(posix: str) -> str:
    posix = str(posix or "").replace("\\", "/").lstrip("/")
    if posix.startswith("silva/"):
        posix = posix[len("silva/") :]
    return posix


def _path_from_change(item: str) -> str:
    import re

    match = re.search(r"\(([^)]+\.py)\)", str(item))
    if match:
        return _normalize_rel(match.group(1))
    return ""


def _lookup_path(table: dict[str, str], posix: str) -> str:
    posix = _normalize_rel(posix)
    if posix in table:
        return table[posix]
    for key, value in table.items():
        if posix.endswith(key):
            return value
    return ""


def _why_for_path(posix: str) -> str:
    return _lookup_path(_MODULE_WHY, posix)


def _tech_for_path(posix: str) -> str:
    return _lookup_path(_MODULE_TECH, posix)


def _sentence_for_change(item: str) -> str:
    raw = str(item or "").strip()
    if not raw or _is_generic_change(raw):
        return ""
    posix = _path_from_change(raw)
    why = _why_for_path(posix) if posix else ""
    if not why:
        why = _clean_changelog_item(raw)
    if not why:
        return ""
    lower = raw.lower()
    if lower.startswith("new feature") or lower.startswith("new module"):
        return f"I added {why}."
    if lower.startswith("removed"):
        return f"I removed {why}."
    return f"I updated {why}."


def _modules_from_last_reload() -> list[str]:
    import re

    from silva.logger import LOG_FILE

    path = LOG_FILE
    if not path.exists():
        return []
    try:
        size = path.stat().st_size
        with open(path, "rb") as handle:
            if size > 1500000:
                handle.seek(size - 1500000)
                handle.readline()
            text = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    matches = re.findall(r"Live-reloaded: ([^\n]+)", text)
    modest: list[str] = []
    useful: list[str] = []
    for line in reversed(matches):
        names = [part.strip() for part in line.split(",") if part.strip()]
        if not names:
            continue
        if 0 < len(names) <= 24 and not modest:
            modest = names
        if not useful:
            useful = [
                name
                for name in names
                if _why_for_path(_module_to_path(name)) or _tech_for_path(_module_to_path(name))
            ]
        if modest and useful:
            break
    if useful and len(useful) > len(modest):
        return useful
    return modest or useful


def _module_to_path(name: str) -> str:
    if name == "silva":
        return ""
    if name.startswith("silva."):
        name = name[len("silva.") :]
    return name.replace(".", "/") + ".py"


def _is_known_code_file(posix: str) -> bool:
    posix = _normalize_rel(posix)
    return bool(_why_for_path(posix) or _tech_for_path(posix))


def remember_code_story(
    *,
    files: list[str] | None = None,
    modules: list[str] | None = None,
    version: str = "",
    changelog: list[str] | None = None,
) -> None:
    """Persist the Python files from the last live load so later questions can describe them."""
    import json
    from datetime import datetime

    from silva.dev.paths import LAST_CODE_STORY_FILE, ensure_dev_dir

    ensure_dev_dir()
    rels: list[str] = []
    seen: set[str] = set()

    def add(posix: str) -> None:
        posix = _normalize_rel(posix)
        if not posix.endswith(".py") or posix in seen:
            return
        if posix.startswith("test") or "/test_" in posix:
            return
        seen.add(posix)
        rels.append(posix)

    for raw in files or []:
        add(str(raw))
    for name in modules or []:
        add(_module_to_path(str(name)))

    known = [path for path in rels if _is_known_code_file(path)]
    if len(rels) > 24:
        rels = known or rels[:24]
    if not rels:
        return
    items = [str(item).strip().rstrip(".") for item in (changelog or []) if str(item).strip()]
    if not items:
        items = _feature_items_from_files(rels)
    try:
        LAST_CODE_STORY_FILE.write_text(
            json.dumps(
                {
                    "version": version,
                    "files": rels,
                    "items": items,
                    "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass


def _load_story() -> dict:
    import json

    from silva.dev.paths import LAST_CODE_STORY_FILE

    try:
        if LAST_CODE_STORY_FILE.exists():
            data = json.loads(LAST_CODE_STORY_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError, TypeError, AttributeError):
        pass
    return {}


def _story_files() -> list[str]:
    files = [_normalize_rel(str(item)) for item in (_load_story().get("files") or []) if str(item).strip()]
    files = [path for path in files if path.endswith(".py")]
    return files


def _story_items() -> list[str]:
    items: list[str] = []
    for raw in _load_story().get("items") or []:
        text = str(raw).strip().rstrip(".")
        if text:
            items.append(text)
    return items


def _sentences_from_files(files: list[str], *, technical: bool) -> list[str]:
    seen: set[str] = set()
    sentences: list[str] = []
    for raw in files:
        posix = _normalize_rel(raw)
        if not posix or posix in seen:
            continue
        if posix.startswith("test") or "/test_" in posix:
            continue
        seen.add(posix)
        if technical:
            desc = _tech_for_path(posix)
            if not desc:
                continue
            sentences.append(desc if desc.endswith(".") else f"{desc}.")
        else:
            why = _why_for_path(posix)
            if why:
                sentences.append(f"I updated {why}.")
    return sentences


def _sentences_from_modules(names: list[str], *, technical: bool = False) -> list[str]:
    return _sentences_from_files([_module_to_path(name) for name in names], technical=technical)


def _last_loaded_changelog() -> tuple[str, list[str]]:
    """Version and changelog lines from the update already loaded in this session."""
    from silva.dev.update_scanner import load_bundled_manifest, load_installed_manifest

    installed = load_installed_manifest()
    bundled = load_bundled_manifest()
    version = str(installed.get("version") or bundled.get("version") or "").strip()
    items = [str(item) for item in (installed.get("changelog") or []) if str(item).strip()]
    if not items:
        items = [str(item) for item in (bundled.get("changelog") or []) if str(item).strip()]
    return version, items


def _detail_sentences(items: list[str], *, technical: bool = False) -> list[str]:
    if technical:
        paths = [_path_from_change(item) for item in items]
        sentences = _sentences_from_files([path for path in paths if path], technical=True)
        if sentences:
            return sentences
    else:
        sentences = [_sentence_for_change(item) for item in items]
        sentences = [item for item in sentences if item]
        if sentences:
            return sentences
    from_modules = _sentences_from_modules(_modules_from_last_reload(), technical=technical)
    if from_modules:
        return from_modules
    return _sentences_from_files(_story_files(), technical=technical)


def _trim_sentences(sentences: list[str], *, technical: bool) -> list[str]:
    limit = 5 if technical else 4
    if len(sentences) <= limit + 1:
        return sentences
    extra = len(sentences) - limit
    label = "Python files" if technical else "related files"
    return sentences[:limit] + [f"And {extra} more {label}."]


def _files_for_summary(items: list[str]) -> list[str]:
    files = [_path_from_change(item) for item in items]
    files = [path for path in files if path]
    return files or _story_files()


# Most-specific / newest first. Keep each line short — speech uses only the first match.
_FEATURE_BULLETS: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        ("conversation/correction_repair.py",),
        "plain go to sleep is calm while cursed sleep wording stays sharp, why are you not doing this the way I want asks for the corrected way, conversation replies recheck the tone right before speaking, and cussing questions are explained",
    ),
    (
        ("dev/code_assist.py",),
        "code-assist now opens a typed text box on request and only writes reports for real code changes",
    ),
    (
        ("stt_fillers.py", "stt_speech_guard.py"),
        "thinking fillers and mic-moving-away audio are treated as thinking instead of commands",
    ),
    (
        ("conversation/complete_sentence.py",),
        "incomplete interruption speech is ignored so Silva does not answer a cut-off sentence",
    ),
    (
        ("conversation/crosschat_memory.py", "dev/code_assist.py"),
        "CrossChat custom instructions and rated speech learning, plus code-assist placement notes written to text files",
    ),
    (
        ("dev/screen_monitor.py", "dev/stream_deck.py"),
        "owner-approved screen context, manual video word learning, and Stream Deck bindings with a dynamic weather tile",
    ),
    (
        ("conversation/learned_phrases.py", "yes_no_prompt.py"),
        "learned phrase replies and corrections, plus a news yes-or-no prompt that listens to full answers",
    ),
    (
        ("assistant.py", "commands/weather_alerts.py"),
        "quiet sleep-mode daily routines that wait after wake before showing news and weather",
    ),
    (
        ("dev/team_updates.py", "notifications/email.py"),
        "team update submissions with owner/admin approval, rejection popups, and optional email replies",
    ),
    (
        ("users/age_verification.py", "conversation/speech_policy.py"),
        "per-user unfiltered reply controls with face-and-age verification and a 10-year age band",
    ),
    (
        ("dev/future_tasks.py", "gui/panel_security_tabs.py"),
        "a Future Tasks panel and voice list for adding, deleting, completing, and assigning future work to admins",
    ),
    (
        ("conversation/safety.py", "conversation/echo_guard.py"),
        "family and speaker safety modes with clean replies, filtered image prompts, and self-echo suppression",
    ),
    (
        ("conversation/attitude.py", "assistant.py"),
        "reply attitudes that shift from shy and skittish to sassy and blunt while still doing the work",
    ),
    (
        ("gui/image_generator_popup.py", "media/image_generator.py"),
        "a standalone Image Studio popup with numbered controls, style and frame choices, seeds, and a bottom action bar",
    ),
    (
        ("planner/paint_tools.py", "gui/planner_window.py"),
        "Paint icons on the planner",
    ),
    (
        ("planner/import_media.py",),
        "photo and video import on the planner",
    ),
    (
        ("media/reference_images.py", "media/reference_image_handler.py"),
        "an owner-only image library that imports Downloads only when asked and blocks deleted images from returning",
    ),
    (
        (
            "media/image_generator.py",
            "media/image_generator_handler.py",
            "gui/image_generator_popup.py",
        ),
        "Image Studio, a low-resource local image generator with edits, descriptions, and save-to-library",
    ),
    (
        ("dev/whats_new_script.py", "commands/update_handler.py", "dev/live_update.py"),
        "update notes that follow the newest published changelog instead of replaying old messages",
    ),
    (
        ("users/voice_access.py", "users/features.py"),
        "voice access for enrolled users with owner-approved admin requests",
    ),
    (
        ("dev/admin_review_queue.py", "dev/code_lab.py"),
        "owner-approved System Panel review tabs with a static-only Code Lab",
    ),
    (
        ("users/feature_requests.py", "gui/feature_request_popup.py"),
        "sending feature requests to the owner and admins",
    ),
    (
        ("users/onboarding.py", "gui/onboarding_popup.py"),
        "a first-run guide with example phrases",
    ),
    (
        ("sleep_prompts.py", "wake_context.py"),
        "shorter sleep replies and better wake phrases",
    ),
    (
        ("interrupt_listen.py", "tts_interrupt.py", "interrupt.py"),
        "a stop command",
    ),
    (
        ("commands/wikipedia.py", "commands/registry.py"),
        "keeping what's-new questions on Silva updates instead of Wikipedia",
    ),
    (
        ("planner/catalog.py", "planner/icons.py"),
        "planner object pictures, custom objects, and copper wire, water, gas, and drain lines you can drag",
    ),
    (
        ("commands/planner_phrases.py", "commands/planner_handler.py"),
        "closing the planner from speech",
    ),
    (
        ("crash_record.py", "crash_report"),
        "crash and failed-command explanations",
    ),
    (
        ("planner/", "gui/planner"),
        "the 2D and 3D planner",
    ),
    (
        ("commands/update_", "dev/auto_update.py"),
        "how I answer what's in an update",
    ),
    (
        ("commands/notes_",),
        "notes",
    ),
    (
        ("stt.py",),
        "the microphone",
    ),
)


def _feature_items_from_files(files: list[str]) -> list[str]:
    joined = " ".join(_normalize_rel(path) for path in files)
    items: list[str] = []
    for needles, spoken in _FEATURE_BULLETS:
        if any(needle in joined for needle in needles):
            if spoken not in items:
                items.append(spoken)
        if len(items) >= 4:
            break
    return items


def _user_facing_items(changelog_items: list[str], files: list[str]) -> list[str]:
    bullets = _feature_items_from_files(files)
    if bullets:
        return bullets[:4]
    story = _story_items()
    story_version = str(_load_story().get("version") or "").strip()
    loaded_version, _ignored = _last_loaded_changelog()
    if story and (not story_version or not loaded_version or story_version == loaded_version):
        return story[:4]
    cleaned = [_clean_changelog_item(item) for item in changelog_items if not _is_generic_change(item)]
    cleaned = [item for item in cleaned if item]
    return cleaned[:4]


def _join_short(parts: list[str]) -> str:
    if not parts:
        return "a few Silva updates"
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    if len(parts) == 3:
        return f"{parts[0]}, {parts[1]}, and {parts[2]}"
    return f"{parts[0]}, {parts[1]}, {parts[2]}, and {parts[3]}"


def _short_loaded(version: str, items: list[str]) -> str:
    prefix = f"The newest update is {version}. " if version else ""
    if not items:
        return (
            prefix
            + "I don't have a fresh list of what that update added. "
            "Ask in more detail if you want more."
        )
    return prefix + f"I added {_join_short(items)}. Ask in more detail if you want more."


def _code_short(version: str, files: list[str], *, pending: bool = False) -> str:
    labels: list[str] = []
    for posix in files:
        posix = _normalize_rel(posix)
        if not _is_known_code_file(posix):
            continue
        labels.append(posix.replace(".py", "").replace("/", " "))
        if len(labels) >= 4:
            break
    listed = _join_short(labels) if labels else "the files from the last load"
    if pending:
        return f"The waiting update is Python under silva: {listed}. Say update Silva to load it."
    prefix = f"The newest update is {version}. " if version else ""
    return prefix + f"It's Python under the silva package: {listed}. Ask in more detail if you want the rest."


def _long_summary(version: str, items: list[str], *, technical: bool, pending: bool) -> str:
    sentences = _detail_sentences(items, technical=technical)
    if not sentences:
        sentences = _sentences_from_files(
            list(_DEFAULT_STORY_FILES) if technical else _story_files(),
            technical=technical,
        )
    if not sentences:
        sentences = ["I don't have a longer list for this update."]
    if technical and not pending:
        intro = "The code added is Python modules under the silva package. "
        if version:
            intro = f"The newest update is {version}. {intro}"
        spoken = intro + " ".join(_trim_sentences(sentences, technical=True))
    elif pending:
        if technical:
            sentences = ["The waiting update is Python under the silva package."] + sentences
        spoken = " ".join(_trim_sentences(sentences, technical=technical))
        spoken += " Say update Silva if you want them applied while I keep running."
        return spoken
    else:
        prefix = f"The newest update is {version}. " if version else "Here's what the newest update added. "
        spoken = prefix + " ".join(_trim_sentences(sentences, technical=False))
    return spoken


def changelog_for_scan(scan) -> list[str]:
    """User-facing changelog lines from a panel scan, not the generic patch sentence."""
    items = list(getattr(scan, "changes", None) or [])
    files = [_path_from_change(item) for item in items]
    files = [path for path in files if path]
    cleaned = [_clean_changelog_item(item) for item in items if not _is_generic_change(item)]
    cleaned = [item for item in cleaned if item]
    if cleaned:
        return cleaned[:6]
    bullets = _feature_items_from_files(files)
    if bullets:
        return [item[0].upper() + item[1:] + ("." if not item.endswith(".") else "") for item in bullets]
    return [item for item in items if str(item).strip()][:4] or ["Silva command updates from the latest files."]


def spoken_change_summary(scan, *, technical: bool = False, detailed: bool = False) -> str:
    """Spoken answer for what was in the update. Short unless the user asked for detail."""
    pending = bool(getattr(scan, "has_changes", False))
    if pending:
        items = list(scan.changes or [])
        version = str(getattr(scan, "version", "") or "").strip()
        if not version:
            version, _ignored = _last_loaded_changelog()
        files = _files_for_summary(items)
        cleaned = [_clean_changelog_item(item) for item in items if not _is_generic_change(item)]
        cleaned = [item for item in cleaned if item][:4]
        user_items = _feature_items_from_files(files) or cleaned
    else:
        version, items = _last_loaded_changelog()
        files = _story_files() or _files_for_summary(items)
        user_items = _user_facing_items(items, files)

    if detailed:
        return _long_summary(version, items, technical=technical, pending=pending)
    if technical:
        return _code_short(version, files, pending=pending)
    if pending:
        if user_items:
            return (
                f"There's a Silva update ready. I added {_join_short(user_items)}. "
                "Say update Silva to load it."
            )
        return "There's a Silva update ready. Say update Silva to load it."
    return _short_loaded(version, user_items)


def is_update_confirm_phrase(text: str) -> bool:
    from silva.commands.update_phrases import is_update_confirm_phrase as _match

    return _match(text)


def is_update_decline_phrase(text: str) -> bool:
    from silva.commands.update_phrases import is_update_decline_phrase as _match

    return _match(text)
