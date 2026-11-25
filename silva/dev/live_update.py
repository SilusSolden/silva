"""Live feature updates while Silva is running."""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from functools import wraps

from silva.config import load_config, save_config
from silva.dev.paths import (
    APPLIED_UPDATE_FILE,
    PENDING_UPDATE_FILE,
    PROGRESS_FILE,
    RELOAD_FLAG_FILE,
    ensure_dev_dir,
)
from silva.dev.speech_training import load_speech_training

_UPDATE_LOCK = threading.RLock()


def _update_locked(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        with _UPDATE_LOCK:
            return func(*args, **kwargs)

    return wrapped


def _write_progress(step: str, percent: int, *, done: bool = False, error: str = "") -> None:
    ensure_dev_dir()
    PROGRESS_FILE.write_text(
        json.dumps(
            {
                "step": step,
                "percent": max(0, min(100, int(percent))),
                "done": done,
                "error": error,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def read_progress() -> dict:
    if not PROGRESS_FILE.exists():
        return {"percent": 0, "step": "Idle", "done": True, "error": ""}
    try:
        data = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"percent": 0, "step": "Idle", "done": True}
    except (json.JSONDecodeError, OSError):
        return {"percent": 0, "step": "Idle", "done": True}


_SKIP_RELOAD = frozenset(
    {
        "silva.assistant",
        "silva.tts",
        "silva.stt",
        "silva.__main__",
        "silva.dev.live_update",
        "silva.gui.display_host",
        "silva.gui.background_mode",
        "silva.gui.profile_panel",
        "silva.interrupt_monitor",
        "silva.background_runner",
    }
)

_FRESH_GUI_MODULES: dict[str, object] = {}


def skip_live_reload(name: str) -> bool:
    """Tk GUI modules must not importlib.reload — that GCs widgets off the Tcl thread."""
    if name in _SKIP_RELOAD:
        return True
    if name == "silva.gui" or name.startswith("silva.gui."):
        return True
    return False


def module_name_from_rel(rel: str) -> str:
    posix = rel.replace("\\", "/").removesuffix(".py")
    if posix.endswith("/__init__"):
        posix = posix[: -len("/__init__")]
    return "silva." + posix.replace("/", ".")


def _reload_one(name: str) -> bool:
    import importlib
    import sys

    from silva.logger import log_error

    try:
        if name not in sys.modules:
            importlib.import_module(name)
        importlib.reload(sys.modules[name])
        return True
    except Exception as exc:
        if type(exc).__name__ == "TclError" or "tcl" in str(exc).lower():
            log_error(f"Live reload skipped Tcl error for {name}", exc=exc)
            return False
        log_error(f"Live reload failed for {name}", exc=exc)
        return False


def _module_reload_sort_key(name: str) -> tuple[int, int, int, str]:
    if name == "silva.dev.paths":
        return (0, 0, 0, name)
    if name == "silva.users.tiers":
        return (1, 0, 0, name)
    return (2, name.count("."), 0 if name.endswith("_phrases") else 1, name)


def _reload_module_names(names: list[str]) -> list[str]:
    from silva.logger import log_info

    reloaded: list[str] = []
    unique: list[str] = []
    skipped_gui: list[str] = []
    seen: set[str] = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        if skip_live_reload(name):
            if name == "silva.gui" or name.startswith("silva.gui."):
                skipped_gui.append(name)
            continue
        unique.append(name)
    # Parents first; phrase matchers before handlers so live imports do not fail mid-reload.
    unique.sort(key=_module_reload_sort_key)
    pending = list(unique)
    for _pass in range(2):
        leftover: list[str] = []
        for name in pending:
            if _reload_one(name):
                if name not in reloaded:
                    reloaded.append(name)
            else:
                leftover.append(name)
        pending = leftover
        if not pending:
            break
    if skipped_gui:
        log_info(
            "Live update left GUI windows alone to avoid a Tcl crash: "
            + ", ".join(skipped_gui[:12])
        )
    if reloaded:
        log_info("Live-reloaded: " + ", ".join(reloaded[:24]))
    return reloaded


def _gui_file_path(name: str):
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    rel = name.split(".", 1)[1].replace(".", "/") + ".py"
    return root / rel


def load_gui_module_from_disk(name: str):
    """Read a GUI module from disk without replacing the live Tk classes.

    Call this only from the Tk thread, when a window is actually opening.
    """
    import importlib.util
    import sys

    path = _gui_file_path(name)
    if not path.is_file():
        return sys.modules.get(name)
    mtime = path.stat().st_mtime
    cached = _FRESH_GUI_MODULES.get(name)
    if cached is not None and getattr(cached, "_silva_gui_mtime", None) == mtime:
        return cached
    alias = f"{name}__fresh"
    spec = importlib.util.spec_from_file_location(alias, path)
    if spec is None or spec.loader is None:
        return sys.modules.get(name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    module._silva_gui_mtime = mtime
    _FRESH_GUI_MODULES[name] = module
    return module


def reload_changed_modules(rels: list[str]) -> list[str]:
    """Hot-load Cursor/code edits into the running process. Skips core runtime modules."""
    return _reload_module_names([module_name_from_rel(rel) for rel in rels])


def reload_loaded_silva_modules() -> list[str]:
    """Reload every already-imported Silva module except the live runtime cores."""
    import sys

    names = [name for name in list(sys.modules) if name == "silva" or name.startswith("silva.")]
    return _reload_module_names(names)


@_update_locked
def queue_live_update(
    *,
    features: list[str] | None = None,
    changelog: list[str] | None = None,
) -> None:
    ensure_dev_dir()
    payload = {
        "requested_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "speech_training": load_speech_training(),
        "universal_features": features or load_config().get("universal_features", []),
        "changelog": [str(item) for item in (changelog or [])],
    }
    PENDING_UPDATE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    RELOAD_FLAG_FILE.write_text(str(time.time()), encoding="utf-8")
    _write_progress("Queued", 0, done=False)


@_update_locked
def apply_pending_update() -> tuple[bool, str]:
    """Called from the running assistant to apply a queued update."""
    ensure_dev_dir()
    if not PENDING_UPDATE_FILE.exists():
        _write_progress("Nothing to update", 100, done=True)
        return False, "No pending update."

    try:
        pending = json.loads(PENDING_UPDATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        _write_progress("Failed", 100, done=True, error=str(exc))
        return False, str(exc)

    changelog = [
        str(item).strip()
        for item in (pending.get("changelog") or [])
        if str(item).strip()
    ]

    try:
        _write_progress("Loading configuration", 15, done=False)
        config = load_config()

        _write_progress("Applying speech training", 40, done=False)
        training = pending.get("speech_training")
        if isinstance(training, dict):
            from silva.dev.paths import SPEECH_TRAINING_FILE

            SPEECH_TRAINING_FILE.write_text(json.dumps(training, indent=2), encoding="utf-8")

        _write_progress("Updating feature flags", 65, done=False)
        features = pending.get("universal_features")
        if isinstance(features, list) and features:
            config["universal_features"] = features
            save_config(config)

        _write_progress("Loading patched code into the running assistant", 85, done=False)
        from silva.dev.update_scanner import (
            code_file_hashes,
            compute_code_fingerprint,
            diff_code_files,
            load_bundled_manifest,
        )

        previous_files = {}
        if APPLIED_UPDATE_FILE.exists():
            try:
                previous = json.loads(APPLIED_UPDATE_FILE.read_text(encoding="utf-8"))
                if isinstance(previous.get("files"), dict):
                    previous_files = previous["files"]
            except (OSError, json.JSONDecodeError):
                previous_files = {}
        diff = diff_code_files(previous_files)
        to_reload = list(diff["added"]) + list(diff["modified"])
        import sys

        reloaded: list[str] = []
        try:
            if to_reload:
                reloaded = reload_changed_modules(to_reload)
            elif "silva.assistant" in sys.modules:
                reloaded = reload_loaded_silva_modules()
        except Exception as exc:
            from silva.logger import log_error

            log_error("Live reload did not finish; code is still saved on disk", exc=exc)
            reloaded = []
        try:
            from silva.dev.runtime_hooks import safe_install_runtime_hooks

            # Hooks force-reload command modules so skip-reload cores pick them up.
            safe_install_runtime_hooks()
        except Exception as exc:
            from silva.logger import log_error

            log_error("Live runtime hooks did not install after update", exc=exc)
        try:
            from silva.cache.refresh import refresh_all_caches

            refresh_all_caches(force=True)
        except Exception:
            pass

        bundled = load_bundled_manifest()
        try:
            from silva.dev.auto_update import remember_code_story

            if to_reload:
                remember_code_story(
                    files=to_reload,
                    version=str(bundled.get("version") or ""),
                    changelog=changelog,
                )
        except Exception:
            pass
        try:
            from silva.dev.whats_new_script import record_apply_delta

            if to_reload:
                record_apply_delta(
                    files=to_reload,
                    version=str(bundled.get("version") or ""),
                    changelog=changelog,
                )
        except Exception:
            pass
        APPLIED_UPDATE_FILE.write_text(
            json.dumps(
                {
                    "applied_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "features": features,
                    "fingerprint": bundled.get("fingerprint") or compute_code_fingerprint(),
                    "files": code_file_hashes(),
                    "speech_training": training if isinstance(training, dict) else load_speech_training(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        PENDING_UPDATE_FILE.unlink(missing_ok=True)
        RELOAD_FLAG_FILE.unlink(missing_ok=True)
        _write_progress("Update complete", 100, done=True)
        detail = "Live update applied while Silva kept running."
        if reloaded:
            detail += f" Reloaded {len(reloaded)} module(s)."
        from silva.logger import log_info

        log_info(detail)
        return True, detail
    except Exception as exc:
        _write_progress("Update failed", 100, done=True, error=str(exc))
        return False, str(exc)


@_update_locked
def apply_code_to_running_assistant() -> tuple[bool, str]:
    """Queue and apply folder code into this process, then stamp it as live."""
    from silva.dev.panel_update import scan_panel_changes
    from silva.dev.update_scanner import (
        load_bundled_manifest,
        mark_update_applied,
        publish_update_manifest,
    )
    from silva.config import load_config

    scan = scan_panel_changes()
    features = list(load_config().get("universal_features", []))
    changelog: list[str] = []
    if scan.has_changes:
        from silva.dev.auto_update import changelog_for_scan

        manifest = publish_update_manifest(
            features=features,
            changelog=changelog_for_scan(scan),
        )
        changelog = [str(item) for item in (manifest.get("changelog") or [])]
    elif load_bundled_manifest().get("changelog"):
        changelog = [str(item) for item in (load_bundled_manifest().get("changelog") or [])]
    queue_live_update(features=features, changelog=changelog)
    ok, message = apply_pending_update()
    if ok:
        try:
            mark_update_applied()
        except Exception as exc:
            from silva.logger import log_error

            log_error("Could not stamp the applied update", exc=exc)
        try:
            from silva.dev.runtime_hooks import safe_install_runtime_hooks

            safe_install_runtime_hooks()
        except Exception as exc:
            from silva.logger import log_error

            log_error("Live runtime hooks did not install after apply", exc=exc)
        extra = " New features and patches are active in this session."
        if not message.endswith("."):
            message += "."
        message += extra
    return ok, message


def reload_flag_pending(last_applied: float) -> bool:
    if not RELOAD_FLAG_FILE.exists():
        return False
    try:
        value = float(RELOAD_FLAG_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        value = RELOAD_FLAG_FILE.stat().st_mtime
    return value > last_applied
