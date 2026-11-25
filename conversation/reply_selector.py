"""Pick non-repeating replies from large local pools."""

from __future__ import annotations

import random

from silva.conversation.response_bank import RESPONSE_POOLS


def pick_reply(pool_name: str, context, *, fallback_pool: str | None = None) -> str:
    pool = RESPONSE_POOLS.get(pool_name)
    if not pool:
        pool = RESPONSE_POOLS.get(fallback_pool or "talk_more", ("I'm listening.",))
    indices = context.response_indices
    index = int(indices.get(pool_name, 0))
    if index >= len(pool):
        index = 0
    reply = pool[index]
    indices[pool_name] = index + 1
    return reply


def pick_random(pool_name: str) -> str:
    pool = RESPONSE_POOLS.get(pool_name, ("I'm here if you want to keep talking.",))
    return random.choice(pool)


def spark_conversation(context) -> str:
    from silva.conversation.vocabulary import vocabulary_fallback

    return vocabulary_fallback("hello", context.response_indices or {})
