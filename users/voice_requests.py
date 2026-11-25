"""Pending voice samples waiting for owner/admin assignment."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

import speech_recognition as sr

from silva.config import CONFIG_DIR
from silva.users.manager import load_store, update_user_profile
from silva.users.voice_id import save_voice_profile, wav_path

VOICE_REQUESTS_DIR = CONFIG_DIR / "pending_voice_requests"
VOICE_REQUESTS_FILE = CONFIG_DIR / "pending_voice_requests.json"


def _load_requests() -> list[dict]:
    if not VOICE_REQUESTS_FILE.exists():
        return []
    data = json.loads(VOICE_REQUESTS_FILE.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def _save_requests(requests: list[dict]) -> None:
    VOICE_REQUESTS_DIR.mkdir(parents=True, exist_ok=True)
    VOICE_REQUESTS_FILE.write_text(json.dumps(requests, indent=2), encoding="utf-8")


def list_voice_requests(*, pending_only: bool = True) -> list[dict]:
    requests = _load_requests()
    if pending_only:
        return [item for item in requests if item.get("status") == "pending"]
    return requests


def has_enrolled_voices() -> bool:
    store = load_store()
    return any(user.get("voice_enrolled") for user in store["users"].values())


def submit_voice_request(
    audio: sr.AudioData,
    *,
    best_score: float = 0.0,
    best_match_id: str | None = None,
    note: str = "",
    intended_user_id: str | None = None,
    intended_name: str = "",
) -> str:
    return queue_voice_sample(
        audio,
        best_score=best_score,
        best_match_id=best_match_id,
        note=note,
        intended_user_id=intended_user_id,
        intended_name=intended_name,
    )


def queue_voice_sample(
    audio: sr.AudioData | None = None,
    *,
    source_wav: Path | None = None,
    best_score: float = 0.0,
    best_match_id: str | None = None,
    note: str = "",
    intended_user_id: str | None = None,
    intended_name: str = "",
) -> str:
    """Copy a recorded WAV into Pending voice samples so it can be assigned per profile."""
    VOICE_REQUESTS_DIR.mkdir(parents=True, exist_ok=True)
    request_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    wav_file = VOICE_REQUESTS_DIR / f"{request_id}.wav"
    if audio is not None:
        wav_file.write_bytes(audio.get_wav_data(convert_rate=16000, convert_width=2))
    elif source_wav is not None and Path(source_wav).is_file():
        wav_file.write_bytes(Path(source_wav).read_bytes())
    else:
        raise RuntimeError("No voice sample to queue.")

    intended = intended_user_id or best_match_id
    requests = _load_requests()
    requests.append(
        {
            "id": request_id,
            "wav_file": str(wav_file),
            "source_wav": str(source_wav or ""),
            "submitted_at": datetime.now().isoformat(timespec="seconds"),
            "best_score": round(best_score, 3),
            "best_match_id": intended,
            "intended_user_id": intended,
            "intended_name": intended_name.strip(),
            "note": note.strip() or (f"Recorded for {intended_name}" if intended_name else "Recorded voice sample"),
            "status": "pending",
        }
    )
    _save_requests(requests)
    from silva.logger import log_info

    log_info(f"Queued pending voice sample {request_id} for {intended_name or intended or 'unassigned profile'}")
    return request_id


def upsert_pending_for_profile(
    user_id: str,
    name: str,
    *,
    audio: sr.AudioData | None = None,
    source_wav: Path | None = None,
) -> str:
    """Keep one pending sample per profile, auto-selected for that user."""
    if not user_id:
        return queue_voice_sample(
            audio,
            source_wav=source_wav,
            intended_name=name,
            note=f"Recorded for {name}" if name else "Recorded voice sample",
        )
    requests = _load_requests()
    existing = next(
        (
            item
            for item in requests
            if item.get("status") == "pending" and str(item.get("intended_user_id") or "") == user_id
        ),
        None,
    )
    if existing is None:
        return queue_voice_sample(
            audio,
            source_wav=source_wav,
            intended_user_id=user_id,
            intended_name=name,
            best_match_id=user_id,
            note=f"Recorded for {name}",
        )

    VOICE_REQUESTS_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = str(existing.get("wav_file") or "")
    wav_file = Path(raw_path) if raw_path else VOICE_REQUESTS_DIR / f"{existing.get('id', user_id)}.wav"
    if wav_file.suffix.lower() != ".wav":
        wav_file = VOICE_REQUESTS_DIR / f"{existing.get('id', user_id)}.wav"
    existing["wav_file"] = str(wav_file)
    if audio is not None:
        wav_file.write_bytes(audio.get_wav_data(convert_rate=16000, convert_width=2))
    elif source_wav is not None and Path(source_wav).is_file():
        wav_file.write_bytes(Path(source_wav).read_bytes())
    existing["source_wav"] = str(source_wav or existing.get("source_wav") or "")
    existing["intended_user_id"] = user_id
    existing["intended_name"] = name
    existing["best_match_id"] = user_id
    existing["note"] = f"Recorded for {name}"
    existing["submitted_at"] = datetime.now().isoformat(timespec="seconds")
    _save_requests(requests)
    from silva.logger import log_info

    log_info(f"Updated pending voice sample {existing.get('id')} for {name}")
    return str(existing.get("id") or "")


def queue_saved_profile_voices() -> list[str]:
    """If a profile already has a WAV and no pending sample, list it for assignment."""
    queued: list[str] = []
    store = load_store()
    existing = _load_requests()
    known = {
        str(item.get("intended_user_id") or item.get("assigned_user_id") or "")
        for item in existing
        if item.get("intended_user_id") or item.get("assigned_user_id")
    }
    for user in store.get("users", {}).values():
        user_id = str(user.get("id") or "")
        if not user_id or user_id in known:
            continue
        saved = wav_path(user_id)
        if not saved.exists():
            continue
        queued.append(
            upsert_pending_for_profile(
                user_id,
                str(user.get("name") or user_id),
                source_wav=saved,
            )
        )
    return queued


def approve_voice_request(request_id: str, user_id: str, *, approver_id: str) -> bool:
    store = load_store()
    if user_id not in store["users"]:
        return False

    requests = _load_requests()
    entry = next((item for item in requests if item.get("id") == request_id), None)
    if entry is None or entry.get("status") != "pending":
        return False

    wav_file = Path(entry["wav_file"])
    if not wav_file.exists():
        return False

    from silva.audio_recorder import VoiceRecorder

    audio = VoiceRecorder.load_wav(wav_file)
    user = store["users"][user_id]
    save_voice_profile(
        user_id,
        audio,
        name=user["name"],
        wav_file=wav_path(user_id),
        queue_pending=False,
    )
    update_user_profile(user_id, voice_enrolled=True)
    try:
        from silva.users.voice_id import invalidate_voice_cache

        invalidate_voice_cache(user_id)
    except Exception:
        pass

    entry["status"] = "approved"
    entry["assigned_user_id"] = user_id
    entry["approved_by"] = approver_id
    entry["approved_at"] = datetime.now().isoformat(timespec="seconds")
    _save_requests(requests)
    return True


def reject_voice_request(request_id: str, *, rejected_by: str) -> bool:
    requests = _load_requests()
    entry = next((item for item in requests if item.get("id") == request_id), None)
    if entry is None or entry.get("status") != "pending":
        return False

    entry["status"] = "rejected"
    entry["rejected_by"] = rejected_by
    entry["rejected_at"] = datetime.now().isoformat(timespec="seconds")

    wav_file = Path(entry.get("wav_file", ""))
    if wav_file.exists():
        wav_file.unlink()

    _save_requests(requests)
    return True
