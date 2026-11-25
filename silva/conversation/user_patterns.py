"""Match user phrasing patterns for contextual replies."""

from __future__ import annotations

import re

from silva.conversation.matching import contains_any as phrase_contains_any, normalize as normalize_text

THANKS_EXTENDED = (
    "thank you for telling",
    "thanks for telling",
    "very good thank",
    "thank you very much",
    "thanks a lot",
    "appreciate you telling",
)

RECIPROCAL = (
    "what about you",
    "how about you",
    "what about yourself",
    "and you",
    "how are you though",
)

NOT_MUCH = (
    "not much",
    "nothing much",
    "not a lot",
    "same old",
    "nothing really",
    "nothing special",
)

AI_CRITIQUE = (
    "get better at speaking",
    "need to get better",
    "you need to improve",
    "speak better",
    "talk better",
    "better at talking",
    "better at speaking",
    "you suck at",
    "you're bad at",
    "you are bad at",
    "worst assistant",
    "useless",
    "not very good",
    "do better",
    "learn to speak",
    "learn to talk",
)

SARCASM = (
    "yeah right",
    "sure you cant",
    "sure you can't",
    "oh great",
    "wow thanks",
    "thanks a lot silva",
    "real helpful",
    "very funny",
    "nice one",
    "good job silva",
    "brilliant",
    "genius",
    "wow silva",
)

FRUSTRATION = (
    "this is stupid",
    "this is dumb",
    "so annoying",
    "why cant you",
    "why can't you",
    "you never",
    "you always",
    "figure it out",
    "come on",
)

FEATURE_REQUEST_PHRASES = (
    "request that feature",
    "ask admin to add",
    "tell admin to add",
    "add that feature",
    "enable that for me",
    "can admin add",
    "request access to",
)


def normalize(text: str) -> str:
    return normalize_text(text)


def contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return phrase_contains_any(text, phrases)


def classify_user_tone(text: str) -> str | None:
    normalized = normalize(text)
    if not normalized:
        return None
    if contains_any(normalized, AI_CRITIQUE):
        return "ai_critique"
    if contains_any(normalized, SARCASM):
        return "sarcasm"
    if contains_any(normalized, FRUSTRATION):
        return "frustration"
    if contains_any(normalized, THANKS_EXTENDED):
        return "thanks_extended"
    if contains_any(normalized, RECIPROCAL) or (
        contains_any(normalized, NOT_MUCH) and "you" in normalized
    ):
        return "reciprocal"
    if contains_any(normalized, NOT_MUCH):
        return "not_much"
    if contains_any(normalized, FEATURE_REQUEST_PHRASES):
        return "feature_request"
    return None
