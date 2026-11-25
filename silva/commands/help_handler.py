"""Reloadable help / feature-detail speech so live update can rebind it."""

from __future__ import annotations

import re

from silva.logger import log_info
from silva.users.manager import get_active_user

_PLAIN_REQUEST_RE = re.compile(
    r"\b(?:i (?:do not|don't) (?:even )?(?:understand|know what you (?:just )?said|follow that)|"
    r"what did (?:that|you) mean|what does that mean|say that (?:again )?in plain (?:english|words)|"
    r"in simpler words|use simpler words|explain that simpler)\b",
    re.I,
)

_ANY_CHOICE_RE = re.compile(
    r"\b(?:any of them|any of these|any of those|any one|pick one|choose one|"
    r"you choose|you pick|your call|whatever)\b",
    re.I,
)

_FUTURE_CHOICE_RE = re.compile(
    r"\b(?:next time|from now on|if i ask|when i ask|that again|supposed to|"
    r"on your own|for yourself|choose on your own|choose for yourself)\b",
    re.I,
)


def _detail_web_reply(topic: str) -> str:
    from silva.config import load_config

    if not bool(load_config().get("detailed_web_skim_enabled", True)):
        return ""
    from silva.commands.knowledge_skim import web_addendum

    return str(web_addendum(topic) or "").strip()


def _script_detail_reply(topic: str) -> str:
    from silva.dev.code_assist import explain_script

    return str(explain_script(topic) or "").strip()


def _simplify_reply(text: str) -> str:
    value = str(text or "").strip()
    value = re.split(r"\bMain pieces:", value, maxsplit=1, flags=re.I)[0]
    value = re.sub(r"[A-Za-z0-9_./\\-]+\.py", "that script", value)
    value = re.sub(r"\b_[A-Za-z0-9_]+\b", "that part", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _plain_reply(assistant, text: str) -> bool:
    from silva.conversation.crosschat_memory import last_reply

    user_getter = getattr(assistant, "_user_id", None)
    user_id = user_getter() if callable(user_getter) else ""
    previous = _simplify_reply(last_reply(user_id=user_id))
    if previous:
        assistant.say(f"In plain words: {previous}", interruptible=False)
    else:
        assistant.say("Tell me what part was confusing and I'll say it in plain words.", interruptible=False)
    return True


def _speaker_id(assistant) -> str:
    getter = getattr(assistant, "_user_id", None)
    return str(getter() if callable(getter) else "")


def _auto_choice_enabled(user_id: str) -> bool:
    from silva.conversation.crosschat_memory import list_instructions

    wanted = "choose one"
    return any(wanted in item.lower() for item in list_instructions(user_id=user_id))


def _remember_auto_choice(user_id: str) -> None:
    from silva.conversation.crosschat_memory import add_instruction

    add_instruction(
        "When I need you to pick from a list of options, choose one on your own.",
        user_id=user_id,
    )


def _choose_for_user(assistant, user_id: str) -> bool:
    from silva.commands.help_phrases import detail_topic
    from silva.conversation.correction_repair import candidate_for, clear_candidate

    candidate = candidate_for(user_id)
    if candidate:
        topic = detail_topic(str(candidate.get("text") or ""))
        clear_candidate(user_id)
        if topic:
            log_info(f"Auto choice: {topic}")
            return bool(assistant._handle_input(f"can you tell me in detail what {topic} does", _phrase_retry=True))
    assistant.say("I'll choose weather. Name one if you want a different one.", interruptible=False)
    return bool(assistant._handle_input("tell me in detail what weather is", _phrase_retry=True))


def _handle_choice_speech(assistant, text: str) -> bool:
    if not _ANY_CHOICE_RE.search(str(text)):
        return False
    user_id = _speaker_id(assistant)
    if _FUTURE_CHOICE_RE.search(str(text)):
        _remember_auto_choice(user_id)
        assistant.say("Got it. Next time I need to pick from a list, I'll choose one myself.", interruptible=False)
        return True
    if _auto_choice_enabled(user_id) or _candidate_exists(user_id):
        return _choose_for_user(assistant, user_id)
    return False


def _candidate_exists(user_id: str) -> bool:
    from silva.conversation.correction_repair import has_candidate_for

    return has_candidate_for(user_id)


def handle_help_speech(assistant, text: str) -> bool:
    """Explain the short capability list or one feature. Never falls through to chat."""
    if not text or not str(text).strip():
        return False
    from silva.commands.update_handler import handle_update_expansion_speech

    if handle_update_expansion_speech(assistant, text):
        return True
    if _PLAIN_REQUEST_RE.search(str(text)):
        return _plain_reply(assistant, text)
    if _handle_choice_speech(assistant, text):
        return True

    # Import at call time so a live update picks up the newest phrase matchers.
    from silva.commands.help_phrases import (
        _WHICH_FEATURE,
        capability_reply_for_user,
        detail_topic,
        feature_detail_reply_for_user,
        help_reply_for_user,
        is_capability_ask,
        is_feature_detail_ask,
        is_help_request,
    )

    from silva.conversation.correction_repair import (
        note_feature_detail_clarification,
        note_repairable_question,
    )

    note_repairable_question(assistant, text)

    user = get_active_user()
    if is_help_request(text):
        assistant.say(help_reply_for_user(user), interruptible=True)
        return True

    detail = feature_detail_reply_for_user(text, user)
    if detail:
        if detail == _WHICH_FEATURE:
            topic = detail_topic(text)
            if topic:
                skim = _script_detail_reply(topic) or _detail_web_reply(topic)
                if skim:
                    detail = skim
        log_info(f"Feature detail: {text[:120]}")
        note_feature_detail_clarification(assistant, text, detail)
        assistant.say(detail, interruptible=True)
        return True

    if is_feature_detail_ask(text):
        assistant.say(help_reply_for_user(user), interruptible=True)
        return True

    capability = capability_reply_for_user(text, user)
    if capability:
        assistant.say(capability, interruptible=False)
        return True

    if is_capability_ask(text):
        assistant.say(help_reply_for_user(user), interruptible=False)
        return True

    return False
