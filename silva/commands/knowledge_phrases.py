"""On-demand web/Wikipedia skims and optional file saves. Never runs unless asked."""

from __future__ import annotations

import re
from dataclasses import dataclass

from silva.commands.game_lookup_phrases import is_game_lookup
from silva.commands.news_phrases import is_news_command
from silva.commands.notes_phrases import is_notes_command


def _normalize(text: str) -> str:
    text = text.strip().lower()
    text = text.replace("'", "")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class KnowledgeSpeech:
    action: str
    query: str = ""
    store: bool = False


_IMPOSSIBLE = (
    "everything on wikipedia",
    "all of wikipedia",
    "entire wikipedia",
    "every wikipedia article",
    "all wikipedia articles",
    "all wikipedia pages",
    "the whole internet",
    "everything on the internet",
    "all information of everything",
    "everything of everything",
    "download wikipedia",
    "copy wikipedia",
    "scrape wikipedia",
    "every page on wikipedia",
)

_MAIN_DRIVE = (
    "use the main drive",
    "use the main drive for extra files",
    "use the main drive for knowledge",
    "keep extra files on the main drive",
    "save extra files on the main drive",
    "put extra files on the main drive",
    "use the main nvme",
    "use the main nvme for extra files",
    "keep extra files on the main nvme",
    "save extra files on the main nvme",
)

_DRIVE_STATUS = (
    "where do you save extra files",
    "where are extra files saved",
    "what drive are extra files on",
    "what drive is knowledge on",
    "where do extra files go",
)

_DRIVE_SET_RE = re.compile(
    r"^(?:please |silva )?(?:use|save|put|keep|store)\s+"
    r"(?:extra files|knowledge|the extra files|stored knowledge)\s+"
    r"(?:on|to|onto)\s+(?:the\s+)?(?:drive\s+)?([a-z])(?:\s+drive)?$",
    re.I,
)
_DRIVE_USE_RE = re.compile(
    r"^(?:please |silva )?use\s+(?:the\s+)?([a-z])\s+drive(?:\s+for\s+(?:extra files|knowledge|stored knowledge))?$",
    re.I,
)

_SAVE_LAST = (
    "save that to a file",
    "store that in a file",
    "save it to a file",
    "store it in a file",
    "put that in a file",
    "write that to a file",
    "save that in a file",
    "store that to a file",
    "save this to a file",
    "put it in a file",
)

_WEB_PREFIXES = (
    "search the web for",
    "search the internet for",
    "search online for",
    "look up on the internet",
    "look up on the web",
    "look it up online",
    "skim the web for",
    "skim the internet for",
    "find me information about",
    "find me information on",
    "find me info about",
    "find me info on",
    "find information about",
    "find information on",
    "find all information about",
    "find all information on",
    "find all information of",
    "look up all information about",
    "look up all information on",
    "look up all information of",
    "look up information about",
    "look up information on",
    "look up information of",
    "look up common knowledge about",
    "common knowledge about",
    "google for",
)

_RETRIEVE_EXACT = (
    "what knowledge did you save",
    "whats my stored knowledge",
    "what is my stored knowledge",
    "show stored knowledge",
    "show my stored knowledge",
    "list stored knowledge",
    "whats on the knowledge drive",
    "what is on the knowledge drive",
    "look in the knowledge files",
    "look in the knowledge drive",
    "retrieve stored knowledge",
    "where did you save that",
    "where is my knowledge saved",
)

_RETRIEVE_PREFIXES = (
    "retrieve",
    "get the stored knowledge about",
    "get stored knowledge about",
    "what did you save about",
    "what did you store about",
    "read the stored file about",
    "look up the stored",
    "open the stored knowledge about",
)

_STORE_RE = re.compile(
    r"\b(store|save|write|put)\b.+\b(file|txt|document)\b"
    r"|\bin (its|their|there|a) own file\b"
    r"|\bto a file\b",
    re.I,
)
_CATALOG_RE = re.compile(
    r"\b(?:find|list|get|save|store|look up)\s+all\s+(.+)$",
    re.I,
)
_INFO_ABOUT_RE = re.compile(
    r"\b(?:find|look up|get|search)\s+(?:all\s+)?(?:information|info|facts|details)\s+(?:about|on|of)\s+(.+)$",
    re.I,
)
_STORE_TAIL_RE = re.compile(
    r"\s+and\s+(?:store|save|write|put)\b.*$|\s+(?:store|save|write|put)\b.+\bfile\b.*$",
    re.I,
)


def _yield_other_commands(text: str) -> bool:
    from silva.commands.help_phrases import is_capability_ask, is_feature_detail_ask, is_help_request

    if is_help_request(text) or is_feature_detail_ask(text) or is_capability_ask(text):
        return True
    if is_notes_command(text) or is_news_command(text) or is_game_lookup(text):
        return True
    return False


def _is_impossible(normalized: str) -> bool:
    if any(phrase in normalized for phrase in _IMPOSSIBLE):
        return True
    if "wikipedia" in normalized and any(
        word in normalized for word in ("everything", "entire", "every article", "all articles", "whole")
    ):
        return True
    if "everything" in normalized and "internet" in normalized:
        return True
    return False


def _strip_store_tail(query: str) -> str:
    cleaned = _STORE_TAIL_RE.sub("", query or "").strip()
    cleaned = re.sub(r"\b(please|silva)\b", " ", cleaned, flags=re.I)
    return re.sub(r"\s+", " ", cleaned).strip(" .,")


def _wants_store(normalized: str) -> bool:
    return bool(_STORE_RE.search(normalized))


def _is_catalog_topic(query: str) -> bool:
    lowered = _normalize(query)
    if not lowered:
        return False
    if re.search(r"\b(information|info|facts|details)\b", lowered):
        return False
    if lowered in {
        "wikipedia",
        "the internet",
        "internet",
        "everything",
        "anything",
        "knowledge",
        "anything on wikipedia",
        "everything on wikipedia",
    }:
        return False
    return True


def _collects_by_default(normalized: str) -> bool:
    if _wants_store(normalized):
        return True
    if re.search(r"\b(look up all|find all|find me information|look up all information)\b", normalized):
        return True
    if re.search(r"\b(information|info|facts|details)\s+(about|on|of)\b", normalized):
        return True
    if re.search(r"\bhow (to|do i|do you) (make|build|craft|form)\b", normalized) and re.search(
        r"\b(look up|find|search|store|save)\b", normalized
    ):
        return True
    return False


def match_knowledge_speech(text: str) -> KnowledgeSpeech | None:
    if not text or not text.strip():
        return None
    if _yield_other_commands(text):
        return None
    normalized = _normalize(text)
    if not normalized:
        return None

    if _is_impossible(normalized):
        return KnowledgeSpeech("impossible")

    if normalized in _MAIN_DRIVE:
        return KnowledgeSpeech("set_drive", "main")
    if normalized in _DRIVE_STATUS:
        return KnowledgeSpeech("drive_status")
    drive_set = _DRIVE_SET_RE.match(normalized) or _DRIVE_USE_RE.match(normalized)
    if drive_set:
        return KnowledgeSpeech("set_drive", drive_set.group(1))

    wants_file = _collects_by_default(normalized)

    if normalized in _SAVE_LAST:
        return KnowledgeSpeech("save_last", store=True)

    if _wants_store(normalized) and normalized in {
        "save that",
        "store that",
        "save it",
        "store it",
    }:
        return KnowledgeSpeech("save_last", store=True)

    if normalized in _RETRIEVE_EXACT:
        return KnowledgeSpeech("retrieve", "")
    for prefix in _RETRIEVE_PREFIXES:
        if normalized == prefix:
            return KnowledgeSpeech("retrieve", "")
        if normalized.startswith(prefix + " "):
            return KnowledgeSpeech("retrieve", normalized[len(prefix) :].strip())

    info = _INFO_ABOUT_RE.search(normalized)
    if info:
        query = _strip_store_tail(info.group(1))
        query = re.sub(r"\bon wikipedia$", "", query).strip()
        if query in {"anything", "everything", "anything on wikipedia"}:
            return KnowledgeSpeech("impossible")
        if query:
            action = "store" if wants_file else "lookup"
            return KnowledgeSpeech(action, query, store=wants_file)

    catalog = _CATALOG_RE.search(normalized)
    if catalog:
        query = _strip_store_tail(catalog.group(1))
        query = re.sub(r"\bon wikipedia$", "", query).strip()
        if query in {"anything", "everything", "information of anything"}:
            return KnowledgeSpeech("impossible")
        if _is_catalog_topic(query):
            return KnowledgeSpeech("catalog", query, store=True)

    for prefix in _WEB_PREFIXES:
        if normalized == prefix:
            return KnowledgeSpeech("lookup", "")
        if normalized.startswith(prefix + " "):
            query = _strip_store_tail(normalized[len(prefix) :].strip())
            query = re.sub(r"\bon wikipedia$", "", query).strip()
            if not query:
                return KnowledgeSpeech("lookup", "")
            if query in {"anything", "everything"}:
                return KnowledgeSpeech("impossible")
            action = "store" if wants_file else "lookup"
            return KnowledgeSpeech(action, query, store=wants_file)

    if _wants_store(normalized):
        query = normalized
        query = re.sub(
            r"^(please |silva |hey silva |can you |could you |would you )+",
            "",
            query,
        )
        query = _strip_store_tail(query)
        query = re.sub(
            r"^(look up|search for|search|find|google)\s+",
            "",
            query,
        )
        query = query.strip()
        if not query or query in {"that", "it", "this", "them"}:
            return KnowledgeSpeech("save_last", store=True)
        return KnowledgeSpeech("store", query, store=True)

    return None


def is_knowledge_command(text: str) -> bool:
    return match_knowledge_speech(text) is not None
