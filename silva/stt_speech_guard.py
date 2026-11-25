"""Detect coughs, sneezes, and speech struggles so Silva waits instead of interrupting."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
import speech_recognition as sr

from silva.config import load_config


class DisruptionKind(str, Enum):
    NONE = "none"
    COUGH_SNEEZE = "cough_sneeze"
    STUTTER = "stutter"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class SpeechAnalysis:
    kind: DisruptionKind
    should_wait: bool
    should_stay_silent: bool


def _speech_guard_enabled() -> bool:
    return bool(load_config().get("speech_guard_enabled", True))


def _audio_samples(audio: sr.AudioData) -> np.ndarray:
    width = audio.sample_width
    if width == 2:
        dtype = np.int16
    elif width == 4:
        dtype = np.int32
    else:
        dtype = np.int8
    return np.frombuffer(audio.get_raw_data(), dtype=dtype).astype(np.float32)


def _frame_rms(samples: np.ndarray, *, frame_size: int) -> list[float]:
    if len(samples) < frame_size:
        return []
    values: list[float] = []
    for index in range(0, len(samples) - frame_size + 1, frame_size):
        chunk = samples[index : index + frame_size]
        values.append(float(np.sqrt(np.mean(chunk * chunk))))
    return values


def analyze_audio(audio: sr.AudioData | None) -> SpeechAnalysis:
    if audio is None or not _speech_guard_enabled():
        return SpeechAnalysis(DisruptionKind.NONE, False, False)

    samples = _audio_samples(audio)
    if len(samples) < 400:
        return SpeechAnalysis(DisruptionKind.NONE, False, False)

    frame_size = max(1, int(audio.sample_rate * 0.05))
    rms = _frame_rms(samples, frame_size=frame_size)
    if not rms:
        return SpeechAnalysis(DisruptionKind.NONE, False, False)

    median = float(np.median(rms))
    if median <= 0:
        return SpeechAnalysis(DisruptionKind.NONE, False, False)

    tail = rms[-max(4, int(1.0 / 0.05)) :]
    tail_peak = max(tail)
    spike_frames = sum(1 for value in tail if value > median * 4)

    if tail_peak > max(600.0, median * 5) and 1 <= spike_frames <= 8:
        return SpeechAnalysis(DisruptionKind.COUGH_SNEEZE, True, False)

    if len(rms) > 24:
        speech_window = rms[len(rms) // 5 : 4 * len(rms) // 5]
        speech_level = float(np.median(speech_window)) if speech_window else median
        if speech_level > 80:
            quiet_tail = sum(1 for value in tail if value < speech_level * 0.35)
            burst_tail = sum(1 for value in tail if value > speech_level * 0.75)
            if quiet_tail >= 2 and burst_tail >= 2:
                return SpeechAnalysis(DisruptionKind.STUTTER, True, False)

    return SpeechAnalysis(DisruptionKind.NONE, False, False)


def mark_stay_silent(analysis: SpeechAnalysis) -> SpeechAnalysis:
    return SpeechAnalysis(
        kind=DisruptionKind.UNCERTAIN if analysis.kind == DisruptionKind.NONE else analysis.kind,
        should_wait=False,
        should_stay_silent=True,
    )


def detect_receding_audio(audio: sr.AudioData | None) -> bool:
    if audio is None or not bool(load_config().get("stt_movement_guard_enabled", True)):
        return False

    samples = _audio_samples(audio)
    if len(samples) < 800:
        return False

    frame_size = max(1, int(audio.sample_rate * 0.05))
    rms = _frame_rms(samples, frame_size=frame_size)
    if len(rms) < 12:
        return False

    tail_seconds = float(load_config().get("stt_movement_tail_seconds", 0.8))
    drop_ratio = float(load_config().get("stt_movement_drop_ratio", 0.35))
    min_body = float(load_config().get("stt_movement_min_body_rms", 120.0))
    tail_frames = max(2, min(len(rms), int(tail_seconds / 0.05)))
    body = rms[: max(1, len(rms) - tail_frames)]
    tail = rms[-tail_frames:]

    body_level = float(np.percentile(body, 75)) if body else 0.0
    tail_level = float(np.median(tail))
    if body_level < min_body or tail_level > body_level * drop_ratio:
        return False

    midpoint = len(tail) // 2
    early = float(np.median(tail[:midpoint])) if midpoint else tail_level
    late = float(np.median(tail[midpoint:])) if midpoint else tail_level
    return late <= early
