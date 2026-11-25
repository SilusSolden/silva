"""Control video and media playback on Windows (global media keys)."""

from __future__ import annotations

import sys

import ctypes

KEYEVENTF_KEYUP = 0x0002
VK_MEDIA_PLAY_PAUSE = 0xAD
VK_MEDIA_STOP = 0xB2


def _send_media_key(vk: int) -> None:
    user32 = ctypes.windll.user32
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def _toggle_play_pause() -> tuple[bool, str]:
    try:
        _send_media_key(VK_MEDIA_PLAY_PAUSE)
        return True, "Toggled play/pause for the active video or music."
    except OSError as exc:
        return False, str(exc)


def pause_playback() -> tuple[bool, str]:
    if sys.platform != "win32":
        return False, "Video playback control only works on Windows."
    ok, message = _toggle_play_pause()
    if ok:
        return True, "Paused the video."
    return False, message


def play_playback() -> tuple[bool, str]:
    if sys.platform != "win32":
        return False, "Video playback control only works on Windows."
    ok, message = _toggle_play_pause()
    if ok:
        return True, "Playing the video."
    return False, message


def toggle_playback() -> tuple[bool, str]:
    if sys.platform != "win32":
        return False, "Video playback control only works on Windows."
    return _toggle_play_pause()


def stop_playback() -> tuple[bool, str]:
    if sys.platform != "win32":
        return False, "Video playback control only works on Windows."
    try:
        _send_media_key(VK_MEDIA_STOP)
        return True, "Stopped playback."
    except OSError as exc:
        return False, str(exc)
