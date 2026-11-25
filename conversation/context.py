"""Multi-turn conversation state for Silva."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from silva.config import CONFIG_DIR

STATE_FILE = CONFIG_DIR / "conversation_state.json"


@dataclass
class ConversationContext:
    category: str | None = None
    follow_up: str | None = None
    turn_count: int = 0
    last_prompt: str | None = None
    last_user_text: str | None = None
    last_denial: str | None = None
    expecting_tone: str | None = None
    response_indices: dict[str, int] | None = None

    def __post_init__(self) -> None:
        if self.response_indices is None:
            self.response_indices = {}

    def reset(self) -> None:
        self.category = None
        self.follow_up = None
        self.turn_count = 0
        self.last_prompt = None
        self.last_user_text = None
        self.last_denial = None
        self.expecting_tone = None

    def note_denial(self, message: str) -> None:
        self.last_denial = message
        self.expecting_tone = "frustration"
        self.follow_up = "after_denial"

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "follow_up": self.follow_up,
            "turn_count": self.turn_count,
            "last_prompt": self.last_prompt,
            "last_user_text": self.last_user_text,
            "last_denial": self.last_denial,
            "expecting_tone": self.expecting_tone,
            "response_indices": self.response_indices or {},
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> ConversationContext:
        if not data:
            return cls()
        return cls(
            category=data.get("category"),
            follow_up=data.get("follow_up"),
            turn_count=int(data.get("turn_count", 0)),
            last_prompt=data.get("last_prompt"),
            last_user_text=data.get("last_user_text"),
            last_denial=data.get("last_denial"),
            expecting_tone=data.get("expecting_tone"),
            response_indices=data.get("response_indices") or {},
        )


def load_context(user_id: str) -> ConversationContext:
    import json

    if not STATE_FILE.exists():
        return ConversationContext()
    try:
        with open(STATE_FILE, encoding="utf-8") as handle:
            data = json.load(handle)
        return ConversationContext.from_dict(data.get(user_id or "guest"))
    except (json.JSONDecodeError, OSError):
        return ConversationContext()


def save_context(user_id: str, context: ConversationContext) -> None:
    import json

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, encoding="utf-8") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, dict):
                data = loaded
        except (json.JSONDecodeError, OSError):
            data = {}
    data[user_id or "guest"] = context.to_dict()
    with open(STATE_FILE, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
