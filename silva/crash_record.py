"""Remember unclean exits and explain the last crash in plain speech plus a .txt dump."""

from __future__ import annotations

import json
import os
import re
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from silva.config import CONFIG_DIR
from silva.logger import LOG_DIR, LOG_FILE

LAST_EXIT_FILE = CONFIG_DIR / "keep_alive" / "last_exit.json"
LAST_UNCLEAN_FILE = CONFIG_DIR / "keep_alive" / "last_unclean.json"
LAST_COMMAND_ERROR_FILE = CONFIG_DIR / "keep_alive" / "last_command_error.json"
REPORT_FILE = LOG_DIR / "last_crash.txt"
COMMAND_REPORT_FILE = LOG_DIR / "last_command_error.txt"
_LOG_OVERRIDE: Path | None = None
_paths_overridden = False

_SPEAK_MAX = 220
_LOG_TAIL_BYTES = 262144

_CLEAN_MARKERS = (
    "INFO: Silva stopped by user.",
    "INFO: Silva stopped.",
    "INFO: Silva process ending.",
)
_AUDIO_HINTS = (
    "microphone stream dropped",
    "no default input device",
    "portaudio",
    "audio device connected",
    "audio device removed",
    "invalid number of channels",
    "capture_active",
)
_TECHNICAL_RE = re.compile(
    r"("
    r"traceback \(most recent call last\)|"
    r"file \".+\.py\".*line \d+|"
    r"\b0x[0-9a-f]+\b|"
    r"access_violation|"
    r"ctypes|"
    r"portaudio|"
    r"\b\w+\.py\b"
    r")",
    re.I,
)
_STARTED_RE = re.compile(r"^\[\d{4}-\d{2}-\d{2}[^\]]*\] INFO: Silva started", re.M)


@dataclass
class CrashExplain:
    kind: str
    spoken: str
    path: Path
    open_file: bool
    technical: bool


def configure_paths(root: Path, *, log_file: Path | None = None) -> None:
    """Point crash files at a folder (tests)."""
    global LAST_EXIT_FILE, LAST_UNCLEAN_FILE, LAST_COMMAND_ERROR_FILE
    global REPORT_FILE, COMMAND_REPORT_FILE, _LOG_OVERRIDE, _paths_overridden
    root = Path(root)
    LAST_EXIT_FILE = root / "last_exit.json"
    LAST_UNCLEAN_FILE = root / "last_unclean.json"
    LAST_COMMAND_ERROR_FILE = root / "last_command_error.json"
    REPORT_FILE = root / "last_crash.txt"
    COMMAND_REPORT_FILE = root / "last_command_error.txt"
    _LOG_OVERRIDE = Path(log_file) if log_file is not None else root / "silva.log"
    _paths_overridden = True


def _recording_enabled() -> bool:
    if _paths_overridden:
        return True
    if "unittest" in sys.modules:
        return False
    return True


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _log_path() -> Path:
    return _LOG_OVERRIDE if _LOG_OVERRIDE is not None else LOG_FILE


def record_clean_exit() -> None:
    if not _recording_enabled():
        return
    _write_json(
        LAST_EXIT_FILE,
        {"kind": "clean", "pid": os.getpid(), "stopped": _now()},
    )


def record_session_start(*, resumed_sleep: bool = False) -> None:
    """On boot, remember if the previous process died without a clean stop."""
    if not _recording_enabled():
        return
    previous = _read_json(LAST_EXIT_FILE)
    if previous.get("kind") == "running":
        clue = _diagnose_from_logs()
        snapshot = {
            "kind": clue.get("kind") or "unclean",
            "caught_at": _now(),
            "previous": previous,
            "resumed_sleep": bool(resumed_sleep),
            "simple": clue.get("simple") or "",
            "log_excerpt": clue.get("excerpt") or "",
        }
        _write_json(LAST_UNCLEAN_FILE, snapshot)
        _write_report(snapshot, clue)
    _write_json(
        LAST_EXIT_FILE,
        {
            "kind": "running",
            "pid": os.getpid(),
            "started": _now(),
            "asleep": bool(resumed_sleep),
        },
    )


def explain_last_crash() -> CrashExplain:
    clue = _diagnose_from_logs()
    unclean = _read_json(LAST_UNCLEAN_FILE)
    last_exit = _read_json(LAST_EXIT_FILE)
    keep = _keep_alive_notes()

    if unclean:
        if not clue.get("kind") or clue.get("kind") in {"unknown", "current"}:
            clue["kind"] = unclean.get("kind") or "unclean"
            if unclean.get("simple") and not clue.get("simple"):
                clue["simple"] = unclean["simple"]
        if unclean.get("resumed_sleep") and clue.get("kind") in {"unclean", "unknown", "current"}:
            clue["kind"] = "sleep_native"
        excerpt = str(unclean.get("log_excerpt") or "")
        if excerpt and excerpt not in str(clue.get("excerpt") or ""):
            clue["excerpt"] = (clue.get("excerpt") or "") + "\n" + excerpt

    stay_active_log = "stay-active" in str(clue.get("excerpt") or "").lower()
    if (
        keep.get("watchdog_restart")
        and (unclean or stay_active_log)
        and clue.get("kind") in {"unclean", "sleep_native", "unknown", "current", None}
    ):
        if clue.get("kind") != "audio_device":
            clue["kind"] = "watchdog"
        clue["simple"] = clue.get("simple") or keep.get("simple") or ""

    if last_exit.get("kind") == "clean" and not unclean:
        if clue.get("kind") in {"clean_goodbye", "clean_window", "clean_stop"}:
            pass
        elif clue.get("kind") in {None, "unknown", "current"}:
            clue["kind"] = "clean_stop"

    kind = clue.get("kind") or "unknown"
    spoken = _spoken_for(kind, clue.get("simple") or "")
    technical = _is_technical(clue.get("excerpt") or "") or _is_technical(clue.get("simple") or "")
    if technical:
        spoken = _spoken_for(kind, "")
        if kind not in {"clean_goodbye", "clean_window", "clean_stop"}:
            spoken = _ensure_file_mention(spoken)

    snapshot = {
        "kind": kind,
        "caught_at": _now(),
        "previous": last_exit,
        "unclean": unclean,
        "resumed_sleep": bool(unclean.get("resumed_sleep")),
        "simple": clue.get("simple") or spoken,
        "log_excerpt": clue.get("excerpt") or "",
        "keep_alive": keep,
    }
    path = _write_report(snapshot, clue)
    open_file = kind not in {"clean_goodbye", "clean_window", "clean_stop"} or technical
    return CrashExplain(
        kind=kind,
        spoken=spoken[:_SPEAK_MAX].rstrip(),
        path=path,
        open_file=open_file,
        technical=technical,
    )


def record_command_error(exc: BaseException) -> None:
    """Remember a live command failure so you can ask why commands did not work."""
    if not _recording_enabled():
        return
    text = f"{type(exc).__name__}: {exc}"
    kind = "planner_stale" if "apply_planner_speech" in text or "planner_window" in text.lower() else "unexpected"
    _write_json(
        LAST_COMMAND_ERROR_FILE,
        {
            "kind": kind,
            "type": type(exc).__name__,
            "message": str(exc)[:400],
            "at": _now(),
            "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[:6000],
        },
    )


def explain_last_command_fail() -> CrashExplain:
    clue = _diagnose_command_fail()
    kind = clue.get("kind") or "none"
    spoken = _spoken_for_command_fail(kind)
    technical = _is_technical(clue.get("excerpt") or "") or _is_technical(clue.get("simple") or "")
    if technical and kind != "none":
        spoken = _ensure_file_mention(spoken)
    snapshot = {
        "kind": kind,
        "caught_at": _now(),
        "simple": clue.get("simple") or spoken,
        "log_excerpt": clue.get("excerpt") or "",
        "recorded": clue.get("recorded") or {},
    }
    path = _write_command_report(snapshot)
    open_file = kind != "none" or technical
    return CrashExplain(
        kind=kind,
        spoken=spoken[:_SPEAK_MAX].rstrip(),
        path=path,
        open_file=open_file,
        technical=technical,
    )


def _diagnose_command_fail() -> dict:
    recorded = _read_json(LAST_COMMAND_ERROR_FILE)
    tail = _read_log_tail()
    sessions = _sessions(tail)
    current = sessions[-1] if sessions else tail
    haystack = current or tail
    lower = haystack.lower()
    excerpt = _excerpt(haystack)
    recorded_text = json.dumps(recorded).lower() if recorded else ""

    planner_hit = (
        "apply_planner_speech" in lower
        or "apply_planner_speech" in recorded_text
        or ("cannot import name" in lower and "planner_window" in lower)
        or ("cannot import name" in recorded_text and "planner" in recorded_text)
    )
    unexpected_hit = "unexpected assistant error" in lower or "planner command failed" in lower
    if planner_hit:
        return {
            "kind": "planner_stale",
            "simple": "The planner window was still an old version after a live update.",
            "excerpt": excerpt,
            "recorded": recorded,
        }
    if unexpected_hit or recorded:
        simple = recorded.get("message") if recorded else _last_error_line(haystack)
        return {
            "kind": "unexpected",
            "simple": simple or "An unexpected assistant error was logged.",
            "excerpt": excerpt,
            "recorded": recorded,
        }
    return {"kind": "none", "simple": "", "excerpt": excerpt, "recorded": recorded}


def _spoken_for_command_fail(kind: str) -> str:
    messages = {
        "planner_stale": (
            "Commands failed after a planner update. The window was still the old version, "
            "so every command hit an unexpected error. I opened a text file with the log details."
        ),
        "unexpected": (
            "Commands hit an unexpected assistant error. "
            "I opened a text file with what the logs caught instead of reading the code out loud."
        ),
        "none": (
            "I don't see a recent command failure in the logs. "
            "If it happens again, ask me and I'll pull the details."
        ),
    }
    return re.sub(r"\s+", " ", messages.get(kind, messages["none"])).strip()


def _write_command_report(snapshot: dict) -> Path:
    COMMAND_REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    recorded = snapshot.get("recorded") or {}
    lines = [
        "Silva last-command-error report",
        "===============================",
        f"Written: {snapshot.get('caught_at') or _now()}",
        f"Kind: {snapshot.get('kind') or 'none'}",
        f"Simple reason: {snapshot.get('simple') or '(none)'}",
        "",
        "Share this file or a screenshot if you want help fixing the issue.",
        "Spoken replies stay short. Extra code, paths, and log lines stay here.",
        "",
        "--- Recorded error ---",
        json.dumps(recorded, indent=2) if recorded else "(none)",
        "",
        "--- Log clues ---",
        str(snapshot.get("log_excerpt") or "").strip() or "(no log excerpt)",
        "",
    ]
    COMMAND_REPORT_FILE.write_text("\n".join(lines), encoding="utf-8")
    return COMMAND_REPORT_FILE


def _keep_alive_notes() -> dict:
    notes = {"watchdog_restart": False, "simple": "", "text": ""}
    try:
        from silva.keep_alive import RESTART_FILE, SLEEP_FILE, STOP_FILE

        parts: list[str] = []
        if RESTART_FILE.exists():
            notes["watchdog_restart"] = True
            notes["simple"] = "Stay-active started Silva again after a sleep stop."
            parts.append(f"last_restart: {RESTART_FILE.read_text(encoding='utf-8').strip()}")
        parts.append(f"sleep.flag: {'yes' if SLEEP_FILE.exists() else 'no'}")
        parts.append(f"stop.flag: {'yes' if STOP_FILE.exists() else 'no'}")
        notes["text"] = "\n".join(parts)
    except Exception as exc:
        notes["text"] = f"(keep-alive files unavailable: {exc})"
    return notes


def _read_log_tail(max_bytes: int = _LOG_TAIL_BYTES) -> str:
    path = _log_path()
    if not path.exists():
        return ""
    try:
        size = path.stat().st_size
        with open(path, "rb") as handle:
            if size > max_bytes:
                handle.seek(size - max_bytes)
                handle.readline()
            return handle.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _sessions(tail: str) -> list[str]:
    if not tail.strip():
        return []
    starts = [match.start() for match in _STARTED_RE.finditer(tail)]
    if not starts:
        return [tail]
    chunks: list[str] = []
    if starts[0] > 0:
        chunks.append(tail[: starts[0]])
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(tail)
        chunks.append(tail[start:end])
    return chunks


def _diagnose_from_logs() -> dict:
    tail = _read_log_tail()
    sessions = _sessions(tail)
    previous = ""
    if len(sessions) >= 2:
        previous = sessions[-2]
    elif sessions:
        previous = sessions[0]
    combined = previous or tail
    lower = combined.lower()
    excerpt = _excerpt(combined)

    if "info: silva stopped by user." in lower:
        return {"kind": "clean_goodbye", "simple": "You said goodbye.", "excerpt": excerpt}
    if "info: silva stopped." in lower and "stay-active" not in lower:
        return {"kind": "clean_stop", "simple": "Silva stopped on purpose.", "excerpt": excerpt}

    audio = any(hint in lower for hint in _AUDIO_HINTS)
    traceback_hit = "traceback (most recent call last)" in lower
    error_line = _last_error_line(combined)
    stay_active = "stay-active: silva stopped during sleep" in lower or "stay-active restart" in lower
    ended_clean = any(marker.lower() in lower for marker in _CLEAN_MARKERS)

    if audio and not ended_clean:
        return {
            "kind": "audio_device",
            "simple": "A microphone or speaker change happened while I was listening.",
            "excerpt": excerpt,
        }
    if stay_active and not ended_clean:
        return {
            "kind": "watchdog",
            "simple": "I stopped during sleep and stay-active started me again.",
            "excerpt": excerpt,
        }
    if traceback_hit or error_line:
        return {
            "kind": "python_error",
            "simple": error_line or "A Python error was logged.",
            "excerpt": excerpt,
        }
    if previous and not ended_clean:
        asleep = (
            "entered sleep mode" in lower
            or "resuming sleep mode" in lower
            or "in sleep mode" in lower
        )
        return {
            "kind": "sleep_native" if asleep else "unclean",
            "simple": (
                "Windows closed Silva before the logs could finish writing."
                if asleep
                else "The last session ended without a normal shutdown."
            ),
            "excerpt": excerpt,
        }
    return {"kind": "unknown", "simple": "", "excerpt": excerpt}


def _last_error_line(text: str) -> str:
    last = ""
    for line in text.splitlines():
        if "] ERROR:" in line:
            last = line.split("ERROR:", 1)[-1].strip()
    return last[:160]


def _excerpt(text: str, limit: int = 80) -> str:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    if len(lines) <= limit:
        return "\n".join(lines)
    return "\n".join(lines[-limit:])


def _is_technical(text: str) -> bool:
    if not text:
        return False
    if _TECHNICAL_RE.search(text):
        return True
    return text.count("\n") > 8 or len(text) > 280


def _spoken_for(kind: str, simple: str) -> str:
    clean_simple = simple.strip()
    if clean_simple and _is_technical(clean_simple):
        clean_simple = ""

    messages = {
        "audio_device": (
            "Last time Windows closed me while I was asleep. "
            "A microphone or speaker change likely caused it. "
            "I opened a text file with the details."
        ),
        "sleep_native": (
            "Last time I closed while asleep without you saying goodbye. "
            "Windows likely stopped the process. "
            "I opened a text file with what I found."
        ),
        "watchdog": (
            "Last time I stopped during sleep and stay-active started me again. "
            "I opened a text file with the details."
        ),
        "python_error": (
            f"Last time I hit an error. {clean_simple} I opened a text file with the rest."
            if clean_simple
            else "Last time I hit an error. I opened a text file with the details instead of reading the code out loud."
        ),
        "unclean": (
            "Last time I closed without a normal shutdown, so the logs may have cut off. "
            "I opened a text file with what I could find."
        ),
        "clean_goodbye": "Last time I closed because you said goodbye. That was not a crash.",
        "clean_window": "Last time the window was closed on purpose. That was not a crash.",
        "clean_stop": "Last time I stopped on purpose. That was not a crash.",
        "unknown": (
            "I could not find a clear crash in the last session. "
            "I still saved what I could see into a text file."
        ),
        "current": (
            "I could not find a clear crash in the last session. "
            "I still saved what I could see into a text file."
        ),
    }
    spoken = messages.get(kind, messages["unknown"])
    return re.sub(r"\s+", " ", spoken).strip()


def _ensure_file_mention(spoken: str) -> str:
    if "text file" in spoken.lower():
        return spoken
    return spoken.rstrip(".") + ". I opened a text file with the details."


def _write_report(snapshot: dict, clue: dict) -> Path:
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    kind = snapshot.get("kind") or clue.get("kind") or "unknown"
    simple = snapshot.get("simple") or clue.get("simple") or ""
    excerpt = snapshot.get("log_excerpt") or clue.get("excerpt") or ""
    keep = snapshot.get("keep_alive") or {}
    previous = snapshot.get("previous") or {}
    unclean = snapshot.get("unclean") or {}
    lines = [
        "Silva last-crash report",
        "=======================",
        f"Written: {snapshot.get('caught_at') or _now()}",
        f"Kind: {kind}",
        f"Simple reason: {simple or '(none)'}",
        "",
        "Share this file or a screenshot if you want help fixing the issue.",
        "Spoken replies stay short. Extra code, paths, and log lines stay here.",
        "",
        "--- What Silva remembered ---",
        f"Previous exit file: {json.dumps(previous, indent=2) if previous else '(none)'}",
        f"Last unclean snapshot: {json.dumps({k: unclean[k] for k in unclean if k != 'log_excerpt'}, indent=2) if unclean else '(none)'}",
        f"Stay-active: {keep.get('text') or '(none)'}",
        "",
        "--- Log clues ---",
        excerpt.strip() or "(no log excerpt)",
        "",
    ]
    REPORT_FILE.write_text("\n".join(lines), encoding="utf-8")
    return REPORT_FILE
