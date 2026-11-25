"""Learned phrase categories and learned replies for Silva."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path

from silva.config import CONFIG_DIR
from silva.conversation.matching import normalize

STORE_FILE = CONFIG_DIR / "learned_phrases.json"

_TEACH_RE = re.compile(
    r"^(?:learn|remember|train)\s+(?:that\s+)?(.+?)\s+"
    r"(?:means|is|should be|reply(?: with)?|respond(?: with)?|say)\s+(.+)$",
    re.I,
)
_WHEN_RE = re.compile(
    r"^(?:when|if)\s+(?:i\s+)?(?:say|ask|type)\s+(.+?)\s*,?\s*"
    r"(?:then\s+)?(?:say|respond|reply|run|do|answer)\s+(.+)$",
    re.I,
)
_CORRECTION_RE = re.compile(
    r"^(?:no|nope|nah|wrong|not quite)\b[, ]*"
    r"(?:(?:it|that)\s+)?(?:means|is|should be|reply|respond|say|i meant|i mean)\s+(.+)$",
    re.I,
)
_MEANT_RE = re.compile(r"^(?:no|nope|nah|actually)\b[, ]*i\s+(?:meant|mean)\s+(.+)$", re.I)
_SHORT_NO_RE = re.compile(r"^(?:no|nope|nah|wrong|not quite)\b", re.I)
_FORGET_RE = re.compile(
    r"^(?:forget|remove|delete|unlearn)\s+(?:learned\s+)?(?:phrase|reply|answer)?\s*(.+)$",
    re.I,
)
_LIST_RE = re.compile(r"^(?:list|show)\s+(?:my\s+)?learned\s+(?:phrases|replies|answers)\b", re.I)
_QUERY_RE = re.compile(
    r"^(?:what|how)\s+(?:should|do|would)\s+i\s+(?:say|respond|answer)\s+"
    r"(?:when|if)\s+i\s+(?:say|ask)\s+(.+)$",
    re.I,
)
_COMMAND_WORDS = (
    "open ",
    "close ",
    "show ",
    "start ",
    "stop ",
    "play ",
    "pause ",
    "set ",
    "add ",
    "delete ",
    "turn on",
    "turn off",
    "look up",
    "search ",
    "tell me ",
)

_LAST_UNKNOWN: dict[str, str] = {}

_STT_WORD_REPAIRS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bwhen i is\b", re.I), "when I ask"),
    (re.compile(r"\bif i is\b", re.I), "if I ask"),
    (re.compile(r"\bsome money answers\b", re.I), "somebody else access"),
    (re.compile(r"\bhelp\s+braces?\b", re.I), "help phrases"),
    (re.compile(r"\bwhat\s+was\s+fits\b", re.I), "what was fixed"),
    (re.compile(r"\bi\s+never\s+said\s+bitch\s+i\s+said\s+bits\s+f\s*i\s*x\b", re.I),
     "no I meant what was fixed"),
    (re.compile(r"\bbits\s+f\s*i\s*x\b", re.I), "fixed"),
    (
        re.compile(r"\bgive\s+me\s+songs\s+that\s+you(?:'re| are)\s+not\s+working\s+correctly\b", re.I),
        "you're pissing me off that you're not working correctly",
    ),
    (
        re.compile(
            r"\bi\s+never\s+said\s+songs\s+i\s+said\s+you(?:'re| are)\s+pissing\s+me\s+off\b",
            re.I,
        ),
        "you're pissing me off",
    ),
    (re.compile(r"\brecently\s+at\b", re.I), "recently added"),
    (re.compile(r"\bfind\s+(?:the\s+)?update\b", re.I), "fine, update"),
    (re.compile(r"\bbackground\s+test\b", re.I), "background task"),
    (re.compile(r"\btest\s+board\b", re.I), "task board"),
    (re.compile(r"\bboard\s+test\b", re.I), "board task"),
    (re.compile(r"\b(?:s\s+t\s+t|stt)\s+(?:e|ee)\b", re.I), "stt"),
    (re.compile(r"\bs\s*\.?\s*t\s*\.?\s*t(?:e|ee)?\b", re.I), "stt"),
)


def repair_stt_words(text: str) -> str:
    value = str(text or "")
    for pattern, replacement in _STT_WORD_REPAIRS:
        value = pattern.sub(replacement, value)
    return value


def _default() -> dict:
    return {"phrases": []}


def _read() -> dict:
    if not STORE_FILE.exists():
        return _default()
    try:
        data = json.loads(STORE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default()
    if not isinstance(data, dict) or not isinstance(data.get("phrases"), list):
        return _default()
    return {"phrases": [item for item in data["phrases"] if isinstance(item, dict)]}


def _write(data: dict) -> None:
    STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = STORE_FILE.with_suffix(".json.tmp")
    temp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temp.replace(STORE_FILE)


def _user_key(user_id: str) -> str:
    return str(user_id or "guest")


def _category(text: str) -> str:
    value = str(text or "").strip().lower()
    if value.endswith("?"):
        return "question"
    if any(value.startswith(word) for word in _COMMAND_WORDS):
        return "command"
    return "conversation"


def _tokens(text: str) -> set[str]:
    return {word for word in normalize(text).split() if len(word) > 2}


def _allowed(item: dict, user_id: str) -> bool:
    scope = str(item.get("user_id") or "")
    return not scope or scope == _user_key(user_id)


def set_unknown_context(user_id: str, text: str) -> None:
    _LAST_UNKNOWN[_user_key(user_id)] = str(text or "")


def take_unknown_context(user_id: str) -> str:
    return _LAST_UNKNOWN.pop(_user_key(user_id), "")


def remember_unknown(text: str, *, user_id: str = "", category: str = "") -> dict:
    value = str(text or "").strip()
    if not value:
        return {}
    key = normalize(value)
    data = _read()
    phrases = data["phrases"]
    for item in phrases:
        if normalize(str(item.get("text") or "")) == key and _allowed(item, user_id):
            item["seen"] = int(item.get("seen") or 0) + 1
            item["last_seen_at"] = datetime.now().isoformat(timespec="seconds")
            if not item.get("category") and category:
                item["category"] = category
            _write(data)
            set_unknown_context(user_id, value)
            return item
    record = {
        "id": uuid.uuid4().hex[:8],
        "text": value,
        "normalized": key,
        "category": str(category or _category(value)),
        "reply": "",
        "kind": "reply",
        "scope": "user",
        "user_id": _user_key(user_id),
        "status": "pending",
        "seen": 1,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    phrases.append(record)
    _write(data)
    set_unknown_context(user_id, value)
    return record


def match_learned(text: str, *, user_id: str = "") -> dict | None:
    key = normalize(text)
    if not key:
        return None
    candidates = [
        item
        for item in _read()["phrases"]
        if str(item.get("reply") or "") and _allowed(item, user_id)
    ]
    for item in candidates:
        if normalize(str(item.get("text") or "")) == key:
            return item

    wanted = _tokens(text)
    if not wanted:
        return None
    best: dict | None = None
    best_score = 0.0
    for item in candidates:
        known = _tokens(str(item.get("text") or ""))
        if not known:
            continue
        overlap = len(wanted & known) / max(len(wanted | known), 1)
        if overlap > best_score:
            best_score = overlap
            best = item
    if best_score >= 0.8:
        return best
    return None


def teach(
    phrase: str,
    reply: str,
    *,
    kind: str = "reply",
    category: str = "",
    user_id: str = "",
    actor_id: str = "",
    global_scope: bool = False,
) -> tuple[bool, str]:
    text = re.sub(r"^[\"']|[\"']$", "", str(phrase or "").strip()).strip(" .,?!")
    answer = re.sub(r"^[\"']|[\"']$", "", str(reply or "").strip())
    if not text or not answer:
        return False, "I need both a phrase and a reply to learn."
    if global_scope:
        from silva.conversation.speech_policy import is_privileged

        if not is_privileged(actor_id or user_id):
            return False, "Only the owner or an admin can teach a reply for everyone."
    key = normalize(text)
    data = _read()
    phrases = data["phrases"]
    scope_user = "" if global_scope else _user_key(actor_id or user_id)
    for item in phrases:
        if (
            normalize(str(item.get("text") or "")) == key
            and str(item.get("user_id") or "") == scope_user
        ):
            item["reply"] = answer
            item["kind"] = "command" if str(kind).lower() == "command" else "reply"
            item["category"] = str(category or item.get("category") or _category(text))
            item["status"] = "learned"
            item["scope"] = "global" if global_scope else "user"
            item["updated_at"] = datetime.now().isoformat(timespec="seconds")
            _write(data)
            return True, f"I updated what I do when you say '{text}'."
    phrases.append(
        {
            "id": uuid.uuid4().hex[:8],
            "text": text,
            "normalized": key,
            "category": str(category or _category(text)),
            "reply": answer,
            "kind": "command" if str(kind).lower() == "command" else "reply",
            "scope": "global" if global_scope else "user",
            "user_id": scope_user,
            "status": "learned",
            "seen": 0,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    _write(data)
    return True, f"I learned to answer '{text}' with '{answer}'."


def learn_from_correction(
    pending: str,
    correction: str,
    *,
    user_id: str = "",
    actor_id: str = "",
) -> tuple[bool, str]:
    text = str(pending or "").strip()
    reply = str(correction or "").strip()
    if not text or not reply:
        return False, ""
    match = _CORRECTION_RE.match(reply) or _MEANT_RE.match(reply)
    if match:
        answer = match.group(1).strip(" .")
    elif _SHORT_NO_RE.match(reply):
        answer = "Okay, I won't do that."
    else:
        answer = reply
    return teach(
        text,
        answer,
        category="correction",
        user_id=user_id,
        actor_id=actor_id,
    )


def forget(phrase: str, *, user_id: str = "", actor_id: str = "") -> tuple[bool, str]:
    key = normalize(phrase)
    if not key:
        return False, "Tell me which learned phrase to forget."
    data = _read()
    kept: list[dict] = []
    removed = 0
    for item in data["phrases"]:
        if normalize(str(item.get("text") or "")) == key and _allowed(item, actor_id or user_id):
            removed += 1
            continue
        kept.append(item)
    if not removed:
        return False, f"I do not have a learned reply for '{phrase}'."
    data["phrases"] = kept
    _write(data)
    return True, f"I forgot the learned reply for '{phrase}'."


def list_learned(*, user_id: str = "", limit: int = 20) -> list[dict]:
    items = [
        item
        for item in _read()["phrases"]
        if str(item.get("reply") or "") and _allowed(item, user_id)
    ]
    return items[-max(1, int(limit)) :][::-1]


def parse_learning_speech(text: str) -> tuple[str, dict] | None:
    value = str(text or "").strip()
    if not value:
        return None
    if _LIST_RE.match(value):
        return ("list", {})
    forget_match = _FORGET_RE.match(value)
    if forget_match:
        return ("forget", {"phrase": forget_match.group(1)})
    query_match = _QUERY_RE.match(value)
    if query_match:
        return ("query", {"phrase": query_match.group(1)})

    teach_match = _TEACH_RE.match(value) or _WHEN_RE.match(value)
    if teach_match:
        phrase = teach_match.group(1).strip(" .,?!")
        answer = teach_match.group(2).strip()
        lowered = value.lower()
        kind = "command" if re.search(r"\b(run|do|execute)\b", lowered) else "reply"
        global_scope = bool(
            re.search(r"\b(for everyone|for everybody|globally|always|all users)\b", lowered)
        )
        return ("teach", {"phrase": phrase, "reply": answer, "kind": kind, "global": global_scope})
    return None


def handle_learned_speech(assistant, text: str) -> bool:
    parsed = parse_learning_speech(text)
    if parsed is not None:
        action, values = parsed
        getter = getattr(assistant, "_user_id", None)
        user_id = getter() if callable(getter) else "guest"
        if action == "list":
            items = list_learned(user_id=user_id, limit=12)
            if not items:
                assistant.say("I have not learned any custom replies yet.", interruptible=False)
            else:
                lines = [f"{item.get('text')}: {item.get('reply')}" for item in items]
                assistant.say("Learned replies: " + "; ".join(lines), interruptible=False)
            return True
        if action == "query":
            item = match_learned(str(values.get("phrase") or ""), user_id=user_id)
            if item is None:
                assistant.say("I have not learned that phrase yet.", interruptible=False)
            else:
                assistant.say(str(item.get("reply") or ""), interruptible=False)
            return True
        if action == "forget":
            ok, message = forget(str(values.get("phrase") or ""), user_id=user_id, actor_id=user_id)
            assistant.say(message, interruptible=False)
            return True
        ok, message = teach(
            str(values.get("phrase") or ""),
            str(values.get("reply") or ""),
            kind=str(values.get("kind") or "reply"),
            user_id=user_id,
            actor_id=user_id,
            global_scope=bool(values.get("global")),
        )
        assistant.say(message, interruptible=False)
        return True

    pending = take_unknown_context(_current_user_id(assistant))
    if pending:
        from silva.commands.intent import is_action_command

        if is_action_command(text):
            set_unknown_context(_current_user_id(assistant), pending)
            return False
        ok, message = learn_from_correction(
            pending,
            text,
            user_id=_current_user_id(assistant),
            actor_id=_current_user_id(assistant),
        )
        if ok:
            assistant.say(
                f"Got it. I'll remember that answer for '{pending}'.",
                interruptible=False,
            )
            return True

    if getattr(assistant, "_learned_command_active", False):
        return False
    item = match_learned(text, user_id=_current_user_id(assistant))
    if item is None:
        return False
    reply = str(item.get("reply") or "")
    if str(item.get("kind") or "reply") == "command":
        assistant._learned_command_active = True
        try:
            return assistant._handle_input(reply)
        finally:
            assistant._learned_command_active = False
    assistant.say(reply, interruptible=True)
    return True


def _current_user_id(assistant) -> str:
    getter = getattr(assistant, "_user_id", None)
    if callable(getter):
        return _user_key(getter())
    from silva.users.manager import get_active_user

    return _user_key((get_active_user() or {}).get("id"))
