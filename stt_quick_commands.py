"""Detect fully spoken commands so Silva does not wait for phrase-completion timers."""

from __future__ import annotations

import re

from silva.commands.playback_handler import handle_playback_speech
from silva.commands.playback_phrases import is_playback_command
from silva.commands.appointment_phrases import is_appointment_command
from silva.commands.background_phrases import is_background_command
from silva.commands.audio_phrases import is_audio_command
from silva.commands.phrase_recorder_phrases import is_phrase_recorder_command
from silva.commands.pronunciation_phrases import is_pronunciation_command
from silva.commands.location_phrases import is_location_command
from silva.commands.camera_setup_phrases import is_camera_setup_command
from silva.commands.game_lookup_phrases import is_game_lookup
from silva.commands.knowledge_phrases import is_knowledge_command
from silva.commands.crash_report_phrases import is_crash_report_ask
from silva.commands.update_phrases import is_update_speech
from silva.commands.planner_phrases import is_planner_command
from silva.commands.help_phrases import is_capability_ask, is_feature_detail_ask, is_help_request
from silva.commands.news_phrases import is_news_command
from silva.commands.notes_phrases import is_notes_command
from silva.commands.math_phrases import is_math_command
from silva.commands.measurement_phrases import is_measurement_command
from silva.commands.weather_feedback import is_weather_feedback_command
from silva.commands.weather_forecast_phrases import is_weather_forecast_command
from silva.conversation.attitude import is_attitude_command
from silva.conversation.crosschat_memory import is_crosschat_command
from silva.conversation.correction_repair import is_correction_repair_command
from silva.conversation.learned_phrases import parse_learning_speech
from silva.conversation.safety import match_safety_speech
from silva.conversation.speech_policy import is_speech_policy_command
from silva.dev.code_assist import is_code_assist_command
from silva.dev.future_tasks import is_future_task_command
from silva.dev.screen_monitor import is_screen_monitor_command
from silva.dev.stream_deck import is_stream_deck_command
from silva.dev.team_updates import is_team_update_command
from silva.media.reference_image_phrases import is_reference_image_speech
from silva.media.image_generator_phrases import is_image_generation_speech
from silva.commands.registry import match_command
from silva.interrupt import is_interrupt_command
from silva.users.profile_phrases import is_profile_open_phrase
from silva.wake import is_sleep_command, is_wake_command

_VOICE_ENROLL_RE = re.compile(
    r"\b(set|save|record|enroll|register|train|remember)\b.*\b(voice|speaker)\b",
    re.I,
)
_BUG_REPORT_RE = re.compile(
    r"\b(report a bug|bug report|report bug|found a bug)\b",
    re.I,
)
_SECURITY_RE = re.compile(
    r"\b(security panel|security alerts|access alerts|show security)\b",
    re.I,
)
_SETTINGS_RE = re.compile(
    r"\b(change settings|open settings|silva settings|assistant settings)\b",
    re.I,
)

_QUICK_EXACT = {
    "help",
    "commands",
    "what can you do",
    "who am i",
    "who is speaking",
    "identify me",
    "exit",
    "quit",
    "goodbye",
    "bye",
    "show logs",
    "open logs",
    "view logs",
    "where are logs",
    "yes",
    "yeah",
    "yep",
    "yup",
    "yea",
    "no",
    "nope",
    "nah",
    "okay",
    "ok",
    "sure",
    "thanks",
    "thank you",
    "hello",
    "hi",
    "hey",
}

# Exact fragments that are clearly unfinished commands.
_EXACT_PARTIAL: frozenset[str] = frozenset(
    {
        "open",
        "show",
        "go",
        "launch",
        "silva",
        "manage",
        "my",
        "who",
        "what",
        "how",
        "tell",
        "look",
        "search",
        "check",
        "get",
        "set",
        "enroll",
        "register",
        "wake",
        "pro",
        "prof",
        "profile",
        "profiles",
        "panel",
        "go to",
        "take me to",
        "take me",
        "tell me",
        "look up",
        "search for",
        "note",
        "note this",
        "note that",
        "add to my",
        "add this to",
        "todo",
        "to do",
        "who am",
        "what is",
        "whats",
        "how is",
        "hows",
        "set my",
        "set voice",
        "save my",
        "record my",
        "enroll my",
        "register my",
        "add user",
        "remove user",
        "check the",
        "get the",
        "wake up",
    }
)

_TRUNCATED_TAIL_RE = re.compile(
    r"^(open|show|go to|launch|take me to|silva|manage|user|my|setup|set up|control|admin)"
    r"(\s+(pro|prof|profile|profiles|panel|panels?))?$",
    re.I,
)

_PROFILE_TAIL_WORDS = frozenset({"pro", "prof", "profile", "panel", "panels", "user", "control", "admin"})


def normalize(text: str) -> str:
    text = text.strip().lower()
    text = text.replace("'", "")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_complete_command(text: str) -> bool:
    """True when the utterance is a full command and should run immediately."""
    if not text or not text.strip():
        return False

    normalized = normalize(text)

    if is_profile_open_phrase(text):
        return True
    if is_correction_repair_command(text):
        return True
    if is_wake_command(text) or is_sleep_command(text):
        return True
    if is_interrupt_command(text):
        return True
    if match_command(text) is not None:
        return True
    if is_appointment_command(text):
        return True
    if is_audio_command(text):
        return True
    if is_pronunciation_command(text) or is_location_command(text):
        return True
    if is_phrase_recorder_command(text):
        return True
    if is_playback_command(text):
        return True
    if is_notes_command(text):
        return True
    if is_math_command(text):
        return True
    if is_measurement_command(text):
        return True
    if is_weather_feedback_command(text):
        return True
    if is_weather_forecast_command(text):
        return True
    if is_news_command(text):
        return True
    if is_camera_setup_command(text):
        return True
    if is_game_lookup(text):
        return True
    if is_knowledge_command(text):
        return True
    if is_crash_report_ask(text):
        return True
    if is_update_speech(text):
        return True
    if is_reference_image_speech(text):
        return True
    if is_image_generation_speech(text):
        return True
    if is_attitude_command(text):
        return True
    if is_crosschat_command(text):
        return True
    if is_screen_monitor_command(text):
        return True
    if is_code_assist_command(text):
        return True
    if is_stream_deck_command(text):
        return True
    if parse_learning_speech(text) is not None:
        return True
    if match_safety_speech(text) is not None:
        return True
    if is_speech_policy_command(text):
        return True
    if is_future_task_command(text):
        return True
    if is_team_update_command(text):
        return True
    if is_planner_command(text):
        return True
    if is_help_request(text) or is_feature_detail_ask(text) or is_capability_ask(text):
        return True
    if is_background_command(text):
        return True
    if normalized in _QUICK_EXACT:
        return True
    if _VOICE_ENROLL_RE.search(text):
        return True
    if _BUG_REPORT_RE.search(text):
        return True
    if _SECURITY_RE.search(text):
        return True
    if _SETTINGS_RE.search(text):
        return True

    if normalized.startswith(("add user ", "remove user ")):
        return True
    if normalized in {"list users", "show users", "who has access", "show requests", "pending requests"}:
        return True

    return False


def is_partial_command(text: str) -> bool:
    """True only when speech is clearly an unfinished command fragment."""
    if is_complete_command(text):
        return False

    normalized = normalize(text)
    if not normalized:
        return False

    if normalized in _EXACT_PARTIAL:
        return True

    if _TRUNCATED_TAIL_RE.match(normalized):
        return True

    words = normalized.split()
    if len(words) <= 3 and words[-1] in _PROFILE_TAIL_WORDS:
        if normalized not in {"open profile", "open profiles", "show profile", "show profiles"}:
            return True

    return False
