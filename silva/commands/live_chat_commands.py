from __future__ import annotations

import re

from silva.gui.live_chat_instance import open_live_chat_popup
from silva.users.live_chat import submit_live_chat_message
from silva.users.manager import get_active_user

_LIVE_CHAT_RE = re.compile(
    r"\b(?:help|live|admin|owner)\s+chat\b|"
    r"\b(?:tell|ask)\s+(?:the\s+)?(?:admins?(?:\s+and\s+(?:the\s+)?owner)?|owner)\b",
    re.I,
)
_OPEN_RE = re.compile(
    r"\b(?:open|show|launch|bring up|display)\b.{0,30}\b(?:help|live|admin|owner)\s+chat\b",
    re.I,
)
_POPUP_RE = re.compile(
    r"\b(?:own|separate|standalone|popup|pop up)\b.{0,50}\b(?:help|live|admin|owner)\s+chat\b|"
    r"\b(?:help|live|admin|owner)\s+chat\b.{0,50}\b(?:own|separate|standalone|popup|pop up)\b",
    re.I,
)
_SEND_PREFIX_RE = re.compile(
    r"^(?:please\s+)?(?:send|submit|post)\s+(?:a\s+|an\s+)?(?:help|live|admin|owner)\s+chat"
    r"\s*(?:message\s*)?(?:that\s*)?(?:saying\s*)?",
    re.I,
)
_TELL_PREFIX_RE = re.compile(
    r"^(?:please\s+)?(?:tell|ask)\s+(?:the\s+)?"
    r"(?:admins?(?:\s+and\s+(?:the\s+)?owner)?|owner(?:\s+and\s+(?:the\s+)?admins?)?)\s*(?:that\s*)?",
    re.I,
)
_UPDATE_RE = re.compile(r"\b(?:update|version|patch|check|install)\w*\b", re.I)


def is_live_chat_speech(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(text or "").strip())
    return bool(normalized) and bool(_LIVE_CHAT_RE.search(normalized))


def _message_text(text: str) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "").strip())
    normalized = _SEND_PREFIX_RE.sub("", normalized, count=1)
    normalized = _TELL_PREFIX_RE.sub("", normalized, count=1)
    return normalized.strip(" ,.")


def handle_live_chat_speech(assistant, text: str, user: dict | None = None) -> bool:
    if not is_live_chat_speech(text):
        return False
    active = user or get_active_user() or {}

    if _OPEN_RE.search(str(text or "")) or _POPUP_RE.search(str(text or "")):
        open_live_chat_popup(user_id=str(active.get("id") or "guest"), reason="voice_open")
        assistant.say("Opening the live chat popup.", interruptible=False)
        return True

    message = _message_text(text)
    if not message:
        assistant.say("What would you like me to send to the admins and owner?", interruptible=False)
        return True

    kind = "update" if _UPDATE_RE.search(message) else "help"
    submit_live_chat_message(active, message, kind=kind)
    assistant.say("Sent to the live admin and owner chat.", interruptible=False)
    return True
