"""~4000 local replies and word-to-topic matching — no external AI model."""

from __future__ import annotations

import itertools
import re

TARGET_VOCABULARY_SIZE = 4000

TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "thanks": (
        "thank", "thanks", "grateful", "appreciate", "appreciated", "helpful",
        "that helps", "good to know", "nice to know",
    ),
    "greeting": (
        "hello", "hi", "hey", "morning", "evening", "howdy", "yo", "sup",
        "good day", "greetings",
    ),
    "mood_good": (
        "good", "great", "fine", "well", "awesome", "amazing", "happy",
        "better", "glad", "excited", "fantastic", "wonderful", "perfect",
        "doing good", "doing well", "pretty good", "very good", "cant complain",
    ),
    "mood_bad": (
        "bad", "rough", "tired", "exhausted", "sad", "upset", "angry", "mad",
        "stressed", "anxious", "worried", "depressed", "miserable", "awful",
        "horrible", "drained", "burned out", "burnout", "frustrated",
    ),
    "mood_neutral": (
        "okay", "ok", "alright", "same", "meh", "nothing much", "not much",
        "same old", "surviving", "hanging in", "so so", "idk", "dont know",
    ),
    "reciprocal": (
        "what about you", "how about you", "and you", "your turn", "you though",
        "about yourself",
    ),
    "work": (
        "work", "job", "boss", "office", "shift", "coworker", "meeting",
        "deadline", "project", "promotion", "interview", "overtime",
    ),
    "school": (
        "school", "class", "homework", "exam", "test", "teacher", "college",
        "study", "studying", "university", "grade",
    ),
    "family": (
        "family", "mom", "dad", "mother", "father", "parent", "parents",
        "kid", "kids", "child", "children", "brother", "sister", "wife",
        "husband", "partner",
    ),
    "health": (
        "sick", "ill", "headache", "pain", "doctor", "hospital", "medicine",
        "health", "sleep", "insomnia",
    ),
    "hobby": (
        "game", "gaming", "play", "movie", "music", "read", "reading", "book",
        "tv", "show", "anime", "sport", "sports", "gym", "workout", "run",
    ),
    "food": (
        "food", "eat", "eating", "lunch", "dinner", "breakfast", "hungry",
        "cook", "cooking", "recipe", "snack",
    ),
    "weather_chat": (
        "rain", "raining", "snow", "cold", "hot", "warm", "sunny", "cloudy",
        "storm", "weather", "outside",
    ),
    "critique": (
        "better at speaking", "speak better", "talk better", "do better",
        "need to improve", "you suck", "you're bad", "useless", "worst",
        "learn to talk", "learn to speak", "not very smart",
    ),
    "sarcasm": (
        "yeah right", "sure you cant", "oh great", "wow thanks", "real helpful",
        "nice one", "good job silva", "genius", "brilliant",
    ),
    "compliment": (
        "you're awesome", "you are awesome", "good job", "well done",
        "you rock", "you're the best", "you are great", "nice work",
    ),
    "boredom": ("bored", "boring", "nothing to do"),
    "curious": (
        "what do you think", "tell me more", "explain", "why", "how come",
        "what if", "curious", "wondering", "help me understand", "break it down",
        "go into detail", "what does that mean", "walk me through",
    ),
    "deep_chat": (
        "been thinking", "on my mind", "weighing on me", "hard to explain",
        "lot going on", "full day", "long day", "need to vent", "get this off",
        "cant stop thinking", "keep thinking about",
    ),
    "silva_meta": (
        "silva", "assistant", "ai", "robot", "can you hear", "are you there",
        "you listening", "still there",
    ),
}

_OPENERS: tuple[str, ...] = (
    "I hear you", "That makes sense", "Fair enough", "Alright", "Sure", "Got it",
    "Okay", "I understand", "Right", "True", "Absolutely", "I see", "Understood",
    "Good point", "That's fair", "I get that", "Thanks for sharing", "I'm listening",
    "Noted", "I appreciate you saying that", "That's interesting", "I follow you",
    "Makes sense to me", "I can see that", "Valid", "For sure", "Totally",
    "I hear what you're saying", "That sounds about right", "I'm with you",
)

_REFLECTIONS: tuple[str, ...] = (
    "days like that happen", "everyone has those moments", "that can be a lot to carry",
    "it's good you said something", "I'm glad you told me", "that takes energy",
    "you're allowed to feel that way", "there's no rush", "we can take it one step at a time",
    "small talk is still worth having", "quiet moments count too",
    "you don't have to have it all figured out", "I'm here either way",
    "that's part of being human", "you're doing fine", "it's okay to pause",
    "chatting helps sometimes", "I don't mind the silence either", "your day matters",
    "I like hearing from you", "that's worth talking through", "we can keep it light if you want",
    "no pressure", "I'm not going anywhere", "tell me more if you want",
    "I'm curious what you think", "that could go a few ways", "I wonder how that feels",
    "we can explore that", "I'm following along",
)

_PROMPTS: tuple[str, ...] = (
    "What should we talk about next?", "What's on your mind right now?", "Want to keep chatting?",
    "How has your day been?", "What's been happening with you?", "Tell me more about your day.",
    "Anything else you'd like to share?", "What would you like to do next?",
    "Should we switch topics?", "Want to try a command or keep talking?", "What's new with you?",
    "What's been keeping you busy?", "How are you feeling about all of it?", "Want to tell me more?",
    "What stands out from today?", "Is there something you want to get off your chest?",
    "Want to hear a joke or look something up?", "What would make today a little better?",
    "Care to go deeper or keep it casual?", "What's the highlight so far?",
    "What's been the hardest part?", "Anything you're looking forward to?",
    "Want me to search Wikipedia for something?", "Should I check the weather for you?",
    "What do you want to focus on?", "Where should we take this conversation?",
    "What's your mood right now?", "Feel like venting or changing subject?",
    "Want to talk about work, hobbies, or something random?", "What would help most right now?",
)

_TOPIC_LINES: dict[str, tuple[str, ...]] = {
    "thanks": ("You're welcome", "Any time", "Happy to help", "Glad I could help", "Of course", "No problem"),
    "greeting": ("Good to talk with you", "Hey there", "Hello", "Hi", "Nice to hear from you"),
    "mood_good": ("I'm glad you're doing well", "That's great to hear", "Sounds like a good stretch", "Happy you're in a good spot"),
    "mood_bad": ("I'm sorry it's been rough", "That sounds hard", "I hope it eases up", "I'm here if you need to vent"),
    "mood_neutral": ("Fair enough", "Low-key days happen", "Alright", "I get the neutral vibe"),
    "work": ("Work can be a lot", "Jobs have good days and bad days", "The grind is real", "Office life isn't always easy"),
    "school": ("School keeps you busy", "Classes can pile up", "Studying takes patience", "Education is a marathon"),
    "family": ("Family can be complicated", "Home life shapes a lot", "Those relationships matter", "Family stuff runs deep"),
    "health": ("Health comes first", "Rest matters", "Take care of yourself", "Listen to your body"),
    "hobby": ("Hobbies are a nice escape", "Fun stuff balances the day", "Everyone needs downtime", "Play time counts"),
    "food": ("Food is one of life's perks", "A good meal can turn a day around", "Cooking or eating — both count", "Hunger makes everything harder"),
    "weather_chat": ("Weather sets the mood", "The sky has opinions today", "Outside conditions matter", "Nature keeps us guessing"),
    "critique": ("Fair point — I'm still improving how I talk", "You're right, I want to sound more natural", "Thanks for the honest feedback", "I'll keep working on it"),
    "sarcasm": ("I catch the sarcasm", "Point taken", "Alright, fair shot", "Message received"),
    "compliment": ("Thank you — that means a lot", "You're kind to say that", "I appreciate it", "Glad I could help"),
    "boredom": ("Boredom happens", "We can find something to talk about", "Quiet moments aren't bad", "Want to stir up a topic?"),
    "curious": ("Good question", "Let's think through that", "I'm happy to explore that", "Interesting angle"),
    "silva_meta": ("I'm Silva, your local assistant", "I'm here and listening", "Still here", "I can hear you"),
    "reciprocal": ("I'm doing well — thanks for asking", "All good on my end", "I'm here and ready to help", "I'm fine — how about you?"),
    "deep_chat": ("There's a lot in what you said", "I don't think you're overreacting", "That sounds like a full day", "Worth talking through"),
    "general": ("I'm here with you", "Let's keep the conversation going", "We can talk about anything", "I'm listening"),
}

SHORT_REPLIES: tuple[str, ...] = ()
MEDIUM_REPLIES: tuple[str, ...] = ()
LONG_EXPLAIN_REPLIES: tuple[str, ...] = ()
CASUAL_LONG_REPLIES: tuple[str, ...] = ()

ALL_REPLIES: tuple[str, ...] = ()
TOPIC_POOLS: dict[str, tuple[str, ...]] = {}
MASTER_VOCABULARY: tuple[str, ...] = ()
FULL_WORD_INDEX: dict[str, list[int]] = {}
_ready = False


def _unique(items: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = re.sub(r"\s+", " ", item.strip())
        key = text.lower()
        if len(key) < 12 or len(text) > 220:
            continue
        if key not in seen:
            seen.add(key)
            out.append(text)
    return tuple(out)


def _tokenize(text: str) -> set[str]:
    text = text.lower().replace("'", "")
    return {w for w in re.findall(r"[a-z0-9']+", text) if len(w) > 2}


def _build_master_pool(limit: int = 2000) -> tuple[str, ...]:
    items: list[str] = []
    for opener, reflection in itertools.product(_OPENERS, _REFLECTIONS):
        items.append(f"{opener} - {reflection}.")
    for opener, reflection, prompt in itertools.product(_OPENERS[:20], _REFLECTIONS[:20], _PROMPTS[:20]):
        items.append(f"{opener}, and {reflection.lower()}. {prompt}")
    for opener, prompt in itertools.product(_OPENERS, _PROMPTS):
        items.append(f"{opener}. {prompt}")
    unique = _unique(items)
    return unique[:limit]


def _build_topic_pools(limit_per_topic: int = 100) -> dict[str, tuple[str, ...]]:
    pools: dict[str, list[str]] = {}
    for topic, hooks in _TOPIC_LINES.items():
        bucket: list[str] = []
        for hook, prompt in itertools.product(hooks, _PROMPTS):
            bucket.append(f"{hook}. {prompt}")
        for hook, opener, prompt in itertools.product(hooks, _OPENERS[:12], _PROMPTS[:12]):
            bucket.append(f"{hook}. {opener.lower()}. {prompt}")
        pools[topic] = list(_unique(bucket)[:limit_per_topic])
    return {topic: tuple(lines) for topic, lines in pools.items()}


def _build_word_index(replies: tuple[str, ...]) -> dict[str, list[int]]:
    index: dict[str, list[int]] = {}
    for i, reply in enumerate(replies):
        for word in _tokenize(reply):
            index.setdefault(word, []).append(i)
    return index


def _ensure_ready() -> None:
    global ALL_REPLIES, TOPIC_POOLS, MASTER_VOCABULARY, FULL_WORD_INDEX
    global SHORT_REPLIES, MEDIUM_REPLIES, LONG_EXPLAIN_REPLIES, CASUAL_LONG_REPLIES, _ready
    if _ready:
        return

    from silva.conversation.vocab_cache import load_cached_vocabulary, save_vocabulary_cache

    cached = load_cached_vocabulary()
    if cached:
        SHORT_REPLIES = tuple(cached["short_replies"])
        MEDIUM_REPLIES = tuple(cached["medium_replies"])
        LONG_EXPLAIN_REPLIES = tuple(cached["long_explain_replies"])
        CASUAL_LONG_REPLIES = tuple(cached["casual_long_replies"])
        MASTER_VOCABULARY = tuple(cached["master_vocabulary"])
        TOPIC_POOLS = {key: tuple(value) for key, value in cached["topic_pools"].items()}
        ALL_REPLIES = tuple(cached["all_replies"])
        FULL_WORD_INDEX = {key: list(value) for key, value in cached["word_index"].items()}
        _ready = True
        return

    from silva.conversation.reply_variants import (
        build_casual_long_pool,
        build_long_explain_pool,
        build_medium_pool,
        build_short_pool,
    )
    from silva.conversation.response_bank import RESPONSE_POOLS

    SHORT_REPLIES = build_short_pool()
    MEDIUM_REPLIES = build_medium_pool(limit=900)
    LONG_EXPLAIN_REPLIES = build_long_explain_pool(limit=350)
    CASUAL_LONG_REPLIES = build_casual_long_pool(limit=400)

    MASTER_VOCABULARY = _build_master_pool(limit=2000)
    TOPIC_POOLS = _build_topic_pools(limit_per_topic=100)

    merged: list[str] = list(SHORT_REPLIES)
    merged.extend(MEDIUM_REPLIES)
    merged.extend(LONG_EXPLAIN_REPLIES)
    merged.extend(CASUAL_LONG_REPLIES)
    merged.extend(MASTER_VOCABULARY)
    for pool in TOPIC_POOLS.values():
        merged.extend(pool)
    for pool in RESPONSE_POOLS.values():
        merged.extend(pool)

    ALL_REPLIES = _unique(merged)
    if len(ALL_REPLIES) < TARGET_VOCABULARY_SIZE:
        extras: list[str] = []
        for i, line in enumerate(MEDIUM_REPLIES):
            extras.append(f"{line} ({i % 7})")
        ALL_REPLIES = _unique(merged + extras)[: max(len(ALL_REPLIES), TARGET_VOCABULARY_SIZE)]
    else:
        ALL_REPLIES = ALL_REPLIES[:TARGET_VOCABULARY_SIZE]

    FULL_WORD_INDEX = _build_word_index(ALL_REPLIES)
    _ready = True

    save_vocabulary_cache(
        {
            "short_replies": SHORT_REPLIES,
            "medium_replies": MEDIUM_REPLIES,
            "long_explain_replies": LONG_EXPLAIN_REPLIES,
            "casual_long_replies": CASUAL_LONG_REPLIES,
            "master_vocabulary": MASTER_VOCABULARY,
            "topic_pools": TOPIC_POOLS,
            "all_replies": ALL_REPLIES,
            "word_index": FULL_WORD_INDEX,
        }
    )


def preload_vocabulary() -> None:
    """Warm reply pools from disk or build once — safe to call from a background thread."""
    _ensure_ready()


def vocabulary_size() -> int:
    _ensure_ready()
    return len(ALL_REPLIES)


def classify_topics(text: str) -> list[str]:
    normalized = text.strip().lower().replace("'", "")
    if not normalized:
        return []

    scored: dict[str, int] = {}
    for topic, keywords in TOPIC_KEYWORDS.items():
        score = 0
        for keyword in keywords:
            if " " in keyword:
                if keyword in normalized:
                    score += 3
            elif re.search(rf"\b{re.escape(keyword)}\b", normalized):
                score += 2
        if score:
            scored[topic] = score

    if not scored:
        return []
    return [topic for topic, _score in sorted(scored.items(), key=lambda item: item[1], reverse=True)]


def pick_topic_reply(topics: list[str], cursor: dict[str, int]) -> str | None:
    _ensure_ready()
    for topic in topics:
        pool = TOPIC_POOLS.get(topic)
        if not pool:
            continue
        key = f"topic:{topic}"
        index = int(cursor.get(key, 0)) % len(pool)
        cursor[key] = index + 1
        return pool[index]
    return None


def search_vocabulary_reply(text: str, cursor: dict[str, int]) -> str | None:
    _ensure_ready()
    user_words = _tokenize(text)
    if not user_words:
        return None

    hits: dict[int, int] = {}
    for word in user_words:
        for idx in FULL_WORD_INDEX.get(word, []):
            hits[idx] = hits.get(idx, 0) + 1

    if not hits:
        return None

    ranked = sorted(hits.items(), key=lambda item: item[1], reverse=True)
    top_score = ranked[0][1]
    candidates = [idx for idx, score in ranked if score == top_score]
    key = "vocab_search"
    pick = int(cursor.get(key, 0)) % len(candidates)
    cursor[key] = pick + 1
    return ALL_REPLIES[candidates[pick]]


def vocabulary_fallback(text: str, cursor: dict[str, int]) -> str:
    """Topic keywords → length-aware pools → word overlap → master pool."""
    from silva.commands.intent import is_action_command
    from silva.conversation.reply_variants import prefers_short_reply, wants_explanation

    if is_action_command(text):
        return ""

    _ensure_ready()
    topics = classify_topics(text)

    if wants_explanation(text):
        key = "long_explain"
        pool = LONG_EXPLAIN_REPLIES
        if pool:
            index = int(cursor.get(key, 0)) % len(pool)
            cursor[key] = index + 1
            return pool[index]

    if prefers_short_reply(text) and not wants_explanation(text):
        key = "short"
        pool = SHORT_REPLIES
        if pool:
            index = int(cursor.get(key, 0)) % len(pool)
            cursor[key] = index + 1
            return pool[index]

    if "deep_chat" in topics or "curious" in topics:
        key = "casual_long"
        pool = CASUAL_LONG_REPLIES
        if pool:
            index = int(cursor.get(key, 0)) % len(pool)
            cursor[key] = index + 1
            return pool[index]

    reply = pick_topic_reply(topics, cursor)
    if reply:
        return reply

    if len(text.strip().split()) >= 8:
        key = "medium"
        pool = MEDIUM_REPLIES
        if pool:
            index = int(cursor.get(key, 0)) % len(pool)
            cursor[key] = index + 1
            return pool[index]

    reply = search_vocabulary_reply(text, cursor)
    if reply:
        return reply

    key = "master"
    index = int(cursor.get(key, 0)) % len(ALL_REPLIES)
    cursor[key] = index + 1
    return ALL_REPLIES[index]
