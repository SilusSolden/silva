"""Open and auto-close briefing text files on Windows."""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

from silva.logger import log_info


def open_briefing_txt(path: Path, *, auto_close_minutes: int) -> None:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(str(path))

    minutes = int(auto_close_minutes)
    if sys.platform == "win32":
        proc = subprocess.Popen(["notepad.exe", str(path)])
        log_info(f"Opened news briefing file: {path}")
        if minutes <= 0:
            return

        def _close() -> None:
            try:
                proc.terminate()
                log_info(f"Closed news briefing viewer after {minutes} minutes.")
            except OSError:
                pass

        closer = threading.Timer(minutes * 60, _close)
        closer.daemon = True
        closer.start()
        return

    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])
    log_info(f"Opened news briefing file: {path}")
