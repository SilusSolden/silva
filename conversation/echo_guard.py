from __future__ import annotations

import re
import threading
import time
from collections import deque
from difflib import SequenceMatcher

from silva.config import load_config

_DIRECT_RE = re.compile(
    r"\b(?:silva|you)\s+(?:answer|respond|reply|say|repeat)\b|"
    r"\b(?:answer|respond|reply to|repeat|say)\s+(?:that|this|it|them|back)\b",
    re.I,
)
_OTHER_AI_RE = re.compile(
    r"\b(?:alexa|siri|hey google|google assistant|jarvis|chatgpt|copilot|"
    r"gemini|claude|other ai|another ai)\b",
    re.I,
)
_STOP_WORDS = {"a", "an", "the", "is", "are", "to", "and", "that", "this", "it", "you", "my"}

_lock = threading.Lock()
_recent: deque[tuple[float, str]] = deque(maxlen=24)


def _normalize(text: str) -> str:
    words = re.findall(r"[a-z0-9']+", str(text or "").lower())
    return " ".join(word for word in words if word and word not in _STOP_WORDS)


def remember_spoken(text: str) -> None:
    normalized = _normalize(text)
    if not normalized:
        return
    with _lock:
        _recent.append((time.time(), normalized))


def forget_spoken() -> None:
    with _lock:
        _recent.clear()


def is_direct_answer_request(text: str) -> bool:
    return bool(_DIRECT_RE.search(str(text or "")))


def looks_like_self_echo(text: str) -> bool:
    candidate = _normalize(text)
    if not candidate:
        return False
    cutoff = time.time() - 20
    with _lock:
        entries = [(spoken, ratio) for stamp, spoken in _recent if stamp >= cutoff for ratio in [SequenceMatcher(None, candidate, spoken).ratio()]]
    if not entries:
        return False
    best = max(entries, key=lambda item: item[1])[1]
    if best >= 0.86:
        return True
    return any(
        len(spoken) >= 12 and (spoken in candidate or candidate in spoken)
        for spoken, _ratio in entries
    )


def mentions_other_ai(text: str) -> bool:
    return bool(_OTHER_AI_RE.search(str(text or "")))


def evaluate_input(text: str) -> str | None:
    config = load_config()
    if not bool(config.get("speaker_safe_mode", False)):
        return None
    if not bool(config.get("speaker_self_echo_guard", True)):
        return None
    if is_direct_answer_request(text):
        return "direct_answer"
    if mentions_other_ai(text):
        return "other_ai"
    if looks_like_self_echo(text):
        return "self_echo"
    return None
