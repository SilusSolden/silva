"""Detect spoken requests for game how-tos and in-game information."""

from __future__ import annotations

import re

_FILLER_RE = re.compile(
    r"^(please |silva |hey silva |can you |could you |would you )+",
    re.I,
)

_STRIP_PREFIXES = (
    "look up a game for information on",
    "look up a game for information",
    "look up a game for",
    "look up the game for",
    "look up the game",
    "look up a game",
    "look up how to",
    "look up how",
    "search the internet for",
    "search online for",
    "search for how to",
    "search for",
    "find out how to",
    "find how to",
    "tell me how to",
    "tell me how",
    "tell me about",
    "look up",
    "how do i",
    "how do you",
    "how can i",
    "how to",
    "where do i find",
    "where can i find",
    "where is",
    "what does",
    "information on",
    "info on",
)

_GAME_TOPIC_RE = re.compile(
    r"\b("
    r"games?|walkthrough|speedrun|boss(?:es)?|dungeon|raid|quest|npc|loot|"
    r"achievement|troph(?:y|ies)|fandom|video games?|modded|"
    r"minecraft|fortnite|zelda|elden ring|sons of the forest|skyrim|"
    r"gta|grand theft auto|valorant|roblox|pokemon|pokémon"
    r")\b",
    re.I,
)

_ASK_RE = re.compile(
    r"\b("
    r"how (?:do i|do you|can i|to)|"
    r"where (?:do i|can i) (?:find|get)|"
    r"where is|"
    r"what does|"
    r"look up|search(?: the internet)?(?: for)?|"
    r"tell me|"
    r"guide|walkthrough|information on|info on"
    r")\b",
    re.I,
)

_IN_TITLE_RE = re.compile(
    r"\b(?:how (?:do i|do you|can i|to)|where (?:do i|can i) (?:find|get)|"
    r"where is|what does|look up|search for|tell me how|guide for)\b.+"
    r"\b(?:in|for|on)\s+(?:the\s+)?(?:game\s+)?(?P<title>.{2,60})$",
    re.I | re.S,
)

_STOP_TITLES = frozenset(
    {
        "time",
        "the morning",
        "morning",
        "the afternoon",
        "afternoon",
        "the evening",
        "evening",
        "night",
        "the night",
        "a hurry",
        "english",
        "general",
        "particular",
        "public",
        "private",
        "bed",
        "love",
        "person",
        "fact",
        "order",
        "case",
        "advance",
        "short",
        "total",
        "common",
        "return",
        "trouble",
        "mind",
        "addition",
        "control",
        "a minute",
        "a second",
        "the future",
        "the past",
        "the world",
        "real life",
        "my life",
        "this",
        "that",
        "here",
        "there",
        "town",
        "the city",
        "school",
        "my house",
        "the house",
        "detail",
        "details",
        "lookups",
        "lookup",
        "wikipedia",
        "weather",
        "news",
        "notes",
        "math",
    }
)

_CHAT_BLOCK = (
    "how are you",
    "hows it going",
    "how's it going",
    "how do you feel",
    "how do you say",
    "how do you pronounce",
    "how is the weather",
    "hows the weather",
    "how's the weather",
)


def _normalize(text: str) -> str:
    text = text.strip().lower()
    text = text.replace("'", "")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _title_ok(title: str) -> bool:
    cleaned = _normalize(title)
    if not cleaned or cleaned in _STOP_TITLES:
        return False
    words = cleaned.split()
    if not 1 <= len(words) <= 8:
        return False
    return True


def is_game_lookup(text: str) -> bool:
    if not text or not text.strip():
        return False
    from silva.commands.help_phrases import is_capability_ask, is_feature_detail_ask, is_help_request

    if is_help_request(text) or is_feature_detail_ask(text) or is_capability_ask(text):
        return False
    try:
        from silva.commands.pronunciation_phrases import is_pronunciation_command

        if is_pronunciation_command(text):
            return False
    except Exception:
        pass
    normalized = _normalize(text)
    if any(normalized == block or normalized.startswith(block + " ") for block in _CHAT_BLOCK):
        return False
    if "wikipedia" in normalized:
        return False

    if _GAME_TOPIC_RE.search(normalized) and _ASK_RE.search(normalized):
        return True

    match = _IN_TITLE_RE.search(normalized)
    if match and _title_ok(match.group("title")):
        return True

    return False


def extract_game_query(text: str) -> str:
    raw = _FILLER_RE.sub("", text.strip())
    normalized = _normalize(raw)
    for prefix in _STRIP_PREFIXES:
        prefix_n = _normalize(prefix)
        if normalized.startswith(prefix_n + " "):
            normalized = normalized[len(prefix_n) :].strip()
            break
        if normalized == prefix_n:
            return ""
    return normalized
