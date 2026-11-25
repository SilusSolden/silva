"""Launch the system default camera and voice recorder apps."""

from __future__ import annotations

import subprocess
import sys

from silva.config import load_config


def profile_capture_seconds() -> int:
    return max(3, int(load_config().get("profile_capture_seconds", 10)))


def _launch_windows(target: str) -> bool:
    try:
        subprocess.Popen(
            ["cmd", "/c", "start", "", target],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except OSError:
        return False


def _launch_mac_app(app_name: str) -> bool:
    try:
        subprocess.Popen(
            ["open", "-a", app_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except OSError:
        return False


def _launch_linux(command: str) -> bool:
    try:
        subprocess.Popen(
            [command],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except OSError:
        return False


def open_default_camera_app() -> bool:
    if sys.platform == "win32":
        for target in (
            "microsoft.windows.camera:",
            r"shell:AppsFolder\Microsoft.WindowsCamera_8wekyb3d8bbwe!App",
        ):
            if _launch_windows(target):
                return True
        return False
    if sys.platform == "darwin":
        for app in ("Photo Booth", "FaceTime"):
            if _launch_mac_app(app):
                return True
        return False
    for app in ("cheese", "guvcview", "webcamoid"):
        if _launch_linux(app):
            return True
    return False


def open_default_voice_recorder_app() -> bool:
    if sys.platform == "win32":
        for target in (
            "microsoft.windows.soundrecorder:",
            r"shell:AppsFolder\Microsoft.WindowsSoundRecorder_8wekyb3d8bbwe!App",
        ):
            if _launch_windows(target):
                return True
        return False
    if sys.platform == "darwin":
        return _launch_mac_app("Voice Memos")
    for app in ("gnome-sound-recorder", "audio-recorder"):
        if _launch_linux(app):
            return True
    return False
