"""Silent system-load checks so Silva does not freeze the PC on heavy camera work."""

from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from dataclasses import dataclass

from silva.config import load_config
from silva.logger import log_info

PERF_REFUSAL = (
    "I'm sorry, but this command can't run due to your system performance. "
    "Please close other heavy programs, try on another PC, or upgrade this one."
)

CAMERA_LAG_REFUSAL = (
    "I'm sorry — the camera test was too laggy and used too much of your PC, "
    "so I stopped it before anything could freeze. Close other camera apps "
    "or heavy programs and try again, or use a stronger system."
)


@dataclass
class PerfSnapshot:
    system_cpu: float
    process_cpu: float
    avail_ram_gb: float


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


def _filetime_to_int(value: _FILETIME) -> int:
    return (int(value.dwHighDateTime) << 32) + int(value.dwLowDateTime)


def _system_times() -> tuple[int, int]:
    idle = _FILETIME()
    kernel = _FILETIME()
    user = _FILETIME()
    if not ctypes.windll.kernel32.GetSystemTimes(
        ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
    ):
        return 0, 0
    idle_i = _filetime_to_int(idle)
    busy = _filetime_to_int(kernel) + _filetime_to_int(user) - idle_i
    return busy, idle_i


def _process_times() -> int:
    handle = ctypes.windll.kernel32.GetCurrentProcess()
    creation = _FILETIME()
    exit_time = _FILETIME()
    kernel = _FILETIME()
    user = _FILETIME()
    if not ctypes.windll.kernel32.GetProcessTimes(
        handle,
        ctypes.byref(creation),
        ctypes.byref(exit_time),
        ctypes.byref(kernel),
        ctypes.byref(user),
    ):
        return 0
    return _filetime_to_int(kernel) + _filetime_to_int(user)


def _available_ram_gb() -> float:
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", wintypes.DWORD),
            ("dwMemoryLoad", wintypes.DWORD),
            ("ullTotalPhys", ctypes.c_uint64),
            ("ullAvailPhys", ctypes.c_uint64),
            ("ullTotalPageFile", ctypes.c_uint64),
            ("ullAvailPageFile", ctypes.c_uint64),
            ("ullTotalVirtual", ctypes.c_uint64),
            ("ullAvailVirtual", ctypes.c_uint64),
            ("ullAvailExtendedVirtual", ctypes.c_uint64),
        ]

    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return 8.0
    return float(status.ullAvailPhys) / (1024**3)


def sample_perf(*, interval: float = 0.35) -> PerfSnapshot:
    if os.name != "nt":
        return PerfSnapshot(system_cpu=0.0, process_cpu=0.0, avail_ram_gb=8.0)
    busy1, idle1 = _system_times()
    proc1 = _process_times()
    time.sleep(max(0.15, interval))
    busy2, idle2 = _system_times()
    proc2 = _process_times()
    total = (busy2 + idle2) - (busy1 + idle1)
    system = 0.0 if total <= 0 else max(0.0, min(100.0, 100.0 * (busy2 - busy1) / total))
    elapsed = max(1, int(interval * 10_000_000))  # 100-ns units of wall time
    cores = max(1, int(os.cpu_count() or 1))
    process = max(0.0, min(100.0, 100.0 * (proc2 - proc1) / (elapsed * cores)))
    return PerfSnapshot(system_cpu=system, process_cpu=process, avail_ram_gb=_available_ram_gb())


def _limits() -> dict:
    config = load_config()
    return {
        "enabled": bool(config.get("perf_guard_enabled", True)),
        "system_cpu_max": float(config.get("perf_system_cpu_max", 88.0)),
        "process_cpu_max": float(config.get("perf_camera_process_cpu_max", 20.0)),
        "min_ram_gb": float(config.get("perf_min_ram_gb", 1.0)),
        "max_frame_ms": float(config.get("perf_max_frame_ms", 180.0)),
    }


def guard_camera_command(camera_name: str = "") -> str | None:
    """Silent Hub + load check before any camera grab that could freeze the PC."""
    from silva.media.camera_apps import camera_app_status, hub_busy_message

    status = camera_app_status(camera_name)
    if status.get("running"):
        return hub_busy_message(status)
    if status.get("installed"):
        log_info(f"{status.get('label') or 'Camera app'} is installed and not running.")
    return preflight_heavy("camera")


def preflight_heavy(kind: str = "camera") -> str | None:
    """Silent check. Returns a spoken refusal, or None if it is safe to continue."""
    limits = _limits()
    if not limits["enabled"]:
        return None
    snap = sample_perf()
    log_info(
        f"Perf preflight ({kind}): system {snap.system_cpu:.0f}% "
        f"process {snap.process_cpu:.0f}% ram {snap.avail_ram_gb:.1f}GB"
    )
    if snap.avail_ram_gb < limits["min_ram_gb"]:
        return PERF_REFUSAL
    if snap.system_cpu >= limits["system_cpu_max"]:
        return PERF_REFUSAL
    return None


def camera_test_too_heavy(*, process_cpu: float, frame_ms: float) -> bool:
    limits = _limits()
    if not limits["enabled"]:
        return False
    if process_cpu >= limits["process_cpu_max"]:
        log_info(f"Camera test aborted: process CPU {process_cpu:.0f}%")
        return True
    if frame_ms >= limits["max_frame_ms"]:
        log_info(f"Camera test aborted: frame time {frame_ms:.0f}ms")
        return True
    return False
