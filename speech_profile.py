"""Learn speaking patterns from user input to adapt Silva's voice."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from silva.config import CONFIG_DIR
from silva.users.manager import get_active_user

PROFILE_DIR = CONFIG_DIR / "speech_profiles"


def _profile_path(user_id: str) -> Path:
    return PROFILE_DIR / f"{user_id}.json"


def _default_profile() -> dict:
    return {
        "input_count": 0,
        "avg_words_per_utterance": 8.0,
        "preferred_tts_rate": 170,
        "common_words": {},
    }


def _load(user_id: str) -> dict:
    path = _profile_path(user_id)
    if not path.exists():
        return _default_profile()
    try:
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return _default_profile()
        data = json.loads(raw)
        if not isinstance(data, dict):
            return _default_profile()
        return {**_default_profile(), **data}
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return _default_profile()


def _save(user_id: str, profile: dict) -> None:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with open(_profile_path(user_id), "w", encoding="utf-8") as handle:
        json.dump(profile, handle, indent=2)


def observe_input(text: str) -> None:
    """Record how the active user speaks so Silva can adapt over time."""
    user = get_active_user()
    user_id = user.get("id", "guest")
    if user_id == "guest":
        return

    words = re.findall(r"[a-zA-Z']+", text.lower())
    if not words:
        return

    profile = _load(user_id)
    count = profile["input_count"] + 1
    old_avg = float(profile["avg_words_per_utterance"])
    word_count = len(words)
    new_avg = old_avg + ((word_count - old_avg) / count)

    common = Counter(profile.get("common_words", {}))
    common.update(words[:20])

    profile["input_count"] = count
    profile["avg_words_per_utterance"] = round(new_avg, 2)
    profile["common_words"] = dict(common.most_common(40))

    if new_avg <= 6:
        profile["preferred_tts_rate"] = 160
    elif new_avg <= 10:
        profile["preferred_tts_rate"] = 170
    else:
        profile["preferred_tts_rate"] = 180

    _save(user_id, profile)


def get_preferred_tts_rate(default: int = 170) -> int:
    user = get_active_user()
    user_id = user.get("id", "guest")
    if user_id == "guest":
        return default
    profile = _load(user_id)
    return int(profile.get("preferred_tts_rate", default))


def get_user_name() -> str:
    user = get_active_user()
    name = user.get("name", "")
    return name if name != "Guest" else ""
