"""Store pronunciation references for any word and remember how each recording sounded."""

from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from silva.config import CONFIG_DIR

STORE_DIR = CONFIG_DIR / "word_pronunciations"
_LOCK = threading.Lock()
_WORD_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class PronunciationClip:
    id: str
    wav_file: str
    created_at: str
    label: str = ""

    @property
    def path(self) -> Path:
        return Path(self.wav_file)


@dataclass(frozen=True)
class WordPronunciation:
    word: str
    clip_id: str
    wav_file: str
    spoken_as: str
    updated_at: str
    variant_id: str = ""
    context: str = ""
    active: bool = False


def normalize_word(text: str) -> str:
    raw = (text or "").strip().lower().replace("'", "")
    raw = _WORD_RE.sub(" ", raw)
    return re.sub(r"\s+", " ", raw).strip()


def normalize_spoken(text: str) -> str:
    raw = (text or "").strip()
    raw = re.sub(r"\s+", " ", raw)
    return raw.strip(" ,.-")


_SKIP_WORDS = frozenset({"the", "a", "an", "to", "of", "and", "or", "ok", "okay", "um", "uh", "please"})


def pick_single_word(heard: str, expected: str | None = None) -> str:
    """Keep the target word or phrase only. 'live live' becomes just live."""
    tokens = [token for token in normalize_word(heard).split() if token]
    want = normalize_word(expected or "")
    want_tokens = [token for token in want.split() if token]
    if len(want_tokens) == 1:
        return want_tokens[0]
    if len(want_tokens) > 1:
        return want
    if not tokens:
        return ""
    content = [token for token in tokens if token not in _SKIP_WORDS]
    use = content or tokens
    if len(set(use)) == 1:
        return use[0]
    counts: dict[str, int] = {}
    for token in use:
        counts[token] = counts.get(token, 0) + 1
    return max(counts, key=lambda token: (counts[token], -use.index(token)))


def pick_spoken_form(heard: str, expected: str | None = None) -> str:
    """Keep what the recording sounded like, without forcing it to the target word."""
    raw = normalize_spoken(heard)
    tokens = [token for token in normalize_word(raw).split() if token and token not in _SKIP_WORDS]
    if not tokens:
        return normalize_word(expected or "")
    if len(set(tokens)) == 1:
        return tokens[0]
    return " ".join(tokens)


def _user_dir(user_id: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", (user_id or "default").strip()) or "default"
    return STORE_DIR / safe


def _index_path(user_id: str) -> Path:
    return _user_dir(user_id) / "index.json"


def _empty_index() -> dict:
    return {"clips": [], "words": {}}


def _load_index(user_id: str) -> dict:
    path = _index_path(user_id)
    if not path.exists():
        return _empty_index()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_index()
    if not isinstance(data, dict):
        return _empty_index()
    clips = data.get("clips")
    words = data.get("words")
    if not isinstance(clips, list):
        clips = []
    if not isinstance(words, dict):
        words = {}
    normalized: dict[str, list[dict]] = {}
    for word, payload in words.items():
        key = normalize_word(str(word))
        if not key:
            continue
        if isinstance(payload, list):
            variants = [dict(item) for item in payload if isinstance(item, dict)]
        elif isinstance(payload, dict):
            variants = [dict(payload)]
        elif isinstance(payload, str) and payload.strip():
            variants = [{"clip_id": payload.strip(), "spoken_as": "", "updated_at": ""}]
        else:
            variants = []
        if variants:
            normalized[key] = variants
    return {"clips": clips, "words": normalized}


def _save_index(user_id: str, index: dict) -> None:
    directory = _user_dir(user_id)
    directory.mkdir(parents=True, exist_ok=True)
    _index_path(user_id).write_text(json.dumps(index, indent=2), encoding="utf-8")


def _clip_from_entry(entry: dict) -> PronunciationClip | None:
    if not isinstance(entry, dict):
        return None
    clip_id = str(entry.get("id", "")).strip()
    wav_file = str(entry.get("wav_file", "")).strip()
    if not clip_id or not wav_file:
        return None
    return PronunciationClip(
        id=clip_id,
        wav_file=wav_file,
        created_at=str(entry.get("created_at", "")),
        label=str(entry.get("label", "")),
    )


def _variant_from_entry(word: str, entry: dict, clips: dict[str, dict]) -> WordPronunciation | None:
    clip_id = str(entry.get("clip_id", "")).strip()
    clip = clips.get(clip_id) or {}
    return WordPronunciation(
        word=word,
        clip_id=clip_id,
        wav_file=str(clip.get("wav_file", "")),
        spoken_as=pick_spoken_form(str(entry.get("spoken_as", "")), word) or word,
        updated_at=str(entry.get("updated_at", "")),
        variant_id=str(entry.get("variant_id", "")) or clip_id,
        context=str(entry.get("context", "")),
        active=bool(entry.get("active", False)),
    )


def list_clips(user_id: str) -> list[PronunciationClip]:
    with _LOCK:
        index = _load_index(user_id)
    rows: list[PronunciationClip] = []
    for entry in index.get("clips", []):
        clip = _clip_from_entry(entry)
        if clip is not None:
            rows.append(clip)
    rows.sort(key=lambda item: item.created_at, reverse=True)
    return rows


def get_clip(user_id: str, clip_id: str) -> PronunciationClip | None:
    wanted = str(clip_id or "").strip()
    if not wanted:
        return None
    for clip in list_clips(user_id):
        if clip.id == wanted:
            return clip
    return None


def list_word_maps(user_id: str) -> list[WordPronunciation]:
    with _LOCK:
        index = _load_index(user_id)
    clips = {str(item.get("id")): item for item in index.get("clips", []) if isinstance(item, dict)}
    rows: list[WordPronunciation] = []
    for word, variants in index.get("words", {}).items():
        key = normalize_word(str(word))
        if not key:
            continue
        for entry in variants:
            row = _variant_from_entry(key, entry, clips)
            if row is not None and row.clip_id:
                rows.append(row)
    rows.sort(key=lambda item: (item.word, -_timestamp_key(item.updated_at), item.variant_id))
    return rows


def _timestamp_key(value: str) -> int:
    digits = re.sub(r"\D", "", str(value or ""))
    return int(digits[:14]) if digits else 0


def repair_word_maps(user_id: str) -> None:
    """Normalize saved variant text without collapsing distinct pronunciations."""
    changed = False
    with _LOCK:
        index = _load_index(user_id)
        for word, variants in index.get("words", {}).items():
            key = normalize_word(str(word))
            if not key:
                continue
            for entry in variants:
                spoken = pick_spoken_form(str(entry.get("spoken_as", "")), key) or key
                if spoken != str(entry.get("spoken_as", "")).strip():
                    entry["spoken_as"] = spoken
                    changed = True
        if changed:
            _save_index(user_id, index)


def word_clip_paths(user_id: str) -> dict[str, Path]:
    repair_word_maps(user_id)
    mapping: dict[str, Path] = {}
    chosen: dict[str, WordPronunciation] = {}
    for item in list_word_maps(user_id):
        path = Path(item.wav_file)
        if not item.word or not path.is_file():
            continue
        current = chosen.get(item.word)
        if current is None or item.active or (not current.active and item.updated_at >= current.updated_at):
            chosen[item.word] = item
            mapping[item.word] = path
    return mapping


def active_word_variants() -> list[WordPronunciation]:
    """All usable pronunciation variants for the active user, newest first."""
    try:
        from silva.users.manager import get_active_user

        user = get_active_user() or {}
        user_id = str(user.get("id") or "").strip()
        if not user_id or user_id == "guest":
            return []
        repair_word_maps(user_id)
        rows = [row for row in list_word_maps(user_id) if Path(row.wav_file).is_file()]
        rows.sort(key=lambda item: (item.word, -_timestamp_key(item.updated_at), item.variant_id))
        return rows
    except Exception:
        return []


def transcribe_clip(wav_file) -> str:
    """Listen to the WAV and return the words that were heard."""
    path = Path(wav_file)
    if not path.is_file():
        return ""
    try:
        from silva.audio_recorder import VoiceRecorder

        audio = VoiceRecorder.load_wav(path)
        import speech_recognition as sr

        recognizer = sr.Recognizer()
        heard = recognizer.recognize_google(audio)
    except Exception:
        return ""
    return normalize_spoken(heard)


def trim_wav_to_speech(wav_file, *, pad_ms: int = 80) -> None:
    """Keep only the spoken part of the WAV so extra silence is not used."""
    import struct
    import wave

    path = Path(wav_file)
    if not path.is_file():
        return
    try:
        with wave.open(str(path), "rb") as handle:
            channels = handle.getnchannels()
            width = handle.getsampwidth()
            rate = handle.getframerate() or 16000
            raw = handle.readframes(handle.getnframes())
    except Exception:
        return
    if width != 2 or channels < 1 or len(raw) < 4:
        return
    sample_count = len(raw) // (width * channels)
    if sample_count <= 0:
        return
    if channels == 1:
        samples = struct.unpack(f"{sample_count}h", raw[: sample_count * 2])
    else:
        interleaved = struct.unpack(f"{sample_count * channels}h", raw[: sample_count * channels * 2])
        samples = interleaved[0::channels]
    threshold = 450
    start = 0
    for index, value in enumerate(samples):
        if abs(value) >= threshold:
            start = index
            break
    else:
        return
    speech_min = int(rate * 0.12)
    silence_needed = int(rate * 0.28)
    max_keep = int(rate * 1.15)
    loud_run = 0
    quiet_run = 0
    heard_enough = False
    burst_end = min(len(samples), start + max_keep)
    for index in range(start, min(len(samples), start + max_keep + silence_needed)):
        if abs(samples[index]) >= threshold:
            loud_run += 1
            quiet_run = 0
            if loud_run >= speech_min:
                heard_enough = True
            burst_end = index + 1
        else:
            quiet_run += 1
            if heard_enough and quiet_run >= silence_needed:
                break
    pad = int(rate * pad_ms / 1000)
    start = max(0, start - pad)
    end = min(len(samples), burst_end + pad, start + max_keep)
    if end - start < int(rate * 0.12):
        return
    piece = samples[start:end]
    payload = struct.pack(f"{len(piece)}h", *piece)
    try:
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(rate)
            handle.writeframes(payload)
    except Exception:
        return


def word_spoken_forms(user_id: str) -> dict[str, str]:
    forms: dict[str, str] = {}
    for item in list_word_maps(user_id):
        if not item.word:
            continue
        current = forms.get(item.word)
        if current is None or item.active:
            forms[item.word] = pick_spoken_form(item.spoken_as, item.word) or item.word
    return forms


def active_spoken_forms() -> dict[str, str]:
    try:
        from silva.users.manager import get_active_user

        user = get_active_user() or {}
        user_id = str(user.get("id") or "").strip()
        if not user_id or user_id == "guest":
            return {}
        return word_spoken_forms(user_id)
    except Exception:
        return {}


def remember_word_from_clip(
    user_id: str,
    clip_id: str,
    expected_word: str | None = None,
    *,
    context: str = "",
) -> WordPronunciation:
    """Save the target word plus how this recording actually sounded."""
    clip = get_clip(user_id, clip_id)
    if clip is None or not Path(clip.wav_file).is_file():
        raise RuntimeError("The recording was not saved.")
    trim_wav_to_speech(clip.wav_file)
    heard = transcribe_clip(clip.wav_file)
    word = normalize_word(expected_word or "") or pick_spoken_form(heard)
    spoken = pick_spoken_form(heard, word) or word
    if not word:
        raise RuntimeError("I did not hear a word. Say only the word, then save.")
    return assign_word(user_id, word, clip.id, spoken_as=spoken, context=context)


def save_clip_from_wav(user_id: str, source_wav, *, label: str = "") -> PronunciationClip:
    source = Path(source_wav)
    if not source.is_file():
        raise RuntimeError("No WAV file was saved.")
    clip_id = uuid.uuid4().hex[:12]
    directory = _user_dir(user_id)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{clip_id}.wav"
    target.write_bytes(source.read_bytes())
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = {
        "id": clip_id,
        "wav_file": str(target),
        "created_at": now,
        "label": (label or "").strip(),
    }
    with _LOCK:
        index = _load_index(user_id)
        index.setdefault("clips", []).append(entry)
        _save_index(user_id, index)
    return PronunciationClip(
        id=clip_id,
        wav_file=str(target),
        created_at=now,
        label=entry["label"],
    )


def new_clip_path(user_id: str) -> tuple[str, Path]:
    clip_id = uuid.uuid4().hex[:12]
    directory = _user_dir(user_id)
    directory.mkdir(parents=True, exist_ok=True)
    return clip_id, directory / f"{clip_id}.wav"


def register_clip(user_id: str, clip_id: str, wav_file, *, label: str = "") -> PronunciationClip:
    path = Path(wav_file)
    if not path.is_file():
        raise RuntimeError("The recording was not saved as a WAV file.")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = {
        "id": clip_id,
        "wav_file": str(path),
        "created_at": now,
        "label": (label or "").strip(),
    }
    with _LOCK:
        index = _load_index(user_id)
        clips = [item for item in index.get("clips", []) if not (isinstance(item, dict) and item.get("id") == clip_id)]
        clips.append(entry)
        index["clips"] = clips
        _save_index(user_id, index)
    return PronunciationClip(id=clip_id, wav_file=str(path), created_at=now, label=entry["label"])


def assign_word(
    user_id: str,
    word: str,
    clip_id: str,
    *,
    spoken_as: str | None = None,
    context: str = "",
    replace: bool = False,
) -> WordPronunciation:
    key = normalize_word(word)
    if not key:
        raise RuntimeError("Type or say the word or phrase this recording should replace.")
    clip = get_clip(user_id, clip_id)
    if clip is None or not Path(clip.wav_file).is_file():
        raise RuntimeError("Pick a saved WAV recording first.")
    spoken = pick_spoken_form(spoken_as or "", key) or key
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    variant_id = uuid.uuid4().hex[:12]
    with _LOCK:
        index = _load_index(user_id)
        words = index.setdefault("words", {})
        variants = [] if replace else list(words.get(key, []))
        for entry in variants:
            if str(entry.get("clip_id", "")).strip() == clip.id and pick_spoken_form(
                str(entry.get("spoken_as", "")), key
            ) == spoken:
                for other in variants:
                    other["active"] = other is entry
                entry["updated_at"] = now
                variant_id = str(entry.get("variant_id", "")) or clip.id
                break
        else:
            for entry in variants:
                entry["active"] = False
            variants.append(
                {
                    "variant_id": variant_id,
                    "clip_id": clip.id,
                    "spoken_as": spoken,
                    "context": normalize_spoken(context),
                    "updated_at": now,
                    "active": True,
                }
            )
        words[key] = variants
        _save_index(user_id, index)
    return WordPronunciation(
        word=key,
        clip_id=clip.id,
        wav_file=clip.wav_file,
        spoken_as=spoken,
        updated_at=now,
        variant_id=variant_id,
        context=normalize_spoken(context),
        active=True,
    )


def set_active_variant(user_id: str, word: str, variant_id: str) -> bool:
    key = normalize_word(word)
    wanted = str(variant_id or "").strip()
    if not key or not wanted:
        return False
    with _LOCK:
        index = _load_index(user_id)
        variants = list(index.get("words", {}).get(key, []))
        found = False
        for entry in variants:
            match = str(entry.get("variant_id", "")) or str(entry.get("clip_id", ""))
            entry["active"] = match == wanted
            found = found or match == wanted
        if not found:
            return False
        index.setdefault("words", {})[key] = variants
        _save_index(user_id, index)
    return True


def remove_variant(user_id: str, word: str, variant_id: str) -> bool:
    key = normalize_word(word)
    wanted = str(variant_id or "").strip()
    if not key or not wanted:
        return False
    with _LOCK:
        index = _load_index(user_id)
        words = index.setdefault("words", {})
        variants = list(words.get(key, []))
        kept: list[dict] = []
        found = False
        for entry in variants:
            match = str(entry.get("variant_id", "")) or str(entry.get("clip_id", ""))
            if match == wanted:
                found = True
                continue
            kept.append(entry)
        if not found:
            return False
        if kept and not any(entry.get("active") for entry in kept):
            kept[-1]["active"] = True
        if kept:
            words[key] = kept
        else:
            words.pop(key, None)
        _save_index(user_id, index)
    return True


def unassign_word(user_id: str, word: str) -> bool:
    key = normalize_word(word)
    if not key:
        return False
    with _LOCK:
        index = _load_index(user_id)
        words = index.setdefault("words", {})
        if key not in words:
            return False
        del words[key]
        _save_index(user_id, index)
    return True


def delete_clip(user_id: str, clip_id: str) -> bool:
    wanted = str(clip_id or "").strip()
    if not wanted:
        return False
    removed_path = ""
    with _LOCK:
        index = _load_index(user_id)
        kept: list[dict] = []
        found = False
        for entry in index.get("clips", []):
            if isinstance(entry, dict) and str(entry.get("id")) == wanted:
                found = True
                removed_path = str(entry.get("wav_file", ""))
                continue
            if isinstance(entry, dict):
                kept.append(entry)
        if not found:
            return False
        index["clips"] = kept
        words = index.setdefault("words", {})
        kept_words: dict[str, list[dict]] = {}
        for word, variants in words.items():
            kept = [
                entry
                for entry in variants
                if not (isinstance(entry, dict) and str(entry.get("clip_id", "")) == wanted)
            ]
            if kept:
                if not any(entry.get("active") for entry in kept):
                    kept[-1]["active"] = True
                kept_words[str(word)] = kept
        index["words"] = kept_words
        _save_index(user_id, index)
    if removed_path:
        Path(removed_path).unlink(missing_ok=True)
    return True
