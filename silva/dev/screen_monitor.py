"""Owner-approved screen context and manually selected video speech learning."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import threading
import time
from pathlib import Path

from silva.config import CONFIG_DIR, load_config, save_config
from silva.logger import log_error, log_info

MONITOR_DIR = CONFIG_DIR / "screen_monitor"
STATE_FILE = MONITOR_DIR / "state.json"
SUMMARY_FILE = MONITOR_DIR / "screen_summary.txt"
WORDS_FILE = MONITOR_DIR / "video_words.txt"
_LOCK = threading.Lock()
_last_capture = 0.0
_pending_transcript: dict[str, str] = {}
_pending_download: set[str] = set()
_video_threads: dict[str, threading.Thread] = {}
_video_stop: set[str] = set()

_WHAT_RE = re.compile(
    r"\b(?:what am i doing|what(?:'s| is) on (?:my|the) screen|are you watching (?:my screen|me)|what do you see)\b",
    re.I,
)
_START_VIDEO_RE = re.compile(
    r"\b(?:select|choose|pick|monitor|watch) (?:this|a|the) video\b"
    r"|\bi(?:'m| am) watching (?:this|a|the)? ?video\b"
    r"|\blearn from (?:this|the) video\b"
    r"|\bvideo (?:is playing|is on|started)\b",
    re.I,
)
_END_VIDEO_RE = re.compile(
    r"\b(?:video (?:done|finished|over)|done watching|finished watching|stop watching(?: this| the)? video|that(?:'s| is) the video)\b",
    re.I,
)
_APPROVE_RE = re.compile(r"\bapprove screen monitoring\b", re.I)


def _user_key(user_id: str) -> str:
    return str(user_id or "guest")


def approved() -> bool:
    return bool(load_config().get("screen_monitor_owner_approved", False))


def enabled(*, asleep: bool = False) -> bool:
    config = load_config()
    if not bool(config.get("screen_monitor_owner_approved", False)):
        return False
    if not bool(config.get("screen_monitor_enabled", False)):
        return False
    if asleep and not bool(config.get("screen_monitor_sleep_enabled", False)):
        return False
    return True


def video_enabled() -> bool:
    config = load_config()
    return bool(config.get("screen_monitor_owner_approved", False)) and bool(
        config.get("video_watch_enabled", True)
    )


def approve(user_id: str) -> bool:
    from silva.users.manager import load_store

    store = load_store()
    user = (store.get("users") or {}).get(_user_key(user_id)) or {}
    if str(store.get("owner_id") or "") != _user_key(user_id) and not user.get("is_owner"):
        return False
    config = load_config()
    config["screen_monitor_owner_approved"] = True
    config["screen_monitor_approved_by"] = _user_key(user_id)
    save_config(config)
    return True


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    try:
        MONITOR_DIR.mkdir(parents=True, exist_ok=True)
        temp = STATE_FILE.with_suffix(".json.tmp")
        temp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        temp.replace(STATE_FILE)
    except OSError:
        pass


def _write_text(path: Path, value: str) -> None:
    try:
        MONITOR_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(str(value or ""), encoding="utf-8")
    except OSError:
        pass


def capture_activity(*, asleep: bool = False, force: bool = False) -> str:
    global _last_capture
    if not enabled(asleep=asleep):
        return ""
    config = load_config()
    interval = max(5, int(config.get("screen_monitor_capture_interval_seconds", 30)))
    now = time.time()
    if not force and now - _last_capture < interval:
        return _read_text(SUMMARY_FILE)
    _last_capture = now
    try:
        from silva.media.screenshot import capture_screen

        _frame, screenshot = capture_screen(save=True)
    except Exception:
        summary = "Screen capture is unavailable right now."
        _write_text(SUMMARY_FILE, summary)
        return summary

    summary = f"Screen activity captured at {time.strftime('%Y-%m-%d %H:%M:%S')}."
    command = str(config.get("screen_monitor_analyzer_command") or "").strip()
    if command and screenshot is not None:
        try:
            args = shlex.split(command) + [str(screenshot)]
            result = subprocess.run(args, capture_output=True, text=True, timeout=20, shell=False)
            text = " ".join((result.stdout or "").split())
            if text:
                summary = text[:600]
        except Exception:
            pass
    _write_text(SUMMARY_FILE, summary)
    return summary


def capture_video_frame(video_path: str) -> str:
    if not video_enabled():
        return ""
    config = load_config()
    try:
        from silva.media.screenshot import capture_screen

        _frame, screenshot = capture_screen(save=True)
    except Exception:
        return ""
    summary = f"Watched frame from {Path(video_path).name} at {time.strftime('%Y-%m-%d %H:%M:%S')}."
    command = str(config.get("screen_monitor_analyzer_command") or "").strip()
    if command and screenshot is not None:
        try:
            args = shlex.split(command) + [str(screenshot)]
            result = subprocess.run(args, capture_output=True, text=True, timeout=20, shell=False)
            text = " ".join((result.stdout or "").split())
            if text:
                summary = text[:600]
        except Exception:
            pass
    return summary


def _append_video_note(user_id: str, note: str) -> None:
    if not note:
        return
    with _LOCK:
        state = _load_state()
        active = state.get("active")
        if not isinstance(active, dict):
            return
        if _user_key(str(active.get("user_id") or "")) != _user_key(user_id):
            return
        notes = active.setdefault("notes", [])
        if not isinstance(notes, list):
            notes = []
            active["notes"] = notes
        notes.append(note[:600])
        del notes[:-40]
        _save_state(state)


def _video_capture_loop(user_id: str, video_path: str) -> None:
    key = _user_key(user_id)
    _video_stop.discard(key)
    config = load_config()
    interval = max(5, int(config.get("video_watch_capture_interval_seconds", 20)))
    while key not in _video_stop and video_enabled():
        note = capture_video_frame(video_path)
        _append_video_note(user_id, note)
        for _ in range(interval):
            if key in _video_stop:
                return
            time.sleep(1)


def stop_video_watch(user_id: str = "") -> bool:
    key = _user_key(user_id)
    _video_stop.add(key)
    thread = _video_threads.pop(key, None)
    with _LOCK:
        state = _load_state()
        active = state.get("active")
        if not isinstance(active, dict):
            return thread is not None
        if user_id and _user_key(str(active.get("user_id") or "")) != key:
            return thread is not None
        state.pop("active", None)
        _save_state(state)
    return True


def answer_video(assistant, text: str) -> bool:
    try:
        from silva.commands.video_learning import answer_video_query

        reply = answer_video_query(text)
    except Exception:
        reply = "I don't have a saved video in that category yet."
    speak = getattr(assistant, "say", None)
    if callable(speak):
        speak(reply, interruptible=False)
    return True


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip() if path.exists() else ""
    except OSError:
        return ""


def answer_what_am_i_doing(*, asleep: bool = False) -> str:
    summary = _read_text(SUMMARY_FILE)
    if not summary:
        summary = capture_activity(asleep=asleep, force=True)
    if not summary:
        return "Screen monitoring is not approved."
    return f"You're on your screen with: {summary}"


def select_video_path() -> str:
    try:
        import tkinter as tk
        from tkinter import filedialog

        from silva.gui.display_host import host_root

        root = host_root() or tk.Tk()
        path = filedialog.askopenfilename(
            parent=root,
            title="Choose the video Silva should watch with you",
            filetypes=(("Video files", "*.mp4 *.mkv *.avi *.mov *.webm *.wmv"), ("All files", "*.*")),
        )
        if root is not tk._default_root:
            try:
                root.withdraw()
            except tk.TclError:
                pass
        return str(path or "")
    except Exception:
        return ""


def begin_video_session(path: str, *, user_id: str = "", title: str = "") -> bool:
    if not video_enabled() or not path:
        return False
    candidate = Path(path)
    if not candidate.exists() or not candidate.is_file():
        return False
    key = _user_key(user_id)
    _video_stop.discard(key)
    state = _load_state()
    state["active"] = {
        "video_path": str(candidate),
        "video_title": " ".join(str(title or candidate.stem).split()),
        "user_id": key,
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "notes": [],
        "spoken": ["I'm watching with you and will save what I learn."],
    }
    _save_state(state)
    note = capture_video_frame(str(candidate))
    _append_video_note(user_id, note)
    thread = threading.Thread(
        target=_video_capture_loop,
        args=(user_id, str(candidate)),
        name=f"silva-video-watch-{key}",
        daemon=True,
    )
    _video_threads[key] = thread
    thread.start()
    return True


def finish_video_session(transcript: str, *, user_id: str = "", reply: str = "") -> bool:
    state = _load_state()
    active = state.get("active")
    if not isinstance(active, dict) or not video_enabled():
        return False
    key = _user_key(user_id)
    _video_stop.add(key)
    _video_threads.pop(key, None)
    notes = " ".join(str(item) for item in (active.get("notes") or []) if item)
    value = " ".join(str(transcript or "").split())
    if not value:
        value = notes
    if not value:
        return False
    title = str(active.get("video_title") or Path(str(active.get("video_path") or "")).stem)
    spoken = " ".join(
        str(item) for item in (active.get("spoken") or []) if item
    )
    combined_reply = " ".join(part for part in (spoken, reply) if part)
    _write_text(WORDS_FILE, value)
    try:
        from silva.commands.video_learning import remember_video

        saved = remember_video(
            user_id,
            title,
            value,
            reply=combined_reply,
            source=str(active.get("video_path") or "screen while you watched"),
        )
        log_info(f"Saved video learning in {saved['category']}: {saved['topic']}")
    except Exception as exc:
        log_error("Video learning save failed", exc=exc)
    try:
        from silva.conversation.crosschat_memory import observe_speech

        observe_speech(value, user_id=user_id)
    except Exception:
        pass
    state["last_session"] = active
    state["last_session"]["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    state["last_session"]["words"] = value[:4000]
    state.pop("active", None)
    _save_state(state)
    command = str(load_config().get("screen_monitor_video_style_command") or "").strip()
    if command:
        try:
            args = shlex.split(command) + [str(WORDS_FILE)]
            subprocess.run(args, capture_output=True, text=True, timeout=60, shell=False)
        except Exception:
            pass
    return True


def request_transcript(assistant, user_id: str) -> None:
    _pending_transcript[_user_key(user_id)] = "waiting"
    assistant.say(
        "Tell me the video title and what you heard or learned, and I'll save it in the right category.",
        interruptible=False,
    )
    if not bool(getattr(assistant, "_voice_mode", True)):
        from silva.gui.text_input_popup import show_text_input_popup

        show_text_input_popup(
            "Silva video notes",
            "Type the video title and what you heard or learned:",
            lambda value: finish_video_session(value, user_id=user_id),
            width=620,
        )


def parse_screen_monitor_speech(text: str) -> dict | None:
    value = str(text or "").strip()
    if not value:
        return None
    if _APPROVE_RE.search(value):
        return {"action": "approve"}
    try:
        from silva.commands.video_learning import (
            is_confirmed_download_request,
            is_explicit_download_request,
            is_video_query,
        )

        if is_confirmed_download_request(value):
            return {"action": "download-confirm"}
        if is_explicit_download_request(value):
            return {"action": "download"}
        if video_enabled() and is_video_query(value):
            return {"action": "video-query"}
    except Exception:
        pass
    if not (enabled() or video_enabled()):
        return None
    if _END_VIDEO_RE.search(value):
        return {"action": "finish"}
    if _START_VIDEO_RE.search(value):
        return {"action": "start"}
    if enabled() and _WHAT_RE.search(value):
        return {"action": "what"}
    return None


def handle_screen_monitor_speech(assistant, text: str, *, asleep: bool = False) -> bool:
    getter = getattr(assistant, "_user_id", None)
    user_id = getter() if callable(getter) else "guest"
    key = _user_key(user_id)
    value = str(text or "").strip()
    if (
        (_START_VIDEO_RE.search(value) or _END_VIDEO_RE.search(value))
        and not video_enabled()
    ):
        assistant.say(
            "Video watch needs owner approval. Say approve screen monitoring if you're the owner.",
            interruptible=False,
        )
        return True
    action = parse_screen_monitor_speech(value)
    kind = str(action.get("action") or "") if action else ""

    if key in _pending_transcript and action is None:
        _pending_transcript.pop(key, None)
        ok = finish_video_session(value, user_id=user_id)
        speak = getattr(assistant, "_say_while_asleep", None) if asleep else assistant.say
        if callable(speak):
            speak("Saved that video in the right category." if ok else "I couldn't save those notes.", interruptible=False)
        return True

    if key in _pending_download and kind not in {"download-confirm", "download"}:
        _pending_download.discard(key)
        assistant.say("No download was started. Nothing was downloaded.", interruptible=False)

    if action is None:
        return False
    if kind == "approve":
        ok = approve(user_id)
        assistant.say("Screen monitoring is approved." if ok else "Only the owner can approve screen monitoring.", interruptible=False)
        return True
    if kind in {"download", "download-confirm"}:
        from silva.commands.video_learning import (
            download_confirmation_reply,
            download_declined_reply,
        )

        if kind == "download-confirm" and key in _pending_download:
            _pending_download.discard(key)
            assistant.say(download_declined_reply(), interruptible=False)
            return True
        if kind == "download":
            _pending_download.add(key)
            assistant.say(download_confirmation_reply(), interruptible=False)
            return True
        assistant.say("No download was started. Nothing was downloaded.", interruptible=False)
        return True
    if kind == "video-query":
        return answer_video(assistant, value)
    if kind == "what":
        summary = answer_what_am_i_doing(asleep=asleep)
        speak = getattr(assistant, "_say_while_asleep", None) if asleep else assistant.say
        if callable(speak):
            speak(summary, interruptible=False)
        return True
    if kind == "start":
        path = select_video_path()
        if not path:
            assistant.say("No video was selected. Nothing was opened.", interruptible=False)
            return True
        ok = begin_video_session(path, user_id=user_id)
        assistant.say(
            "I'll watch with you without opening or controlling the video. Say video finished when it's done."
            if ok
            else "I couldn't start that video session.",
            interruptible=False,
        )
        return True
    if kind == "finish":
        request_transcript(assistant, user_id)
        return True
    return False


def is_screen_monitor_command(text: str) -> bool:
    value = str(text or "")
    if _APPROVE_RE.search(value):
        return True
    if _START_VIDEO_RE.search(value) or _END_VIDEO_RE.search(value):
        return True
    return parse_screen_monitor_speech(value) is not None
