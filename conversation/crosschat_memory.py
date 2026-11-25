"""Persistent cross-chat custom instructions and feedback-shaped speech style."""

from __future__ import annotations

import json
import re
import threading

from silva.config import CONFIG_DIR, load_config

STORE_FILE = CONFIG_DIR / "crosschat_memory.json"
_LOCK = threading.Lock()
_LAST_REPLY: dict[str, str] = {}
_LAST_REPLY_CONTEXT: dict[str, dict] = {}
_OBSERVATIONS: dict[str, int] = {}

_STATE: dict = {}

_TRAIT_WORDS = {
    "casual": ("casual", "relaxed", " laid back", "everyday"),
    "formal": ("formal", "professional", "polite"),
    "brief": ("brief", "short", "concise", "quick"),
    "detailed": ("detailed", "thorough", "explain more"),
    "warm": ("warm", "friendly", "kind", "gentle"),
    "direct": ("direct", "straight", "blunt"),
    "sassy": ("sassy", "snarky", "playful"),
}

_INSTRUCTION_RE = re.compile(
    r"(?:cross ?chat|custom instruction|memory instruction|remember)\s*"
    r"(?:that\s+|to\s+|always\s+|never\s+|please\s+|instruction\s*:\s*)?(.{3,})",
    re.I,
)
_FORGET_RE = re.compile(r"(?:forget|remove|delete)\s+(?:my\s+)?(?:cross ?chat\s+)?(?:custom\s+)?instruction", re.I)
_LIST_RE = re.compile(r"(?:list|show|what are)\s+(?:my\s+)?(?:cross ?chat\s+)?(?:custom\s+)?instructions?", re.I)
_RATING_RE = re.compile(
    r"(?:rate|rating|score)\s+(?:this|that|the reply|the answer|you)\s*"
    r"(?:reply|answer|response)?\s*(?:a\s+)?([1-5])\s*(?:/|out of|of)\s*5",
    re.I,
)
_FEEDBACK_RE = re.compile(
    r"\b(?:talk|speak|sound|respond|answer|reply|be)\s+"
    r"(?:a\s+(?:bit|little)\s+|more\s+|less\s+)?"
    r"(casual|casually|formal|formally|brief|briefly|short|concise|quick|detailed|thorough|warm|friendly|kind|gentle|direct|sassy|snarky)\b",
    re.I,
)
_TOO_RE = re.compile(
    r"\btoo\s+(sassy|snarky|mean|formal|brief|short|long|detailed|causal|casual|friendly|warm|direct)\b",
    re.I,
)
_LIKE_RE = re.compile(r"\b(?:more like that|keep that|do that again|that was good|perfect)\b", re.I)
_REPLY_EXPLAIN_RE = re.compile(
    r"\bwhy\s+(?:did|do|would|could|are|were)\s+you\s+"
    r"(?:say|said|use|used|word|phrase|put|talk|respond|answer|call)\b"
    r"|\bwhy\s+(?:that|the)\s+(?:word|phrase|way|tone|line)\b"
    r"|\bwhy\s+did\s+you\s+say\s+that\s+(?:in\s+that\s+way|like\s+that)\b"
    r"|\b(?:explain|tell\s+me)\s+why\s+you\s+(?:said|used|chose|worded)\b"
    r"|\bwhat\s+(?:did|do)\s+you\s+mean\s+by\b"
    r"|\bwhy\s+(?:health\s+comes\s+first|that\s+word|that\s+phrase|that\s+line)\b",
    re.I,
)
_REPLY_FOCUS_STOPWORDS = {
    "did", "do", "does", "for", "from", "mean", "said", "say", "that", "the", "this",
    "way", "what", "why", "with", "you", "your", "was", "were", "are", "in", "like", "it",
}


def _key(user_id: str) -> str:
    return str(user_id or "guest")


def _load_state() -> dict:
    if not STORE_FILE.exists():
        return {"users": {}}
    try:
        data = json.loads(STORE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"users": {}}
    if not isinstance(data, dict):
        return {"users": {}}
    if not isinstance(data.get("users"), dict):
        data["users"] = {}
    return data


def _save_state() -> None:
    try:
        STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp = STORE_FILE.with_suffix(".json.tmp")
        temp.write_text(json.dumps(_STATE, indent=2), encoding="utf-8")
        temp.replace(STORE_FILE)
    except OSError:
        pass


def _user_state(user_id: str) -> dict:
    users = _STATE.setdefault("users", {})
    key = _key(user_id)
    state = users.get(key)
    if not isinstance(state, dict):
        state = {
            "instructions": [],
            "traits": {},
            "speech_patterns": [],
            "feedback": [],
            "rating": {"average": 0.0, "count": 0},
            "emotion": "",
        }
        users[key] = state
    return state


def enabled() -> bool:
    return bool(load_config().get("crosschat_memory_enabled", True))


def add_instruction(text: str, *, user_id: str = "", scope: str = "user", actor_id: str = "") -> bool:
    value = str(text or "").strip(" .")
    if not value or not enabled():
        return False
    if scope == "global" and not _privileged(actor_id or user_id):
        return False
    with _LOCK:
        if scope == "global":
            state = _user_state("global")
        else:
            state = _user_state(user_id)
        items = state.setdefault("instructions", [])
        if not isinstance(items, list):
            items = []
            state["instructions"] = items
        if value in items:
            return True
        items.append(value)
        if len(items) > 60:
            del items[: len(items) - 60]
        state["updated_at"] = _now()
        _save_state()
    return True


def list_instructions(*, user_id: str = "", include_global: bool = True) -> list[str]:
    with _LOCK:
        items = list(_user_state(user_id).get("instructions") or [])
        if include_global:
            items.extend(_user_state("global").get("instructions") or [])
    return [str(item) for item in items if str(item).strip()]


def forget_instruction(text: str, *, user_id: str = "", actor_id: str = "") -> bool:
    value = str(text or "").strip(" .").lower()
    if not value:
        return False
    with _LOCK:
        removed = False
        keys = [_key(user_id)]
        if _privileged(actor_id or user_id):
            keys.append("global")
        for key in keys:
            state = _user_state(key)
            items = state.get("instructions") or []
            kept = []
            for item in items:
                name = str(item).strip(" .").lower()
                if value in name or name in value:
                    removed = True
                else:
                    kept.append(item)
            state["instructions"] = kept
        _save_state()
    return removed


def note_feedback(text: str, *, user_id: str = "") -> bool:
    value = str(text or "").strip()
    if not value or not enabled():
        return False
    traits = _user_state(user_id).setdefault("traits", {})
    changed = False
    match = _FEEDBACK_RE.search(value)
    if match:
        trait = _normalize_trait(match.group(1))
        if trait:
            direction = -1 if re.search(r"\bless\b", value, re.I) else 1
            traits[trait] = _clamp(int(traits.get(trait) or 0) + direction)
            changed = True
    too = _TOO_RE.search(value)
    if too:
        trait = _normalize_trait(too.group(1))
        if trait:
            traits[trait] = _clamp(-abs(int(traits.get(trait) or 0)) - 1)
            changed = True
    if _LIKE_RE.search(value):
        rating = _LAST_REPLY.get(_key(user_id))
        if rating:
            changed = rate_reply(5, user_id=user_id, comment="more like that") or changed
    if re.search(r"\b(?:calm down|stop being mean|don't be mean|dont be mean)\b", value, re.I):
        traits["sassy"] = -2
        changed = True
    if changed:
        with _LOCK:
            state = _user_state(user_id)
            feedback = state.setdefault("feedback", [])
            feedback.append({"text": value[:300], "at": _now()})
            if len(feedback) > 80:
                del feedback[: len(feedback) - 80]
            _save_state()
    return changed


def rate_reply(rating: int, *, user_id: str = "", comment: str = "") -> bool:
    try:
        value = int(rating)
    except (TypeError, ValueError):
        return False
    if value < 1 or value > 5 or not enabled():
        return False
    with _LOCK:
        state = _user_state(user_id)
        current = state.setdefault("rating", {"average": 0.0, "count": 0})
        count = int(current.get("count") or 0)
        average = float(current.get("average") or 0.0)
        count += 1
        average = ((average * (count - 1)) + value) / count
        current["count"] = count
        current["average"] = round(average, 2)
        state.setdefault("feedback", []).append(
            {"rating": value, "text": str(comment or "")[:300], "at": _now()}
        )
        if value <= 2:
            traits = state.setdefault("traits", {})
            traits["sassy"] = _clamp(int(traits.get("sassy") or 0) - 1)
        elif value >= 4:
            traits = state.setdefault("traits", {})
            traits["warm"] = _clamp(int(traits.get("warm") or 0) + 1)
        _save_state()
    return True


def observe_speech(text: str, *, user_id: str = "") -> None:
    value = " ".join(str(text or "").split())
    if not value or not enabled():
        return
    lowered = value.lower()
    patterns = {
        "contractions": bool(re.search(r"\b(?:i'm|you're|we're|don't|can't|won't|it's)\b", lowered)),
        "questions": value.endswith("?") or lowered.startswith(
            ("what", "why", "how", "when", "where", "who", "can", "could", "do", "does")
        ),
    }
    changed = False
    user_key = _key(user_id)
    _OBSERVATIONS[user_key] = int(_OBSERVATIONS.get(user_key) or 0) + 1
    with _LOCK:
        state = _user_state(user_id)
        items = state.setdefault("speech_patterns", [])
        for key, present in patterns.items():
            if present and key not in items:
                items.append(key)
                changed = True
        if len(items) > 24:
            del items[: len(items) - 24]
        match = re.search(
            r"\b(?:i feel|i am feeling|i'm feeling)\s+(happy|sad|angry|calm|nervous|excited)\b",
            lowered,
        )
        if match and state.get("emotion") != match.group(1):
            state["emotion"] = match.group(1)
            changed = True
        if changed and _OBSERVATIONS[user_key] >= 5:
            _save_state()


def remember_last_reply(text: str, *, user_id: str = "") -> None:
    value = str(text or "").strip()
    if value:
        _LAST_REPLY[_key(user_id)] = value


def remember_reply_context(user_text: str, reply: str, *, user_id: str = "") -> None:
    from silva.conversation.attitude import classify_response_tone, profanity_trigger
    from silva.conversation.vocabulary import TOPIC_KEYWORDS, classify_topics

    value = " ".join(str(user_text or "").split())
    answer = str(reply or "").strip()
    if not answer:
        return
    topics = classify_topics(value)
    topic = topics[0] if topics else ""
    lowered = value.lower().replace("'", "")
    keywords: list[str] = []
    for keyword in TOPIC_KEYWORDS.get(topic, ()):
        normalized = keyword.lower().replace("'", "")
        if (" " in normalized and normalized in lowered) or re.search(
            rf"\b{re.escape(normalized)}\b", lowered
        ):
            keywords.append(keyword)
            if len(keywords) >= 4:
                break
    _LAST_REPLY_CONTEXT[_key(user_id)] = {
        "reply": answer,
        "user_text": value,
        "topic": topic,
        "keywords": keywords,
        "tone": classify_response_tone(value) or "",
        "profanity": profanity_trigger(value) or "",
    }


def _reply_focus(question: str, reply: str) -> str:
    quoted = re.search(r"['\"]([^'\"]+)['\"]", question)
    if quoted and quoted.group(1).strip().lower() in reply.lower():
        return quoted.group(1).strip()
    question_words = {
        word.lower().strip("'") for word in re.findall(r"[A-Za-z0-9']+", question.lower())
    }
    focus = [
        word
        for word in re.findall(r"[A-Za-z0-9']+", reply)
        if word.lower().strip("'") in question_words
        and word.lower().strip("'") not in _REPLY_FOCUS_STOPWORDS
    ]
    return " ".join(focus[:6])


def explain_last_reply(text: str, *, user_id: str = "") -> str:
    context = _LAST_REPLY_CONTEXT.get(_key(user_id))
    if not context:
        return "I don't have a recent reply to explain."
    reply = str(context.get("reply") or "")
    topic = str(context.get("topic") or "")
    keywords = [str(item) for item in context.get("keywords") or []]
    tone = str(context.get("tone") or "")
    profanity = str(context.get("profanity") or "")
    focus = _reply_focus(text, reply)
    pieces = []
    if focus:
        pieces.append(f'You mean "{focus}" from "{reply}".')
    else:
        pieces.append(f'You mean "{reply}".')
    if keywords:
        pieces.append(f'I chose it because "{keywords[0]}" matched the {topic} topic.')
    elif topic:
        pieces.append(f"I chose it because your words matched the {topic} topic.")
    else:
        pieces.append("I chose it as a general conversational reply.")
    if tone in {"mean", "sassy"}:
        if profanity:
            pieces.append(f'The sharper way I said it came from "{profanity}" in what you said.')
        else:
            pieces.append(f"The {tone} way I said it came from your frustrated wording.")
    elif tone:
        pieces.append(f"I kept the {tone} tone because that is how your wording came across.")
    if topic == "health":
        pieces.append("Health here meant sleep and rest, not a judgment about your anger or mental state.")
    elif re.search(r"\b(?:anger|angry|mental|state)\b", text, re.I):
        pieces.append("I was not making a clinical judgment about your mental state.")
    return " ".join(pieces)


def is_reply_explanation_ask(text: str) -> bool:
    return bool(_REPLY_EXPLAIN_RE.search(str(text or "")))


def last_reply(*, user_id: str = "") -> str:
    return _LAST_REPLY.get(_key(user_id), "")


def preferences(*, user_id: str = "") -> dict:
    with _LOCK:
        state = _user_state(user_id)
        traits = dict(state.get("traits") or {})
        rating = dict(state.get("rating") or {})
        emotion = str(state.get("emotion") or "")
        patterns = list(state.get("speech_patterns") or [])
        instructions = list(state.get("instructions") or [])
    return {
        "traits": traits,
        "rating": rating,
        "emotion": emotion,
        "speech_patterns": patterns,
        "instructions": instructions,
    }


def apply_to_reply(text: str, *, user_id: str = "") -> str:
    reply = str(text or "")
    if not reply or not enabled():
        return reply
    prefs = preferences(user_id=user_id)
    traits = prefs["traits"]
    if int(traits.get("brief") or 0) >= 1 and len(reply) > 120:
        parts = re.split(r"(?<=[.!?])\s+", reply)
        reply = " ".join(parts[:2]).strip()
    if int(traits.get("direct") or 0) >= 1:
        reply = re.sub(r"^(?:well|okay|ok|sure),\s+", "", reply, flags=re.I)
    if int(traits.get("casual") or 0) >= 2:
        reply = reply.replace("I am ", "I'm ").replace("you are ", "you're ")
    if prefs["emotion"] == "sad" and int(traits.get("warm") or 0) >= 1:
        reply = f"I hear you. {reply}"
    return reply


def parse_crosschat_speech(text: str) -> dict | None:
    value = str(text or "").strip()
    if not value:
        return None
    if is_reply_explanation_ask(value):
        return {"action": "explain_reply"}
    if not enabled():
        return None
    if _LIST_RE.search(value):
        return {"action": "list"}
    if _FORGET_RE.search(value):
        match = re.search(r"(?:instruction|memory)\s+(.+)$", value, re.I)
        return {"action": "forget", "value": match.group(1) if match else ""}
    rating = _RATING_RE.search(value)
    if rating:
        return {"action": "rate", "value": int(rating.group(1))}
    feedback = _FEEDBACK_RE.search(value) or _TOO_RE.search(value)
    if feedback or _LIKE_RE.search(value) or re.search(r"\bcalm down|stop being mean\b", value, re.I):
        return {"action": "feedback", "value": value}
    match = _INSTRUCTION_RE.search(value)
    if match:
        instruction = match.group(1).strip(" .")
        if instruction and len(instruction) > 2:
            scope = "global" if re.search(r"\beveryone\b|\ball users\b|\bglobal\b", value, re.I) else "user"
            return {"action": "instruction", "value": instruction, "scope": scope}
    return None


def handle_crosschat_speech(assistant, text: str) -> bool:
    action = parse_crosschat_speech(text)
    if action is None:
        return False
    getter = getattr(assistant, "_user_id", None)
    user_id = getter() if callable(getter) else "guest"
    user = getattr(assistant, "_active_user", None)
    if callable(user):
        user = user()
    actor_id = str(user.get("id") or user_id) if isinstance(user, dict) else str(user_id)
    kind = str(action.get("action") or "")

    if kind == "explain_reply":
        assistant.say(explain_last_reply(text, user_id=user_id), interruptible=True)
        return True
    if kind == "list":
        items = list_instructions(user_id=user_id)
        if items:
            assistant.say("Saved instructions: " + "; ".join(items[:8]) + ".", interruptible=False)
        else:
            assistant.say("No CrossChat instructions are saved yet.", interruptible=False)
        return True
    if kind == "forget":
        removed = forget_instruction(str(action.get("value") or ""), user_id=user_id, actor_id=actor_id)
        assistant.say("Removed that instruction." if removed else "I could not find that instruction.", interruptible=False)
        return True
    if kind == "rate":
        ok = rate_reply(int(action.get("value") or 0), user_id=user_id)
        assistant.say("Thanks, I'll use that rating." if ok else "I couldn't save that rating.", interruptible=False)
        return True
    if kind == "feedback":
        ok = note_feedback(str(action.get("value") or ""), user_id=user_id)
        assistant.say("Got it, I'll adjust how I talk." if ok else "I couldn't use that feedback.", interruptible=False)
        return True
    if kind == "instruction":
        ok = add_instruction(
            str(action.get("value") or ""),
            user_id=user_id,
            scope=str(action.get("scope") or "user"),
            actor_id=actor_id,
        )
        assistant.say("Saved that CrossChat instruction." if ok else "I couldn't save that instruction.", interruptible=False)
        return True
    return False


def is_crosschat_command(text: str) -> bool:
    return parse_crosschat_speech(text) is not None


def reset_state_for_tests() -> None:
    with _LOCK:
        _STATE.clear()
        _STATE["users"] = {}
        _LAST_REPLY.clear()
        _LAST_REPLY_CONTEXT.clear()
        _OBSERVATIONS.clear()


def _privileged(user_id: str) -> bool:
    from silva.conversation.speech_policy import is_privileged

    return is_privileged(_key(user_id))


def _normalize_trait(value: str) -> str:
    value = str(value or "").strip().lower()
    if value in ("causal", "casually"):
        return "casual"
    if value == "snarky":
        return "sassy"
    if value == "short":
        return "brief"
    if value in ("thorough", "explain more"):
        return "detailed"
    if value in ("friendly", "gentle"):
        return "warm"
    if value in ("straight", "blunt"):
        return "direct"
    return value if value in _TRAIT_WORDS else ""


def _clamp(value: int) -> int:
    return max(-3, min(3, value))


def _now() -> str:
    import datetime

    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


_STATE = _load_state()
