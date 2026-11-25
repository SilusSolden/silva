"""Rule-based multi-turn conversation engine — no external AI models."""

from __future__ import annotations

import random
import re

from silva.conversation.context import ConversationContext
from silva.conversation.history_fallback import combined_fallback
from silva.conversation.learned_phrases import match_learned, remember_unknown
from silva.conversation.matching import contains_any, dedupe_repeated_phrase, normalize as normalize_text
from silva.commands.help_phrases import is_help_request, help_reply_for_user
from silva.commands.visual_guide_phrases import match_visual_guide_speech
from silva.conversation.vocabulary import classify_topics, pick_topic_reply, vocabulary_fallback
from silva.conversation import small_talk as st
from silva.conversation.reply_selector import pick_reply, pick_random, spark_conversation
from silva.conversation.user_patterns import classify_user_tone
from silva.users.manager import get_active_user

GREETINGS = st.GREETING_TRIGGERS
FAREWELLS = ("goodbye", "bye", "see you", "see ya", "talk later", "later", "take care")
THANKS = st.THANKS_TRIGGERS
HOW_ARE_YOU = st.HOW_ARE_YOU_TRIGGERS
WHATS_UP = st.WHATS_UP_TRIGGERS
NAME_ASK = (
    "what is your name", "whats your name", "who are you", "what should i call you",
)
JOKE_ASK = (
    "tell me a joke", "make me laugh", "say something funny", "got a joke", "joke please",
)
COMPLIMENTS = (
    "you are awesome", "you are great", "good job", "well done", "nice work",
    "you rock", "you're the best", "you are the best",
)
ENCOURAGEMENT = st.ENCOURAGEMENT
SMALL_TALK = (
    "nice day", "beautiful day", "cold today", "hot today",
)
LOVE_LIKE = ("i like you", "i love you", "you're cool", "you are cool")
CONFUSED = (
    "i don't understand", "i dont understand", "what do you mean",
    "say that again", "repeat that",
    "that is not what i said", "thats not what i said",
    "that was not what i said", "i did not say that", "i didnt say that",
    "i misspoke", "i mis spoke", "thats wrong", "that is wrong", "that was wrong",
)

MAX_TURNS = 200


def _normalize(text: str) -> str:
    return normalize_text(text)


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return contains_any(text, phrases)


def _user_name() -> str:
    try:
        user = get_active_user()
    except Exception:
        return ""
    return user.get("name", "")


def _name_suffix() -> str:
    name = _user_name()
    return f", {name}" if name and name != "Guest" else ""


def _match_mood(normalized: str) -> str:
    for word in st.MOOD_BAD:
        if word in normalized:
            return "bad"
    for word in st.MOOD_GOOD:
        if word in normalized:
            return "good"
    for word in st.MOOD_NEUTRAL:
        if word in normalized:
            return "neutral"
    return "neutral"


def _pick(pool: tuple[str, ...]) -> str:
    return random.choice(pool)


def _reply_from_tone(tone: str, context: ConversationContext) -> str | None:
    if tone == "thanks_extended":
        context.category = "thanks"
        context.follow_up = "talk_more"
        return pick_reply("thanks_extended", context)
    if tone == "reciprocal":
        context.category = "reciprocal"
        context.follow_up = "talk_more"
        from silva.conversation.response_bank import RECIPROCAL_AI_STATUS, RECIPROCAL_QUESTIONS

        return f"{_pick(RECIPROCAL_AI_STATUS)} {_pick(RECIPROCAL_QUESTIONS)}"
    if tone == "not_much":
        context.category = "whats_up"
        context.follow_up = "talk_more"
        return pick_reply("not_much", context)
    if tone == "ai_critique":
        context.category = "critique"
        context.follow_up = "talk_more"
        return pick_reply("ai_critique", context)
    if tone in {"sarcasm", "frustration"}:
        context.category = "sarcasm"
        context.follow_up = "talk_more"
        context.expecting_tone = None
        context.last_denial = None
        return pick_reply("sarcasm", context)
    return None


def _handle_follow_up(context: ConversationContext, normalized: str) -> tuple[str | None, str | None]:
    key = context.follow_up
    if not key:
        return None, None

    if key == "after_denial":
        tone = classify_user_tone(normalized) or context.expecting_tone
        if tone in {"sarcasm", "frustration", "ai_critique"}:
            reply = pick_reply("sarcasm", context)
            context.last_denial = None
            context.expecting_tone = None
            return reply, "talk_more"
        reply = pick_reply("denial_followup", context)
        return reply, "talk_more"

    if key == "how_are_you":
        mood = _match_mood(normalized)
        if mood == "good":
            reply = _pick(st.FOLLOW_UP_HOW_ARE_YOU[st.MOOD_GOOD])
        elif mood == "bad":
            reply = _pick(st.FOLLOW_UP_HOW_ARE_YOU[st.MOOD_BAD])
        else:
            reply = _pick(st.FOLLOW_UP_HOW_ARE_YOU[st.MOOD_NEUTRAL])
        return reply, "talk_more"

    if key == "whats_up":
        mood = _match_mood(normalized)
        if mood == "good":
            reply = _pick(st.FOLLOW_UP_WHATS_UP[st.MOOD_GOOD])
        elif mood == "bad":
            reply = _pick(st.FOLLOW_UP_WHATS_UP[st.MOOD_BAD])
        else:
            reply = _pick(st.FOLLOW_UP_WHATS_UP[st.MOOD_NEUTRAL])
        return reply, "talk_more"

    if key == "greeting":
        mood = _match_mood(normalized)
        if mood == "good":
            reply = _pick(st.FOLLOW_UP_GREETING[st.MOOD_GOOD])
        elif mood == "bad":
            reply = _pick(st.FOLLOW_UP_GREETING[st.MOOD_BAD])
        else:
            reply = _pick(st.FOLLOW_UP_GREETING[st.MOOD_NEUTRAL])
        return reply, "talk_more"

    if key == "talk_more":
        tone = classify_user_tone(normalized)
        if tone:
            reply = _reply_from_tone(tone, context)
            if reply:
                return reply, "talk_more"
        vocab = _reply_from_vocabulary(normalized, context)
        if vocab:
            return vocab, "talk_more"
        from silva.conversation.vocabulary import vocabulary_fallback

        reply = vocabulary_fallback(context.last_user_text or normalized, context.response_indices or {})
        return reply, "talk_more"

    if key == "plans":
        for patterns, replies in st.FOLLOW_UP_PLANS.items():
            if any(p in normalized for p in patterns):
                return _pick(replies), "talk_more"
        return pick_reply("talk_more", context), "talk_more"

    return None, None


def is_conversational_utterance(text: str) -> bool:
    normalized = _normalize(text)
    if not normalized:
        return False

    short_complete = {
        "hello", "hi", "hey", "howdy", "yo", "hiya", "heya", "sup",
        "thanks", "thank you", "ok", "okay", "yes", "no", "good", "fine", "great",
        "goodbye", "bye", "morning", "evening",
    }
    if normalized in short_complete:
        return True

    if classify_user_tone(text):
        return True

    if len(normalized.split()) >= 3:
        if _contains_any(normalized, GREETINGS + HOW_ARE_YOU + WHATS_UP + THANKS + SMALL_TALK):
            return True
        if _contains_any(normalized, st.CASUAL_CHECKINS):
            return True
        if _contains_any(normalized, COMPLIMENTS + ENCOURAGEMENT + LOVE_LIKE + CONFUSED):
            return True
        if normalized.endswith("?"):
            return True

    if _contains_any(normalized, GREETINGS + HOW_ARE_YOU + WHATS_UP + NAME_ASK + JOKE_ASK + THANKS):
        return True
    if _contains_any(normalized, st.CASUAL_CHECKINS):
        return True

    return False


def is_recall_request(text: str) -> str | None:
    normalized = _normalize(text)
    if normalized in {"recall history", "show my history", "past conversations", "my history"}:
        return "all"
    if normalized in {"recall searches", "past searches", "my searches", "what did i search"}:
        return "searches"
    if normalized in {"recall guides", "past guides", "my guides", "crafting history"}:
        return "guides"
    if normalized in {"recall conversations", "past chats", "what did we talk about"}:
        return "conversations"
    return None


def _reply_from_vocabulary(text: str, context: ConversationContext) -> str | None:
    topics = classify_topics(text)
    reply = pick_topic_reply(topics, context.response_indices or {})
    if reply:
        context.category = topics[0] if topics else "vocabulary"
        context.follow_up = "talk_more"
        return reply
    return None


def _fallback_reply(text: str, context: ConversationContext, user_id: str) -> str:
    remember_unknown(text, user_id=user_id, category=context.category or "unknown")
    return combined_fallback(user_id, text, context.response_indices or {})


def _should_reset_follow_up(normalized: str) -> bool:
    """Fresh openers should not be swallowed by an old talk_more follow-up."""
    if is_help_request(normalized):
        return True
    if match_visual_guide_speech(normalized):
        return True
    if is_conversational_utterance(normalized):
        return True
    return _contains_any(
        normalized,
        HOW_ARE_YOU
        + WHATS_UP
        + GREETINGS
        + NAME_ASK
        + JOKE_ASK
        + THANKS
        + FAREWELLS
        + st.CASUAL_CHECKINS
        + COMPLIMENTS,
    )


def _try_opener_reply(
    normalized: str,
    context: ConversationContext,
    suffix: str,
) -> tuple[str, ConversationContext, str | None, float] | None:
    """Fast path for greetings and check-ins — skips slow fallback pools."""
    if _contains_any(normalized, HOW_ARE_YOU):
        reply, follow = _pick(st._build_how_are_you_openers(suffix))
        context.category = "how_are_you"
        context.follow_up = follow
        context.turn_count += 1
        context.last_prompt = reply
        return reply, context, follow, 1.0

    if _contains_any(normalized, WHATS_UP):
        reply, follow = _pick(st._build_whats_up_openers(suffix))
        context.category = "whats_up"
        context.follow_up = follow
        context.turn_count += 1
        context.last_prompt = reply
        return reply, context, follow, 1.0

    if _contains_any(normalized, GREETINGS):
        reply, follow = _pick(st._build_greeting_openers(suffix))
        context.category = "greeting"
        context.follow_up = follow
        context.turn_count += 1
        context.last_prompt = reply
        return reply, context, follow, 1.0

    if _contains_any(normalized, st.CASUAL_CHECKINS):
        reply = _pick(st.CASUAL_CHECKIN_REPLIES)
        context.category = "how_are_you"
        context.follow_up = "how_are_you"
        context.turn_count += 1
        context.last_prompt = reply
        return reply, context, "how_are_you", 1.0

    return None


def try_conversation_with_context(
    text: str,
    context: ConversationContext,
    *,
    user_id: str = "guest",
) -> tuple[str | None, ConversationContext, float]:
    text = dedupe_repeated_phrase(text)
    normalized = _normalize(text)
    if not normalized:
        return None, context, 0.0

    from silva.commands.intent import is_action_command

    if is_action_command(text):
        return None, context, 0.0

    learned = match_learned(text, user_id=user_id)
    if learned is not None and str(learned.get("kind") or "reply") == "reply":
        reply = str(learned.get("reply") or "")
        context.category = "learned"
        context.follow_up = "talk_more"
        context.turn_count += 1
        context.last_prompt = reply
        return reply, context, 0.98

    if context.turn_count >= MAX_TURNS:
        context.reset()

    context.last_user_text = text

    if is_help_request(text):
        context.reset()
        user = get_active_user()
        return help_reply_for_user(user), context, 1.0

    suffix = _name_suffix()
    opener = _try_opener_reply(normalized, context, suffix)
    if opener is not None:
        reply, context, _follow, confidence = opener
        return reply, context, confidence

    tone = classify_user_tone(text)
    if tone:
        reply = _reply_from_tone(tone, context)
        if reply:
            context.turn_count += 1
            context.last_prompt = reply
            return reply, context, 0.95

    if context.follow_up:
        if _should_reset_follow_up(normalized):
            context.follow_up = None
        else:
            reply, next_key = _handle_follow_up(context, normalized)
            if reply:
                context.follow_up = next_key
                context.turn_count += 1
                context.last_prompt = reply
                confidence = 0.35 if next_key == "talk_more" else 0.85
                return reply, context, confidence

    if _contains_any(normalized, st.CONTINUE_PHRASES) and context.category:
        reply = pick_reply("talk_more", context)
        context.follow_up = "talk_more"
        context.turn_count += 1
        return reply, context, 1.0

    if _contains_any(normalized, st.ANOTHER_JOKE):
        reply = _pick(st.JOKE_RESPONSES)
        context.category = "joke"
        context.follow_up = "talk_more"
        context.turn_count += 1
        context.last_prompt = reply
        return reply, context, 1.0

    if _contains_any(normalized, THANKS):
        reply = _pick(st.THANKS_REPLIES)
        context.category = "thanks"
        context.follow_up = "talk_more"
        context.turn_count += 1
        return reply, context, 1.0

    if _contains_any(normalized, NAME_ASK):
        context.reset()
        return st.NAME_ASK_REPLY, context, 1.0

    if _contains_any(normalized, JOKE_ASK):
        reply = _pick(st.JOKE_RESPONSES)
        context.category = "joke"
        context.follow_up = "talk_more"
        context.turn_count += 1
        return reply, context, 1.0

    if _contains_any(normalized, COMPLIMENTS):
        reply = _pick(st.COMPLIMENT_REPLIES)
        context.category = "compliment"
        context.follow_up = "talk_more"
        context.turn_count += 1
        return reply, context, 1.0

    if _contains_any(normalized, ENCOURAGEMENT):
        if "bored" in normalized:
            reply = _pick(st.BORED_REPLIES)
        elif "tired" in normalized:
            reply = _pick(st.STRESSED_REPLIES)
        else:
            reply = _pick(st.STRESSED_REPLIES)
        context.category = "encouragement"
        context.follow_up = "talk_more"
        context.turn_count += 1
        return reply, context, 1.0

    if _contains_any(normalized, SMALL_TALK):
        if "cold" in normalized:
            reply = _pick(st.SMALL_TALK_COLD)
        elif "hot" in normalized:
            reply = _pick(st.SMALL_TALK_HOT)
        else:
            reply = _pick(st.SMALL_TALK_WEATHER)
        context.category = "small_talk"
        context.follow_up = "talk_more"
        context.turn_count += 1
        return reply, context, 1.0

    topics = classify_topics(text)
    if "deep_chat" in topics or (len(normalized.split()) >= 10 and topics):
        reply = _fallback_reply(text, context, user_id)
        context.category = topics[0] if topics else "chat"
        context.follow_up = "talk_more"
        context.turn_count += 1
        context.last_prompt = reply
        return reply, context, 0.55

    if _contains_any(normalized, LOVE_LIKE):
        reply = _pick(st.LOVE_LIKE_REPLIES)
        context.category = "love_like"
        context.follow_up = "talk_more"
        context.turn_count += 1
        return reply, context, 1.0

    from silva.conversation.reply_variants import wants_explanation

    if wants_explanation(text):
        reply = _fallback_reply(text, context, user_id)
        context.category = "explain"
        context.follow_up = "talk_more"
        context.turn_count += 1
        context.last_prompt = reply
        return reply, context, 0.65

    if _contains_any(normalized, CONFUSED):
        reply = _pick(st.CONFUSED_REPLIES)
        context.category = "confused"
        context.follow_up = "talk_more"
        context.turn_count += 1
        return reply, context, 1.0

    if _contains_any(normalized, FAREWELLS):
        context.reset()
        return None, context, 0.0

    if re.search(r"\bmy name is (\w+)", normalized):
        captured = re.search(r"\bmy name is (\w+)", normalized)
        spoken_name = captured.group(1).title() if captured else "friend"
        name = _user_name()
        if name and name.lower() == spoken_name.lower():
            return f"Yes, I know you as {name}.", context, 1.0
        context.follow_up = "talk_more"
        return f"Nice to meet you, {spoken_name}. I'll remember that for our chat.", context, 0.9

    if normalized.endswith("?"):
        if "your name" in normalized or "who are you" in normalized:
            return st.NAME_ASK_REPLY, context, 1.0
        if "my name" in normalized:
            name = _user_name()
            return f"You're {name}." if name else "I don't have your name saved yet.", context, 1.0
        from silva.conversation.reply_variants import wants_explanation

        if wants_explanation(text) or _contains_any(normalized, HOW_ARE_YOU + WHATS_UP + st.CASUAL_CHECKINS):
            if wants_explanation(text):
                reply = _fallback_reply(text, context, user_id)
            else:
                reply = _pick(st.CASUAL_QUESTION_REPLIES)
        else:
            reply = pick_random("talk_more")
        context.category = "question"
        context.follow_up = "talk_more"
        context.turn_count += 1
        return reply, context, 1.0

    if context.category:
        reply = pick_reply("talk_more", context)
        context.follow_up = "talk_more"
        context.turn_count += 1
        return reply, context, 1.0

    reply = _fallback_reply(text, context, user_id)
    context.category = "fallback"
    context.follow_up = "talk_more"
    context.turn_count += 1
    context.last_prompt = reply
    return reply, context, 0.5


def try_conversation(text: str) -> str | None:
    reply, _ctx, _confidence = try_conversation_with_context(text, ConversationContext())
    return reply
