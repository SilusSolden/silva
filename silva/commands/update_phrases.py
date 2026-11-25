"""Spoken ways to ask what's new or to apply a live Silva update."""

from __future__ import annotations

import re

_PUNCT_RE = re.compile(r"[^\w\s]")
_SPACE_RE = re.compile(r"\s+")

_WAKE_PREFIXES = (
    "hey silva ",
    "ok silva ",
    "okay silva ",
    "yo silva ",
    "silva ",
    "please ",
    "hey ",
    "all right ",
    "alright ",
    "fine ",
    "okay so ",
    "ok so ",
    "so ",
    "i said ",
    "i asked ",
    "i just said ",
    "now ",
    "can you tell me ",
    "could you tell me ",
    "would you tell me ",
    "can you ",
    "could you ",
    "would you ",
    "tell me ",
)


def _fold(text: str) -> str:
    normalized = text.strip().lower().replace("'", "")
    normalized = _PUNCT_RE.sub(" ", normalized)
    normalized = _SPACE_RE.sub(" ", normalized).strip()
    changed = True
    while changed and normalized:
        changed = False
        for prefix in _WAKE_PREFIXES:
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix) :].strip()
                changed = True
                break
    return normalized


_CHAT_EXACT = frozenset(
    {
        "whats up",
        "what is up",
        "sup",
        "whats going on",
        "what is going on",
        "whats new with you",
        "what is new with you",
        "whats new with ya",
        "how are you",
        "how are you doing",
        "whats the weather",
        "what is the weather",
        "whats the news",
        "what is the news",
        "whats my weather",
        "whats my news",
        "whats my reminder",
        "whats my notes",
        "whats my to do list",
        "whats my todo list",
    }
)

_CHAT_PREFIXES = (
    "whats my ",
    "what is my ",
    "whats the weather",
    "what is the weather",
    "whats the news",
    "what is the news",
    "how is the weather",
)

WHATS_NEW_EXACT = frozenset(
    {
        "whats the new update",
        "what is the new update",
        "whats the newest update",
        "what is the newest update",
        "whats the latest update",
        "what is the latest update",
        "whats the current update",
        "what is the current update",
        "whats new",
        "what is new",
        "whats new silva",
        "what is new silva",
        "whats new in silva",
        "what is new in silva",
        "whats new with silva",
        "what is new with silva",
        "whats new this update",
        "whats new in this update",
        "what is new in this update",
        "whats new in the update",
        "what is new in the update",
        "whats new in that update",
        "what is new in that update",
        "whats new this time",
        "any new features",
        "any new feature",
        "any new updates",
        "any new update",
        "any updates",
        "any update",
        "any patches",
        "any new patches",
        "any changes",
        "anything new",
        "anything new in silva",
        "is there anything new",
        "is there a new update",
        "is there an update",
        "is there a update",
        "did you get an update",
        "did you get a update",
        "did you get updated",
        "have you been updated",
        "were you updated",
        "was there an update",
        "what new features",
        "what new feature",
        "what are the new features",
        "what are the new updates",
        "what features were added",
        "what features got added",
        "what was added",
        "what got added",
        "what did you add",
        "what did the update add",
        "what did this update add",
        "what changed",
        "what was changed",
        "what got changed",
        "what has changed",
        "what changes were made",
        "what was fixed",
        "what got fixed",
        "what did you fix",
        "what bugs were fixed",
        "what bugs did you fix",
        "what issues were fixed",
        "what fixes were added",
        "what was patched",
        "what patches",
        "what patches were added",
        "what patches got added",
        "tell me the new update",
        "tell me about the update",
        "tell me about the new update",
        "tell me whats new",
        "tell me what is new",
        "tell me the changes",
        "tell me the new features",
        "read me the update",
        "read the update",
        "show me the new features",
        "show me the update",
        "show the new update",
        "list the new features",
        "list new features",
        "list the updates",
        "new update",
        "latest update",
        "newest update",
        "current update",
        "silva updates",
        "silva update",
        "check for updates",
        "check updates",
        "check the update",
        "check for a new update",
        "scan for updates",
        "whats the patch",
        "what is the patch",
        "whats the changelog",
        "what is the changelog",
        "whats in the new update",
        "what is in the new update",
        "whats in the update",
        "what is in the update",
        "whats in this update",
        "what is in this update",
        "whats in the last update",
        "what is in the last update",
        "whats in the latest update",
        "what is in the latest update",
        "what was the newest part of the update",
        "what was the newest part of the new update",
        "newest part of the update",
        "latest part of the update",
        "what was recently added",
        "what was added recently",
        "what recently got added",
        "what just got added",
        "what just got updated",
        "what did you just add",
        "what did you just update",
        "what did the last update do",
        "what did this update do",
        "what did the update do",
        "what did we just add",
        "what came in the update",
        "what came in the last update",
        "what was the last update",
        "what was the newest update",
        "what was in the update",
        "what was in the new update",
        "what was in the news update",
        "what was in the last update",
        "what changed in the update",
        "what changed in the last update",
        "tell me whats in the update",
        "tell me what is in the update",
        "tell me whats in the new update",
        "tell me about the last update",
        "tell me about the newest update",
        "what new stuff",
        "what new stuff was added",
        "what did the newest update add",
        "what was added in the newest update",
        "what was added in the new update",
        "what was added in the latest update",
        "what was added in the last update",
        "can you tell me what was added in the newest update",
        "what was in the code that was added",
        "what was in the code that got added",
        "what was in the code",
        "what code was added",
        "what was added in the code",
        "tell me what was in the code",
        "what in the code was added",
        "what got added in the code",
        "what files were added",
        "what files changed",
        "what code changed",
        "what type of code",
        "what type of code was added",
        "what type of code it was added",
        "what the recent thing was added",
        "what the recent thing that was added",
        "can you tell me what the recent thing was added",
        "tell me the code that was added",
        "describe the code",
        "describe the code that was added",
        "whats in the codebase",
        "what is in the codebase",
        "what modules were added",
        "what python files",
        "what python was added",
        "tell me in detail",
        "tell me in more detail",
        "whats in the update in detail",
        "what is in the update in detail",
        "what was added in detail",
        "what was added in more detail",
    }
)

_WHATS_NEW_RE = re.compile(
    r"\b("
    r"what(?:s| is| was)? (?:the |in the )?(?:new(?:est)?|latest|last|current) "
    r"(?:part of (?:the )?)?update|"
    r"what(?:s| is| was)? in (?:the |this |that )?(?:new |latest |last |newest |news )?update|"
    r"(?:newest|latest|last) part of (?:the )?update|"
    r"what was recently added|"
    r"what (?:was |got )?added recently|"
    r"what (?:did you |did the |did this |did we )?(?:just )?(?:add|update|change)|"
    r"what(?:s| is)? new in (?:the |this |that )?(?:last |latest |new )?update|"
    r"what (?:came|changed) in (?:the )?(?:new |last |latest )?update|"
    r"what (?:was |got )?changed|"
    r"what (?:was |got )?fixed|"
    r"what (?:bugs?|issues?) (?:were |got )?fixed|"
    r"what did you fix|"
    r"what fixes were added|"
    r"what was added in (?:the )?(?:new(?:est)?|latest|last )?update|"
    r"what was in the code(?: that (?:was |got )?added)?|"
    r"what (?:code|files?) (?:was |were )?(?:added|changed)|"
    r"what (?:got |was )?added in the code|"
    r"what type of code|"
    r"what the recent thing(?: that)? was added|"
    r"what(?:s| is)? in the codebase|"
    r"describe the code|"
    r"what (?:modules|python files|python) (?:were |was )?(?:added|changed)"
    r")\b",
    re.I,
)

_WHATS_NEW_NEEDLES = (
    "new update",
    "latest update",
    "newest update",
    "current update",
    "new features",
    "new feature",
    "new patches",
    "whats new in silva",
    "what is new in silva",
    "features were added",
    "features got added",
    "what was added",
    "what got added",
    "what did you add",
    "what changed",
    "what has changed",
    "any updates",
    "any patches",
    "changelog",
    "in the new update",
    "in the news update",
    "in the update",
    "newest part of the update",
    "recently added",
    "last update",
    "newest update",
    "in the code",
    "code that was added",
    "added in the newest",
    "added in the new update",
    "type of code",
    "recent thing",
    "codebase",
    "describe the code",
    "details of what was added",
    "details of multiple",
)

APPLY_EXACT = frozenset(
    {
        "update",
        "update now",
        "now update",
        "update silva",
        "silva update now",
        "yes update",
        "yeah update",
        "yep update",
        "yes install",
        "yes apply",
        "apply update",
        "apply the update",
        "apply that update",
        "apply those changes",
        "install update",
        "install the update",
        "do the update",
        "do that update",
        "go ahead and update",
        "go ahead and install",
        "confirm update",
        "confirm the update",
        "push the update",
        "push it live",
        "push the changes",
        "load the update",
        "load those features",
        "load the new features",
        "put the update in",
        "make the update live",
        "apply live update",
        "run the update",
        "start the update",
        "yes please update",
        "please update",
        "please update silva",
        "go on and update",
    }
)

AMBIGUOUS_CONFIRM = frozenset(
    {
        "yes",
        "yeah",
        "yep",
        "yup",
        "sure",
        "ok",
        "okay",
        "do it",
        "go ahead",
        "apply it",
        "install it",
        "load it",
        "yes please",
    }
)

_APPLY_NEEDLES = (
    "update silva",
    "apply update",
    "apply the update",
    "install update",
    "install the update",
    "do the update",
    "push the update",
    "load the update",
    "confirm the update",
    "make the update live",
    "go ahead and update",
)

_DECLINE_EXACT = frozenset(
    {
        "not now",
        "later",
        "no update",
        "skip update",
        "no thanks",
        "dont update",
        "do not update",
        "not yet",
        "maybe later",
        "skip it",
    }
)


_CODE_DETAIL_EXACT = frozenset(
    {
        "what type of code",
        "what type of code was added",
        "what type of code it was added",
        "what type of code that was added",
        "what code was added",
        "what code got added",
        "what was in the code that was added",
        "what was in the code that got added",
        "what was in the code",
        "what was added in the code",
        "tell me what was in the code",
        "tell me the code that was added",
        "describe the code",
        "describe the code that was added",
        "whats in the codebase",
        "what is in the codebase",
        "what modules were added",
        "what python files",
        "what python was added",
        "what python files were added",
        "tell me technically",
        "be technical",
        "the technical stuff",
        "technical description",
    }
)

_CODE_DETAIL_NEEDLES = (
    "type of code",
    "codebase",
    "what code",
    "in the code",
    "the code that was added",
    "the code that got added",
    "describe the code",
    "python files",
    "python was added",
    "what modules",
    "source files",
    "technical",
)


_DETAIL_NEEDLES = (
    "in detail",
    "in more detail",
    "more detail",
    "more details",
    "more information",
    "tell me more about the update",
    "explain the update",
    "go into detail",
    "full details",
    "what exactly was added",
    "everything that was added",
    "break down the update",
    "break it down",
)


def is_code_detail_ask(text: str) -> bool:
    """True when the user wants module/file descriptions, not the short changelog."""
    normalized = _fold(text)
    if not normalized or normalized in _CHAT_EXACT:
        return False
    if normalized in _CODE_DETAIL_EXACT:
        return True
    return any(needle in normalized for needle in _CODE_DETAIL_NEEDLES)


def is_update_detail_ask(text: str) -> bool:
    """True when the user wants the longer update explanation."""
    normalized = _fold(text)
    if not normalized or normalized in _CHAT_EXACT:
        return False
    if not any(needle in normalized for needle in _DETAIL_NEEDLES):
        return False
    return any(
        token in normalized
        for token in ("update", "added", "code", "changelog", "patch", "feature")
    )


_UPDATE_STATUS_RE = re.compile(
    r"\b(?:up to date|on (?:the )?(?:latest|newest)|using (?:the )?(?:latest|newest)|"
    r"running (?:the )?(?:latest|newest)|installed (?:the )?(?:latest|newest)|"
    r"have (?:the )?(?:latest|newest)|correct version|right version|right update|"
    r"correct update|already in place|already installed|already applied|am i on|are you on|is silva on|are we on|"
    r"do you have (?:the )?(?:latest|newest))\b",
    re.I,
)
_UPDATE_MISSING_RE = re.compile(
    r"\bwhy\b.{0,80}\b(?:not|never|wasn.?t|weren.?t|didn.?t|hasn.?t|haven.?t)\b.{0,60}"
    r"\b(?:in|include|included|add|added|part|update|patch|changelog)\b|"
    r"\b(?:why|how come)\b.{0,60}\b(?:update|patch|release|changelog)\b.{0,60}"
    r"\b(?:not|never|wasn.?t|weren.?t|didn.?t|missing|left out)\b|"
    r"\bnot in (?:the )?(?:new |latest |newest |last |current )?(?:update|patch|release)\b",
    re.I,
)
_UPDATE_CURRENT_RE = re.compile(
    r"\bwhy\b.{0,80}\b(?:not|never|wasn.?t|weren.?t|haven.?t|hasn.?t|didn.?t|stuck|behind)\b.{0,70}"
    r"\b(?:up to date|updated|right version|correct version|latest|newest|version|update|patch)\b|"
    r"\bwhy\b.{0,30}\b(?:are|is|on|using|running)\b.{0,60}"
    r"\b(?:version|update|patch|\d+(?:\.\d+)?|latest|newest|right|wrong)\b|"
    r"\b(?:not up to date|not updated|wrong version|old version|outdated|behind version)\b|"
    r"\b(?:tell me|what is|what's|exact|what version)\b.{0,30}\b(?:exact )?version\b",
    re.I,
)


def is_update_feature_request_phrase(text: str) -> bool:
    normalized = _fold(text)
    if not normalized or normalized in _CHAT_EXACT:
        return False
    return bool(_UPDATE_MISSING_RE.search(normalized))


def is_update_not_current_phrase(text: str) -> bool:
    normalized = _fold(text)
    if not normalized or normalized in _CHAT_EXACT:
        return False
    return bool(_UPDATE_CURRENT_RE.search(normalized))


def is_update_status_phrase(text: str) -> bool:
    """True when the user asks whether the newest update is already installed."""
    normalized = _fold(text)
    if not normalized or normalized in _CHAT_EXACT:
        return False
    if normalized in APPLY_EXACT or any(
        normalized.startswith(f"{phrase} ") for phrase in APPLY_EXACT
    ):
        return False
    if is_update_feature_request_phrase(text) or is_update_not_current_phrase(text):
        return False
    return bool(_UPDATE_STATUS_RE.search(normalized))


def is_whats_new_update_phrase(text: str) -> bool:
    """True when the user asks what was added or what the new update is."""
    normalized = _fold(text)
    if not normalized or normalized in _CHAT_EXACT:
        return False
    if is_update_status_phrase(text) or is_update_feature_request_phrase(text) or is_update_not_current_phrase(text):
        return False
    if any(normalized.startswith(prefix) for prefix in _CHAT_PREFIXES):
        return False
    if is_update_detail_ask(text) or is_code_detail_ask(text):
        return True
    if normalized in WHATS_NEW_EXACT:
        return True
    if _WHATS_NEW_RE.search(normalized):
        return True
    return any(needle in normalized for needle in _WHATS_NEW_NEEDLES)


def is_update_confirm_phrase(text: str) -> bool:
    """True when the user wants the waiting update applied into the running AI."""
    try:
        from silva.commands.pronunciation_phrases import is_pronunciation_command

        if is_pronunciation_command(text):
            return False
    except Exception:
        pass
    normalized = _fold(text)
    if not normalized or normalized in _CHAT_EXACT:
        return False
    if is_whats_new_update_phrase(text) and normalized not in APPLY_EXACT:
        return False
    if is_update_status_phrase(text) or is_update_feature_request_phrase(text) or is_update_not_current_phrase(text):
        return False
    if normalized in APPLY_EXACT:
        return True
    if any(normalized.startswith(phrase + " ") for phrase in APPLY_EXACT):
        return True
    return any(needle in normalized for needle in _APPLY_NEEDLES)


def is_ambiguous_update_confirm(text: str) -> bool:
    return _fold(text) in AMBIGUOUS_CONFIRM


def is_update_decline_phrase(text: str) -> bool:
    normalized = _fold(text)
    return normalized in _DECLINE_EXACT


_EXPAND_MARKERS: tuple[str, ...] = (
    "expand",
    "more detail",
    "more details",
    "more about",
    "extra detail",
    "tell me more",
    "go into",
    "break down",
    "explain",
    "describe",
    "details on",
    "details for",
    "details about",
    "details of",
)

_EXPAND_MARKER_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:one|both) of (?:them|these|those)\b", re.I),
)

_AMBIGUOUS_CHOICE_RE = re.compile(
    r"\b(?:one|1|any|both|either)\s+of\s+(?:them|these|those)\b|"
    r"\b(?:any|pick|choose)\s+one\b",
    re.I,
)

_ORDINAL_RE = re.compile(
    r"\b(?:the\s+)?(?:number\s+|item\s+|thing\s+)?"
    r"(first|second|third|1st|2nd|3rd|one|two|three|[123])"
    r"(?:\s+(?:one|item|thing))?\b",
    re.I,
)

_ORDINAL_INDEX = {
    "first": 0,
    "1st": 0,
    "one": 0,
    "1": 0,
    "second": 1,
    "2nd": 1,
    "two": 1,
    "2": 1,
    "third": 2,
    "3rd": 2,
    "three": 2,
    "3": 2,
}


_UPDATE_EXTRA_RE = re.compile(
    r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+"
    r"(?:other|others|more|extra|additional)\b|"
    r"\b(?:other|remaining)\s+(?:one|ones|two|three|four|five|six|seven|eight|nine|ten|\d+)\b|"
    r"\b(?:rest|remaining)\s+of\s+(?:them|these|those|it)\b|"
    r"\b(?:what|which|tell\s+me|read\s+me|list|show\s+me)\b.{0,40}\b(?:rest|remaining|others?)\b",
    re.I,
)


def is_update_expand_phrase(text: str) -> bool:
    """True for a follow-up asking for more detail on a named update item."""
    normalized = _fold(text)
    if not normalized or normalized in _CHAT_EXACT:
        return False
    return any(marker in normalized for marker in _EXPAND_MARKERS) or any(
        pattern.search(normalized) for pattern in _EXPAND_MARKER_RES
    )


def is_update_extra_ask(text: str) -> bool:
    """True for a follow-up asking for items hidden behind 'and more'."""
    normalized = _fold(text)
    if not normalized or normalized in _CHAT_EXACT:
        return False
    return bool(_UPDATE_EXTRA_RE.search(normalized))


def update_expand_index(text: str, items: list[str]) -> int | None:
    """Resolve a follow-up to one of the update items spoken a moment ago."""
    normalized = _fold(text)
    if not normalized or not items:
        return None
    searchable = _AMBIGUOUS_CHOICE_RE.sub(" ", normalized)
    match = _ORDINAL_RE.search(searchable)
    if match:
        index = _ORDINAL_INDEX.get(match.group(1).lower())
        if index is not None and index < len(items):
            return index
    for index, item in enumerate(items):
        name = _fold(str(item))
        if name and name in searchable:
            return index
    return None


def is_update_speech(text: str) -> bool:
    return (
        is_whats_new_update_phrase(text)
        or is_update_status_phrase(text)
        or is_update_confirm_phrase(text)
        or is_update_feature_request_phrase(text)
        or is_update_not_current_phrase(text)
    )
