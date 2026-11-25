"""True when spoken text is a real Silva command, not small talk."""

from __future__ import annotations

from silva.commands.appointment_phrases import is_appointment_command
from silva.commands.background_phrases import is_background_command
from silva.commands.crash_report_phrases import is_crash_report_ask
from silva.commands.planner_phrases import is_planner_command
from silva.commands.audio_phrases import is_audio_command
from silva.commands.camera_setup_phrases import is_camera_setup_command
from silva.users.camera_access import is_camera_access_phrase
from silva.commands.game_lookup_phrases import is_game_lookup
from silva.commands.help_phrases import is_capability_ask, is_feature_detail_ask, is_help_request
from silva.commands.knowledge_phrases import is_knowledge_command
from silva.commands.location_phrases import is_location_command
from silva.commands.math_phrases import is_math_command
from silva.commands.measurement_phrases import is_measurement_command
from silva.commands.news_phrases import is_news_command
from silva.commands.notes_phrases import is_notes_command
from silva.commands.phrase_recorder_phrases import is_phrase_recorder_command
from silva.commands.pronunciation_phrases import is_pronunciation_command
from silva.commands.playback_phrases import is_playback_command
from silva.commands.registry import match_command
from silva.commands.system_panel_commands import match_system_panel_speech
from silva.commands.visual_guide_phrases import match_visual_guide_speech
from silva.commands.weather_feedback import is_weather_feedback_command
from silva.commands.weather_forecast_phrases import is_weather_forecast_command
from silva.media.reference_image_phrases import is_reference_image_speech
from silva.media.image_generator_phrases import is_image_generation_speech
from silva.close_phrases import is_close_command
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
from silva.interrupt import is_interrupt_command
from silva.users.profile_phrases import is_profile_open_phrase
from silva.wake import is_sleep_command, is_wake_command


def is_action_command(text: str) -> bool:
    if not text or not text.strip():
        return False
    if is_help_request(text) or is_feature_detail_ask(text) or is_capability_ask(text):
        return True
    if is_correction_repair_command(text):
        return True
    if is_crash_report_ask(text):
        return True
    if is_planner_command(text):
        return True
    try:
        from silva.commands.update_phrases import is_update_speech

        if is_update_speech(text):
            return True
    except Exception:
        pass
    if is_background_command(text):
        return True
    if is_wake_command(text) or is_sleep_command(text) or is_interrupt_command(text):
        return True
    if is_close_command(text):
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
    if is_news_command(text):
        return True
    if is_game_lookup(text):
        return True
    if is_knowledge_command(text):
        return True
    if is_weather_forecast_command(text) or is_weather_feedback_command(text):
        return True
    if is_notes_command(text):
        return True
    if is_camera_access_phrase(text) or is_camera_setup_command(text):
        return True
    if is_appointment_command(text) or is_math_command(text) or is_measurement_command(text):
        return True
    if is_audio_command(text) or is_playback_command(text):
        return True
    if is_pronunciation_command(text) or is_location_command(text):
        return True
    if is_phrase_recorder_command(text) or is_profile_open_phrase(text):
        return True
    if match_visual_guide_speech(text):
        return True
    if match_system_panel_speech(text) is not None:
        return True
    if is_reference_image_speech(text):
        return True
    if is_image_generation_speech(text):
        return True
    if match_command(text) is not None:
        return True
    return False
