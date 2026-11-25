"""Speech training phrases for the dev panel."""

from __future__ import annotations

import json
from datetime import datetime

from silva.dev.paths import SPEECH_TRAINING_FILE, ensure_dev_dir

DEFAULT_TRAINING = {
    "say_phrases": [],
    "dont_say_phrases": [],
    "updated_at": "",
}


def _normalize_lines(text: str) -> list[str]:
    lines = []
    for raw in text.splitlines():
        phrase = raw.strip()
        if phrase and not phrase.startswith("#"):
            lines.append(phrase)
    return lines


def load_speech_training() -> dict:
    ensure_dev_dir()
    if not SPEECH_TRAINING_FILE.exists():
        return DEFAULT_TRAINING.copy()
    try:
        data = json.loads(SPEECH_TRAINING_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {**DEFAULT_TRAINING, **data}
    except (json.JSONDecodeError, OSError):
        pass
    return DEFAULT_TRAINING.copy()


def save_speech_training(*, say_text: str, dont_say_text: str) -> dict:
    ensure_dev_dir()
    payload = {
        "say_phrases": _normalize_lines(say_text),
        "dont_say_phrases": _normalize_lines(dont_say_text),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    SPEECH_TRAINING_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def phrases_to_text(items: list[str]) -> str:
    return "\n".join(items)


def clear_blocked_phrases() -> int:
    data = load_speech_training()
    count = len(data.get("dont_say_phrases") or [])
    data["dont_say_phrases"] = []
    data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    SPEECH_TRAINING_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return count


def is_blocked_phrase(text: str, user_id: str = "") -> bool:
    normalized = text.strip().lower()
    if not normalized:
        return False
    from silva.conversation.speech_policy import allows_unfiltered

    if user_id and allows_unfiltered(user_id):
        return False
    for phrase in load_speech_training().get("dont_say_phrases", []):
        target = str(phrase).strip().lower()
        if not target:
            continue
        if normalized == target or target in normalized:
            return True
    return False


def is_trained_say_phrase(text: str) -> bool:
    normalized = text.strip().lower()
    if not normalized:
        return False
    for phrase in load_speech_training().get("say_phrases", []):
        target = str(phrase).strip().lower()
        if not target:
            continue
        if normalized == target or normalized.startswith(target):
            return True
    return False
