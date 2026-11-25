"""One running Silva. A Stream Deck press shows that window instead of starting a second copy."""

from __future__ import annotations

import atexit
import os
import sys
from pathlib import Path

from silva.config import CONFIG_DIR
from silva.logger import log_info

LOCK_FILE = CONFIG_DIR / "silva.lock"
CONSOLE_TITLE = "Silva Assistant"


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


def _read_lock_pid(path: Path | None = None) -> int:
    lock = path or LOCK_FILE
    if not lock.exists():
        return 0
    try:
        return int(lock.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def _release_lock() -> None:
    try:
        pid = _read_lock_pid()
        if pid == os.getpid() and LOCK_FILE.exists():
            LOCK_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def silva_is_running(*, lock_file: Path | None = None) -> bool:
    pid = _read_lock_pid(lock_file or LOCK_FILE)
    return bool(pid and pid != os.getpid() and _process_alive(pid))


def acquire_silva_instance(*, lock_file: Path | None = None) -> bool:
    """Return True when this process should run Silva."""
    lock = lock_file or LOCK_FILE
    lock.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        pid = _read_lock_pid(lock)
        if pid == os.getpid() and lock.exists():
            return True
        if pid and pid != os.getpid() and _process_alive(pid):
            return False
        try:
            if lock.exists():
                lock.unlink()
        except OSError:
            pass
        try:
            handle = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            continue
        try:
            os.write(handle, str(os.getpid()).encode("utf-8"))
        finally:
            os.close(handle)
        atexit.register(_release_lock)
        return True
    return False


def set_console_title(title: str = CONSOLE_TITLE) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleTitleW(title)
    except Exception:
        pass


def ensure_console() -> None:
    """Give pythonw / Stream Deck a real window so speech and errors can be read."""
    if sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    kernel32.GetConsoleWindow.restype = wintypes.HWND
    if kernel32.GetConsoleWindow():
        set_console_title()
        return
    if not kernel32.AllocConsole():
        return
    try:
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
        sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
        sys.stdin = open("CONIN$", "r", encoding="utf-8", errors="replace")
    except OSError:
        pass
    try:
        os.dup2(sys.stdin.fileno(), 0)
        os.dup2(sys.stdout.fileno(), 1)
        os.dup2(sys.stderr.fileno(), 2)
    except (OSError, AttributeError):
        pass
    set_console_title()


def find_silva_window() -> int:
    if sys.platform != "win32":
        return 0
    import ctypes

    hwnd = ctypes.windll.user32.FindWindowW(None, CONSOLE_TITLE)
    return int(hwnd or 0)


def handoff_to_running() -> bool:
    """Bring the already-running Silva console forward. True if a window was shown."""
    from silva.gui.background_mode import show_console_front

    hwnd = find_silva_window()
    if show_console_front(hwnd or None):
        log_info("Stream Deck / launcher showed the running Silva window.")
        return True
    log_info("Silva is already running, but the console window was not found.")
    return False
