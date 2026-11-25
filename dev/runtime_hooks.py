"""Rebind the running Assistant to freshly reloaded command modules."""

from __future__ import annotations

import importlib
import sys
import time

from silva.logger import log_error, log_info

_ASSISTANT_REBINDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("silva.assistant", ("say", "_wake_up", "_monitor_screen_activity")),
    ("silva.commands.registry", ("match_command", "run_command")),
    ("silva.commands.intent", ("is_action_command",)),
    ("silva.commands.notes_handler", ("handle_notes_speech", "continue_notes_flow")),
    ("silva.commands.notes_phrases", ("is_notes_command", "match_notes_speech")),
    ("silva.commands.todo_nags", ("announce_todo_nags",)),
    ("silva.yes_no_prompt", ("dispatch", "check_news_briefing", "handle_news_flow", "offer_plugged_in_camera", "handle_camera_setup_flow", "handle_camera_setup_command")),
    (
        "silva.commands.camera_setup_handler",
        (
            "continue_camera_setup_flow",
            "handle_camera_setup_speech",
            "offer_for_camera",
            "start_camera_test",
            "SKIP_TEST_MESSAGE",
        ),
    ),
    ("silva.commands.camera_setup_phrases", ("is_camera_cancel_speech", "is_camera_setup_command", "parse_test_duration")),
    ("silva.commands.math", ("handle_math_speech",)),
    ("silva.commands.math_phrases", ("is_math_command",)),
    ("silva.commands.knowledge_skim", ("handle_knowledge_speech",)),
    ("silva.commands.knowledge_phrases", ("is_knowledge_command",)),
    ("silva.commands.game_lookup", ("handle_game_lookup_speech",)),
    ("silva.commands.game_lookup_phrases", ("is_game_lookup",)),
    ("silva.commands.news_handler", ("handle_news_speech", "continue_news_flow")),
    ("silva.commands.news_phrases", ("is_news_command",)),
    ("silva.commands.audio_handler", ("handle_audio_speech",)),
    ("silva.commands.audio_phrases", ("is_audio_command",)),
    ("silva.commands.playback_handler", ("handle_playback_speech",)),
    ("silva.commands.playback_phrases", ("is_playback_command",)),
    ("silva.commands.weather_feedback", ("handle_weather_feedback", "is_weather_feedback_command")),
    ("silva.commands.weather_forecast_handler", ("handle_forecast_speech", "continue_forecast_flow")),
    ("silva.commands.weather_forecast_phrases", ("is_weather_forecast_command",)),
    ("silva.commands.visual_guide_handler", ("handle_visual_guide_speech",)),
    (
        "silva.commands.help_phrases",
        (
            "is_help_request",
            "is_feature_detail_ask",
            "is_capability_ask",
            "should_yield_to_feature_help",
            "help_reply_for_user",
            "capability_reply_for_user",
            "feature_detail_reply_for_user",
        ),
    ),
    ("silva.commands.help_handler", ("handle_help_speech",)),
    ("silva.commands.crash_report_handler", ("handle_crash_report_speech",)),
    ("silva.commands.crash_report_phrases", ("is_crash_report_ask", "is_command_fail_ask", "wants_crash_file")),
    (
        "silva.commands.system_panel_commands",
        ("match_system_panel_speech", "handle_system_panel_speech"),
    ),
    (
        "silva.media.reference_image_phrases",
        ("is_reference_image_speech", "match_reference_image_speech", "reference_query"),
    ),
    ("silva.media.reference_image_handler", ("handle_reference_image_speech",)),
    (
        "silva.media.image_generator_phrases",
        ("is_image_generation_speech", "match_image_generation_speech", "image_prompt", "edit_prompt"),
    ),
    ("silva.media.image_generator_handler", ("handle_image_generation_speech",)),
    ("silva.commands.planner_handler", ("handle_planner_speech",)),
    ("silva.commands.planner_phrases", ("is_planner_command", "match_planner_view", "is_planner_map_ask", "is_planner_site_ask", "match_planner_draw_tool", "is_planner_close_ask")),
    ("silva.crash_record", ("explain_last_crash", "explain_last_command_fail", "record_command_error", "record_session_start", "record_clean_exit")),
    ("silva.commands.update_handler", ("handle_update_speech",)),
    ("silva.dev.whats_new_script", ("run_whats_new_script", "record_apply_delta")),
    ("silva.commands.pronunciation_handler", ("handle_pronunciation_speech",)),
    ("silva.commands.pronunciation_phrases", ("is_pronunciation_command", "match_pronunciation_speech")),
    ("silva.commands.location_handler", ("handle_location_speech",)),
    ("silva.commands.location_phrases", ("is_location_command",)),
    ("silva.commands.wiki_guide", ("handle_guide_control", "is_guide_control", "is_crafting_query")),
    ("silva.tts_word_clips", ("build_speech_parts", "speak_parts", "speak_impl")),
    ("silva.tts_pronunciation", ("prepare_for_speech",)),
    (
        "silva.users.word_pronunciations",
        (
            "pick_single_word",
            "pick_spoken_form",
            "remember_word_from_clip",
            "assign_word",
            "set_active_variant",
            "remove_variant",
            "active_word_variants",
            "word_clip_paths",
        ),
    ),
    ("silva.wake", ("is_sleep_command", "is_wake_command")),
    ("silva.close_phrases", ("is_close_command",)),
    ("silva.sleep_prompts", ("maybe_idle_sleep_reminder", "remind_asleep", "looks_like_user_attempt")),
    ("silva.conversation", ("try_conversation_with_context",)),
    ("silva.conversation.attitude", ("handle_attitude_speech", "is_attitude_command", "note_user_text", "style_reply")),
    (
        "silva.conversation.crosschat_memory",
        ("apply_to_reply", "handle_crosschat_speech", "is_crosschat_command", "remember_last_reply"),
    ),
    (
        "silva.conversation.learned_phrases",
        ("handle_learned_speech", "match_learned", "teach", "learn_from_correction"),
    ),
    (
        "silva.conversation.correction_repair",
        (
            "handle_correction_repair",
            "handle_exact_repeat",
            "is_awaiting_exact_repeat",
            "note_feature_detail_clarification",
            "note_pronunciation_question",
            "note_repairable_question",
        ),
    ),
    (
        "silva.dev.code_assist",
        ("handle_code_assist_speech", "parse_code_assist_speech", "scan_codebase", "write_placement_report"),
    ),
    (
        "silva.dev.screen_monitor",
        ("capture_activity", "handle_screen_monitor_speech", "parse_screen_monitor_speech"),
    ),
    (
        "silva.dev.stream_deck",
        ("handle_stream_deck_speech", "parse_stream_deck_speech", "publish_weather_tile", "resolve_slot_action"),
    ),
    ("silva.dev.auto_update", ("is_update_confirm_phrase", "is_update_decline_phrase")),
    ("silva.audio_recorder", ("VoiceRecorder", "pause_live_listen")),
)

_FORCE_RELOAD_PREFIXES: tuple[str, ...] = (
    "silva.commands.",
    "silva.crash_record",
    "silva.planner",
    "silva.conversation",
    "silva.dev.code_assist",
    "silva.dev.screen_monitor",
    "silva.media.image_generator_phrases",
    "silva.dev.stream_deck",
    "silva.interrupt",
    "silva.stt_quick_commands",
    "silva.interrupt_listen",
    "silva.stt_fillers",
    "silva.stt_speech_guard",
    "silva.tts_interrupt",
    "silva.wake",
    "silva.close_phrases",
    "silva.sleep_prompts",
    "silva.yes_no_prompt",
    "silva.mic_guard",
    "silva.users.camera_access",
    "silva.users.profile_phrases",
    "silva.users.word_pronunciations",
    "silva.tts_word_clips",
    "silva.tts_pronunciation",
    "silva.dev.whats_new_script",
    "silva.dev.future_tasks",
    "silva.dev.team_updates",
    "silva.users.age_verification",
    "silva.dev.auto_update",
    "silva.dev.panel_update",
    "silva.dev.update_scanner",
)

_NEVER_RELOAD: frozenset[str] = frozenset(
    {
        "silva.assistant",
        "silva.tts",
        "silva.stt",
        "silva.__main__",
        "silva.dev.live_update",
        "silva.dev.runtime_hooks",
        "silva.gui.display_host",
        "silva.gui.background_mode",
        "silva.gui.profile_panel",
        "silva.interrupt_monitor",
        "silva.background_runner",
    }
)


def _reload_priority(name: str) -> tuple:
    # Wake/sleep first, then phrase matchers, so intent/handlers import the new functions.
    if name in {"silva.wake", "silva.interrupt"}:
        return (0, name.count("."), name)
    if name.endswith("_phrases") or "help_phrases" in name:
        return (1, name.count("."), name)
    if name.endswith(".intent") or name.endswith(".registry") or "help_handler" in name:
        return (2, name.count("."), name)
    if "handler" in name:
        return (4, name.count("."), name)
    return (3, name.count("."), name)


def _should_force_reload(name: str) -> bool:
    if name in _NEVER_RELOAD:
        return False
    if name == "silva.gui" or name.startswith("silva.gui."):
        return False
    return any(name == prefix.rstrip(".") or name.startswith(prefix) for prefix in _FORCE_RELOAD_PREFIXES)


def reload_live_modules() -> list[str]:
    """Reload command/phrase modules from disk so skip-reload cores can rebind them."""
    names = [name for name in list(sys.modules) if _should_force_reload(name)]
    names.sort(key=_reload_priority)
    reloaded: list[str] = []
    for name in names:
        module = sys.modules.get(name)
        if module is None:
            continue
        try:
            importlib.reload(module)
            reloaded.append(name)
        except Exception as exc:
            log_error(f"Live command reload failed for {name}", exc=exc)
    if reloaded:
        log_info("Live command modules refreshed: " + ", ".join(reloaded[:24]))
    return reloaded


def _unwrap_handle_input(assistant_cls):
    current = assistant_cls._handle_input
    saved = getattr(assistant_cls, "_silva_unwrapped_handle_input", None)
    if saved is not None and not getattr(saved, "_silva_is_input_wrap", False):
        return saved
    unwrapped = current
    seen: set[int] = set()
    while getattr(unwrapped, "_silva_is_input_wrap", False):
        marker = id(unwrapped)
        if marker in seen:
            break
        seen.add(marker)
        nxt = getattr(unwrapped, "__wrapped__", None)
        if nxt is None or nxt is unwrapped:
            break
        unwrapped = nxt
    base = getattr(assistant_cls, "_silva_base_handle_input", None)
    if getattr(unwrapped, "_silva_is_input_wrap", False) and base is not None:
        unwrapped = base
    assistant_cls._silva_unwrapped_handle_input = unwrapped
    return unwrapped


def _patch_skip_reload_modules() -> int:
    patched = 0
    try:
        from silva.stt_quick_commands import is_complete_command, is_partial_command

        stt_mod = sys.modules.get("silva.stt")
        if stt_mod is not None:
            setattr(stt_mod, "is_complete_command", is_complete_command)
            setattr(stt_mod, "is_partial_command", is_partial_command)
            patched += 2
    except Exception as exc:
        log_error("Could not rebind speech complete-command checks", exc=exc)

    try:
        from silva.commands.intent import is_action_command
        from silva.interrupt import is_interrupt_command
        from silva.stt_quick_commands import is_complete_command
        from silva.wake import is_sleep_command

        monitor_mod = sys.modules.get("silva.interrupt_monitor")
        if monitor_mod is not None:
            setattr(monitor_mod, "is_action_command", is_action_command)
            setattr(monitor_mod, "is_interrupt_command", is_interrupt_command)
            setattr(monitor_mod, "is_complete_command", is_complete_command)
            setattr(monitor_mod, "is_sleep_command", is_sleep_command)
            patched += 4
        from silva.interrupt_listen import voice_stop_loop
        from silva.interrupt_monitor import InterruptMonitor

        InterruptMonitor._voice_loop = voice_stop_loop
        patched += 1
        from silva.interrupt_listen import (
            dispatch_overlay_command_impl,
            set_active_monitor,
            submit_typed_terminal_command_impl,
        )

        assistant_mod = sys.modules.get("silva.assistant")
        assistant_cls = getattr(assistant_mod, "SilvaAssistant", None) if assistant_mod else None
        if assistant_cls is not None:
            assistant_cls._submit_typed_terminal_command = submit_typed_terminal_command_impl
            assistant_cls._dispatch_overlay_command = dispatch_overlay_command_impl
            patched += 2

        orig_start = getattr(InterruptMonitor, "_silva_orig_start", None) or InterruptMonitor.start
        orig_stop = getattr(InterruptMonitor, "_silva_orig_stop", None) or InterruptMonitor.stop
        InterruptMonitor._silva_orig_start = orig_start
        InterruptMonitor._silva_orig_stop = orig_stop

        def _start(self, *args, **kwargs):
            set_active_monitor(self)
            return orig_start(self, *args, **kwargs)

        def _stop(self, *args, **kwargs):
            try:
                return orig_stop(self, *args, **kwargs)
            finally:
                from silva.interrupt_listen import active_monitor as _active

                if _active() is self:
                    set_active_monitor(None)

        InterruptMonitor.start = _start
        InterruptMonitor.stop = _stop
        patched += 2
    except Exception as exc:
        log_error("Could not rebind stop-while-talking listen", exc=exc)

    try:
        from silva.tts import TextToSpeech
        from silva.tts_interrupt import speak_interruptible_impl, stop_impl
        from silva.tts_word_clips import speak_impl

        TextToSpeech.speak = speak_impl
        TextToSpeech.speak_interruptible = speak_interruptible_impl
        TextToSpeech.stop = stop_impl
        patched += 3
    except Exception as exc:
        log_error("Could not rebind interruptible speech", exc=exc)

    return patched


def install_runtime_hooks() -> None:
    """Patch the live Assistant class so new commands work without restarting."""
    reloaded = reload_live_modules()

    assistant_mod = sys.modules.get("silva.assistant")
    if assistant_mod is None:
        log_info("Live runtime hooks: assistant is not loaded yet.")
        return
    assistant_cls = getattr(assistant_mod, "SilvaAssistant", None) or getattr(
        assistant_mod, "Assistant", None
    )
    if assistant_cls is None:
        return

    rebound = 0
    for module_name, names in _ASSISTANT_REBINDS:
        source = sys.modules.get(module_name)
        if source is None:
            try:
                __import__(module_name)
                source = sys.modules.get(module_name)
            except Exception:
                continue
        if source is None:
            continue
        target = assistant_cls if module_name == "silva.assistant" else assistant_mod
        for name in names:
            if hasattr(source, name):
                setattr(target, name, getattr(source, name))
                rebound += 1

    def _handle_update_speech(self, text: str) -> bool:
        from silva.commands.update_handler import handle_update_speech

        return handle_update_speech(self, text)

    assistant_cls._handle_update_speech = _handle_update_speech

    try:
        from silva.sleep_prompts import maybe_idle_sleep_reminder, remind_asleep

        assistant_cls._maybe_idle_sleep_reminder = maybe_idle_sleep_reminder
        assistant_cls._remind_asleep = remind_asleep
        rebound += 2
    except Exception as exc:
        log_error("Could not rebind sleep reminders", exc=exc)

    def _check_todo_nags(self) -> None:
        from silva.commands.todo_nags import announce_todo_nags

        announce_todo_nags(self)

    def _check_news_briefing(self) -> None:
        try:
            grace_until = float(getattr(self, "_daily_routine_grace_until", 0.0))
        except (TypeError, ValueError):
            grace_until = 0.0
        if getattr(self, "_asleep", False) or time.time() < grace_until:
            return
        from silva.yes_no_prompt import check_news_briefing

        check_news_briefing(self)

    def _handle_news_flow(self, text: str) -> bool:
        from silva.yes_no_prompt import handle_news_flow

        return handle_news_flow(self, text)

    def _offer_plugged_in_camera(self) -> None:
        from silva.yes_no_prompt import offer_plugged_in_camera

        offer_plugged_in_camera(self)

    def _handle_camera_setup_flow(self, text: str) -> bool:
        from silva.yes_no_prompt import handle_camera_setup_flow

        return handle_camera_setup_flow(self, text)

    def _handle_camera_setup_command(self, text: str) -> bool:
        from silva.yes_no_prompt import handle_camera_setup_command

        return handle_camera_setup_command(self, text)

    assistant_cls._check_todo_nags = _check_todo_nags
    assistant_cls._check_news_briefing = _check_news_briefing
    assistant_cls._handle_news_flow = _handle_news_flow
    assistant_cls._offer_plugged_in_camera = _offer_plugged_in_camera
    assistant_cls._handle_camera_setup_flow = _handle_camera_setup_flow
    assistant_cls._handle_camera_setup_command = _handle_camera_setup_command
    rebound += 8

    unwrapped = _unwrap_handle_input(assistant_cls)
    assistant_cls._silva_base_handle_input = unwrapped

    def _handle_input(self, text: str, *, _phrase_retry: bool = False) -> bool:
        from silva.conversation.learned_phrases import repair_stt_words
        from silva.stt_fillers import should_ignore_movement_uncertainty

        repaired_text = repair_stt_words(text)
        if repaired_text != text:
            log_info(f"Speech word repair: {text[:120]} -> {repaired_text[:120]}")
            text = repaired_text

        if should_ignore_movement_uncertainty(
            text,
            receding_audio=bool(getattr(self, "_last_input_receding", False)),
        ):
            log_info(f"Ignored thinking/mic-movement speech: {text[:120]}")
            return True

        from silva.commands.crash_report_handler import handle_crash_report_speech
        from silva.commands.help_handler import handle_help_speech
        from silva.commands.location_handler import handle_location_speech
        from silva.commands.pronunciation_handler import handle_pronunciation_speech
        from silva.commands.system_panel_commands import handle_system_panel_speech
        from silva.commands.update_handler import handle_update_speech
        from silva.yes_no_prompt import dispatch as dispatch_yes_no

        if text:
            from silva.dev.screen_monitor import stop_video_watch
            from silva.gui.display_manager import close_all
            from silva.interrupt import is_interrupt_command
            from silva.interrupt_listen import interrupt_now

            if is_interrupt_command(text):
                queue = getattr(self, "_parallel_queue", None)
                pending = getattr(self, "_pending_readbacks", None)
                active = bool(
                    getattr(self, "_speaking", False)
                    or getattr(self, "_parallel_command_active", False)
                    or pending
                    or (queue is not None and not queue.empty())
                )
                interrupt_now("input", command=text, tts=getattr(self, "_tts", None))
                if active:
                    close_all()
                    lock = getattr(self, "_followup_lock", None)
                    if lock is not None and pending is not None:
                        with lock:
                            pending.clear()
                    if queue is not None:
                        while True:
                            try:
                                queue.get_nowait()
                            except Exception:
                                break
                for _ in range(40):
                    if not getattr(self, "_speaking", False):
                        break
                    time.sleep(0.02)
                if getattr(self, "_speaking", False):
                    tts = getattr(self, "_tts", None)
                    if tts is not None:
                        try:
                            tts.stop()
                        except Exception:
                            pass
                    self._speaking = False
                lock = getattr(self, "_followup_lock", None)
                if lock is not None and pending is not None:
                    with lock:
                        pending.clear()
                user_getter = getattr(self, "_user_id", None)
                user_id = user_getter() if callable(user_getter) else "guest"
                stop_video_watch(user_id)
                self.say(getattr(self, "STOPPED_MESSAGE", "Stopped."), immediate=True)
                return True
        if text:
            from silva.conversation.correction_repair import (
                handle_correction_repair,
                handle_exact_repeat,
            )

            if handle_exact_repeat(self, text):
                return True
            if handle_correction_repair(self, text):
                return True
        if text:
            from silva.close_phrases import is_close_command
            from silva.conversation.attitude import handle_attitude_speech, note_user_text
            from silva.conversation.complete_sentence import should_ignore_after_interruption
            from silva.conversation.crosschat_memory import handle_crosschat_speech, observe_speech
            from silva.conversation.echo_guard import evaluate_input
            from silva.conversation.learned_phrases import handle_learned_speech
            from silva.conversation.safety import handle_safety_speech
            from silva.conversation.speech_policy import handle_speech_policy_speech
            from silva.dev.code_assist import handle_code_assist_speech
            from silva.dev.future_tasks import handle_future_task_speech
            from silva.dev.screen_monitor import handle_screen_monitor_speech
            from silva.dev.stream_deck import handle_stream_deck_speech
            from silva.dev.team_updates import handle_team_update_speech

            if not is_close_command(text) and should_ignore_after_interruption(
                text,
                interrupted_at=float(getattr(self, "_last_interruption_at", 0.0) or 0.0),
            ):
                log_info(f"Ignored incomplete speech after interruption: {text[:120]}")
                return True

            echo_decision = evaluate_input(text)

            if echo_decision == "self_echo":
                log_info(f"Ignored Silva's own speaker echo: {text[:120]}")
                return True
            if handle_safety_speech(self, text):
                return True
            if handle_speech_policy_speech(self, text):
                return True
            if handle_future_task_speech(self, text):
                return True
            if handle_team_update_speech(self, text):
                return True
            if handle_code_assist_speech(self, text):
                return True
            if handle_stream_deck_speech(self, text):
                return True
            if handle_screen_monitor_speech(self, text):
                return True
            if handle_crosschat_speech(self, text):
                return True
            if handle_attitude_speech(self, text):
                return True
            if getattr(self, "_silva_last_tone_text", "") != text:
                getter = getattr(self, "_user_id", None)
                user_id = getter() if callable(getter) else "guest"
                note_user_text(user_id, text, audio=getattr(self, "_last_audio", None))
                observe_speech(text, user_id=user_id)
                self._silva_last_tone_text = text
        if text:
            from silva.users.guest_demo import handle_guest_demo_speech
            from silva.users.manager import get_active_user

            if handle_guest_demo_speech(self, text, get_active_user()):
                return True
        if text:
            from silva.wake import is_sleep_command, is_wake_command

            if not getattr(self, "_asleep", False) and is_wake_command(text):
                log_info(f"Already awake; acknowledged wake phrase: {text[:120]}")
                self.say("I'm already awake. Listening.", interruptible=False)
                return True
            if is_sleep_command(text):
                self._pending_transition_text = text
                self._enter_sleep()
                return True
            from silva.room_speech import check_turn as check_room_turn

            room_check = check_room_turn(self, text, getattr(self, "_last_audio", None))
            if room_check.decision == "hold":
                log_info("Held reply until the room is clear")
                return True
            if room_check.decision == "reply":
                self.say(room_check.reply, interruptible=False)
                return True
        if text and handle_crash_report_speech(self, text):

            return True
        if text:
            try:
                from silva.commands.planner_handler import handle_planner_speech

                if handle_planner_speech(self, text):
                    return True
            except Exception as exc:
                log_error("Planner command failed", exc=exc)
                try:
                    from silva.crash_record import record_command_error

                    record_command_error(exc)
                except Exception:
                    pass
        if text:
            try:
                from silva.users.manager import get_active_user

                if handle_system_panel_speech(self, text, get_active_user()):
                    return True
            except Exception as exc:
                log_error("System Panel voice command failed", exc=exc)
        if text and handle_help_speech(self, text):
            return True
        if text:
            try:
                from silva.commands.live_chat_commands import handle_live_chat_speech
                from silva.users.manager import get_active_user

                if handle_live_chat_speech(self, text, get_active_user()):
                    return True
            except Exception as exc:
                log_error("Live chat speech command failed", exc=exc)
        if text and handle_pronunciation_speech(self, text):
            return True
        if text and handle_location_speech(self, text):
            return True
        if text and handle_update_speech(self, text):
            return True
        if text and dispatch_yes_no(self, text):
            return True
        if text and handle_learned_speech(self, text):
            return True
        return unwrapped(self, text, _phrase_retry=_phrase_retry)

    _handle_input._silva_is_input_wrap = True
    _handle_input.__wrapped__ = unwrapped
    assistant_cls._handle_input = _handle_input
    assistant_cls._silva_live_input_wrap = True
    assistant_cls._silva_live_input_wrap_version = 37

    if not getattr(assistant_cls, "_silva_conversation_tone_wrap", False):
        original_say_conversation = getattr(assistant_cls, "_say_conversation", None)
        if original_say_conversation is not None:

            def _say_conversation(self, text: str, user_text: str, *, category: str | None = None):
                from silva.conversation.attitude import note_user_text

                getter = getattr(self, "_user_id", None)
                user_id = getter() if callable(getter) else "guest"
                note_user_text(user_id, user_text, audio=getattr(self, "_last_audio", None))
                return original_say_conversation(self, text, user_text, category=category)

            assistant_cls._say_conversation = _say_conversation
            assistant_cls._silva_conversation_tone_wrap = True
            rebound += 1

    rebound += _patch_skip_reload_modules()
    log_info(
        f"Live runtime hooks installed ({rebound} bindings, {len(reloaded)} command modules refreshed)."
    )


def safe_install_runtime_hooks() -> None:
    try:
        install_runtime_hooks()
    except Exception as exc:
        log_error("Live runtime hooks failed", exc=exc)
