"""Speech patterns for personal notes and the to-do list."""

from __future__ import annotations

import re
from dataclasses import dataclass

TYPE_FAIL_LIMIT = 3

_FILLER_RE = re.compile(
    r"^(please |silva |hey silva |okay |ok |all right |alright |"
    r"now |just |so |can you |could you |would you |will you |tell me )+",
    re.I,
)


def _normalize(text: str) -> str:
    text = text.strip().lower()
    text = text.replace("'", "")
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\bto-do\b", "todo", text)
    text = re.sub(r"\bto do\b", "todo", text)
    return re.sub(r"\s+", " ", text).strip()


def fold_todo_words(text: str) -> str:
    return _normalize(text)


@dataclass
class NotesSpeech:
    action: str
    query: str = ""
    kind: str = "note"
    time_hm: tuple[int, int] | None = None
    daily: bool = False
    number: int | None = None
    dest_number: int | None = None


_TYPE_NOTE = (
    "type the note",
    "type my note",
    "type a note",
    "type that note",
    "ill type the note",
    "i will type the note",
    "i will type it",
    "ill type it",
    "open the note box",
    "open a note box",
    "open the text box for the note",
    "open a text popup for the note",
)

_TYPE_TODO = (
    "type the todo",
    "type my todo",
    "type a todo",
    "type the todo list",
    "type my todo list",
    "ill type the todo",
    "i will type the todo",
    "open the todo box",
    "open a todo box",
    "open the text box for the todo",
    "open a text popup for the todo list",
)

_LIST_NOTES = (
    "what are my notes",
    "whats my notes",
    "what is my notes",
    "whats in my notes",
    "what is in my notes",
    "read my notes",
    "list my notes",
    "show my notes",
    "bring up my notes",
    "bring up the notes",
    "my notes",
    "what notes do i have",
)

_SEARCH_NOTE_PREFIXES = (
    "what did i note about",
    "what did i note on",
    "whats my note about",
    "what is my note about",
    "look up my note about",
    "look up my notes about",
    "find my note about",
    "find my notes about",
    "bring up my note about",
    "bring up my notes about",
    "read my note about",
    "whats my note on",
    "what is my note on",
    "remind me what i noted about",
)

_DELETE_NOTE_PREFIXES = (
    "delete my note about",
    "delete my note",
    "remove my note about",
    "remove my note",
    "forget my note about",
    "forget my note",
)

_REMIND_NOTE_PREFIXES = (
    "remind me about my note",
    "set a reminder for my note",
    "remind me of my note",
)

_ADD_NOTE_PREFIXES = (
    "make a personal note",
    "personal note",
    "take a note",
    "make a note",
    "add a note",
    "save a note",
    "write this down",
    "jot this down",
    "jot down",
    "note this",
    "note that",
    "remember this",
    "remember that",
    "note",
)

_OPEN_TODO = (
    "open the todo list",
    "open my todo list",
    "open todo list",
    "show the todo list",
    "show my todo list",
    "bring up my todo list",
    "bring up the todo list",
    "bring up my todos",
    "bring up the checklist",
    "open the checklist",
    "open my checklist",
)

_CLOSE_TODO = (
    "close the todo list",
    "close my todo list",
    "hide the todo list",
    "close the checklist",
)

_LIST_TODO = (
    "what is my todo list",
    "whats my todo list",
    "what are my todos",
    "whats on my todo list",
    "what is on my todo list",
    "list my todos",
    "list my todo list",
    "read my todo list",
    "my todo list",
    "my todos",
    "remind me of my todo list",
    "remind me of my todos",
    "remind me of the todo list",
)

_ASK_REMINDER = (
    "whats my reminder",
    "what is my reminder",
    "what are my reminders",
    "whats my reminders",
    "what is my reminders",
    "show my reminder",
    "show my reminders",
    "my reminder",
    "my reminders",
    "what reminders do i have",
    "whats my reminders",
    "remind me of it",
    "remind me",
)

_REMIND_OF_NOTES = (
    "remind me of my notes",
    "remind me of the notes",
    "remind me of my note",
)

_ADD_TODO_PREFIXES = (
    "add this to the todo list",
    "add that to the todo list",
    "add this to my todo list",
    "add that to my todo list",
    "put this on my todo list",
    "put that on my todo list",
    "put this on the todo list",
    "add to my todo list",
    "add to the todo list",
    "add a todo",
    "add todo",
    "new todo",
    "create a todo",
    "remind myself to",
    "remind myself",
    "remind me to",
    "remind me at",
)

_NOT_MATH = (
    "that was not a math problem",
    "that wasnt a math problem",
    "thats not a math problem",
    "that is not a math problem",
    "not a math problem",
    "that wasnt math",
    "thats not math",
    "i wasnt doing math",
    "i was not doing math",
    "that wasnt a math question",
    "thats not a math question",
)

_COMPLETE_TODO_PREFIXES = (
    "check off",
    "check of",
    "mark done on my todo list",
    "mark complete on my todo list",
    "mark as done",
    "mark as complete",
    "i completed",
    "i finished",
    "i done",
)

_DELETE_TODO_PREFIXES = (
    "remove from my todo list",
    "remove from the todo list",
    "delete from my todo list",
    "delete from the todo list",
    "remove todo number",
    "delete todo number",
    "remove number",
    "delete number",
    "remove todo",
    "delete todo",
    "delete that todo for good",
    "forget that todo completely",
    "delete it for good",
    "delete that todo",
    "remove that todo",
    "delete this todo",
    "remove this todo",
    "get rid of todo",
    "scratch todo",
    "take off todo",
)

_CLEAR_TODO_LIST = (
    "delete the entire todo list",
    "delete my entire todo list",
    "delete that entire todo list",
    "delete entire todo list",
    "delete the todo list",
    "delete my todo list",
    "delete that todo list",
    "delete todo list",
    "remove the todo list",
    "remove my todo list",
    "erase the todo list",
    "get rid of the todo list",
    "get rid of my todo list",
    "clear my todo list",
    "clear the todo list",
    "clear all todos",
    "restart my todo list",
    "restart the todo list",
    "start over my todo list",
    "start over the todo list",
    "wipe my todo list",
    "reset my todo list",
    "empty my todo list",
    "delete all todos",
    "remove all todos",
)

_UNDO_LAST_TODO = (
    "undo that todo",
    "undo that",
    "scratch that todo",
    "scratch that",
    "delete that last one",
    "delete the last todo",
    "delete the last one",
    "remove the last one",
    "remove the last todo",
    "wrong one",
    "wrong todo",
    "not that one",
    "no not that",
)

_EDIT_TODO_PREFIXES = (
    "edit todo number",
    "change todo number",
    "edit number",
    "change number",
    "edit todo",
    "change todo",
    "fix todo",
    "fix number",
    "change that todo",
    "edit that todo",
    "thats not right change",
)

_MOVE_TODO_PREFIXES = (
    "move todo number",
    "move number",
    "move todo",
)

_ARCHIVE_TODO_PREFIXES = (
    "i no longer need to do",
    "i no longer need to",
    "i no longer need",
    "i dont need to do",
    "i do not need to do",
    "get rid of that",
    "get rid of the",
    "get rid of",
    "stop reminding me to",
    "stop reminding me about",
    "i dont have to do",
    "i do not have to do",
    "take that off my list",
    "take that off the list",
    "i dont need that reminder",
    "cancel the daily",
    "cancel daily",
)

_RESTORE_TODO_PREFIXES = (
    "bring back",
    "bring that back",
    "put back",
    "restore the todo",
    "restore my todo",
    "i still need to do",
    "i still need to",
    "i didnt mean to delete",
    "i did not mean to delete",
    "undo that todo",
    "put that back on my list",
)

_ADD_DAILY_PREFIXES = (
    "add a daily todo",
    "add daily todo",
    "add a repeating todo",
    "add a repeat todo",
    "repeat todo",
    "repeating todo",
    "daily todo",
    "every day todo",
    "remind me every day to",
    "remind me everyday to",
    "remind me daily to",
    "every day remind me to",
)

_DAILY_RE = re.compile(
    r"\b(every\s*day|everyday|each day|daily|every morning|every evening|every night)\b",
    re.I,
)
_CHORE_HINTS = (
    "meds",
    "medication",
    "medicine",
    "pills",
    "vitamins",
    "wegovy",
    "ozempic",
    "mounjaro",
    "saxenda",
    "metformin",
    "insulin",
    "trash",
    "garbage",
    "rubbish",
    "cleaning",
    "dishes",
    "laundry",
    "take out",
)
_CLOCK_RE = re.compile(
    r"\b(?:at\s+)?(\d{1,2})(?:[:\s](\d{2}))?\s*(a\.?\s*m\.?|p\.?\s*m\.?|am|pm|a m|p m)\b"
    r"|\bat\s+(\d{1,2})(?:[:\s](\d{2}))?\b"
    r"|\b(\d{1,2})(?:[:\s](\d{2}))?\s+(?:in the morning|in the afternoon|in the evening)\b"
    r"|\b(noon|midnight)\b",
    re.I,
)


def parse_todo_clock(text: str) -> tuple[int, int] | None:
    raw = text or ""
    cleaned = re.sub(r"a\.?\s*m\.?", "am", raw, flags=re.I)
    cleaned = re.sub(r"p\.?\s*m\.?", "pm", cleaned, flags=re.I)
    match = _CLOCK_RE.search(cleaned) or _CLOCK_RE.search(_normalize(cleaned))
    if not match:
        return None
    groups = match.groups()
    # 1 hour, 2 min, 3 meridiem | 4 hour, 5 min | 6 hour, 7 min period | 8 noon/midnight
    if groups[7]:
        return (12, 0) if groups[7].lower() == "noon" else (0, 0)
    if groups[0] is not None:
        hour = int(groups[0])
        minute = int(groups[1] or 0)
        meridiem = (groups[2] or "").replace(" ", "").replace(".", "").lower()
    elif groups[3] is not None:
        hour = int(groups[3])
        minute = int(groups[4] or 0)
        meridiem = ""
    else:
        hour = int(groups[5])
        minute = int(groups[6] or 0)
        span = match.group(0).lower()
        meridiem = "am" if "morning" in span else "pm"
    if meridiem.startswith("p") and hour < 12:
        hour += 12
    if meridiem.startswith("a") and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    return hour, minute


_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
}

_MED_WORDS = {
    "meds",
    "medication",
    "medicine",
    "pills",
    "pill",
    "vitamins",
    "wegovy",
    "ozempic",
    "mounjaro",
    "saxenda",
    "metformin",
    "insulin",
    "prescription",
}

_STOP_WORDS = {
    "a", "an", "the", "to", "my", "me", "i", "at", "in", "on", "of", "and", "for",
    "need", "take", "remind", "myself", "every", "day", "daily", "am", "pm",
    "morning", "afternoon", "tonight", "please", "silva", "this", "that", "it",
}

_COMMON_WORDS = {
    "take", "my", "meds", "trash", "out", "clean", "cleaning", "dishes", "laundry",
    "need", "remind", "myself", "morning", "afternoon", "evening", "night",
    "todo", "list", "add", "new", "daily", "every", "day", "week", "time",
    "pills", "vitamins", "water", "plants", "walk", "dog", "cat", "kids",
    "work", "call", "email", "pay", "bills", "garbage", "recycle", "shower",
    "breakfast", "lunch", "dinner", "appointment", "doctor", "pickup", "pick",
    "up", "from", "school", "store", "groceries", "milk", "batteries",
    "health", "shot", "injection", "dose", "weekly", "today",
    "tomorrow", "tonight", "later", "after", "before", "with", "food",
    "buy", "get", "make", "put", "bring", "check", "grab", "wash", "feed",
    "fill", "book", "send", "write", "read", "start", "stop", "finish",
    "pack", "charge", "off", "the", "some", "more", "go", "going", "do",
    "doing", "done", "have", "has", "had", "will", "would", "should",
    "can", "could", "then", "when", "next", "now", "again", "back",
    "home", "car", "keys", "phone", "mail", "package", "box", "door",
} | _MED_WORDS | _STOP_WORDS | set(_NUMBER_WORDS)


def looks_like_timed_reminder(text: str) -> bool:
    normalized = _normalize(text)
    if not normalized:
        return False
    if any(word in normalized for word in ("weather", "forecast")):
        return False
    if re.search(r"\b(plus|minus|divided)\b", normalized):
        return False
    has_remind = bool(re.search(r"\bremind (me|myself)\b", normalized))
    has_task = any(hint in normalized for hint in _CHORE_HINTS) or "need to" in normalized or "take my" in normalized
    has_time = parse_todo_clock(text) is not None or "in the morning" in normalized
    if has_remind and (has_task or has_time or "to take" in normalized):
        return True
    if has_time and has_task:
        return True
    return False


def unknown_heard_words(text: str) -> list[str]:
    unknown: list[str] = []
    for word in _normalize(text).split():
        if word.isdigit() or len(word) <= 1:
            continue
        if word in _COMMON_WORDS or word in _MED_WORDS or word in _STOP_WORDS:
            continue
        if re.fullmatch(r"\d{1,2}", word):
            continue
        unknown.append(word)
    return unknown


def _looks_like_stt_junk(word: str) -> bool:
    if not re.search(r"[aeiouy]", word):
        return True
    if re.search(r"(.)\1{2,}", word):
        return True
    if len(word) <= 4:
        return True
    return False


def needs_todo_confirm(text: str, *, confidence: float | None = None) -> bool:
    if looks_like_mumble(text, confidence=confidence):
        return True
    unknown = unknown_heard_words(text)
    if not unknown:
        return False
    lowered = _normalize(text)
    if any(word in lowered.split() for word in _MED_WORDS) or "take my" in lowered:
        return True
    return any(_looks_like_stt_junk(word) for word in unknown)


def match_reminder_choice(text: str) -> str | None:
    normalized = _normalize(text)
    if not normalized:
        return None
    if normalized in {"notes", "note", "my notes", "the notes", "a note", "the note"}:
        return "note"
    if "note" in normalized.split() or normalized.endswith("notes"):
        if "todo" not in normalized:
            return "note"
    if normalized in {
        "todo",
        "todos",
        "todo list",
        "my todo",
        "my todos",
        "my todo list",
        "the todo list",
        "the list",
        "checklist",
        "list",
    }:
        return "todo"
    if "todo" in normalized or "checklist" in normalized:
        return "todo"
    return None


def is_yes_speech(text: str) -> bool:
    normalized = _normalize(text)
    return normalized in {
        "yes",
        "yeah",
        "yep",
        "yup",
        "correct",
        "thats right",
        "that is right",
        "right",
        "it is",
        "thats it",
        "that is it",
        "save it",
        "save",
        "sure",
        "ok",
        "okay",
        "yes it is",
        "yes thats right",
    }


def is_no_speech(text: str) -> bool:
    normalized = _normalize(text)
    if normalized in {
        "no",
        "nope",
        "nah",
        "wrong",
        "thats wrong",
        "that is wrong",
        "not right",
        "thats not right",
        "that is not right",
        "incorrect",
        "type it",
        "let me type",
        "let me type it",
        "no thats wrong",
        "no not that",
    }:
        return True
    return normalized.startswith("no ") and "math" not in normalized


def looks_like_daily_todo(text: str) -> bool:
    normalized = _normalize(text)
    if not _DAILY_RE.search(normalized):
        return False
    if "news" in normalized or "weather" in normalized:
        return False
    if "todo" in normalized or "remind" in normalized or "checklist" in normalized:
        return True
    return any(hint in normalized for hint in _CHORE_HINTS)


def strip_daily_todo_text(text: str) -> str:
    cleaned = _normalize(text)
    cleaned = _DAILY_RE.sub(" ", cleaned)
    cleaned = _CLOCK_RE.sub(" ", cleaned)
    for prefix in (
        "add a daily todo",
        "add daily todo",
        "add a repeating todo",
        "add a repeat todo",
        "repeat todo",
        "repeating todo",
        "daily todo",
        "every day todo",
        "remind me every day to",
        "remind me everyday to",
        "remind me daily to",
        "every day remind me to",
        "add this to the todo list",
        "add that to the todo list",
        "add this to my todo list",
        "add to my todo list",
        "add to the todo list",
        "add a todo",
        "remind me to",
        "remind myself to",
        "remind myself",
        "remind me at",
        "at",
    ):
        if cleaned.startswith(prefix + " "):
            cleaned = cleaned[len(prefix) :].strip()
        elif cleaned == prefix:
            cleaned = ""
    cleaned = re.sub(r"\b(to do|todo|please|silva)\b", " ", cleaned)
    cleaned = re.sub(r"^\s*to\s+", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip(" ,.-")


_MUMBLE_TOKENS = {
    "uh",
    "um",
    "er",
    "ah",
    "hmm",
    "mm",
    "mmm",
    "uhh",
    "umm",
    "huh",
    "nuh",
    "eh",
    "uhhuh",
}


def parse_todo_number(text: str) -> int | None:
    normalized = _normalize(text)
    if not normalized:
        return None
    match = re.search(r"\b(?:number|todo|item|#)?\s*(\d{1,2})\b", normalized)
    if match:
        value = int(match.group(1))
        return value if 1 <= value <= 99 else None
    for word, value in _NUMBER_WORDS.items():
        if re.search(rf"\b{word}\b", normalized):
            return value
    return None


def parse_move_numbers(text: str) -> tuple[int, int] | None:
    normalized = _normalize(text)
    src = parse_todo_number(normalized)
    if src is None:
        return None
    dest_match = re.search(
        r"\b(?:to|onto)\s+(?:number\s+|todo\s+)?(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|first|second|third)\b",
        normalized,
    )
    if dest_match:
        raw = dest_match.group(1)
        dest = int(raw) if raw.isdigit() else _NUMBER_WORDS.get(raw)
        if dest:
            return src, dest
    if re.search(r"\bup\b", normalized):
        return src, max(1, src - 1)
    if re.search(r"\bdown\b", normalized):
        return src, src + 1
    return None


def looks_like_mumble(text: str, *, confidence: float | None = None) -> bool:
    """True when speech sounds slurred, mumbled, or the recognizer was unsure."""
    if confidence is not None and 0 < confidence < 0.58:
        return True
    body = _normalize(text)
    if not body:
        return False
    words = body.split()
    if not words:
        return False
    fillers = sum(1 for word in words if word in _MUMBLE_TOKENS or len(word) == 1)
    if len(words) >= 2 and fillers / len(words) >= 0.6:
        return True
    if re.search(r"(.)\1{3,}", body):
        return True
    letters = re.sub(r"[^a-z]", "", body)
    if len(letters) >= 10:
        vowels = sum(1 for char in letters if char in "aeiou")
        if vowels / len(letters) < 0.16:
            return True
    return False


def _strip_prefix(normalized: str, prefixes: tuple[str, ...]) -> tuple[str, str] | None:
    for prefix in prefixes:
        if normalized == prefix:
            return prefix, ""
        if normalized.startswith(prefix + " "):
            return prefix, normalized[len(prefix) :].strip()
    return None


def match_notes_speech(text: str) -> NotesSpeech | None:
    if not text or not text.strip():
        return None
    from silva.commands.help_phrases import should_yield_to_feature_help

    if should_yield_to_feature_help(text):
        return None
    raw = _FILLER_RE.sub("", text.strip())
    normalized = _normalize(raw)
    if not normalized:
        return None

    if normalized in {"cancel", "never mind", "nevermind", "forget it", "stop that"}:
        return NotesSpeech("cancel")

    if normalized in _NOT_MATH or "not a math" in normalized:
        return NotesSpeech("type", "", kind="todo")

    hit = _strip_prefix(normalized, _TYPE_NOTE)
    if hit:
        return NotesSpeech("type", hit[1], kind="note")
    hit = _strip_prefix(normalized, _TYPE_TODO)
    if hit:
        return NotesSpeech("type", hit[1], kind="todo")

    if normalized in _OPEN_TODO:
        return NotesSpeech("open_todo", kind="todo")
    if normalized in _CLOSE_TODO:
        return NotesSpeech("close_todo", kind="todo")
    if normalized in _LIST_TODO:
        return NotesSpeech("list_todo", kind="todo")
    if normalized in _REMIND_OF_NOTES:
        return NotesSpeech("list_notes")
    if normalized in _ASK_REMINDER:
        return NotesSpeech("ask_reminder")
    delete_index = re.match(
        r"^(delete|remove|scratch|take off|get rid of)\s+"
        r"(the\s+|my\s+|that\s+)?"
        r"(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|\d+)\s+"
        r"(todo|item)(\s+list)?$",
        normalized,
    )
    if delete_index:
        number = parse_todo_number(delete_index.group(3))
        return NotesSpeech("delete_todo", delete_index.group(3), kind="todo", number=number)

    if (
        normalized in _CLEAR_TODO_LIST
        or normalized.startswith("delete the entire")
        or normalized.startswith("clear the entire")
        or re.match(r"^(delete|remove|erase|clear|wipe)\s+(the |my |that )?(entire )?todo list$", normalized)
    ):
        return NotesSpeech("clear_todos", kind="todo")
    if normalized in _UNDO_LAST_TODO:
        return NotesSpeech("undo_last_todo", kind="todo")

    hit = _strip_prefix(normalized, _MOVE_TODO_PREFIXES)
    if hit or normalized.startswith("move "):
        rest = hit[1] if hit else normalized
        pair = parse_move_numbers(normalized)
        number = pair[0] if pair else parse_todo_number(rest)
        dest = pair[1] if pair else None
        if number is not None or hit:
            return NotesSpeech("move_todo", rest, kind="todo", number=number, dest_number=dest)

    hit = _strip_prefix(normalized, _EDIT_TODO_PREFIXES)
    if hit:
        return NotesSpeech("edit_todo", hit[1], kind="todo", number=parse_todo_number(hit[1] or normalized))

    hit = _strip_prefix(normalized, _COMPLETE_TODO_PREFIXES)
    if hit:
        needs_list_word = hit[0] in {"i completed", "i finished", "i done"}
        if needs_list_word and "todo" not in normalized:
            pass
        else:
            return NotesSpeech("complete_todo", hit[1], kind="todo")

    hit = _strip_prefix(normalized, _RESTORE_TODO_PREFIXES)
    if hit:
        return NotesSpeech("restore_todo", hit[1], kind="todo")

    hit = _strip_prefix(normalized, _ARCHIVE_TODO_PREFIXES)
    if hit:
        return NotesSpeech("archive_todo", hit[1], kind="todo", number=parse_todo_number(hit[1] or normalized))

    hit = _strip_prefix(normalized, _DELETE_TODO_PREFIXES)
    if hit:
        return NotesSpeech("delete_todo", hit[1], kind="todo", number=parse_todo_number(hit[1] or normalized))
    if re.match(
        r"^(delete|remove)\s+(number\s+)?("
        r"\d+|one|two|three|four|five|six|seven|eight|nine|ten|"
        r"first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth"
        r")\b",
        normalized,
    ):
        return NotesSpeech("delete_todo", normalized, kind="todo", number=parse_todo_number(normalized))

    hit = _strip_prefix(normalized, _ADD_DAILY_PREFIXES)
    if hit:
        clock = parse_todo_clock(raw) or parse_todo_clock(normalized)
        title = strip_daily_todo_text(hit[1] or normalized)
        return NotesSpeech("add_todo", title, kind="todo", time_hm=clock, daily=True)

    if looks_like_daily_todo(normalized):
        clock = parse_todo_clock(raw) or parse_todo_clock(normalized)
        title = strip_daily_todo_text(normalized)
        return NotesSpeech("add_todo", title, kind="todo", time_hm=clock, daily=True)

    hit = _strip_prefix(normalized, _ADD_TODO_PREFIXES)
    if hit:
        clock = parse_todo_clock(raw) or parse_todo_clock(hit[1] or normalized)
        daily = bool(_DAILY_RE.search(hit[1] or normalized)) or clock is not None
        title = strip_daily_todo_text(hit[1] or normalized)
        return NotesSpeech("add_todo", title, kind="todo", time_hm=clock, daily=daily)

    if looks_like_timed_reminder(raw) or looks_like_timed_reminder(normalized):
        clock = parse_todo_clock(raw) or parse_todo_clock(normalized)
        title = strip_daily_todo_text(normalized)
        return NotesSpeech("add_todo", title, kind="todo", time_hm=clock, daily=clock is not None)

    if normalized in _LIST_NOTES:
        return NotesSpeech("list_notes")

    hit = _strip_prefix(normalized, _SEARCH_NOTE_PREFIXES)
    if hit:
        return NotesSpeech("search_note", hit[1])

    hit = _strip_prefix(normalized, _REMIND_NOTE_PREFIXES)
    if hit:
        return NotesSpeech("remind_note", hit[1])

    hit = _strip_prefix(normalized, _DELETE_NOTE_PREFIXES)
    if hit:
        return NotesSpeech("delete_note", hit[1])

    hit = _strip_prefix(normalized, _ADD_NOTE_PREFIXES)
    if hit:
        if hit[0] == "remember this" and hit[1].startswith("voice"):
            return None
        if hit[0] == "remember that" and hit[1].startswith("voice"):
            return None
        return NotesSpeech("add_note", hit[1])

    if "todo list" in normalized or normalized.endswith(" todo"):
        if normalized.startswith("what") or normalized.startswith("list") or normalized.startswith("read"):
            return NotesSpeech("list_todo", kind="todo")
        if normalized.startswith("open") or normalized.startswith("show") or normalized.startswith("bring up"):
            return NotesSpeech("open_todo", kind="todo")

    if re.search(r"\bmy notes\b", normalized) and (
        normalized.startswith("what") or normalized.startswith("list") or normalized.startswith("read")
    ):
        return NotesSpeech("list_notes")

    return None


def is_notes_command(text: str) -> bool:
    from silva.commands.help_phrases import should_yield_to_feature_help

    if should_yield_to_feature_help(text):
        return False
    return match_notes_speech(text) is not None


def is_weak_note_body(text: str) -> bool:
    body = _normalize(text)
    if not body:
        return True
    if body in {"this", "that", "it", "um", "uh", "er", "ah", "hmm", "something", "stuff", "thing"}:
        return True
    if len(body) < 3:
        return True
    return False
