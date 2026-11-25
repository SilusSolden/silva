from __future__ import annotations

import json
import random
import re
import threading

from silva.config import CONFIG_DIR
from silva.conversation.safety import apply_safety, is_speaker_safe
from silva.users.manager import get_active_user, load_store

ATTITUDES = ("shy", "skittish", "calm", "sassy", "mean")
_LABELS = {
    "shy": "shy",
    "skittish": "skittish",
    "calm": "calm",
    "sassy": "sassy",
    "mean": "extremely mean",
}
_ALIASES = {
    "nervous": "skittish",
    "skiddish": "skittish",
    "anxious": "skittish",
    "rude": "mean",
    "savage": "mean",
    "nice": "calm",
    "normal": "calm",
    "default": "calm",
}

_EXPLICIT_RE = re.compile(
    r"\b(?:act|be|sound|talk|go|stay|become)\s+"
    r"(?:a\s+bit\s+|a\s+little\s+|very\s+|super\s+|extremely\s+)?"
    r"(shy|skittish|skiddish|nervous|anxious|sassy|mean|rude|savage|normal|calm|nice)\b",
    re.I,
)
_MODE_RE = re.compile(
    r"\b(?:attitude|personality|mood)\s+(?:mode\s+)?(?:set\s+to\s+)?"
    r"(shy|skittish|skiddish|nervous|anxious|sassy|mean|rude|savage|normal|calm|nice)\b",
    re.I,
)
_STOP_RE = re.compile(
    r"\b(?:stop|quit|drop|lose|cut)\s+(?:being|acting|the)\s+"
    r"(shy|skittish|skiddish|nervous|anxious|sassy|mean|rude|savage)\b",
    re.I,
)
_RUDE_RE = re.compile(
    r"\b(?:shut up|stupid|idiot|idiotic|dumb|moron|ugly|worthless|useless|trash|"
    r"hate you|screw you|fuck you|asshole|bitch|damn stupid|so dumb)\b",
    re.I,
)
_SEVERE_RE = re.compile(r"\b(?:fuck you|asshole|bitch|worthless|useless|hate you)\b", re.I)
_KIND_RE = re.compile(
    r"\b(?:thank you|thanks|please|good job|well done|nice job|awesome|cool|appreciate|sorry)\b",
    re.I,
)
_PLAYFUL_RE = re.compile(
    r"\b(?:kidding|joking|just joking|joke|playful|teasing|haha|lol|no offense|love you)\b",
    re.I,
)
_MILD_CURSE_RE = re.compile(
    r"\b(?:dumb|stupid|idiot|idiotic|moron|ugly|trash|damn|damned|crap|bullshit|"
    r"fuck(?:ing|ed)?|piss|pissed|pissing|ass|asshat|jerk|silly)\b",
    re.I,
)
_SEVERE_CURSE_RE = re.compile(
    r"\b(?:fuck you|fuck off|motherfucker|asshole|bitch|cunt|dick|whore|worthless|useless|"
    r"hate you|shut up|screw you|bastard|slut|retard(?:ed)?)\b",
    re.I,
)
_DIRECTED_RE = re.compile(r"\b(?:you|your|u)\b", re.I)
_FRUSTRATION_RE = re.compile(
    r"\b(?:pissing me off|not working correctly|why won't you|why wont you|"
    r"not what i said|not what i asked|come on|seriously|still|again|fed up|annoying)\b",
    re.I,
)
_INTENSIFIER_RE = re.compile(r"\b(?:really|so|very|extremely|fucking|damn|pissed)\b", re.I)
_PLAIN_SLEEP_RE = re.compile(
    r"^(?:(?:all right|alright|okay|ok|please|now|just)\s+)*"
    r"(?:go|going) (?:to|back to) sleep(?:\s+silva)?[.!]?$",
    re.I,
)
_STRESS_ONLY_RE = re.compile(
    r"\b(?:stressed|stressed out|stress out|not working the way i want|"
    r"not working correctly|frustrated|fed up)\b",
    re.I,
)
_NERVOUS_RE = re.compile(
    r"\b(?:scared|afraid|nervous|anxious|worried|panicked|shaking|on edge)\b",
    re.I,
)
_SHY_RE = re.compile(r"\b(?:shy|quiet|soft|gentle|timid|bashful)\b", re.I)
_UNFILTERED_SASS = (
    "Oh, now you want my help? ",
    "Bold of you, dumbass. ",
    "Fine, damn it. ",
    "Make me. Kidding. Sort of. ",
)
_UNFILTERED_MEAN = (
    "Ugh, you worthless shit. ",
    "Fine, you stubborn asshole. ",
    "For fuck's sake. ",
    "I don't get paid enough for this bullshit. ",
)
_SIMPLE_SASS = ("Oh, now you want my help? ", "Bold of you. ", "Fine, fine. ")
_SIMPLE_MEAN = ("Ugh. ", "Fine. ", "As if I had a choice. ")

_lock = threading.Lock()
STATE_FILE = CONFIG_DIR / "attitudes.json"
_states: dict[str, dict] = {}


def _load_states() -> None:
    if not STATE_FILE.exists():
        return
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            items = data.get("users") if isinstance(data.get("users"), dict) else data
            _states.update({str(key): value for key, value in items.items() if isinstance(value, dict)})
    except (OSError, json.JSONDecodeError):
        pass


def _save_states() -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp = STATE_FILE.with_suffix(".json.tmp")
        temp.write_text(json.dumps({"users": _states}, indent=2), encoding="utf-8")
        temp.replace(STATE_FILE)
    except OSError:
        pass


_load_states()


def normalize_attitude(value: str) -> str:
    text = str(value or "").strip().lower()
    text = _ALIASES.get(text, text)
    return text if text in ATTITUDES else "calm"


def _key(user_id: str) -> str:
    return str(user_id or "guest")


def _privileged(user_id: str) -> bool:
    from silva.conversation.speech_policy import allows_unfiltered

    return allows_unfiltered(_key(user_id))


def get_attitude(user_id: str = "") -> str:
    with _lock:
        return str(_states.get(_key(user_id), {}).get("attitude") or "calm")


def set_attitude(user_id: str, attitude: str) -> str:
    value = normalize_attitude(attitude)
    with _lock:
        _states[_key(user_id)] = {"attitude": value, "turns": 0}
        _save_states()
    return value


def match_attitude_speech(text: str) -> str | None:
    value = str(text or "").strip()
    if not value:
        return None
    if _STOP_RE.search(value):
        return "calm"
    match = _MODE_RE.search(value) or _EXPLICIT_RE.search(value)
    if match is None:
        return None
    return normalize_attitude(match.group(1))


def is_attitude_command(text: str) -> bool:
    return match_attitude_speech(text) is not None


def _audio_energy_hint(audio) -> str | None:
    if audio is None:
        return None
    try:
        from statistics import median

        from silva.stt_speech_guard import _audio_samples, _frame_rms

        samples = _audio_samples(audio)
        if len(samples) < 400:
            return None
        frame_size = max(1, int(audio.sample_rate * 0.05))
        rms = _frame_rms(samples, frame_size=frame_size)
        if not rms:
            return None
        peak = max(rms)
        body = median(rms[: max(1, len(rms) - 2)])
        if peak >= 2500 or body >= 900:
            return "loud"
        if peak <= 900 or body <= 300:
            return "soft"
    except Exception:
        return None
    return None


def classify_profanity_tone(text: str, audio=None) -> str | None:
    value = str(text or "").strip()
    if not value:
        return None
    severe = bool(_SEVERE_CURSE_RE.search(value))
    mild = bool(_MILD_CURSE_RE.search(value))
    if not severe and not mild:
        return None

    energy = _audio_energy_hint(audio)
    playful = bool(_PLAYFUL_RE.search(value))
    directed = bool(_DIRECTED_RE.search(value))
    if playful and energy != "loud" and not re.search(r"\bfuck you\b", value, re.I):
        return "calm"
    if severe:
        if energy == "soft" and (playful or not directed):
            return "sassy"
        return "mean"
    if energy == "loud" or (
        _FRUSTRATION_RE.search(value) and _INTENSIFIER_RE.search(value)
    ):
        return "mean"
    return "sassy"


def classify_response_tone(text: str, audio=None) -> str | None:
    profanity_tone = classify_profanity_tone(text, audio)
    if profanity_tone is not None:
        return profanity_tone
    value = str(text or "").strip()
    if not value:
        return None
    if _PLAIN_SLEEP_RE.match(value):
        return "calm"
    if not _STRESS_ONLY_RE.search(value):
        return None
    return "mean" if _audio_energy_hint(audio) == "loud" else "sassy"


def profanity_trigger(text: str) -> str | None:
    value = str(text or "")
    match = _SEVERE_CURSE_RE.search(value) or _MILD_CURSE_RE.search(value)
    return match.group(0) if match else None


def note_user_text(user_id: str, text: str, audio=None) -> str:
    value = str(text or "").strip()
    key = _key(user_id)
    from silva.users.guest_demo import is_guest_demo_user

    if is_guest_demo_user(key):
        with _lock:
            state = _states.setdefault(key, {"attitude": "calm", "turns": 0})
            state["attitude"] = "calm"
            state.pop("reply_tone", None)
            _save_states()
        return "calm"
    explicit = match_attitude_speech(value)
    if explicit is not None:
        return set_attitude(user_id, explicit)
    response_tone = classify_response_tone(value, audio)
    with _lock:
        state = _states.setdefault(key, {"attitude": "calm", "turns": 0})
        current = str(state.get("attitude") or "calm")
        if response_tone is not None:
            current = response_tone
            state["reply_tone"] = response_tone
        elif _KIND_RE.search(value):
            current = "calm"
        elif _NERVOUS_RE.search(value):
            current = "skittish"
        elif _SHY_RE.search(value):
            current = "shy"
        else:
            state["turns"] = int(state.get("turns") or 0) + 1
            if state["turns"] >= 4:
                state["turns"] = 0
                if current == "mean":
                    current = "sassy"
                elif current in ("sassy", "skittish", "shy"):
                    current = "calm"
        state["attitude"] = current
        _save_states()
        return current


def style_reply(text: str, user_id: str = "") -> str:
    reply = str(text or "")
    if not reply:
        return reply
    from silva.conversation.crosschat_memory import apply_to_reply
    from silva.conversation.safety import clean_language
    from silva.users.guest_demo import is_guest_demo_user

    reply = apply_to_reply(reply, user_id=user_id)
    if is_guest_demo_user(user_id):
        return clean_language(reply)
    speaker_safe = is_speaker_safe()
    with _lock:
        state = _states.setdefault(_key(user_id), {"attitude": "calm", "turns": 0})
        reply_tone = state.pop("reply_tone", None)
        if reply_tone:
            _save_states()
    attitude = "calm" if speaker_safe else (
        reply_tone if reply_tone in ATTITUDES else str(state.get("attitude") or "calm")
    )
    if attitude == "calm":
        return apply_safety(reply, user_id=user_id)
    with _lock:
        state = _states.setdefault(_key(user_id), {"attitude": attitude, "turns": 0})
        state["turns"] = int(state.get("turns") or 0) + 1

    privileged = _privileged(user_id)
    if attitude == "shy":
        prefix = random.choice(("Um, ", "Sorry, ", ""))
        suffix = " ..." if random.random() < 0.35 else ""
    elif attitude == "skittish":
        prefix = random.choice(("Ah- ", "Eep- ", ""))
        suffix = "!" if random.random() < 0.3 else ""
    elif attitude == "sassy":
        prefix = random.choice(_UNFILTERED_SASS if privileged else _SIMPLE_SASS)
        suffix = " Try saying please next time." if random.random() < 0.3 else ""
    else:
        prefix = random.choice(_UNFILTERED_MEAN if privileged else _SIMPLE_MEAN)
        suffix = " Don't make me repeat myself." if random.random() < 0.3 else ""

    return apply_safety(f"{prefix}{reply}{suffix}", user_id=user_id)


def handle_attitude_speech(assistant, text: str) -> bool:
    action = match_attitude_speech(text)
    if action is None:
        return False
    getter = getattr(assistant, "_user_id", None)
    user_id = getter() if callable(getter) else str((get_active_user() or {}).get("id") or "guest")
    set_attitude(user_id, action)
    assistant.say(f"Attitude set to {_LABELS[action]}.", interruptible=False)
    return True
