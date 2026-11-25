"""Natural short, medium, and long reply building blocks — no external AI."""

from __future__ import annotations

import itertools
import re

# ---------------------------------------------------------------------------
# Short & sweet (one complete thought, sounds human)
# ---------------------------------------------------------------------------

SHORT_CASUAL: tuple[str, ...] = (
    "Yeah, I get that.",
    "Totally fair.",
    "Makes sense to me.",
    "I hear you.",
    "That tracks.",
    "For sure.",
    "Right on.",
    "I feel that.",
    "Same here, honestly.",
    "Valid point.",
    "Could be worse.",
    "Could be better too.",
    "That's life sometimes.",
    "Happens to everyone.",
    "You're not alone in that.",
    "Rough, but you'll get through it.",
    "Glad you said something.",
    "I'm here for it.",
    "No rush at all.",
    "Take your time.",
    "We can keep it light.",
    "I'm listening.",
    "Go on.",
    "Tell me more if you want.",
    "That's interesting.",
    "I didn't know that.",
    "Good to know.",
    "Nice.",
    "Cool.",
    "Sounds good.",
    "Fair enough.",
    "Alright then.",
    "I follow you.",
    "True enough.",
    "Can't argue with that.",
    "I see what you mean.",
    "That would bug me too.",
    "I'd feel the same way.",
    "You handled that well.",
    "That's a lot though.",
    "Whew.",
    "Man, yeah.",
    "I bet.",
    "No doubt.",
    "Exactly.",
    "Absolutely.",
    "For real.",
    "Honestly? Same.",
    "I feel you on that.",
    "Mood.",
    "Big mood.",
    "Relatable.",
    "Story of my week.",
    "Classic.",
    "Of course that happened.",
    "Why am I not surprised.",
    "That's so you though.",
    "Love that for you.",
    "Not ideal, but okay.",
    "Silver lining maybe.",
    "Tomorrow's a new day.",
    "One thing at a time.",
    "You'll figure it out.",
    "You've got this.",
    "Hang in there.",
    "Rooting for you.",
    "I'm on your side.",
    "Say less.",
    "Bet.",
    "Word.",
    "Copy that.",
    "Noted.",
    "Loud and clear.",
    "Gotcha.",
    "Sure thing.",
    "Anytime.",
    "You know it.",
    "That's the spirit.",
    "Keep going.",
    "Don't stop now.",
    "Almost there.",
    "Worth a shot.",
    "Why not.",
    "Might as well.",
    "Can't hurt to try.",
    "Nothing wrong with that.",
    "Live and learn.",
    "Part of the process.",
    "Growth hurts sometimes.",
    "Character building, I guess.",
    "At least you tried.",
    "Better than nothing.",
    "Small wins count.",
    "Progress is progress.",
    "Baby steps.",
    "Slow is fine.",
    "No judgment here.",
    "Your call.",
    "Whatever feels right.",
    "Trust your gut.",
    "You know yourself best.",
)

# ---------------------------------------------------------------------------
# Natural two-sentence flows (medium — not choppy)
# ---------------------------------------------------------------------------

_MEDIUM_OPENERS: tuple[str, ...] = (
    "I hear you",
    "That makes sense",
    "Honestly",
    "Yeah",
    "I get it",
    "Fair point",
    "You're right",
    "I can see that",
    "Totally",
    "For sure",
    "I mean",
    "Look",
    "Real talk",
    "Truth is",
    "I'll say this",
    "Here's the thing",
    "You know what",
    "I've noticed",
    "From where I sit",
    "In my experience",
)

_MEDIUM_MIDDLE: tuple[str, ...] = (
    "and days like that just pile up sometimes",
    "and it's okay to not have it all sorted out",
    "and talking it out can help more than people admit",
    "and you don't owe anyone a perfect day",
    "and small stuff adds up faster than we expect",
    "and everyone needs a breather now and then",
    "and you're allowed to feel however you feel",
    "and there's no wrong way to unwind",
    "and sometimes venting is enough",
    "and I'm glad you're sharing it with me",
    "and that kind of thing sticks with you",
    "and it makes sense you'd feel that way",
    "and life throws curveballs at the worst times",
    "and you're handling more than you give yourself credit for",
    "and a good conversation beats sitting alone with it",
    "and we can take this at whatever pace you want",
    "and I'm not going anywhere if you want to keep going",
    "and honestly most people would feel the same",
    "and it's worth saying out loud even if it's messy",
    "and you don't have to perform being fine",
)

_MEDIUM_CLOSERS: tuple[str, ...] = (
    "What's on your mind next?",
    "Want to keep going?",
    "How are you feeling about it now?",
    "Anything else you want to get off your chest?",
    "Should we switch gears or stay on this?",
    "What would help most right now?",
    "Tell me what happened if you want.",
    "I'm here either way.",
    "Want to talk it through or change subject?",
    "What do you think you'll do?",
    "Does that sound about right?",
    "Am I reading that correctly?",
    "Want my take or just an ear?",
    "Where do you want to take this?",
    "What's the part that bothers you most?",
)

# ---------------------------------------------------------------------------
# Long-form explain / deep chat (when user asks to understand something)
# ---------------------------------------------------------------------------

_LONG_EXPLAIN_FRAMES: tuple[str, ...] = (
    "So here's how I'd think about it. {body} Does that line up with what you were wondering?",
    "Good question. {body} Let me know if you want me to go deeper on any part.",
    "I'll walk you through it. {body} If something still feels fuzzy, just point at it.",
    "Alright, let me break it down. {body} We can unpack any piece of that.",
    "Here's my honest read. {body} Tell me if that matches what you're trying to figure out.",
)

_LONG_EXPLAIN_BODIES: tuple[str, ...] = (
    "Most of the time people feel stuck because the problem is really two problems stacked together — the situation itself, and the pressure to fix it instantly. When you separate those, it usually gets easier to breathe and think.",
    "When someone asks 'why,' they're usually not looking for one perfect answer. They want to feel like the reaction they're having is reasonable. And most of the time, it is.",
    "Feelings don't always need fixing right away. Sometimes naming what's going on — tired, overwhelmed, annoyed, lonely — is already half the work. The rest can wait until you're ready.",
    "Stress often comes from carrying tomorrow's problems in today's backpack. You don't have to solve the whole month tonight. One small next step is enough.",
    "Relationships, work, health, money — they all bleed into each other. So if one area feels heavy, it's normal for everything else to feel off too. That doesn't mean you're failing.",
    "Boredom isn't always laziness. Sometimes it's your brain asking for change, rest, or something that actually interests you. Worth listening to instead of fighting.",
    "Bad days happen in clusters sometimes. That doesn't mean the good stretch wasn't real, and it doesn't mean another good stretch isn't coming.",
    "When you're tired, everything sounds harder than it is. Rest isn't giving up — it's maintenance. You wouldn't skip charging your phone and expect it to run all week.",
    "Comparison steals the joy out of normal progress. You're allowed to move at your own speed even if everyone online looks like they're sprinting.",
    "Anger usually has a softer feeling underneath — hurt, fear, feeling ignored. If you can find that layer, it gets easier to explain what you actually need.",
    "Not knowing what you want yet is different from wanting nothing. Confusion is a stage, not a personality flaw.",
    "Small talk isn't shallow. It's how people test whether it's safe to go deeper. You're allowed to take your time getting there.",
    "If something keeps looping in your head, your brain is probably trying to solve it without enough information. Talking it out or writing it down can unblock that.",
    "Nobody has a perfectly balanced life every day. Balance is something you recorrect over weeks, not something you nail by lunch on Monday.",
    "It's okay to outgrow old routines, friends, or habits. Growth sometimes feels like loss before it feels like freedom.",
    "When work or school eats your energy, the fix isn't always 'try harder.' Sometimes it's boundaries, sleep, or asking for help before you're empty.",
    "Loneliness can show up even around people. Connection is about being understood, not just being in the same room.",
    "Hope isn't toxic positivity. It's choosing to believe one decent thing might still happen even when today's rough.",
    "You don't need the perfect words to start a hard conversation. 'I'm not okay' or 'Can we talk?' is enough.",
    "Healing isn't linear. A bad day after a good week doesn't erase the progress — it just means you're human.",
)

# ---------------------------------------------------------------------------
# Casual long chat (not explain — just richer normal conversation)
# ---------------------------------------------------------------------------

_CASUAL_LONG_OPENERS: tuple[str, ...] = (
    "You know, I was thinking about what you said",
    "I've been sitting with that",
    "That's actually a pretty normal thing to feel",
    "I don't think you're overreacting",
    "It sounds like you've had a full day",
    "There's a lot in what you just shared",
    "I appreciate you trusting me with that",
    "That's more common than people admit out loud",
)

_CASUAL_LONG_MIDDLE: tuple[str, ...] = (
    "and I think anyone in your shoes would feel stretched thin.",
    "and it makes sense that you'd want to talk it through instead of bottling it.",
    "and you deserve space to feel that without rushing to fix it.",
    "and sometimes the bravest thing is just admitting it's a lot.",
    "and I'm not here to judge — just to listen and help where I can.",
    "and you don't have to have a neat ending to the story yet.",
    "and if today was heavy, that doesn't define every day ahead.",
    "and small kindnesses to yourself count more than people think.",
)

_CASUAL_LONG_CLOSERS: tuple[str, ...] = (
    "So tell me — what's the part that's weighing on you most?",
    "Where do you want to go from here?",
    "I'm curious what you're hoping changes.",
    "Want to keep unpacking it or take a breather?",
    "What would a good rest of the day look like for you?",
    "Is there something practical I can help with, or do you just need to vent?",
    "How long has this been building up?",
    "What usually helps you when it gets like this?",
)

EXPLAIN_TRIGGERS: tuple[str, ...] = (
    "explain",
    "tell me more",
    "help me understand",
    "what do you mean",
    "can you elaborate",
    "go into detail",
    "break it down",
    "why is that",
    "how come",
    "what does that mean",
    "walk me through",
    "help me figure out",
    "make sense of",
    "unpack",
    "go deeper",
    "more detail",
    "in depth",
    "what's your take",
    "what do you think about",
)


def wants_explanation(text: str) -> bool:
    normalized = text.strip().lower().replace("'", "")
    if any(trigger.strip() in normalized for trigger in EXPLAIN_TRIGGERS):
        return True
    if normalized.endswith("?") and any(
        word in normalized for word in ("why", "how", "what", "explain", "mean")
    ):
        if len(normalized.split()) >= 5:
            return True
    return False


def prefers_short_reply(text: str) -> bool:
    words = text.strip().split()
    if len(words) <= 4:
        return True
    normalized = text.strip().lower()
    short_moods = (
        "good", "fine", "okay", "ok", "yeah", "yep", "nah", "nope", "sure",
        "thanks", "cool", "nice", "same", "mood", "tired", "busy", "stressed",
    )
    return normalized in short_moods or any(normalized.startswith(m) for m in short_moods)


def _unique(items: list[str], *, min_len: int = 8, max_len: int = 480) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = re.sub(r"\s+", " ", item.strip())
        key = text.lower()
        if len(key) < min_len or len(text) > max_len:
            continue
        if key not in seen:
            seen.add(key)
            out.append(text)
    return tuple(out)


def build_short_pool() -> tuple[str, ...]:
    return _unique(list(SHORT_CASUAL), min_len=6, max_len=80)


def build_medium_pool(limit: int = 900) -> tuple[str, ...]:
    items: list[str] = []
    for opener, middle in itertools.product(_MEDIUM_OPENERS, _MEDIUM_MIDDLE):
        items.append(f"{opener}, {middle}.")
        for closer in _MEDIUM_CLOSERS:
            items.append(f"{opener}, {middle}. {closer}")
    return _unique(items, min_len=20, max_len=220)[:limit]


def build_long_explain_pool(limit: int = 350) -> tuple[str, ...]:
    items: list[str] = []
    for frame, body in itertools.product(_LONG_EXPLAIN_FRAMES, _LONG_EXPLAIN_BODIES):
        items.append(frame.format(body=body))
    return _unique(items, min_len=80, max_len=480)[:limit]


def build_casual_long_pool(limit: int = 400) -> tuple[str, ...]:
    items: list[str] = []
    for opener, middle, closer in itertools.product(
        _CASUAL_LONG_OPENERS, _CASUAL_LONG_MIDDLE, _CASUAL_LONG_CLOSERS
    ):
        items.append(f"{opener}, {middle} {closer}")
    return _unique(items, min_len=60, max_len=320)[:limit]
