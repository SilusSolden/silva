"""Natural-language phrases to open the personal phrase recorder (~100+ variations)."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Short exact matches.
EXACT_PHRASES: frozenset[str] = frozenset(
    {
        "recorder",
        "phrase recorder",
        "speech recorder",
        "voice recorder",
        "voice phrase recorder",
        "phrase recording",
        "speech recording",
        "voice phrase recording",
        "audio phrase recorder",
        "personal recorder",
        "personal phrase recorder",
        "my recorder",
        "my phrase recorder",
        "phrase trainer",
        "speech trainer",
        "voice trainer",
        "phrase training",
        "speech training",
    }
)

# Full phrases — exact, prefix, or contained in longer utterances.
OPEN_PHRASES: tuple[str, ...] = (
    # Open / show / launch
    "open the recorder",
    "open recorder",
    "open up the recorder",
    "open up recorder",
    "open my recorder",
    "open the voice recorder",
    "open voice recorder",
    "open the speech recorder",
    "open speech recorder",
    "open the phrase recorder",
    "open phrase recorder",
    "open the audio recorder",
    "open audio recorder",
    "open a recorder",
    "open recording tool",
    "open the recording tool",
    "open recording panel",
    "open the recording panel",
    "open recording screen",
    "open the recording screen",
    "open recording window",
    "open the recording window",
    "open my recording panel",
    "open my phrase recorder",
    "open my speech recorder",
    "open my voice recorder",
    "open personal recorder",
    "open my personal recorder",
    "open phrase recording",
    "open speech recording",
    "open voice phrase recorder",
    "open the phrase recording tool",
    "open the speech recording tool",
    "show the recorder",
    "show recorder",
    "show phrase recorder",
    "show the phrase recorder",
    "show speech recorder",
    "show the speech recorder",
    "show voice recorder",
    "show the voice recorder",
    "show recording panel",
    "show my recorder",
    "show phrase recording",
    "display the recorder",
    "display recorder",
    "display phrase recorder",
    "bring up the recorder",
    "bring up recorder",
    "bring up phrase recorder",
    "pull up the recorder",
    "pull up recorder",
    "pull up phrase recorder",
    "launch the recorder",
    "launch recorder",
    "launch phrase recorder",
    "launch speech recorder",
    "launch voice recorder",
    "go to recorder",
    "go to the recorder",
    "go to phrase recorder",
    "go to the phrase recorder",
    "take me to the recorder",
    "take me to recorder",
    "take me to phrase recorder",
    # Start / begin
    "start the recorder",
    "start recorder",
    "start recording phrases",
    "start phrase recording",
    "start speech recording",
    "start voice recording",
    "start phrase recorder",
    "start the phrase recorder",
    "start recording my phrases",
    "start recording my voice",
    "start recording my speech",
    "begin recording phrases",
    "begin phrase recording",
    "begin speech recording",
    "begin voice recording",
    # Record / save
    "record my phrases",
    "record my phrase",
    "record my speech",
    "record my voice",
    "record my voice phrases",
    "record my voice phrase",
    "record how i say things",
    "record how i speak",
    "record how i talk",
    "record how i say words",
    "record how i say commands",
    "record how i say it",
    "record the way i speak",
    "record the way i talk",
    "record the way i say things",
    "record my wake phrase",
    "record my wake word",
    "record wake phrases",
    "record wake words",
    "record command phrases",
    "record my commands",
    "record phrases for silva",
    "record voice samples",
    "record speech samples",
    "record phrase samples",
    "record audio samples",
    "save my phrases",
    "save phrase recordings",
    "save how i speak",
    "save how i say things",
    "save my speech patterns",
    "save voice phrases",
    # Teach / train / setup
    "teach silva my voice",
    "teach silva how i speak",
    "teach silva how i talk",
    "teach silva my phrases",
    "teach silva my pronunciation",
    "teach my phrases",
    "teach my speech",
    "teach my voice",
    "teach you how i talk",
    "teach you how i speak",
    "teach you my pronunciation",
    "teach you my phrases",
    "train my phrases",
    "train my speech",
    "train my voice",
    "train my voice phrases",
    "train silva my voice",
    "train phrase recognition",
    "train speech recognition for me",
    "setup phrase recording",
    "set up phrase recording",
    "setup speech recording",
    "set up speech recording",
    "setup voice phrases",
    "set up voice phrases",
    "setup my voice phrases",
    "set up my voice phrases",
    "configure phrase recorder",
    "configure speech recorder",
    "speech recording setup",
    "phrase recording setup",
    "voice phrase setup",
    "voice recording setup",
    # Need / want / help
    "i need the recorder",
    "i need phrase recorder",
    "i need the phrase recorder",
    "i need speech recorder",
    "i need to record phrases",
    "i need to record my voice",
    "i need to record how i speak",
    "i want the recorder",
    "i want phrase recorder",
    "i want to record phrases",
    "i want to record my voice",
    "i want to record my speech",
    "i want to record how i talk",
    "i want to teach you my voice",
    "let me record phrases",
    "let me record my speech",
    "let me record my voice",
    "let me record how i speak",
    "help me record phrases",
    "help me record my voice",
    "help me record my speech",
    "help me teach you my voice",
    # Speech / recognition fixes
    "speech impediment recorder",
    "record for speech impediment",
    "fix speech recognition",
    "fix how you hear me",
    "fix how silva hears me",
    "fix voice recognition",
    "improve speech recognition",
    "improve how you hear me",
    "custom phrase recorder",
    "custom speech recorder",
    "personal speech recorder",
    "personal voice recorder",
    "my speech recorder",
    "my voice recorder",
    "voice phrase trainer",
    "phrase sample recorder",
    "record phrase samples for my profile",
    "add phrase recording",
    "add a phrase recording",
    "add voice phrase recording",
    "create phrase recording",
    "create a phrase recording",
    "make a phrase recording",
    "make phrase recording",
    "new phrase recording",
    "new phrase recorder",
)

_POLITE_PREFIXES: tuple[str, ...] = (
    "can you ",
    "could you ",
    "would you ",
    "will you ",
    "please ",
    "go ahead and ",
    "i need you to ",
    "i want you to ",
)

_WAKE_PREFIXES: tuple[str, ...] = (
    "hey silva ",
    "silva ",
    "hey silver ",
    "silver ",
    "okay silva ",
    "ok silva ",
)

_RECORDER_HEURISTIC_RE = re.compile(
    r"\b("
    r"open|show|launch|start|begin|display|bring up|pull up|go to|take me to|"
    r"record|save|teach|train|setup|set up|configure|fix|improve|help me|let me|"
    r"i need|i want|add|create|make|new"
    r")\b.*\b("
    r"recorder|phrase record|speech record|voice record|phrase sample|speech sample|"
    r"voice phrase|phrase training|speech training|how i speak|how i talk|how i say|"
    r"wake phrase|wake word|my pronunciation|speech impediment"
    r")\b",
    re.I,
)

_PHRASE_RECORD_RE = re.compile(
    r"\b(phrase|speech|voice|audio)\b.*\b(record|recording|recorder|trainer|training|samples?)\b|"
    r"\b(record|recording|recorder|trainer|training|samples?)\b.*\b(phrase|speech|voice|audio)\b",
    re.I,
)


@dataclass
class PhraseRecorderSpeech:
    action: str = "open"


def _normalize(text: str) -> str:
    text = text.strip().lower()
    text = text.replace("'", "")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _strip_leading(text: str) -> str:
    normalized = _normalize(text)
    changed = True
    while changed:
        changed = False
        for prefix in _WAKE_PREFIXES:
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix) :].strip()
                changed = True
                break
        for prefix in _POLITE_PREFIXES:
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix) :].strip()
                changed = True
                break
    return normalized


def _phrase_matches(normalized: str, phrase: str) -> bool:
    if not phrase:
        return False
    if normalized == phrase:
        return True
    if normalized.startswith(phrase + " "):
        return True
    if len(phrase.split()) >= 3 and phrase in normalized:
        return True
    return False


def match_phrase_recorder_speech(text: str) -> PhraseRecorderSpeech | None:
    try:
        from silva.commands.pronunciation_phrases import is_pronunciation_command

        if is_pronunciation_command(text):
            return None
    except Exception:
        pass
    normalized = _strip_leading(text)
    if not normalized:
        return None

    if normalized in EXACT_PHRASES:
        return PhraseRecorderSpeech()

    for phrase in OPEN_PHRASES:
        if _phrase_matches(normalized, phrase):
            return PhraseRecorderSpeech()

    if _RECORDER_HEURISTIC_RE.search(normalized):
        return PhraseRecorderSpeech()
    if _PHRASE_RECORD_RE.search(normalized):
        return PhraseRecorderSpeech()

    # Very short requests after wake word.
    if normalized in {"recording", "record phrases", "record speech", "record voice"}:
        return PhraseRecorderSpeech()

    return None


def is_phrase_recorder_command(text: str) -> bool:
    return match_phrase_recorder_speech(text) is not None


def phrase_count() -> int:
    """Return how many distinct open phrases are registered."""
    return len(EXACT_PHRASES) + len(OPEN_PHRASES)
