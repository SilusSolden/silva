from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from silva.config import CONFIG_DIR

DEV_BRANCH_DIR = CONFIG_DIR / "backups" / "dev_branch"
DEV_BRANCH_META = DEV_BRANCH_DIR / "dev_branch_meta.json"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def prepare_dev_branch() -> Path:
    from silva.dev.codebase_backup import copy_project_to

    path = copy_project_to(DEV_BRANCH_DIR)
    DEV_BRANCH_DIR.mkdir(parents=True, exist_ok=True)
    DEV_BRANCH_META.write_text(
        json.dumps({"path": str(path), "updated_at": _now()}, indent=2),
        encoding="utf-8",
    )
    return path


def dev_branch_path() -> Path:
    return DEV_BRANCH_DIR


def run_dev_branch_checks() -> tuple[bool, str]:
    if not (DEV_BRANCH_DIR / "tests").exists():
        prepare_dev_branch()
    try:
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
            cwd=str(DEV_BRANCH_DIR),
            capture_output=True,
            text=True,
            timeout=600,
        )
    except Exception as exc:
        return False, f"Dev branch checks could not run: {exc}"
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode == 0, output[-5000:]
