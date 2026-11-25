from __future__ import annotations

import re

from silva.config import load_config
from silva.logger import log_info

_SELF_TALK_RE = re.compile(
    r"\b(?:you|your|yourself|silva|why did you|why are you|why do you|are you|"
    r"do you hear|can you hear|pissing me off|not working|work correctly|"
    r"what i said|i said|not what|update|version|patch|live chat|system panel)\b",
    re.I,
)

_INFORMATION_SHAPE_RE = re.compile(
    r"^(?:(?:can|could|would|will) you (?:please )?)?"
    r"(?:tell me (?:about|what|who|where|when|why|the details on)|"
    r"what (?:is|are|was|were|does|did)|who (?:is|was|were)|"
    r"where (?:is|was|were)|when (?:was|were|did)|explain|describe|break down)\b",
    re.I,
)

_REJECT_TOPICS = frozenset(
    {
        "by the way",
        "that",
        "this",
        "it",
        "you",
        "yourself",
        "silva",
        "the options",
        "available options",
        "whatever",
        "something",
        "anything",
    }
)


def unknown_information_topic(text: str) -> str:
    value = re.sub(r"\s+", " ", str(text or "").strip())
    if not value:
        return ""
    if not bool(load_config().get("unknown_information_wikipedia_fallback_enabled", True)):
        return ""
    if _SELF_TALK_RE.search(value):
        return ""

    from silva.commands.help_phrases import detail_topic, is_capability_ask, is_feature_detail_ask, match_feature_id
    from silva.conversation.correction_repair import is_correction_repair_command, parse_correction

    if is_correction_repair_command(value) or parse_correction(value):
        return ""
    if is_feature_detail_ask(value) or is_capability_ask(value) or match_feature_id(value):
        return ""
    if not _INFORMATION_SHAPE_RE.search(value):
        return ""

    topic = detail_topic(value)
    if not topic or topic.strip().lower() in _REJECT_TOPICS:
        return ""
    if len(topic.split()) > 12:
        return ""
    return topic


def handle_unknown_information_speech(assistant, text: str) -> bool:
    topic = unknown_information_topic(text)
    if not topic:
        return False

    from silva.commands.knowledge_skim import skim_topic

    result = skim_topic(topic)
    if result.spoken:
        log_info(f"Unknown-information Wikipedia fallback: {topic[:120]}")
        assistant.say(f"I skimmed Wikipedia for {topic}: {result.spoken}", interruptible=True)
    else:
        assistant.say(f"I could not find a clear Wikipedia answer for {topic}.", interruptible=False)
    return True
