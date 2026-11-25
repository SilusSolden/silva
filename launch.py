"""Stream Deck / shortcut entry: start Silva, or show the window if it is already on."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CREATE_NEW_CONSOLE = 0x00000010


def console_python(executable: str | None = None) -> str:
    """pythonw has no window; Stream Deck / shortcuts need python.exe so the console shows."""
    exe = Path(executable or sys.executable)
    if exe.name.lower() == "pythonw.exe":
        candidate = exe.with_name("python.exe")
        if candidate.is_file():
            return str(candidate)
    return str(exe)


def start_silva_process(extra_args: list[str] | None = None) -> None:
    flags = CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    command = [console_python(), "-u", "-m", "silva", "--console"]
    if extra_args:
        command.extend(extra_args)
    subprocess.Popen(
        command,
        cwd=str(ROOT),
        env=env,
        creationflags=flags,
        close_fds=True,
    )


def launch_or_show() -> int:
    """Start Silva with a visible console, or restore the one that is already running."""
    from silva.instance import handoff_to_running, silva_is_running

    if silva_is_running():
        handoff_to_running()
        return 0
    start_silva_process()
    return 0


def main() -> None:
    raise SystemExit(launch_or_show())


if __name__ == "__main__":
    main()
