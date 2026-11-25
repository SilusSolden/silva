"""Stay-active script: Silva keeps running in sleep unless you close the window or say goodbye.

A detached watchdog watches the Silva process. If it dies while sleep mode was on,
and you did not stop it on purpose, the watchdog starts Silva again still asleep.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from silva.config import CONFIG_DIR, load_config
from silva.logger import log_info

KEEP_DIR = CONFIG_DIR / "keep_alive"
HEARTBEAT_FILE = KEEP_DIR / "heartbeat.txt"
STOP_FILE = KEEP_DIR / "stop.flag"
SLEEP_FILE = KEEP_DIR / "sleep.flag"
WATCHDOG_PID_FILE = KEEP_DIR / "watchdog.pid"
RESTART_FILE = KEEP_DIR / "last_restart.txt"

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000

_handler_ref = None


def configure_paths(root: Path) -> None:
    """Point keep-alive files at a folder (tests)."""
    global KEEP_DIR, HEARTBEAT_FILE, STOP_FILE, SLEEP_FILE, WATCHDOG_PID_FILE, RESTART_FILE
    KEEP_DIR = Path(root)
    HEARTBEAT_FILE = KEEP_DIR / "heartbeat.txt"
    STOP_FILE = KEEP_DIR / "stop.flag"
    SLEEP_FILE = KEEP_DIR / "sleep.flag"
    WATCHDOG_PID_FILE = KEEP_DIR / "watchdog.pid"
    RESTART_FILE = KEEP_DIR / "last_restart.txt"


def keep_alive_enabled() -> bool:
    if os.environ.get("SILVA_KEEP_ALIVE", "1").strip().lower() in {"0", "false", "no"}:
        return False
    if "unittest" in sys.modules:
        return False
    return bool(load_config().get("keep_alive_enabled", True))


def _ensure_dir() -> None:
    KEEP_DIR.mkdir(parents=True, exist_ok=True)


def _write(path: Path, text: str) -> None:
    _ensure_dir()
    path.write_text(text, encoding="utf-8")


def beat(*, pid: int | None = None) -> None:
    _write(HEARTBEAT_FILE, f"{int(pid or os.getpid())}:{time.time():.0f}")


def mark_running() -> None:
    try:
        STOP_FILE.unlink(missing_ok=True)
    except OSError:
        pass
    beat()


def mark_sleep_active() -> None:
    _write(SLEEP_FILE, "1")
    beat()


def clear_sleep_active() -> None:
    try:
        SLEEP_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def mark_clean_stop() -> None:
    _write(STOP_FILE, "1")
    clear_sleep_active()
    try:
        from silva.crash_record import record_clean_exit

        record_clean_exit()
    except Exception:
        pass


def sleep_should_stay_active() -> bool:
    return SLEEP_FILE.exists() and not STOP_FILE.exists()


def _watchdog_python() -> str:
    exe = Path(sys.executable)
    if exe.name.lower() == "python.exe":
        candidate = exe.with_name("pythonw.exe")
        if candidate.is_file():
            return str(candidate)
    return str(exe)


def _watchdog_alive() -> bool:
    if not WATCHDOG_PID_FILE.exists():
        return False
    try:
        pid = int(WATCHDOG_PID_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    from silva.instance import _process_alive

    return bool(pid and pid != os.getpid() and _process_alive(pid))


def start_watchdog(silva_pid: int | None = None) -> None:
    """Detach a watcher so closing the console does not kill the stay-active script."""
    if not keep_alive_enabled():
        return
    if _watchdog_alive():
        return
    pid = int(silva_pid or os.getpid())
    _ensure_dir()
    flags = 0
    if sys.platform == "win32":
        flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        if Path(_watchdog_python()).name.lower() == "python.exe":
            flags |= CREATE_NO_WINDOW
    try:
        import subprocess

        from silva.launch import ROOT

        subprocess.Popen(
            [_watchdog_python(), "-m", "silva.keep_alive", "--watch", str(pid)],
            cwd=str(ROOT),
            creationflags=flags,
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log_info("Stay-active watchdog started.")
    except Exception as exc:
        log_info(f"Stay-active watchdog did not start: {exc}")


def install_console_stop_handler() -> None:
    """Closing the window or Ctrl+C counts as a manual stop — do not auto-restart."""
    if sys.platform != "win32":
        return
    global _handler_ref
    try:
        import ctypes

        Handler = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)

        def _handler(_ctrl_type: int) -> int:
            mark_clean_stop()
            return 0

        _handler_ref = Handler(_handler)
        ctypes.windll.kernel32.SetConsoleCtrlHandler(_handler_ref, True)
    except Exception:
        pass


def _restart_silva() -> None:
    from silva.instance import silva_is_running
    from silva.launch import start_silva_process

    if STOP_FILE.exists() or not SLEEP_FILE.exists():
        return
    if silva_is_running():
        return
    now = time.time()
    try:
        last = float(RESTART_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        last = 0.0
    wait = 20.0 - (now - last)
    if wait > 0:
        time.sleep(wait)
        if silva_is_running() or STOP_FILE.exists() or not SLEEP_FILE.exists():
            return
    _write(RESTART_FILE, f"{time.time():.0f}")
    log_info("Stay-active: Silva stopped during sleep — starting it again.")
    start_silva_process(["--resume-sleep"])


def watch_loop(silva_pid: int) -> int:
    from silva.instance import _process_alive

    _ensure_dir()
    _write(WATCHDOG_PID_FILE, str(os.getpid()))
    try:
        while _process_alive(silva_pid):
            time.sleep(3.0)
        if STOP_FILE.exists() or not SLEEP_FILE.exists():
            return 0
        time.sleep(1.5)
        _restart_silva()
        return 0
    finally:
        try:
            if WATCHDOG_PID_FILE.exists() and WATCHDOG_PID_FILE.read_text(encoding="utf-8").strip() == str(
                os.getpid()
            ):
                WATCHDOG_PID_FILE.unlink(missing_ok=True)
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) >= 2 and args[0] == "--watch":
        try:
            pid = int(args[1])
        except ValueError:
            return 1
        return watch_loop(pid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
