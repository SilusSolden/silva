from __future__ import annotations

import re

from silva.config import load_config, save_config

_FAMILY_ON_RE = re.compile(
    r"\b(?:children|kids?|family)\s+(?:are|is)?\s*(?:here|over|present|around)|"
    r"\bmind the (?:kids|children)\b|\bwatch your language\b|\bkeep it clean\b|"
    r"\bfamily (?:safe )?mode on\b|\bsafe mode on\b|\bclean (?:replies|language) on\b",
    re.I,
)
_FAMILY_OFF_RE = re.compile(
    r"\bfamily (?:safe )?mode off\b|\bsafe mode off\b|"
    r"\bclean (?:replies|language) off\b|\bkids? (?:are|have)? ?(?:left|gone)\b|"
    r"\bchildren (?:are|have)? ?(?:left|gone)\b",
    re.I,
)
_SPEAKER_ON_RE = re.compile(
    r"\b(?:speaker mode on|speakers? mode on|playing (?:me |silva )?over (?:the )?speakers?|"
    r"silva is on (?:the )?speakers?|we are on speakers?|limit (?:replies|answers) for speakers?|"
    r"speaker safe mode on)\b",
    re.I,
)
_SPEAKER_OFF_RE = re.compile(
    r"\b(?:speaker mode off|speakers? mode off|stop playing (?:me |silva )?over (?:the )?speakers?|"
    r"take (?:me |silva )?off (?:the )?speakers?|speaker safe mode off)\b",
    re.I,
)
_PROFANITY = {
    "fuck": "freak",
    "fucking": "messing",
    "shit": "stuff",
    "bullshit": "nonsense",
    "bitch": "mean person",
    "asshole": "jerk",
    "bastard": "jerk",
    "cunt": "jerk",
    "dick": "jerk",
    "cock": "jerk",
    "piss": "annoy",
    "slut": "person",
    "whore": "person",
    "damn": "darn",
    "hell": "heck",
    "crap": "junk",
}
_PROFANITY_RE = re.compile(
    r"\b(?:" + "|".join(sorted(_PROFANITY, key=len, reverse=True)) + r")\b",
    re.I,
)


def is_family_safe() -> bool:
    return bool(load_config().get("family_safe_mode", False))


def is_speaker_safe() -> bool:
    return bool(load_config().get("speaker_safe_mode", False))


def safety_active() -> bool:
    return is_family_safe() or is_speaker_safe()


def _set_key(key: str, enabled: bool) -> None:
    config = load_config()
    config[key] = bool(enabled)
    save_config(config)


def set_family_safe(enabled: bool) -> None:
    _set_key("family_safe_mode", enabled)


def set_speaker_safe(enabled: bool) -> None:
    _set_key("speaker_safe_mode", enabled)


def match_safety_speech(text: str) -> tuple[str, bool] | None:
    value = str(text or "").strip()
    if not value:
        return None
    if _SPEAKER_OFF_RE.search(value):
        return "speaker", False
    if _SPEAKER_ON_RE.search(value):
        return "speaker", True
    if _FAMILY_OFF_RE.search(value):
        return "family", False
    if _FAMILY_ON_RE.search(value):
        return "family", True
    return None


def clean_language(text: str) -> str:
    return _PROFANITY_RE.sub(lambda match: _PROFANITY[match.group(0).lower()], str(text or ""))


def sanitize_image_prompt(text: str, *, user_id: str = "") -> str:
    value = str(text or "").strip()
    if not safety_active() or not value:
        return value
    value = clean_language(value)
    value = re.sub(r"\s{2,}", " ", value)
    return value


def apply_safety(text: str, *, image: bool = False, user_id: str = "") -> str:
    value = str(text or "")
    if not value or not safety_active():
        return value
    value = sanitize_image_prompt(value, user_id=user_id) if image else clean_language(value)
    if is_speaker_safe():
        sentences = re.split(r"(?<=[.!?])\s+", value)
        value = " ".join(sentences[:2])[:240].strip()
    return value


def handle_safety_speech(assistant, text: str) -> bool:
    action = match_safety_speech(text)
    if action is None:
        return False
    mode, enabled = action
    if not enabled:
        from silva.conversation.speech_policy import is_privileged

        getter = getattr(assistant, "_user_id", None)
        actor = getter() if callable(getter) else ""
        if not is_privileged(actor):
            assistant.say(
                "Only the owner or an admin can turn safe-reply modes off.",
                interruptible=False,
            )
            return True
    if mode == "speaker":
        set_speaker_safe(enabled)
        message = "Speaker-safe replies are on." if enabled else "Speaker-safe replies are off."
    else:
        set_family_safe(enabled)
        message = "Family-safe replies are on." if enabled else "Family-safe replies are off."
    assistant.say(message, interruptible=False)
    return True
