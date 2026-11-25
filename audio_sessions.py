"""Per-application Windows audio session control via pycaw."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class AudioSessionInfo:
    process_name: str
    display_name: str
    muted: bool


# Spoken names -> process name fragments (without .exe).
APP_ALIASES: dict[str, str] = {
    "google": "chrome",
    "google chrome": "chrome",
    "chrome browser": "chrome",
    "browser": "chrome",
    "firefox": "firefox",
    "edge": "msedge",
    "microsoft edge": "msedge",
    "discord": "discord",
    "spotify": "spotify",
    "steam": "steam",
    "vlc": "vlc",
    "youtube": "chrome",
    "netflix": "chrome",
    "zoom": "zoom",
    "teams": "teams",
    "obs": "obs64",
    "game": "game",
    "video": "video",
    "movie": "movie",
}


def _normalize_token(value: str) -> str:
    text = value.strip().lower()
    text = text.replace("'", "")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _process_key(process_name: str) -> str:
    return process_name.lower().removesuffix(".exe")


def _resolve_query_tokens(query: str) -> list[str]:
    normalized = _normalize_token(query)
    if not normalized:
        return []

    if normalized in APP_ALIASES:
        return [_normalize_token(APP_ALIASES[normalized])]

    tokens = [_normalize_token(part) for part in normalized.split() if part.strip()]
    if not tokens:
        return []

    joined = " ".join(tokens)
    if joined in APP_ALIASES:
        return [_normalize_token(APP_ALIASES[joined])]

    return tokens


def _session_label(process_name: str, display_name: str) -> str:
    label = (display_name or "").strip()
    if label and not label.startswith("@") and label.lower() not in {"system sounds", ""}:
        return label
    return _process_key(process_name)


def _iter_sessions():
    if sys.platform != "win32":
        return

    try:
        from pycaw.pycaw import AudioUtilities
    except Exception:
        return

    try:
        sessions = AudioUtilities.GetAllSessions()
    except Exception:
        return

    for session in sessions or []:
        process = session.Process
        if process is None:
            continue
        try:
            process_name = process.name()
        except Exception:
            continue
        if not process_name:
            continue

        display_name = ""
        try:
            display_name = session.DisplayName or ""
        except Exception:
            pass

        try:
            volume = session.SimpleAudioVolume
            muted = bool(volume.GetMute())
        except Exception:
            continue

        yield session, process_name, display_name, muted, volume


def list_active_audio_sessions() -> list[AudioSessionInfo]:
    rows: list[AudioSessionInfo] = []
    seen: set[str] = set()

    for _session, process_name, display_name, muted, _volume in _iter_sessions():
        key = process_name.lower()
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            AudioSessionInfo(
                process_name=process_name,
                display_name=_session_label(process_name, display_name),
                muted=muted,
            )
        )

    rows.sort(key=lambda row: row.display_name.lower())
    return rows


def _matches_query(process_name: str, display_name: str, tokens: list[str]) -> bool:
    proc = _process_key(process_name)
    label = _normalize_token(_session_label(process_name, display_name))
    haystacks = {proc, label, _normalize_token(process_name)}

    for token in tokens:
        if not token:
            continue
        if any(token in hay for hay in haystacks):
            return True
    return False


def find_sessions_for_query(query: str) -> list[tuple[object, str, str, object]]:
    tokens = _resolve_query_tokens(query)
    if not tokens:
        return []

    matches: list[tuple[object, str, str, object]] = []
    seen: set[str] = set()

    for session, process_name, display_name, _muted, volume in _iter_sessions():
        if not _matches_query(process_name, display_name, tokens):
            continue
        key = process_name.lower()
        if key in seen:
            continue
        seen.add(key)
        matches.append((session, process_name, display_name, volume))

    return matches


def set_session_mute(session_volume, muted: bool) -> bool:
    try:
        session_volume.SetMute(1 if muted else 0, None)
        return True
    except Exception:
        return False


def mute_app(query: str) -> tuple[bool, str]:
    if sys.platform != "win32":
        return False, "App audio control only works on Windows."

    matches = find_sessions_for_query(query)
    if not matches:
        active = list_active_audio_sessions()
        if not active:
            return False, "I do not see any apps playing audio right now."
        names = ", ".join(row.display_name for row in active[:6])
        return False, f"I could not find audio for {query}. Apps with sound now: {names}."

    labels: list[str] = []
    for _session, process_name, display_name, volume in matches:
        if not set_session_mute(volume, True):
            continue
        labels.append(_session_label(process_name, display_name))

    if not labels:
        return False, f"I found {query} but could not mute it."

    if len(labels) == 1:
        return True, f"Muted {labels[0]}. Other apps are still playing."
    joined = ", ".join(labels[:-1]) + f", and {labels[-1]}"
    return True, f"Muted {joined}. Other apps are still playing."


def unmute_app(query: str) -> tuple[bool, str]:
    if sys.platform != "win32":
        return False, "App audio control only works on Windows."

    matches = find_sessions_for_query(query)
    if not matches:
        active = list_active_audio_sessions()
        if not active:
            return False, "I do not see any apps with audio right now."
        names = ", ".join(row.display_name for row in active[:6])
        return False, f"I could not find audio for {query}. Apps with sound now: {names}."

    labels: list[str] = []
    for _session, process_name, display_name, volume in matches:
        if not set_session_mute(volume, False):
            continue
        labels.append(_session_label(process_name, display_name))

    if not labels:
        return False, f"I found {query} but could not unmute it."

    if len(labels) == 1:
        return True, f"Unmuted {labels[0]}."
    joined = ", ".join(labels[:-1]) + f", and {labels[-1]}"
    return True, f"Unmuted {joined}."


def describe_active_audio() -> str:
    if sys.platform != "win32":
        return "App audio control only works on Windows."

    sessions = list_active_audio_sessions()
    if not sessions:
        return "Nothing is playing audio right now."

    lines = ["Apps with audio right now:"]
    for row in sessions:
        state = "muted" if row.muted else "playing"
        lines.append(f"- {row.display_name} ({state})")
    return "\n".join(lines)
