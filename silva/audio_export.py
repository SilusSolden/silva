"""Export captured speech to MP3 when ffmpeg is available."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import speech_recognition as sr


def write_speech_audio(audio: sr.AudioData, target: Path) -> Path:
    """Save speech as MP3 when possible, otherwise WAV."""
    target.parent.mkdir(parents=True, exist_ok=True)
    wav_bytes = audio.get_wav_data(convert_rate=16000, convert_width=2)
    mp3_path = target if target.suffix.lower() == ".mp3" else target.with_suffix(".mp3")

    if _write_mp3_via_ffmpeg(wav_bytes, mp3_path):
        return mp3_path

    wav_path = mp3_path.with_suffix(".wav")
    wav_path.write_bytes(wav_bytes)
    return wav_path


def _write_mp3_via_ffmpeg(wav_bytes: bytes, mp3_path: Path) -> bool:
    if not shutil.which("ffmpeg"):
        return False

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
        handle.write(wav_bytes)
        wav_temp = Path(handle.name)

    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(wav_temp),
                "-codec:a",
                "libmp3lame",
                "-qscale:a",
                "4",
                str(mp3_path),
            ],
            capture_output=True,
            check=False,
        )
        return result.returncode == 0 and mp3_path.exists()
    except OSError:
        return False
    finally:
        wav_temp.unlink(missing_ok=True)
