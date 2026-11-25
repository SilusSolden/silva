"""Per-profile phrase audio samples for silent fallback matching."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import speech_recognition as sr

from silva.audio_export import write_speech_audio
from silva.config import CONFIG_DIR, load_config
from silva.users.voice_id import build_fingerprint, compare_fingerprints

PHRASE_DIR = CONFIG_DIR / "phrase_recordings"

DEFAULT_INTENDED_PHRASES: tuple[str, ...] = (
    "silva wake up",
    "hey silva wake up",
    "silva",
    "hey silva",
    "silva sleep",
    "stop",
    "weather",
    "next few days weather",
    "help",
    "pause the video",
    "play the video",
    "mute chrome",
    "unmute chrome",
    "mute this game",
    "open the phrase recorder",
    "what time is it",
    "tell me the news",
)


@dataclass(frozen=True)
class PhraseSample:
    id: str
    user_id: str
    intended_text: str
    phrase_kind: str
    audio_file: str
    created_at: str


@dataclass(frozen=True)
class PhraseMatch:
    user_id: str
    sample_id: str
    intended_text: str
    phrase_kind: str
    score: float


def _user_dir(user_id: str) -> Path:
    return PHRASE_DIR / user_id


def _index_path(user_id: str) -> Path:
    return _user_dir(user_id) / "index.json"


def _match_threshold() -> float:
    return float(load_config().get("phrase_match_threshold", 0.68))


def phrase_recording_enabled() -> bool:
    return bool(load_config().get("phrase_recording_enabled", True))


def _load_index(user_id: str) -> dict:
    path = _index_path(user_id)
    if not path.exists():
        return {"samples": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("samples"), list):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"samples": []}


def _save_index(user_id: str, index: dict) -> None:
    directory = _user_dir(user_id)
    directory.mkdir(parents=True, exist_ok=True)
    _index_path(user_id).write_text(json.dumps(index, indent=2), encoding="utf-8")


def list_phrase_samples(user_id: str) -> list[PhraseSample]:
    rows: list[PhraseSample] = []
    for item in _load_index(user_id).get("samples", []):
        if not isinstance(item, dict):
            continue
        sample_id = str(item.get("id", "")).strip()
        if not sample_id:
            continue
        rows.append(
            PhraseSample(
                id=sample_id,
                user_id=user_id,
                intended_text=str(item.get("intended_text", "")),
                phrase_kind=str(item.get("phrase_kind", "command")),
                audio_file=str(item.get("audio_file", "")),
                created_at=str(item.get("created_at", "")),
            )
        )
    return rows


def save_phrase_sample(
    user_id: str,
    audio: sr.AudioData,
    *,
    intended_text: str,
    phrase_kind: str = "command",
) -> PhraseSample:
    intended = intended_text.strip().lower()
    if not intended:
        raise RuntimeError("Choose what phrase this recording is for.")

    sample_id = uuid.uuid4().hex[:12]
    directory = _user_dir(user_id)
    directory.mkdir(parents=True, exist_ok=True)
    audio_path = write_speech_audio(audio, directory / f"{sample_id}.mp3")
    fingerprint = build_fingerprint(audio)

    entry = {
        "id": sample_id,
        "intended_text": intended,
        "phrase_kind": phrase_kind,
        "audio_file": audio_path.name,
        "fingerprint": fingerprint,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    index = _load_index(user_id)
    index.setdefault("samples", []).append(entry)
    _save_index(user_id, index)

    return PhraseSample(
        id=sample_id,
        user_id=user_id,
        intended_text=intended,
        phrase_kind=phrase_kind,
        audio_file=audio_path.name,
        created_at=entry["created_at"],
    )


def delete_phrase_sample(user_id: str, sample_id: str) -> bool:
    index = _load_index(user_id)
    kept: list[dict] = []
    removed = False
    for item in index.get("samples", []):
        if not isinstance(item, dict):
            continue
        if str(item.get("id")) == sample_id:
            removed = True
            audio_name = str(item.get("audio_file", ""))
            if audio_name:
                path = _user_dir(user_id) / audio_name
                path.unlink(missing_ok=True)
            continue
        kept.append(item)
    if not removed:
        return False
    index["samples"] = kept
    _save_index(user_id, index)
    return True


def _iter_samples(
    *,
    user_ids: list[str] | None = None,
    phrase_kinds: set[str] | None = None,
):
    from silva.users.manager import load_store

    store = load_store()
    targets = user_ids or list(store.get("users", {}).keys())
    for user_id in targets:
        for item in _load_index(user_id).get("samples", []):
            if not isinstance(item, dict):
                continue
            kind = str(item.get("phrase_kind", "command"))
            if phrase_kinds and kind not in phrase_kinds:
                continue
            fingerprint = item.get("fingerprint")
            if not isinstance(fingerprint, list):
                continue
            yield user_id, item, fingerprint


def match_phrase_recording(
    audio: sr.AudioData | None,
    *,
    active_user_id: str | None = None,
    phrase_kinds: set[str] | None = None,
) -> PhraseMatch | None:
    if audio is None or not phrase_recording_enabled():
        return None

    try:
        probe = build_fingerprint(audio)
    except RuntimeError:
        return None

    threshold = _match_threshold()
    best: PhraseMatch | None = None

    user_order: list[str] = []
    if active_user_id:
        user_order.append(active_user_id)
    from silva.users.manager import load_store

    for user_id in load_store().get("users", {}):
        if user_id not in user_order:
            user_order.append(user_id)

    for user_id in user_order:
        for item, fingerprint in (
            (entry, fp)
            for uid, entry, fp in _iter_samples(user_ids=[user_id], phrase_kinds=phrase_kinds)
        ):
            score = compare_fingerprints(probe, fingerprint)
            if score < threshold:
                continue
            candidate = PhraseMatch(
                user_id=user_id,
                sample_id=str(item.get("id", "")),
                intended_text=str(item.get("intended_text", "")),
                phrase_kind=str(item.get("phrase_kind", "command")),
                score=score,
            )
            if best is None or candidate.score > best.score:
                best = candidate
        if best is not None and best.user_id == active_user_id:
            break

    return best
