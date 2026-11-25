"""Single-instance control for the Silva System Panel."""

from __future__ import annotations

import atexit
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from silva.dev.paths import DEV_DIR, ensure_dev_dir

PANEL_LOCK_FILE = DEV_DIR / "system_panel.lock"
PANEL_FOCUS_FILE = DEV_DIR / "system_panel_focus.json"
PANEL_TITLE = "Silva System Panel"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        synchronize = 0x00100000
        handle = kernel32.OpenProcess(synchronize, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    else:
        return True


def _release_lock() -> None:
    try:
        if PANEL_LOCK_FILE.exists():
            current = int(PANEL_LOCK_FILE.read_text(encoding="utf-8").strip())
            if current == os.getpid():
                PANEL_LOCK_FILE.unlink(missing_ok=True)
    except (OSError, ValueError):
        PANEL_LOCK_FILE.unlink(missing_ok=True)


def focus_existing_panel() -> bool:
    if sys.platform != "win32":
        return False
    import ctypes

    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, PANEL_TITLE)
    if not hwnd:
        return False
    user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    return True


def request_panel_tab(tab_id: str | None = None, title: str | None = None) -> None:
    """Ask the System Panel to focus a tab, whether it is open now or starts later."""
    ensure_dev_dir()
    payload = {
        "tab_id": str(tab_id or ""),
        "title": str(title or ""),
        "requested_at": uuid.uuid4().hex,
    }
    PANEL_FOCUS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def consume_panel_tab_request() -> dict:
    if not PANEL_FOCUS_FILE.exists():
        return {}
    try:
        data = json.loads(PANEL_FOCUS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    try:
        PANEL_FOCUS_FILE.unlink(missing_ok=True)
    except OSError:
        pass
    return data if isinstance(data, dict) else {}


def open_system_panel(*, tab_id: str | None = None, title: str | None = None) -> bool:
    request_panel_tab(tab_id, title)
    if focus_existing_panel():
        return True
    subprocess.Popen(
        [sys.executable, "-m", "silva", "--dev-panel"],
        cwd=str(PROJECT_ROOT),
        close_fds=True,
    )
    return True


def acquire_panel_instance() -> bool:
    """Return True when this process should open the panel."""
    ensure_dev_dir()
    if PANEL_LOCK_FILE.exists():
        try:
            pid = int(PANEL_LOCK_FILE.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            pid = 0
        if _process_alive(pid):
            return False
        PANEL_LOCK_FILE.unlink(missing_ok=True)

    PANEL_LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
    atexit.register(_release_lock)
    return True


def hide_console_window() -> None:
    if sys.platform != "win32":
        return
    import ctypes

    hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    if hwnd:
        ctypes.windll.user32.ShowWindow(hwnd, 0)
