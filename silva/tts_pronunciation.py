"""Prepare text for pyttsx3 — spell tricky words (OpenAI, acronyms) without changing TTS engine."""

from __future__ import annotations

import json
import re
import threading

import requests

from silva.config import CONFIG_DIR, load_config
from silva.logger import log_info

CACHE_FILE = CONFIG_DIR / "cache" / "pronunciation_cache.json"
_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, str] = {}
_LOADED = False

KNOWN: dict[str, str] = {
    "openai": "Open A I",
    "chatgpt": "Chat G P T",
    "gpt": "G P T",
    "gpt-4": "G P T 4",
    "gpt4": "G P T 4",
    "ai": "A I",
    "api": "A P I",
    "cpu": "C P U",
    "gpu": "G P U",
    "wifi": "Wi-Fi",
    "wi-fi": "Wi-Fi",
    "ios": "I O S",
    "macos": "Mac O S",
    "nvidia": "Envidia",
    "github": "Git Hub",
    "youtube": "You Tube",
    "tiktok": "Tik Tok",
    "iphone": "I phone",
    "ipad": "I pad",
    "url": "U R L",
    "html": "H T M L",
    "css": "C S S",
    "json": "Jay son",
    "sql": "S Q L",
    "aws": "A W S",
    "fbi": "F B I",
    "cia": "C I A",
    "nasa": "Nasa",
    "covid": "Co vid",
    "covid-19": "Co vid nineteen",
    "ukraine": "You crane",
    "englewood": "Engle wood",
}

_TOKEN_RE = re.compile(
    r"\b([A-Za-z][A-Za-z0-9+\-]*[A-Za-z0-9]|[A-Z]{2,})\b"
)


def _enabled() -> bool:
    return bool(load_config().get("tts_pronunciation_enabled", True))


def _lookup_enabled() -> bool:
    return bool(load_config().get("tts_pronunciation_lookup_enabled", True))


def _load_cache() -> None:
    global _LOADED, _CACHE
    if _LOADED:
        return
    _LOADED = True
    if not CACHE_FILE.exists():
        return
    try:
        with CACHE_FILE.open(encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            _CACHE = {str(k).lower(): str(v) for k, v in data.items()}
    except (OSError, json.JSONDecodeError):
        _CACHE = {}


def _save_cache() -> None:
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with CACHE_FILE.open("w", encoding="utf-8") as handle:
            json.dump(_CACHE, handle, indent=2)
    except OSError:
        pass


def _split_camel(word: str) -> str:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", word)
    spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", spaced)
    return spaced.strip()


def _spell_acronym(word: str) -> str:
    return " ".join(list(word.upper()))


def _heuristic(word: str) -> str | None:
    key = word.lower()
    if key in KNOWN:
        return KNOWN[key]
    if word.isupper() and 2 <= len(word) <= 6:
        return _spell_acronym(word)
    if re.search(r"[a-z]", word) and re.search(r"[A-Z]", word[1:]):
        spaced = _split_camel(word)
        if spaced != word:
            parts = []
            for part in spaced.split():
                part_key = part.lower()
                if part_key in KNOWN:
                    parts.append(KNOWN[part_key])
                elif part.isupper() and len(part) <= 4:
                    parts.append(_spell_acronym(part))
                else:
                    parts.append(part)
            return " ".join(parts)
    return None


def _clean_phonetic(raw: str) -> str:
    text = raw.strip().strip("/")
    text = text.replace("ˈ", "").replace("ˌ", "")
    text = re.sub(r"[()]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _lookup_online(word: str) -> str | None:
    if not _lookup_enabled():
        return None
    key = word.lower()
    try:
        resp = requests.get(
            f"https://api.dictionaryapi.dev/api/v2/entries/en/{key}",
            timeout=4,
            headers={"User-Agent": "SilvaAssistant/1.0"},
        )
        if resp.status_code == 200:
            payload = resp.json()
            if isinstance(payload, list):
                for entry in payload:
                    for item in entry.get("phonetics", []):
                        text = str(item.get("text", "")).strip()
                        if text:
                            cleaned = _clean_phonetic(text)
                            if cleaned and cleaned.lower() != key:
                                return cleaned
    except Exception:
        pass

    try:
        resp = requests.get(
            "https://clients1.google.com/complete/search",
            params={"client": "dictionary", "q": word, "hl": "en"},
            timeout=4,
            headers={"User-Agent": "SilvaAssistant/1.0"},
        )
        if resp.status_code == 200:
            body = resp.text
            if body.startswith(")]}'"):
                body = body[4:]
            data = json.loads(body)
            if isinstance(data, list) and len(data) > 1:
                entries = data[1]
                if isinstance(entries, list) and entries:
                    first = entries[0]
                    if isinstance(first, list) and len(first) > 2:
                        phonetic = str(first[2]).strip()
                        if phonetic:
                            return _clean_phonetic(phonetic)
    except Exception:
        pass
    return None


def resolve_word(word: str) -> str:
    if not word:
        return word
    _load_cache()
    key = word.lower()
    with _CACHE_LOCK:
        if key in _CACHE:
            return _CACHE[key]

    spoken = _heuristic(word)
    if spoken is None and _lookup_enabled():
        spoken = _lookup_online(word)
    if spoken is None:
        spoken = word

    with _CACHE_LOCK:
        _CACHE[key] = spoken
    _save_cache()
    return spoken


def prefetch_text_async(text: str) -> None:
    if not _enabled():
        return

    def _run() -> None:
        for token in _TOKEN_RE.findall(text):
            if _needs_help(token):
                resolve_word(token)

    threading.Thread(target=_run, name="silva-pronunciation-prefetch", daemon=True).start()


def _needs_help(token: str) -> bool:
    if token.lower() in KNOWN:
        return True
    if token.isupper() and 2 <= len(token) <= 6:
        return True
    if re.search(r"[a-z]", token) and re.search(r"[A-Z]", token[1:]):
        return True
    return any(ch.isdigit() for ch in token)


def _trained_words() -> set[str]:
    try:
        from silva.users.word_pronunciations import active_spoken_forms

        return {str(word).strip().lower() for word in active_spoken_forms() if str(word).strip()}
    except Exception:
        return set()


def _protect_trained_phrases(text: str, trained: set[str]) -> tuple[str, dict[str, str]]:
    protected = text
    placeholders: dict[str, str] = {}
    phrases = sorted((word for word in trained if " " in word), key=lambda word: (-len(word.split()), -len(word)))
    for index, phrase in enumerate(phrases):
        pattern = re.compile(
            r"\b" + r"[\s\-'\u2019]+".join(re.escape(part) for part in phrase.split()) + r"\b",
            re.IGNORECASE,
        )
        key = f"SILVATRAINEDPHRASE{index}"
        protected = pattern.sub(lambda match, key=key: placeholders.setdefault(key, match.group(0)) and key, protected)
    return protected, placeholders


def prepare_for_speech(text: str) -> str:
    if not text:
        return text

    trained = _trained_words()
    if not _enabled():
        return text

    _load_cache()
    protected, placeholders = _protect_trained_phrases(text, trained)

    def replace(match: re.Match[str]) -> str:
        token = match.group(1)
        if token in placeholders:
            return placeholders[token]
        if token.lower() in trained:
            return token
        if not _needs_help(token):
            return token
        return resolve_word(token)

    prepared = _TOKEN_RE.sub(replace, protected)
    if prepared != text:
        log_info("Pronunciation prep applied before speak.")
    return prepared
