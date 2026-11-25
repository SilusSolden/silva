from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from silva.dev.paths import DEV_DIR, ensure_dev_dir

LIVE_CHAT_TITLE = "Silva Live Chat"
LIVE_CHAT_LOCK_FILE = DEV_DIR / "live_chat_popup.lock"
LIVE_CHAT_REQUEST_FILE = DEV_DIR / "live_chat_popup_request.json"
LIVE_CHAT_NOTIFY_FILE = DEV_DIR / "live_chat_popup_notify.json"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x00100000, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _release_lock() -> None:
    try:
        if LIVE_CHAT_LOCK_FILE.exists():
            current = int(LIVE_CHAT_LOCK_FILE.read_text(encoding="utf-8").strip())
            if current == os.getpid():
                LIVE_CHAT_LOCK_FILE.unlink(missing_ok=True)
    except (OSError, ValueError):
        LIVE_CHAT_LOCK_FILE.unlink(missing_ok=True)


def _focus_window(title: str) -> bool:
    if sys.platform != "win32":
        return False
    import ctypes

    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        return False
    user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    return True


def focus_existing_live_chat() -> bool:
    return _focus_window(LIVE_CHAT_TITLE) or _focus_window("(new message) " + LIVE_CHAT_TITLE)


def request_live_chat_popup(*, user_id: str | None = None, reason: str = "") -> None:
    ensure_dev_dir()
    LIVE_CHAT_REQUEST_FILE.write_text(
        json.dumps(
            {
                "user_id": str(user_id or ""),
                "reason": str(reason or ""),
                "requested_at": uuid.uuid4().hex,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def consume_live_chat_request() -> dict:
    if not LIVE_CHAT_REQUEST_FILE.exists():
        return {}
    try:
        data = json.loads(LIVE_CHAT_REQUEST_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    try:
        LIVE_CHAT_REQUEST_FILE.unlink(missing_ok=True)
    except OSError:
        pass
    return data if isinstance(data, dict) else {}


def notify_live_chat_popup(message: str, *, user_id: str | None = None) -> None:
    ensure_dev_dir()
    LIVE_CHAT_NOTIFY_FILE.write_text(
        json.dumps(
            {
                "message": str(message or ""),
                "user_id": str(user_id or ""),
                "requested_at": uuid.uuid4().hex,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def consume_live_chat_notification() -> dict:
    if not LIVE_CHAT_NOTIFY_FILE.exists():
        return {}
    try:
        data = json.loads(LIVE_CHAT_NOTIFY_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    try:
        LIVE_CHAT_NOTIFY_FILE.unlink(missing_ok=True)
    except OSError:
        pass
    return data if isinstance(data, dict) else {}


def open_live_chat_popup(*, user_id: str | None = None, reason: str = "") -> bool:
    request_live_chat_popup(user_id=user_id, reason=reason)
    if focus_existing_live_chat():
        return True
    subprocess.Popen(
        [sys.executable, "-m", "silva", "--live-chat"],
        cwd=str(PROJECT_ROOT),
        close_fds=True,
    )
    return True


def acquire_live_chat_instance() -> bool:
    ensure_dev_dir()
    if LIVE_CHAT_LOCK_FILE.exists():
        try:
            pid = int(LIVE_CHAT_LOCK_FILE.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            pid = 0
        if _process_alive(pid):
            return False
        LIVE_CHAT_LOCK_FILE.unlink(missing_ok=True)
    LIVE_CHAT_LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
    import atexit

    atexit.register(_release_lock)
    return True
