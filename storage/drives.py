"""Keep extra Silva files on the main drive unless you pick another disk yourself."""

from __future__ import annotations

import ctypes
import os
import re
from dataclasses import dataclass
from pathlib import Path

from silva.config import load_config, save_config
from silva.logger import log_info

DRIVE_REMOVABLE = 2
DRIVE_FIXED = 3

_kernel32 = ctypes.windll.kernel32
_MAIN_ALIASES = {"", "main", "main drive", "nvme", "main nvme", "system", "system drive"}


@dataclass
class DriveInfo:
    letter: str
    root: Path
    total: int
    free: int
    drive_type: int
    is_system: bool

    @property
    def used_ratio(self) -> float:
        if self.total <= 0:
            return 1.0
        return max(0.0, min(1.0, 1.0 - (self.free / self.total)))


class StorageRefused(RuntimeError):
    """Raised when the chosen drive cannot be used."""


def system_root() -> Path:
    letter = os.environ.get("SystemDrive") or "C:"
    if not letter.endswith("\\"):
        letter = letter.rstrip(":") + ":\\"
    return Path(letter)


def _drive_strings() -> list[str]:
    length = _kernel32.GetLogicalDriveStringsW(0, None)
    if not length:
        return []
    buf = ctypes.create_unicode_buffer(length)
    wrote = _kernel32.GetLogicalDriveStringsW(length, buf)
    if not wrote:
        return []
    return [part for part in buf.value.split("\x00") if part]


def _space(root: str) -> tuple[int, int]:
    free = ctypes.c_uint64(0)
    total = ctypes.c_uint64(0)
    total_free = ctypes.c_uint64(0)
    ok = _kernel32.GetDiskFreeSpaceExW(
        ctypes.c_wchar_p(root),
        ctypes.byref(free),
        ctypes.byref(total),
        ctypes.byref(total_free),
    )
    if not ok:
        return 0, 0
    return int(total.value), int(free.value)


def list_drives() -> list[DriveInfo]:
    sys_root = system_root()
    found: list[DriveInfo] = []
    try:
        letters = _drive_strings()
    except Exception:
        letters = []
    if not letters:
        letters = [str(sys_root)]
    for raw in letters:
        root = raw if raw.endswith("\\") else raw + "\\"
        try:
            dtype = int(_kernel32.GetDriveTypeW(ctypes.c_wchar_p(root)))
        except Exception:
            dtype = 0
        if dtype not in {DRIVE_FIXED, DRIVE_REMOVABLE}:
            continue
        total, free = _space(root)
        if total <= 0:
            continue
        path = Path(root)
        found.append(
            DriveInfo(
                letter=path.drive or root[:2],
                root=path,
                total=total,
                free=free,
                drive_type=dtype,
                is_system=path.drive.upper() == sys_root.drive.upper(),
            )
        )
    return found


def folder_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    try:
        for item in path.rglob("*"):
            if item.is_file():
                try:
                    total += item.stat().st_size
                except OSError:
                    continue
    except OSError:
        return total
    return total


def silva_data_root(drive: DriveInfo) -> Path:
    return drive.root / "SilvaData"


def normalize_drive_letter(value: str) -> str:
    text = re.sub(r"\s+", " ", (value or "").strip().lower())
    text = text.replace("\\", "").replace("/", "")
    if text in _MAIN_ALIASES:
        return ""
    match = re.search(r"\b([a-z])\b", text)
    if not match:
        match = re.fullmatch(r"([a-z]):?", text)
    if not match:
        return ""
    return match.group(1).upper() + ":"


def _letter(drive: DriveInfo) -> str:
    return (drive.letter or "").upper()[:2]


def configured_data_letter() -> str:
    return normalize_drive_letter(str(load_config().get("knowledge_data_drive") or ""))


def system_drive() -> DriveInfo | None:
    for drive in list_drives():
        if drive.is_system:
            return drive
    return None


def find_drive(letter: str) -> DriveInfo | None:
    wanted = normalize_drive_letter(letter)
    if not wanted:
        return system_drive()
    for drive in list_drives():
        if _letter(drive) == wanted:
            return drive
    return None


def pick_data_drive(needed: int = 0, *, used_lookup=None) -> DriveInfo | None:
    """Main drive by default. Another disk only if you set it yourself."""
    del needed, used_lookup
    wanted = configured_data_letter()
    if wanted:
        found = find_drive(wanted)
        if found is not None:
            log_info(f"Extra Silva data uses the drive you picked: {wanted}")
            return found
        log_info(f"Chosen data drive {wanted} is not connected; extra files stay on the main drive.")
    drive = system_drive()
    if drive is not None:
        log_info(f"Extra Silva data stays on the main drive {_letter(drive)}")
    return drive


def set_data_drive(value: str) -> str:
    """Remember which disk extra files should use. Empty / main = the NVMe."""
    letter = normalize_drive_letter(value)
    config = load_config()
    config["knowledge_data_drive"] = letter
    save_config(config)
    if not letter:
        return "I'll keep extra files on the main drive."
    if find_drive(letter) is not None:
        return f"I'll save extra files on {letter} from now on."
    return (
        f"I'll use {letter} for extra files when that drive is plugged in. "
        "Until then I'll keep them on the main drive."
    )


def describe_data_drive() -> str:
    wanted = configured_data_letter()
    chosen = pick_data_drive()
    main = _letter(chosen) if chosen is not None else "the main drive"
    if wanted and chosen is not None and _letter(chosen) == wanted:
        return f"Extra files go on {wanted}, the drive you picked."
    if wanted:
        return (
            f"You picked {wanted}, but it isn't plugged in, so extra files are on the main drive for now."
        )
    return (
        f"Extra files stay on the main drive ({main}). "
        "Say use the D drive for extra files if you add another disk yourself."
    )
