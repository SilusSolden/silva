"""Detect vendor camera programs (Elgato Camera Hub, etc.) without opening the camera."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from silva.logger import log_info

PROGRAM_FILES = [
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
    Path(os.environ.get("LOCALAPPDATA", "")),
]


@dataclass(frozen=True)
class CameraApp:
    label: str
    camera_hints: tuple[str, ...]
    exe_names: tuple[str, ...]
    install_folders: tuple[str, ...]


CAMERA_APPS: tuple[CameraApp, ...] = (
    CameraApp(
        label="Elgato Camera Hub",
        camera_hints=("elgato", "facecam"),
        exe_names=("Camera Hub.exe", "Elgato Camera Hub.exe", "CameraHub.exe"),
        install_folders=("Elgato\\Camera Hub", "Elgato\\CameraHub"),
    ),
    CameraApp(
        label="Elgato 4K Capture Utility",
        camera_hints=("cam link", "elgato"),
        exe_names=("4K Capture Utility.exe", "4KCaptureUtility.exe"),
        install_folders=("Elgato\\4K Capture Utility",),
    ),
)


def _process_names() -> set[str]:
    names: set[str] = set()
    if os.name != "nt":
        return names
    try:
        import ctypes
        from ctypes import wintypes

        TH32CS_SNAPPROCESS = 0x00000002

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260),
            ]

        kernel32 = ctypes.windll.kernel32
        snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snap != -1:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
            while ok:
                names.add(entry.szExeFile.lower())
                ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
            kernel32.CloseHandle(snap)
    except Exception:
        names = set()
    if names:
        return names
    try:
        import subprocess

        result = subprocess.run(
            ["tasklist", "/fo", "csv", "/nh"],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
        )
        for line in result.stdout.splitlines():
            if line.startswith('"'):
                names.add(line.split('","', 1)[0].strip('"').lower())
    except Exception:
        pass
    return names


def app_is_installed(app: CameraApp) -> Path | None:
    for root in PROGRAM_FILES:
        if not root:
            continue
        for folder in app.install_folders:
            path = root / folder
            if path.exists():
                return path
            for exe in app.exe_names:
                candidate = path / exe
                if candidate.exists():
                    return candidate
    return None


def app_is_running(app: CameraApp, processes: set[str] | None = None) -> bool:
    running = processes if processes is not None else _process_names()
    wanted = {name.lower() for name in app.exe_names}
    return any(proc in wanted for proc in running)


def matching_apps(camera_name: str) -> list[CameraApp]:
    lowered = (camera_name or "").lower()
    return [app for app in CAMERA_APPS if any(hint in lowered for hint in app.camera_hints)]


def camera_app_status(camera_name: str) -> dict:
    """installed / running (including minimized) for the camera's own software."""
    processes = _process_names()
    matches = matching_apps(camera_name)
    if not matches:
        return {"label": "", "installed": False, "running": False, "path": ""}
    for app in matches:
        path = app_is_installed(app)
        running = app_is_running(app, processes)
        if path or running:
            if running:
                log_info(f"{app.label} is running (may have the camera).")
            return {
                "label": app.label,
                "installed": bool(path) or running,
                "running": running,
                "path": str(path or ""),
            }
    app = matches[0]
    return {"label": app.label, "installed": False, "running": False, "path": ""}


def hub_busy_message(status: dict) -> str:
    label = status.get("label") or "the camera app"
    return (
        f"{label} is already running, even if it's minimized. "
        "Opening the camera in Silva at the same time can freeze your PC. "
        f"Please exit {label}, then say test the camera again."
    )
