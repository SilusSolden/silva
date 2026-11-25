"""Voice exit cues — same as clicking the close button on the Silva window."""

from __future__ import annotations

import re

_CLOSE = frozenset(
    {
        "goodbye",
        "good bye",
        "bye",
        "exit",
        "quit",
        "close silva",
        "exit silva",
        "quit silva",
    }
)


def _normalize(text: str) -> str:
    text = (text or "").strip().lower().replace("'", "")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_close_command(text: str) -> bool:
    """True when the user is telling Silva to shut down, like clicking the X."""
    return _normalize(text) in _CLOSE
