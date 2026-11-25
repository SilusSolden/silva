"""Room voice gating and crowd speech policy for Silva."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

import speech_recognition as sr

from silva.config import load_config

ALLOW = "allow"
HOLD = "hold"
REPLY = "reply"

_YES_RE = re.compile(r"^(?:yes|yeah|yep|yup|sure|there are|there is)\b", re.I)
_NO_RE = re.compile(r"^(?:no|nope|nah|none|there aren t|there are not|there is not)\b", re.I)


@dataclass(frozen=True)
class RoomCheck:
    decision: str
    reply: str = ""
    voice_count: int = 1


@dataclass(frozen=True)
class RoomSnapshot:
    voice_count: int
    main_speaking: bool
    single_clear_voice: bool


def can_listen(user: dict | None) -> bool:
    config = load_config()
    if not bool(config.get("room_voice_gating_enabled", True)):
        return False
    from silva.users.permissions import has_permission
    from silva.users.tiers import PERM_ROOM_AUDIO
    from silva.users.voice_access import can_use_voice_control

    user = user or {}
    if has_permission(user, PERM_ROOM_AUDIO):
        return True
    return can_use_voice_control(user, "room_audio")


def _frame_seconds(audio: sr.AudioData, frame_size: int) -> float:
    return frame_size / max(1, int(audio.sample_rate))


def _slice_audio(audio: sr.AudioData, start: int, end: int) -> sr.AudioData:
    width = int(audio.sample_width)
    raw = audio.get_raw_data()[start * width : end * width]
    return sr.AudioData(raw, audio.sample_rate, audio.sample_width)


def snapshot(audio: sr.AudioData | None, user: dict | None) -> RoomSnapshot:
    if audio is None:
        return RoomSnapshot(1, True, True)
    from silva.stt_speech_guard import _audio_samples, _frame_rms

    config = load_config()
    frame_size = max(400, int(audio.sample_rate * 0.02))
    samples = _audio_samples(audio)
    rms = _frame_rms(samples, frame_size=frame_size)
    if not rms:
        return RoomSnapshot(1, True, True)
    threshold = float(config.get("room_voice_energy_threshold", 180.0))
    seconds_per_frame = _frame_seconds(audio, frame_size)
    max_gap = max(1, int(0.24 / seconds_per_frame))
    min_length = max(1, int(0.1 / seconds_per_frame))
    runs: list[tuple[int, int]] = []
    start: int | None = None
    last_active = -max_gap - 1
    for index, value in enumerate(rms):
        if value < threshold:
            continue
        if start is None or index - last_active > max_gap:
            if start is not None and last_active - start + 1 >= min_length:
                runs.append((start, last_active + 1))
            start = index
        last_active = index
    if start is not None and last_active - start + 1 >= min_length:
        runs.append((start, last_active + 1))
    if not runs:
        return RoomSnapshot(1, True, True)

    user = user or {}
    active_id = str(user.get("id") or "")
    candidates: dict[str, dict] = {}
    try:
        from silva.users.manager import load_store

        candidates = {
            str(key): value for key, value in (load_store().get("users") or {}).items()
        }
    except Exception:
        candidates = {}

    other_ids: set[str] = set()
    unknown = 0
    main_speaking = False
    for begin, end in runs:
        ranked: list[tuple[str, float]] = []
        if candidates:
            try:
                from silva.users.voice_id import rank_voice_matches

                ranked = rank_voice_matches(_slice_audio(audio, begin * frame_size, end * frame_size), candidates)
            except Exception:
                ranked = []
        if ranked:
            speaker_id = str(ranked[0][0])
            if active_id and speaker_id == active_id:
                main_speaking = True
            else:
                other_ids.add(speaker_id)
        else:
            unknown += 1

    count = len(other_ids) + unknown + (1 if main_speaking or not other_ids and not unknown else 0)
    cap = max(2, int(config.get("room_voice_max_speakers", 5)))
    count = min(count, cap)
    return RoomSnapshot(count, main_speaking or not other_ids, count <= 1)


def _camera_active() -> bool:
    config = load_config()
    return bool(
        config.get("camera_active", False)
        or config.get("camera_enabled", False)
        or config.get("allow_webcam_mic", False)
    )


def _set_kids_wait(assistant, voice_count: int) -> None:
    setattr(assistant, "_room_awaiting_kids", True)
    setattr(assistant, "_room_kids_expected", max(1, voice_count))
    setattr(assistant, "_room_kids_replies", {"yes": 0, "no": 0})
    setattr(assistant, "_room_kids_started", time.time())


def record_kids_reply(assistant, text: str) -> bool:
    if not getattr(assistant, "_room_awaiting_kids", False):
        return False
    value = re.sub(r"[^a-z\s]", " ", str(text or "").lower())
    value = re.sub(r"\s+", " ", value).strip()
    replies = getattr(assistant, "_room_kids_replies", {"yes": 0, "no": 0})
    if _YES_RE.search(value):
        replies["yes"] = int(replies.get("yes", 0)) + 1
    elif _NO_RE.search(value):
        replies["no"] = int(replies.get("no", 0)) + 1
    else:
        return True
    setattr(assistant, "_room_kids_replies", replies)
    expected = max(1, int(getattr(assistant, "_room_kids_expected", 1)))
    waited = time.time() - float(getattr(assistant, "_room_kids_started", time.time()))
    timeout = float(load_config().get("room_kids_check_wait_seconds", 8.0))
    if sum(replies.values()) >= expected or waited >= timeout:
        setattr(assistant, "_room_kids_present", bool(replies.get("yes", 0)))
        setattr(assistant, "_room_awaiting_kids", False)
        return False
    return True


def _kids_present(assistant) -> bool:
    try:
        from silva.conversation.safety import is_speaker_safe

        if is_speaker_safe():
            return True
    except Exception:
        pass
    return bool(getattr(assistant, "_room_kids_present", False))


def _crowd_reply(assistant, snapshot: RoomSnapshot) -> str:
    attempts = int(getattr(assistant, "_room_crowd_attempts", 0)) + 1
    setattr(assistant, "_room_crowd_attempts", attempts)
    kids = _kids_present(assistant)
    many = snapshot.voice_count >= 3
    if not kids and attempts >= 2 and not getattr(assistant, "_room_awaiting_kids", False):
        _set_kids_wait(assistant, snapshot.voice_count)
        return "Are there kids in the room? Please answer yes or no."
    if kids:
        return "I can hear more than one of you. One at a time, please."
    if many:
        if attempts == 1:
            return "I hear several of you. Please stop and speak one at a time."
        return "I asked you to stop. One voice at a time."
    if attempts == 1:
        return "I hear someone else talking. Please speak one at a time."
    return "One at a time, please. I cannot answer when voices overlap."


def check_turn(assistant, text: str, audio: sr.AudioData | None) -> RoomCheck:
    if not text or not str(text).strip():
        return RoomCheck(ALLOW)
    try:
        from silva.users.manager import get_active_user

        user = get_active_user()
    except Exception:
        user = {}
    if not can_listen(user):
        return RoomCheck(ALLOW)
    if record_kids_reply(assistant, text):
        return RoomCheck(HOLD)
    room_snapshot = snapshot(audio, user)
    if room_snapshot.single_clear_voice:
        return RoomCheck(ALLOW)
    config = load_config()
    if bool(config.get("room_reply_with_others_enabled", False)):
        return RoomCheck(ALLOW)
    if _camera_active():
        return RoomCheck(HOLD, voice_count=room_snapshot.voice_count)
    if not room_snapshot.main_speaking:
        return RoomCheck(HOLD, voice_count=room_snapshot.voice_count)
    return RoomCheck(REPLY, _crowd_reply(assistant, room_snapshot), room_snapshot.voice_count)
