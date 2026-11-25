"""Large local response banks — no external AI model."""

from __future__ import annotations

import itertools

# Phrasing inspired by real Silva chats (screenshot reference).
SCREENSHOT_REPLIES: tuple[str, ...] = (
    "That's nice to hear. What should we talk about next?",
    "Alright. Tell me what's been happening.",
    "Sure. What's been on your mind lately?",
    "I'm glad that helped. What would you like to talk about now?",
    "Good to know. What's going on with you today?",
    "Fair enough. How has your day been treating you?",
    "I hear you. Want to keep chatting or do something else?",
    "Not much on my end — I'm here whenever you need me. What about you?",
    "Same as always, listening and ready. What's new with you?",
)

THANKS_EXTENDED_ACK: tuple[str, ...] = (
    "You're very welcome",
    "Any time",
    "Happy to help",
    "Glad I could help",
    "Of course",
    "No problem at all",
    "I'm glad that worked for you",
    "That's what I'm here for",
)

THANKS_EXTENDED_TAIL: tuple[str, ...] = (
    "What should we talk about next?",
    "Is there anything else on your mind?",
    "Want to keep chatting?",
    "What would you like to do next?",
    "I'm here if you need anything else.",
    "Let me know what you'd like to talk about.",
    "Feel free to ask me anything else.",
)

RECIPROCAL_AI_STATUS: tuple[str, ...] = (
    "I'm doing pretty well, thanks for asking.",
    "I'm good — thanks for checking in.",
    "Doing alright on my end.",
    "I'm okay. Appreciate you asking.",
    "Not bad at all, honestly.",
    "I'm fine. How about you?",
    "All good here.",
)

RECIPROCAL_QUESTIONS: tuple[str, ...] = (
    "What's been happening with you?",
    "What should we talk about next?",
    "Tell me what's on your mind.",
    "How has your day been?",
    "What's new with you?",
    "Anything interesting going on?",
)

AI_CRITIQUE_REPLIES: tuple[str, ...] = (
    "You're right — I'm still learning how to talk naturally. I'll keep improving. What felt off?",
    "Fair point. I want to get better at this. Tell me what you'd prefer I say.",
    "I hear you. I'm working on sounding more natural. Want to keep trying?",
    "Thanks for the honest feedback. I'll do my best to improve our chats.",
    "That's valid. I'm not perfect yet, but I'm listening. How can I do better?",
    "I appreciate you telling me that. I'll try to respond more naturally from here.",
)

SARCASM_REPLIES: tuple[str, ...] = (
    "I get the sarcasm. Fair enough — what would you actually like me to do?",
    "Point taken. Tell me what you need and I'll try to help for real.",
    "Alright, I deserve that one. What can I actually help with?",
    "You're not wrong to be frustrated. Want to try a command instead?",
    "I hear the attitude — I'll roll with it. What's next?",
    "Okay, okay. Message received. How can I make this better?",
)

DENIAL_FOLLOWUP_REPLIES: tuple[str, ...] = (
    "I know that's not what you wanted to hear. You can ask an admin to enable it.",
    "I wish I could. If you submit a request, an admin can review it.",
    "I get it — it's annoying when I can't do something. Want to request access?",
    "Fair reaction. I'm limited right now, but admins can approve new features.",
)

PENDING_FEATURE_REPLIES: tuple[str, ...] = (
    "That feature was already requested. Please wait for the admins to install the new patch.",
    "Your request is pending.admin approval. I'll let you know once it's available.",
    "Admins are reviewing that feature request. Hang tight for the next patch.",
)

NAG_WARNING_REPLIES: tuple[str, ...] = (
    "Please stop repeatedly asking for that feature — it may get blocked on your profile.",
    "I've noted your requests. Asking again and again could limit your access when it releases.",
    "Warning: continued requests may flag your account. Wait for admin approval instead.",
)

BLOCKED_FEATURE_REPLIES: tuple[str, ...] = (
    "That feature request is blocked on your profile until an admin removes the flag.",
    "You're temporarily blocked from requesting that feature. Contact an admin if you need help.",
)

SPARK_CONVERSATION: tuple[str, ...] = (
    "We can talk about your day, the weather, look something up, or try a command — your call.",
    "Want to tell me how your day's going, hear a joke, or look something up on Wikipedia?",
    "I'm here to chat or help. What's on your mind right now?",
    "If you want small talk, I'm in. Or say weather, open profile, or sleep mode anytime.",
    "Tell me something about your day, or ask me to search for something you're curious about.",
)

NOT_MUCH_REPLIES: tuple[str, ...] = (
    "Not much? That's okay. What's been on your mind anyway?",
    "Fair enough — quiet days happen. Want to chat about anything?",
    "Alright. Even when it's not much, I'm still here to listen.",
    "I get it. Sometimes it's a low-key day. What would make it better?",
)

VERY_GOOD_REPLIES: tuple[str, ...] = (
    "Very good — I'm glad to hear that.",
    "That's great to hear.",
    "Happy you're doing well.",
    "Good to know things are going well.",
)


def _unique(items: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(item.strip())
    return tuple(out)


def build_thanks_extended_pool() -> tuple[str, ...]:
    items = list(SCREENSHOT_REPLIES)
    for ack, tail in itertools.product(THANKS_EXTENDED_ACK, THANKS_EXTENDED_TAIL):
        items.append(f"{ack}. {tail}")
    for ack in VERY_GOOD_REPLIES:
        for tail in THANKS_EXTENDED_TAIL:
            items.append(f"{ack} {tail}")
    return _unique(items)


def build_reciprocal_pool() -> tuple[str, ...]:
    items = list(SCREENSHOT_REPLIES)
    for status, question in itertools.product(RECIPROCAL_AI_STATUS, RECIPROCAL_QUESTIONS):
        items.append(f"{status} {question}")
    for line in RECIPROCAL_AI_STATUS:
        items.append(line)
    return _unique(items)


def build_talk_more_pool() -> tuple[str, ...]:
    acks = (
        "That's nice to hear",
        "I hear you",
        "Fair enough",
        "Alright",
        "Sure",
        "Got it",
        "Okay",
        "I understand",
        "Makes sense",
        "Right",
        "True",
        "Absolutely",
        "I see",
        "Understood",
        "Good point",
    )
    questions = (
        "What should we talk about next?",
        "Tell me what's been happening.",
        "What's been on your mind lately?",
        "What's going on with you today?",
        "How has your day been?",
        "Want to keep chatting?",
        "Anything else you'd like to discuss?",
        "What would you like to do next?",
        "What's new with you?",
        "Tell me more about your day.",
        "What's been keeping you busy?",
        "How are you feeling about everything?",
        "Want to switch topics?",
        "Should we keep talking or try a command?",
        "What's on your mind right now?",
    )
    moods = (
        "Things sound pretty good.",
        "Sounds like a calm moment.",
        "I'm glad you're sharing that.",
        "Thanks for telling me.",
        "I appreciate you chatting with me.",
    )
    items = list(SCREENSHOT_REPLIES)
    items.extend(SPARK_CONVERSATION)
    items.extend(NOT_MUCH_REPLIES)
    for a, q in itertools.product(acks, questions):
        items.append(f"{a}. {q}")
    for m, q in itertools.product(moods, questions):
        items.append(f"{m} {q}")
    return _unique(items)


def build_all_pools() -> dict[str, tuple[str, ...]]:
    return {
        "thanks_extended": build_thanks_extended_pool(),
        "reciprocal": build_reciprocal_pool(),
        "ai_critique": _unique(list(AI_CRITIQUE_REPLIES) * 20),
        "sarcasm": _unique(list(SARCASM_REPLIES) * 15),
        "denial_followup": _unique(list(DENIAL_FOLLOWUP_REPLIES) * 15),
        "talk_more": build_talk_more_pool(),
        "spark": _unique(list(SPARK_CONVERSATION) * 20),
        "not_much": _unique(list(NOT_MUCH_REPLIES) * 15),
    }


RESPONSE_POOLS = build_all_pools()
