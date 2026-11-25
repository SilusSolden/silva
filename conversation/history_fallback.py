"""Use past Silva chat logs to suggest follow-up replies."""

from __future__ import annotations

import random

from silva.history_store import get_recent_conversations


def history_based_reply(user_id: str, user_text: str) -> str | None:
    """Pick a contextual reply based on similar past exchanges."""
    history = get_recent_conversations(user_id, limit=50)
    if not history:
        return None

    user_lower = user_text.strip().lower()
    words = {w for w in user_lower.split() if len(w) > 2}

    best_score = 0
    best_ai: str | None = None

    for entry in history:
        past_user = str(entry.get("user", "")).lower()
        past_ai = str(entry.get("ai", "")).strip()
        if not past_user or not past_ai:
            continue
        past_words = {w for w in past_user.split() if len(w) > 2}
        overlap = len(words & past_words)
        if overlap > best_score:
            best_score = overlap
            best_ai = past_ai

    if best_score >= 2 and best_ai:
        return best_ai

    if best_score == 1 and best_ai and len(words) <= 4:
        return best_ai

    recent_ai = [str(e.get("ai", "")).strip() for e in history if e.get("ai")]
    if recent_ai:
        return random.choice(recent_ai[-10:])
    return None


def combined_fallback(user_id: str, user_text: str, cursor: dict[str, int]) -> str:
    """Logs first, then the vocabulary repository."""
    from silva.conversation.vocabulary import vocabulary_fallback

    history = history_based_reply(user_id, user_text)
    if history:
        return history
    return vocabulary_fallback(user_text, cursor)
