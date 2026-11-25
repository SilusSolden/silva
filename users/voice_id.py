"""Voice fingerprint enrollment, WAV storage, and identification."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import speech_recognition as sr

from silva.config import CONFIG_DIR, load_config

VOICES_DIR = CONFIG_DIR / "voices"


def _match_threshold() -> float:
    return float(load_config().get("voice_match_threshold", 0.72))


def wav_path(user_id: str) -> Path:
    return VOICES_DIR / f"{user_id}.wav"


def fingerprint_path(user_id: str) -> Path:
    return VOICES_DIR / f"{user_id}.fingerprint.json"


def profile_path(user_id: str) -> Path:
    return VOICES_DIR / f"{user_id}.profile.json"


_FP_CACHE: dict[str, tuple[float, list[list[float]]]] = {}


def invalidate_voice_cache(user_id: str | None = None) -> None:
    if user_id is None:
        _FP_CACHE.clear()
        return
    _FP_CACHE.pop(user_id, None)


def _audio_to_array(audio: sr.AudioData) -> np.ndarray:
    raw = audio.get_raw_data(convert_rate=16000, convert_width=2)
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    if len(samples) == 0:
        return samples
    return samples / 32768.0


def _trim_silence(samples: np.ndarray, threshold: float = 0.02) -> np.ndarray:
    if len(samples) < 800:
        return samples
    mag = np.abs(samples)
    loud = np.where(mag >= threshold)[0]
    if len(loud) < 400:
        loud = np.where(mag >= threshold * 0.25)[0]
    if len(loud) < 400:
        return samples
    pad = 1600
    start = max(0, int(loud[0]) - pad)
    end = min(len(samples), int(loud[-1]) + pad)
    trimmed = samples[start:end]
    return trimmed if len(trimmed) >= 800 else samples


def _features_from_samples(samples: np.ndarray) -> list[float]:
    features: list[float] = []
    chunks = np.array_split(samples, 16)
    for chunk in chunks:
        if len(chunk) == 0:
            continue
        features.extend(
            [
                float(np.mean(np.abs(chunk))),
                float(np.std(chunk)),
                float(np.mean(np.abs(np.diff(chunk)))),
            ]
        )

    spectrum = np.abs(np.fft.rfft(samples[: min(len(samples), 16000)]))
    bands = np.array_split(spectrum, 12)
    for band in bands:
        features.append(float(np.mean(band)))
    return features


def build_fingerprint(audio: sr.AudioData) -> list[float]:
    samples = _trim_silence(_audio_to_array(audio))
    if len(samples) < 800:
        raise RuntimeError("Voice sample was too short. Please speak a little longer.")
    return _features_from_samples(samples)


def fingerprints_from_audio(audio: sr.AudioData) -> list[list[float]]:
    samples = _trim_silence(_audio_to_array(audio))
    if len(samples) < 800:
        raise RuntimeError("Voice sample was too short. Please speak a little longer.")
    prints = [_features_from_samples(samples)]
    window = min(len(samples), 32000)
    if len(samples) > window + 800:
        prints.append(_features_from_samples(samples[:window]))
        prints.append(_features_from_samples(samples[-window:]))
    return prints


def _compare(a: list[float], b: list[float]) -> float:
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    length = min(len(va), len(vb))
    if length == 0:
        return 0.0
    va = va[:length]
    vb = vb[:length]
    norm_a = np.linalg.norm(va)
    norm_b = np.linalg.norm(vb)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(va, vb) / (norm_a * norm_b))


def compare_fingerprints(a: list[float], b: list[float]) -> float:
    return _compare(a, b)


def save_voice_profile(
    user_id: str,
    audio: sr.AudioData,
    *,
    name: str,
    wav_file: Path | None = None,
    queue_pending: bool = True,
) -> Path:
    """Write the user's WAV, then listen to that file to build the match print."""
    VOICES_DIR.mkdir(parents=True, exist_ok=True)
    target_wav = wav_file or wav_path(user_id)
    wav_bytes = audio.get_wav_data(convert_rate=16000, convert_width=2)
    target_wav.write_bytes(wav_bytes)

    from silva.audio_recorder import VoiceRecorder
    from silva.logger import log_info

    loaded = VoiceRecorder.load_wav(target_wav)
    prints = fingerprints_from_audio(loaded)
    invalidate_voice_cache(user_id)
    _FP_CACHE[user_id] = (target_wav.stat().st_mtime, prints)

    log_info(f"Wrote voice WAV for {name}: {target_wav} ({len(wav_bytes)} bytes)")

    fingerprint_path(user_id).write_text(
        json.dumps(
            {
                "fingerprint": prints[0],
                "fingerprints": prints,
                "wav_file": str(target_wav),
                "source": "wav",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    profile_path(user_id).write_text(
        json.dumps(
            {
                "user_id": user_id,
                "name": name,
                "wav_file": str(target_wav),
                "saved_at": datetime.now().isoformat(timespec="seconds"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    self_score = _compare(build_fingerprint(audio), prints[0])
    log_info(f"Voice library ready for {name} from {target_wav.name} (self-match {self_score:.2f})")
    if queue_pending:
        try:
            from silva.users.voice_requests import upsert_pending_for_profile

            upsert_pending_for_profile(user_id, name, audio=audio, source_wav=target_wav)
        except Exception as exc:
            log_info(f"Pending voice sample was not queued for {name}: {exc}")
    return target_wav


def load_voice_prints(user_id: str) -> list[list[float]]:
    wav = wav_path(user_id)
    if wav.exists():
        mtime = wav.stat().st_mtime
        cached = _FP_CACHE.get(user_id)
        if cached and cached[0] == mtime:
            return cached[1]
        from silva.audio_recorder import VoiceRecorder

        audio = VoiceRecorder.load_wav(wav)
        prints = fingerprints_from_audio(audio)
        _FP_CACHE[user_id] = (mtime, prints)
        fingerprint_path(user_id).write_text(
            json.dumps(
                {
                    "fingerprint": prints[0],
                    "fingerprints": prints,
                    "wav_file": str(wav),
                    "source": "wav",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return prints

    path = fingerprint_path(user_id)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    prints = data.get("fingerprints")
    if isinstance(prints, list) and prints and isinstance(prints[0], list):
        return [list(item) for item in prints if isinstance(item, list)]
    fp = data.get("fingerprint")
    return [fp] if isinstance(fp, list) else []


def load_fingerprint(user_id: str) -> list[float] | None:
    prints = load_voice_prints(user_id)
    return prints[0] if prints else None


def save_fingerprint(user_id: str, audio: sr.AudioData) -> None:
    save_voice_profile(user_id, audio, name=user_id)


def _ambiguity_margin() -> float:
    return float(load_config().get("voice_match_ambiguity_margin", 0.06))


def _has_voice_file(user_id: str, user: dict) -> bool:
    return bool(user.get("voice_enrolled")) or wav_path(user_id).exists()


def _best_score(probe_prints: list[list[float]], stored: list[list[float]]) -> float:
    best = 0.0
    for probe in probe_prints:
        for item in stored:
            score = _compare(probe, item)
            if score > best:
                best = score
    return best


def rank_voice_matches(
    audio: sr.AudioData, candidates: dict[str, dict]
) -> list[tuple[str, float]]:
    try:
        probe_prints = fingerprints_from_audio(audio)
    except RuntimeError:
        return []

    threshold = _match_threshold()
    scored: list[tuple[str, float]] = []
    for user_id, user in candidates.items():
        if not _has_voice_file(user_id, user):
            continue
        stored = load_voice_prints(user_id)
        if not stored:
            continue
        score = _best_score(probe_prints, stored)
        if score >= threshold:
            scored.append((user_id, score))

    scored.sort(key=lambda item: item[1], reverse=True)
    return scored


def identify_user(
    audio: sr.AudioData, candidates: dict[str, dict]
) -> tuple[str | None, float, str | None]:
    ranked = rank_voice_matches(audio, candidates)
    if not ranked:
        # Return best below threshold for logging
        try:
            probe_prints = fingerprints_from_audio(audio)
        except RuntimeError:
            return None, 0.0, None
        best_id: str | None = None
        best_score = 0.0
        for user_id, user in candidates.items():
            if not _has_voice_file(user_id, user):
                continue
            stored = load_voice_prints(user_id)
            if not stored:
                continue
            score = _best_score(probe_prints, stored)
            if score > best_score:
                best_score = score
                best_id = user_id
        return None, best_score, best_id

    user_id, score = ranked[0]
    return user_id, score, user_id


def is_ambiguous_match(ranked: list[tuple[str, float]]) -> bool:
    if len(ranked) < 2:
        return False
    margin = _ambiguity_margin()
    return ranked[0][1] - ranked[1][1] < margin


def list_enrolled_voice_files() -> list[Path]:
    if not VOICES_DIR.exists():
        return []
    return sorted(VOICES_DIR.glob("*.wav"))
