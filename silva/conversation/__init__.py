"""Silva conversation package — rule-based small talk, no external AI."""

from silva.conversation.context import ConversationContext, load_context, save_context
from silva.conversation.engine import (
    COMPLIMENTS,
    CONFUSED,
    ENCOURAGEMENT,
    FAREWELLS,
    GREETINGS,
    HOW_ARE_YOU,
    JOKE_ASK,
    LOVE_LIKE,
    NAME_ASK,
    SMALL_TALK,
    THANKS,
    WHATS_UP,
    is_conversational_utterance,
    is_recall_request,
    try_conversation,
    try_conversation_with_context,
)

__all__ = [
    "COMPLIMENTS",
    "CONFUSED",
    "ConversationContext",
    "ENCOURAGEMENT",
    "FAREWELLS",
    "GREETINGS",
    "HOW_ARE_YOU",
    "JOKE_ASK",
    "LOVE_LIKE",
    "NAME_ASK",
    "SMALL_TALK",
    "THANKS",
    "WHATS_UP",
    "is_conversational_utterance",
    "is_recall_request",
    "load_context",
    "save_context",
    "try_conversation",
    "try_conversation_with_context",
]
