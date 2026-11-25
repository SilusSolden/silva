from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import re

from silva.commands.weather import get_weather
from silva.commands.wikipedia import search_wikipedia

CommandHandler = Callable[[str | None], str]

COMMANDS: dict[str, CommandHandler] = {
    "weather": lambda _query: get_weather(),
    "wikipedia": lambda query: search_wikipedia(query or ""),
}

WEATHER_PHRASES: tuple[str, ...] = (
    "what's my local weather",
    "whats my local weather",
    "what is my local weather",
    "what's the local weather",
    "whats the local weather",
    "what is the local weather",
    "what's my weather",
    "whats my weather",
    "what is my weather",
    "what's the weather",
    "whats the weather",
    "what is the weather",
    "how's my local weather",
    "hows my local weather",
    "how is my local weather",
    "how's the local weather",
    "hows the local weather",
    "how is the local weather",
    "how's my weather",
    "hows my weather",
    "how is my weather",
    "how's the weather",
    "hows the weather",
    "how is the weather",
    "tell me my local weather",
    "tell me the local weather",
    "tell me my weather",
    "tell me the weather",
    "tell me what's my local weather",
    "tell me whats my local weather",
    "can you tell me what's my local weather",
    "can you tell me whats my local weather",
    "can you tell me my local weather",
    "can you tell me the local weather",
    "can you tell me my weather",
    "can you tell me the weather",
    "can you tell me what's the weather",
    "could you tell me the weather",
    "please tell me the weather",
    "please tell me my local weather",
    "give me my local weather",
    "give me the local weather",
    "give me my weather",
    "give me the weather",
    "check my local weather",
    "check the local weather",
    "check my weather",
    "check the weather",
    "get my local weather",
    "get the local weather",
    "get my weather",
    "get the weather",
    "my local weather",
    "the local weather",
    "local weather",
    "my weather",
    "current weather",
    "weather today",
    "weather right now",
    "weather outside",
    "weather now",
    "today's weather",
    "todays weather",
    "weather forecast",
    "local forecast",
    "temperature outside",
    "how hot is it",
    "how cold is it",
    "is it raining",
    "will it rain",
    "weather",
)

WIKIPEDIA_PREFIXES: tuple[str, ...] = (
    "search wikipedia for",
    "search wikipedia about",
    "search wikipedia on",
    "search wikipedia",
    "look up on wikipedia",
    "look up wikipedia",
    "find on wikipedia",
    "find in wikipedia",
    "search for on wikipedia",
    "search for in wikipedia",
    "search for",
    "wikipedia search for",
    "wikipedia search",
    "tell me about",
    "look up",
    "how do you make",
    "how do i make",
    "how to make",
    "how do i build",
    "how to build",
    "how do i form",
    "how to form",
    "how do i craft",
    "how to craft",
    "how do i construct",
    "how to construct",
    "recipe for",
    "steps to make",
    "guide for making",
    "construction steps for",
    "what is",
    "who is",
    "define",
    "wikipedia",
)

WIKIPEDIA_SUFFIXES: tuple[str, ...] = (
    " on wikipedia",
    " from wikipedia",
    " in wikipedia",
)


@dataclass
class CommandMatch:
    name: str
    query: str | None = None


def _normalize(text: str) -> str:
    text = text.strip().lower()
    text = text.replace("'", "")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _match_weather(normalized: str) -> bool:
    from silva.commands.help_phrases import should_yield_to_feature_help

    if should_yield_to_feature_help(normalized):
        return False
    if normalized == "weather":
        return True
    for phrase in WEATHER_PHRASES:
        phrase_norm = _normalize(phrase)
        if phrase_norm == "weather":
            continue
        if normalized == phrase_norm or phrase_norm in normalized:
            return True
    return False


def _extract_wikipedia_query(normalized: str) -> str | None:
    for prefix in WIKIPEDIA_PREFIXES:
        prefix_norm = _normalize(prefix)
        if normalized.startswith(prefix_norm + " "):
            query = normalized[len(prefix_norm) :].strip()
            if query:
                return _strip_wikipedia_suffix(query)
        if normalized == prefix_norm:
            return None

    for suffix in WIKIPEDIA_SUFFIXES:
        suffix_norm = _normalize(suffix)
        if normalized.endswith(suffix_norm):
            query = normalized[: -len(suffix_norm)].strip()
            for prefix in ("look up", "search for", "search", "find"):
                if query.startswith(prefix + " "):
                    query = query[len(prefix) + 1 :].strip()
            if query:
                return query

    return None


_WIKI_CHAT_PREFIXES: tuple[str, ...] = (
    "what is going on",
    "whats going on",
    "what is up",
    "whats up",
    "what is wrong",
    "whats wrong",
    "what is happening",
    "whats happening",
    "what is that",
    "whats that",
    "what is this",
    "whats this",
    "what is it",
    "whats it",
    "what is your",
    "whats your",
    "what is my",
    "whats my",
    "who are you",
    "who am i",
    "tell me about your",
    "tell me about my",
    "tell me about our",
    "tell me about it",
    "search for something",
)


def _wikipedia_should_yield(normalized: str, query: str) -> bool:
    """Don't treat news, weather, game how-tos, or casual chat as a Wikipedia lookup."""
    from silva.commands.game_lookup_phrases import is_game_lookup
    from silva.commands.help_phrases import should_yield_to_feature_help
    from silva.commands.knowledge_phrases import is_knowledge_command
    from silva.commands.notes_phrases import is_notes_command
    from silva.commands.update_phrases import is_update_speech

    if should_yield_to_feature_help(normalized):
        return True
    if is_game_lookup(normalized):
        return True
    if is_notes_command(normalized):
        return True
    if is_knowledge_command(normalized):
        return True
    if is_update_speech(normalized):
        return True
    tokens = set(normalized.split())
    if "update" in tokens and tokens & {"new", "this", "silva", "latest", "newest"}:
        return True
    if tokens & {"news", "headlines", "briefing", "weather", "forecast", "outlook"}:
        return True
    if query in {"your name", "my name", "going on", "up", "wrong", "that", "this", "it", "happening"}:
        return True
    if any(normalized == prefix or normalized.startswith(prefix + " ") for prefix in _WIKI_CHAT_PREFIXES):
        return True
    return False


def _strip_wikipedia_suffix(query: str) -> str:
    for suffix in WIKIPEDIA_SUFFIXES:
        suffix_norm = _normalize(suffix)
        if query.endswith(suffix_norm):
            return query[: -len(suffix_norm)].strip()
    return query


def match_command(text: str) -> CommandMatch | None:
    normalized = _normalize(text)
    if not normalized:
        return None

    from silva.commands.help_phrases import should_yield_to_feature_help

    if should_yield_to_feature_help(text):
        return None

    if _match_weather(normalized):
        return CommandMatch("weather")

    wiki_query = _extract_wikipedia_query(normalized)
    if wiki_query and not _wikipedia_should_yield(normalized, wiki_query):
        return CommandMatch("wikipedia", wiki_query)

    for command in COMMANDS:
        if command == "weather":
            continue
        if command in normalized:
            return CommandMatch(command)

    return None


def run_command(match: CommandMatch) -> str:
    handler = COMMANDS.get(match.name)
    if handler is None:
        raise KeyError(f"Unknown command: {match.name}")
    return handler(match.query)
