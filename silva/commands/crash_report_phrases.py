"""Detect when the user asks why Silva crashed last time."""

from __future__ import annotations

import re

_BUG_REPORT_STEAL = (
    "i found a bug",
    "report a bug",
    "bug report",
    "report bug",
)

_ASK_RE = re.compile(
    r"\b("
    r"(?:can you |could you |would you |please )?(?:tell me )?"
    r"why (?:did |do )?(?:you|the ai|silva|the assistant) "
    r"(?:crash(?:ed)?|die(?:d)?)"
    r"|"
    r"why (?:you|did you) crash(?:ed)?"
    r"|"
    r"what (?:made|caused) (?:you|the ai|silva) (?:crash|close|stop)"
    r"|"
    r"what happened last time you "
    r"(?:crash(?:ed)?|close(?:d)?|stop(?:ped)?|died|shut down)"
    r"|"
    r"why did you (?:close|stop|shut down|die) last time"
    r"|"
    r"did you crash(?:ed)?(?: last time)?"
    r"|"
    r"(?:show|open|see|pull up)(?: me)?(?: the)?(?: last)? "
    r"crash(?: report| log| file| txt)?"
    r"|"
    r"(?:last crash|crash report|crash log)"
    r")\b",
    re.I,
)

_COMMAND_FAIL_RE = re.compile(
    r"\b("
    r"(?:can you |could you |would you |please )?(?:tell me )?"
    r"why .{0,36}commands? .{0,28}(?:not work(?:ing)?|fail(?:ed)?|broke|broken|error)"
    r"|"
    r"why (?:were|are|did) (?:your |the |silvas? |the ais? )?commands? .{0,24}"
    r"(?:not work(?:ing)?|fail(?:ed)?)"
    r"|"
    r"why (?:did |were )?(?:every|all(?: of)?(?: the)?) commands? .{0,20}"
    r"(?:fail|error|not work)"
    r"|"
    r"why .{0,28}(?:every|all) command.{0,24}(?:error|fail)"
    r"|"
    r"unexpected assistant error"
    r"|"
    r"commands? were not work"
    r")\b",
    re.I,
)

_FILE_RE = re.compile(
    r"\b(show|open|see|popup|pop up|text file|\.txt|notepad|screenshot)\b",
    re.I,
)


def _normalize(text: str) -> str:
    text = (text or "").strip().lower()
    text = text.replace("'", "")
    text = re.sub(r"[^\w\s.]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_command_fail_ask(text: str) -> bool:
    normalized = _normalize(text)
    if not normalized:
        return False
    if any(phrase in normalized for phrase in _BUG_REPORT_STEAL):
        return False
    return bool(_COMMAND_FAIL_RE.search(normalized))


def is_crash_report_ask(text: str) -> bool:
    normalized = _normalize(text)
    if not normalized:
        return False
    if any(phrase in normalized for phrase in _BUG_REPORT_STEAL):
        return False
    if is_command_fail_ask(text):
        return True
    return bool(_ASK_RE.search(normalized))


def wants_crash_file(text: str) -> bool:
    return bool(_FILE_RE.search(_normalize(text)))
