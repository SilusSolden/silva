"""Spoken ways to train, assign, or edit custom word pronunciations."""

from __future__ import annotations

import re
from dataclasses import dataclass

from silva.commands.help_phrases import should_yield_to_feature_help

_PUNCT_RE = re.compile(r"[^\w\s]")
_SPACE_RE = re.compile(r"\s+")

_WAKE_PREFIXES = (
    "hey silva ",
    "ok silva ",
    "okay silva ",
    "yo silva ",
    "silva ",
    "hey silver ",
    "silver ",
    "please ",
    "hey ",
)

_POLITE_PREFIXES = (
    "can you ",
    "could you ",
    "would you ",
    "will you ",
    "i want you to ",
    "i need you to ",
    "go ahead and ",
    "help me ",
    "let me ",
    "i want to ",
    "i need to ",
    "i wanna ",
    "all right ",
    "alright ",
    "now ",
    "just ",
)

EDIT_EXACT = frozenset(
    {
        "edit pronunciations",
        "edit pronunciation",
        "edit the pronunciations",
        "edit the pronunciation",
        "edit custom words",
        "edit custom word",
        "edit word pronunciations",
        "edit word pronunciation",
        "edit how you say words",
        "edit how you say a word",
        "edit how you pronounce words",
        "edit pronunciation mappings",
        "edit pronunciation map",
        "edit word recordings",
        "edit the word recordings",
        "edit wav matches",
        "edit the wav matches",
        "manage pronunciations",
        "manage pronunciation",
        "manage custom words",
        "manage word pronunciations",
        "show pronunciations",
        "show pronunciation",
        "show custom words",
        "show word recordings",
        "list pronunciations",
        "list custom words",
        "list word recordings",
        "open pronunciation editor",
        "open the pronunciation editor",
        "pronunciation editor",
        "word pronunciation editor",
        "fix pronunciation mappings",
        "change which recording matches",
        "change which wav matches",
        "change which audio matches",
        "update word recordings",
        "update pronunciations",
        "update the pronunciations",
    }
)

RECORD_EXACT = frozenset(
    {
        "pronunciation recorder",
        "word recorder",
        "custom word recorder",
        "record pronunciation",
        "record a pronunciation",
        "record the pronunciation",
        "record a custom word",
        "record custom word",
        "record custom words",
        "record a word pronunciation",
        "record word pronunciation",
        "record how you say a word",
        "record how you should say a word",
        "record how you pronounce a word",
        "train pronunciation",
        "train a pronunciation",
        "train your pronunciation",
        "train how you say words",
        "train how you say a word",
        "train how you should say a word",
        "add a custom word",
        "add custom word",
        "add a pronunciation",
        "add pronunciation",
        "override a word",
        "override the word",
        "override pronunciation",
        "custom pronunciation",
        "custom word pronunciation",
        "change how you say a word",
        "change how you say words",
        "change how you pronounce a word",
        "change how you pronounce words",
        "change how the ai says a word",
        "change how the ai says words",
        "change how silva says a word",
        "fix how you say a word",
        "fix how you pronounce a word",
        "open pronunciation recorder",
        "open the pronunciation recorder",
        "open word pronunciation",
        "bring up pronunciation recorder",
        "bring up the pronunciation recorder",
        "start pronunciation recorder",
        "start the pronunciation recorder",
        "new pronunciation recording",
        "new custom word",
        "open pronunciation",
        "open the pronunciation",
        "open pronunciation popup",
        "open the pronunciation popup",
        "open wav recorder",
        "open the wav recorder",
        "open wav popup",
        "open the wav popup",
        "open word recording",
        "open the word recording",
        "open word recording popup",
        "open the word recording popup",
        "bring up pronunciation",
        "bring up the pronunciation popup",
        "bring up wav recorder",
        "show pronunciation popup",
        "show the pronunciation popup",
        "pronunciation popup",
        "wav popup",
        "wav recorder",
        "record wav",
        "record a wav",
        "record the wav",
        "update the audio",
        "update the audio to the correct wording",
        "update the audio to the correct word",
        "update audio to the correct wording",
        "update the wording",
        "update the correct wording",
        "update the wording to the correct audio",
        "correct the wording",
        "correct the audio",
        "fix the audio",
        "fix the wording",
        "change the audio",
        "change the wording",
        "update the word recording",
        "update the wav",
        "update the recording",
    }
)

ASK_EXACT = frozenset(
    {
        "how do you say it",
        "how should you say it",
        "how would you say it",
        "how do you say this word",
        "how do you say that word",
        "how do you say a word",
        "how would you say this word",
        "how would you say that word",
        "how should you say this word",
        "how should you say that word",
        "how do you pronounce it",
        "how do you pronounce this word",
        "how do you pronounce that word",
        "how is this pronounced",
        "how is that pronounced",
        "how is this word pronounced",
        "how is that word pronounced",
        "tell me how you say it",
        "tell me how you say this word",
        "tell me how you say that word",
    }
)

_RECORD_CAPTURE = (
    re.compile(
        r"\b(?:change|fix|train|override|replace|correct|update|record|teach)\b.{0,40}?"
        r"\bhow (?:you|silva|the ai|it) (?:should )?(?:say|pronounce|speak)(?:s|es)?(?: the word)? (.+)$"
    ),
    re.compile(
        r"\b(?:record|save|add|train|make) (?:a |the )?(?:custom )?(?:pronunciation|word(?: pronunciation)?|recording)"
        r" (?:for|of|on) (?:the word )?(.+)$"
    ),
    re.compile(r"\bteach (?:you|silva) how to (?:say|pronounce|speak) (.+)$"),
    re.compile(r"\b(?:say|pronounce) (?:the word )?(.+?) (?:like this|this way|correctly|differently|the right way)$"),
    re.compile(r"\b(?:custom|new) (?:pronunciation|recording) for (?:the word )?(.+)$"),
    re.compile(r"\boverride (?:the )?(?:word|pronunciation) (.+)$"),
    re.compile(
        r"\bopen (?:the )?(?:pronunciation|wav|word recording)(?: recorder| popup)?(?: for(?: the word)? (.+))?$"
    ),
    re.compile(
        r"\b(?:update|correct|fix|change) (?:the )?(?:audio|wording|wav|recording)"
        r"(?: to (?:the )?(?:correct )?(?:wording|word|audio|pronunciation))?"
        r"(?: (?:for|of|on) (?:the word )?(.+))?$"
    ),
    re.compile(
        r"\b(?:update|correct) (?:the )?(?:correct )?wording(?: (?:for|of|on) (?:the word )?(.+))?$"
    ),
)

_ASK_CAPTURE = (
    re.compile(r"\bhow (?:do you|should you|would you|do i) (?:say|pronounce)(?: the word)? (.+)$"),
    re.compile(r"\btell me how (?:you|silva|the ai) (?:say|pronounce|speak)(?:s)?(?: the word)? (.+)$"),
    re.compile(r"\b(?:what is|whats) (?:the )?(?:pronunciation of|how you say) (.+)$"),
    re.compile(r"\bhow is (?:the word )?(.+?) pronounced$"),
)

_EDIT_CAPTURE = (
    re.compile(r"\bedit how (?:you|silva|the ai) (?:say|pronounce|speak)(?:s)?(?: the word)? (.+)$"),
    re.compile(r"\b(?:edit|change|update|fix) (?:the )?(?:wav|recording|audio|clip) (?:match|mapping) (?:for|of) (.+)$"),
    re.compile(r"\b(?:change|pick) which (?:wav|recording|audio|clip) (?:matches|for|goes to) (.+)$"),
)

_TRAILING_JUNK = (
    " please",
    " for me",
    " now",
    " thanks",
    " thank you",
    " real quick",
    " quickly",
)


@dataclass(frozen=True)
class PronunciationSpeech:
    action: str
    word: str | None = None


def _fold(text: str) -> str:
    normalized = (text or "").strip().lower().replace("'", "")
    normalized = _PUNCT_RE.sub(" ", normalized)
    normalized = _SPACE_RE.sub(" ", normalized).strip()
    changed = True
    while changed and normalized:
        changed = False
        for prefix in _WAKE_PREFIXES + _POLITE_PREFIXES:
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix) :].strip()
                changed = True
                break
    for suffix in _TRAILING_JUNK:
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)].strip()
    return normalized


def _clean_word(raw: str | None) -> str | None:
    if not raw:
        return None
    word = raw.strip().lower()
    word = re.sub(r"\b(the word|a word|this word)\b", " ", word)
    word = re.sub(r"\s+", " ", word).strip(" .,-")
    if not word or word in {"a word", "words", "it", "that", "this", "something"}:
        return None
    if len(word) > 48:
        word = " ".join(word.split()[:4])
    return word or None


_LANGUAGE_ASK_RE = re.compile(
    r"\bin (spanish|french|german|italian|japanese|chinese|korean|russian|latin|portuguese|arabic)\b"
)

_NON_COMMAND_SPEECH_RE = re.compile(
    r"^(?:why|how come|i (?:do not|don't)|that is not|you (?:just|keep|always)|stop|quit)\b"
    r"|\b(?:repeating yourself|rephrasing me|you just said|you said that)\b"
)


def match_pronunciation_speech(text: str) -> PronunciationSpeech | None:
    if should_yield_to_feature_help(text):
        return None
    normalized = _fold(text)
    if not normalized:
        return None
    if _LANGUAGE_ASK_RE.search(normalized):
        return None
    if _NON_COMMAND_SPEECH_RE.search(normalized):
        return None

    if normalized in EDIT_EXACT:
        return PronunciationSpeech(action="edit")
    if normalized in ASK_EXACT:
        return PronunciationSpeech(action="ask")
    if normalized in RECORD_EXACT:
        return PronunciationSpeech(action="record")

    for pattern in _EDIT_CAPTURE:
        match = pattern.search(normalized)
        if match:
            return PronunciationSpeech(action="edit", word=_clean_word(match.group(1)))

    for pattern in _ASK_CAPTURE:
        match = pattern.search(normalized)
        if match:
            return PronunciationSpeech(action="ask", word=_clean_word(match.group(1)))

    for pattern in _RECORD_CAPTURE:
        match = pattern.search(normalized)
        if match:
            return PronunciationSpeech(action="record", word=_clean_word(match.group(1)))

    if re.search(
        r"\b(pronunciation recorder|word pronunciation|custom word|how you should say|"
        r"how you say a word|override the word|update the audio|correct wording)\b",
        normalized,
    ):
        return PronunciationSpeech(action="record")

    if re.search(
        r"\b(edit|manage|list|show)\b.+\b(pronunciation|custom words|word recordings|wav matches)\b",
        normalized,
    ):
        return PronunciationSpeech(action="edit")

    return None


def is_pronunciation_command(text: str) -> bool:
    return match_pronunciation_speech(text) is not None
