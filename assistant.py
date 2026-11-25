import os
import queue
import re
import threading
import time

from silva.config import load_config
from silva.commands.weather_feedback import (
    continue_weather_feedback_flow,
    handle_weather_feedback,
    is_weather_feedback_command,
)
from silva.commands.weather_forecast_handler import (
    continue_forecast_flow,
    handle_forecast_speech,
)
from silva.commands.weather_forecast_phrases import is_weather_forecast_command
from silva.background_runner import BackgroundRunner, wake_listen_timeout
from silva.cache import preload_router_cache, refresh_all_caches
from silva.commands.news_handler import (
    continue_news_flow,
    deny_message,
    handle_news_speech,
    offer_prompt_if_ready,
)
from silva.commands.news_monitor import can_use_news_briefing, refresh_daily_briefing
from silva.commands.measurement_phrases import is_measurement_command
from silva.commands.math import handle_math_speech
from silva.commands.math_phrases import is_math_command
from silva.commands.appointment_handler import (
    continue_appointment_flow,
    handle_appointment_speech,
)
from silva.commands.appointment_phrases import is_appointment_command
from silva.commands.audio_handler import handle_audio_speech
from silva.commands.audio_phrases import is_audio_command
from silva.commands.playback_handler import handle_playback_speech
from silva.commands.playback_phrases import is_playback_command
from silva.commands.phrase_recorder_phrases import is_phrase_recorder_command
from silva.commands.game_lookup import handle_game_lookup_speech
from silva.commands.game_lookup_phrases import is_game_lookup
from silva.commands.knowledge_phrases import is_knowledge_command
from silva.commands.knowledge_skim import handle_knowledge_speech
from silva.commands.news_phrases import is_news_command
from silva.commands.notes_handler import (
    continue_notes_flow,
    handle_notes_speech,
    handle_silence_during_notes,
)
from silva.commands.notes_phrases import is_notes_command
from silva.commands.camera_setup_handler import (
    continue_camera_setup_flow,
    handle_camera_setup_speech,
    offer_for_camera,
    start_camera_test,
)
from silva.commands.camera_setup_phrases import (
    is_camera_cancel_speech,
    is_camera_setup_command,
    parse_test_duration,
)
from silva.commands.appointments import check_due_reminders
from silva.commands.notes_store import check_due_note_reminders
from silva.commands.background_phrases import (
    is_background_command,
    is_hide_console_command,
    is_show_console_command,
)
from silva.commands.help_handler import handle_help_speech
from silva.commands.help_phrases import (
    HELP_CAPABILITIES_TEXT,
    capability_reply_for_user,
    feature_detail_reply_for_user,
    help_reply_for_user,
    is_help_request,
)
from silva.commands.registry import match_command, run_command
from silva.commands.weather import get_weather
from silva.commands.wiki_guide import (
    handle_guide_control,
    is_crafting_query,
    recall_history,
    resume_guide,
    start_guide,
)
from silva.commands.wikipedia import search_wikipedia
from silva.conversation import (
    ConversationContext,
    is_recall_request,
    load_context,
    save_context,
    try_conversation_with_context,
)
from silva.history_store import record_conversation_turn
from silva.gui.audio_record_dialog import run_audio_record_blocking
from silva.gui.phrase_record_dialog import show_phrase_record_popup
from silva.gui.display_manager import close_all, shutdown
from silva.gui.face_scan_dialog import run_face_verify
from silva.gui.permission_request_panel import run_permission_request_form
from silva.gui.profile_confirm_dialog import confirm_profile_switch
from silva.gui.bug_report_dialog import run_bug_report_dialog
from silva.gui.profile_panel import run_profile_panel
from silva.gui.security_panel import run_security_panel
from silva.interrupt import get_interrupt_min_chars, is_interrupt_command
from silva.interrupt_monitor import InterruptMonitor
from silva.logger import log_command, log_error, log_info, log_input, log_path, log_response
from silva.speech_profile import get_preferred_tts_rate, observe_input
from silva.stt import SpeechToText
from silva.tts import TextToSpeech
from silva.users.commands import try_user_command
from silva.users.access_security import (
    block_actor,
    expire_sessions,
    get_active_grant,
    is_blocked,
    log_access_attempt,
    notify_owner_message,
    update_attempt_status,
)
from silva.users.bug_reports import is_silva_bug_report
from silva.users.features import (
    FEATURE_APPOINTMENTS,
    FEATURE_AUDIO_CONTROL,
    FEATURE_BUG_REPORT,
    FEATURE_MATH,
    FEATURE_MEASUREMENT,
    FEATURE_MEDIA_PLAYBACK,
    FEATURE_NOTES,
    FEATURE_VISUAL_GUIDE,
    FEATURE_WEATHER,
    FEATURE_WIKIPEDIA,
    feature_allowed,
)
from silva.users.feature_requests import (
    feature_offer_pending,
    mark_feature_offer_made,
    record_feature_ask,
    submit_feature_request,
)
from silva.users.greetings import listening_prompt, startup_greeting, wake_greeting_for_user
from silva.users.manager import (
    get_active_user,
    get_owner,
    identify_and_set_active,
    is_owner,
    load_store,
    user_can,
)
from silva.users.profile_phrases import classify_profile_speech
from silva.users.phrase_speech import resolve_text_with_phrase_audio
from silva.users.voice_access import can_use_voice_control
from silva.users.profile_access import (
    can_open_control_panel,
    can_open_self_profile,
    owner_auto_profile_enabled,
    profile_mode_for_user,
    startup_owner_user,
)
from silva.users.system_identity import (
    apply_system_startup_access,
    bypass_security_checks,
    is_main_owner_system,
    is_remote_system,
    system_role_label,
)
from silva.users.permission_requests import (
    can_submit_request,
    requests_remaining,
    submit_access_request,
)
from silva.users.permissions import (
    PERM_APPROVE_ACTIONS,
    PERM_CHANGE_SETTINGS,
    PERM_CONVERSATION,
    PERM_ENROLL_VOICE,
    PERM_MANAGE_USERS,
    PERM_RUN_COMMANDS,
    PERM_USE_NEW_FEATURES,
    PERM_VIEW_LOGS,
)
from silva.users.tier_chat import try_tier_conversation
from silva.users.tiers import MAX_TIER, normalize_tier
from silva.users.voice_id import is_ambiguous_match, rank_voice_matches
from silva.security.protection_protocol import (
    activate_protection,
    can_enable_protection,
    classify_protection_command,
    deactivate_protection,
    is_protection_active,
    mark_session_verified,
    owner_may_reveal_private,
    protection_enabled_for_monitor_user,
    is_protection_enabled_for_user,
)
from silva.security.protection_gate import check_protection_access
from silva.gui.protection_verify_dialog import run_protection_verification
from silva.users.face_id import has_face_enrolled, requires_face_for_tier
from silva.commands.visual_guide_handler import handle_visual_guide_speech
from silva.dev.terminal_commands import start_terminal_listener
from silva.wake import is_sleep_command, is_wake_command
from silva.wake_context import evaluate_wake, wait_for_clear_moment

_YES_RE = re.compile(
    r"^(yes|yeah|yep|yup|correct|that'?s me|sure|ok(ay)?|switch|confirm)\b",
    re.I,
)
_NO_RE = re.compile(r"^(no|nope|nah|cancel|don't|do not|stop|negative)\b", re.I)
_FEATURE_REQUEST_ASK_RE = re.compile(
    r"\b(?:i wish you could|i need (?:a |the )?(?:feature|ability)|"
    r"can you add (?:a |the )?(?:feature|ability)|"
    r"please add (?:a |the )?(?:feature|ability)|"
    r"you (?:don't|do not) have (?:a |the )?(?:feature|ability)|"
    r"add (?:a |the )?feature)\b",
    re.I,
)
_ADMIN_COMMANDS = (
    "add user",
    "remove user",
    "list users",
    "show users",
    "who has access",
    "show requests",
    "pending requests",
    "list requests",
)


class SilvaAssistant:
    HELP_TEXT = HELP_CAPABILITIES_TEXT
    SLEEP_MESSAGE = "Going to sleep. Say wake up Silva to wake me."
    STOPPED_MESSAGE = "Stopped."
    _daily_routine_grace_until = 0.0
    _last_interruption_at = 0.0

    def __init__(self, voice_mode: bool = True, *, resume_sleep: bool = False):
        config = load_config()
        self._voice_mode = voice_mode
        self._resume_sleep = bool(resume_sleep)
        self._asleep = False
        self._stop_requested = False
        self._speaking = False
        self._last_interruption_at = 0.0
        self._last_input_receding = False
        self._last_audio = None
        self._pending_profile_switch: dict | None = None
        self._permission_flow: dict | None = None
        self._feature_request_flow: dict | None = None
        self._appointment_flow: dict | None = None
        self._weather_feedback_flow: dict | None = None
        self._weather_forecast_flow: dict | None = None
        self._news_flow: dict | None = None
        self._guest_demo_owner_returned = False
        self._notes_flow: dict | None = None
        self._notes_typing = False
        self._camera_setup_flow: dict | None = None
        self._camera_gui_queue: queue.Queue[str] = queue.Queue()
        self._pending_camera_command: str | None = None
        self._yes_no_owner: str | None = None
        self._todo_nag_shown: dict[str, float] = {}
        self._next_mic_retry = 0.0
        self._mic_fail_delay = 1.0
        self._mic_fail_logged = False
        self._protection_flow: dict | None = None
        self._last_protection_check = 0.0
        self._visual_guide_flow: dict | None = None
        self._last_dev_reload_applied = 0.0
        self._last_code_notice_fp = ""
        self._last_update_check = 0.0
        self._update_offer: dict | None = None
        self._update_notify_version = ""
        self._update_apply_in_progress = False
        self._sleep_reminder_index = 0
        self._sleep_idle_reminder_index = 0
        self._last_sleep_reminder_at = 0.0
        self._last_idle_sleep_reminder_at = 0.0
        self._sleep_started_at = 0.0
        self._temp_grant_actor: str | None = None
        self._main_detection_failures = 0
        self._tts = TextToSpeech(
            rate=get_preferred_tts_rate(config.get("tts_rate", 170)),
            volume=config.get("tts_volume", 0.65),
            voice_index=config.get("voice_index"),
        )
        self._tts.warmup()
        self._stt: SpeechToText | None = None
        self._startup_checks_done = False
        self._defer_owner_startup = False
        self._shutdown_done = False
        grace = float(load_config().get("weather_startup_grace_seconds", 90))
        self._weather_grace_until = time.time() + max(30.0, grace)
        self._daily_routine_grace_until = 0.0
        self._weather_post_startup_done = False
        self._conversation_context = ConversationContext()
        self._background_runner = BackgroundRunner(self._run_background_tasks)
        self._typed_command_queue: queue.Queue[str] = queue.Queue()
        self._followup_speech: list[str] = []
        self._followup_lock = threading.Lock()
        self._draining_followup = False
        self._pending_readbacks: list[tuple[str, str]] = []
        self._parallel_command_active = False
        self._parallel_queue: queue.Queue[str] = queue.Queue()
        threading.Thread(
            target=self._parallel_worker,
            name="silva-parallel-worker",
            daemon=True,
        ).start()
        active = apply_system_startup_access()
        self._ensure_main_owner_session(reset_failures=True)
        log_info(
            f"Silva started ({'voice' if voice_mode else 'typed'} mode, {system_role_label()}). "
            f"Active profile: {active.get('name', 'Guest')}. Log file: {log_path()}"
        )
        if self._should_skip_update_prompts():
            log_info("Terminal update ready — type update, scan, or revert in the terminal.")
        elif bool(load_config().get("terminal_update_button_enabled", True)):
            log_info("Terminal update ready — click Update Silva (bottom-left) or type update / scan.")
        threading.Thread(
            target=self._preload_runtime_caches,
            name="silva-cache-preload",
            daemon=True,
        ).start()

    def _preload_runtime_caches(self) -> None:
        try:
            refresh_all_caches()
        except Exception as exc:
            log_error("Cache preload failed", exc=exc)

    def _main_profile_popup_threshold(self) -> int:
        return max(1, int(load_config().get("main_system_profile_popup_after_failures", 3)))

    def _ensure_main_owner_session(self, *, reset_failures: bool = False) -> None:
        if not is_main_owner_system():
            return
        from silva.users.access_security import clear_main_system_security_history

        clear_main_system_security_history()
        owner = get_owner()
        if get_active_user().get("id") != owner["id"]:
            identify_and_set_active(owner["id"])
            log_info(f"Main system restored active profile to owner {owner['name']}.")
        if reset_failures:
            self._main_detection_failures = 0

    def _record_main_detection_failure(self, reason: str) -> None:
        if not is_main_owner_system():
            return
        self._main_detection_failures += 1
        self._ensure_main_owner_session()
        log_info(
            f"Main system detection miss ({reason}). "
            f"Failures: {self._main_detection_failures}/{self._main_profile_popup_threshold()}"
        )
        if self._main_detection_failures >= self._main_profile_popup_threshold():
            self._main_detection_failures = 0
            # Already the owner on this PC — do not freeze listening with a profile popup.
            log_info(
                "Main system voice miss streak — keeping the owner profile active "
                "and continuing to listen."
            )

    def _apply_adaptive_voice(self) -> None:
        config = load_config()
        self._tts.set_rate(get_preferred_tts_rate(config.get("tts_rate", 170)))

    def _shutdown(self) -> None:
        if self._shutdown_done:
            return
        self._shutdown_done = True
        self._stop_requested = True
        try:
            from silva.keep_alive import mark_clean_stop

            mark_clean_stop()
        except Exception:
            pass
        self._background_runner.stop()
        try:
            from silva.gui.background_mode import stop_background_mode

            stop_background_mode()
        except Exception:
            pass
        self._tts.stop()
        shutdown()

    def _close_like_exit(self) -> bool:
        """Voice goodbye — same shutdown as clicking the window close button."""
        self._stop_requested = True
        self._asleep = False
        user = get_active_user()
        name = str(user.get("name") or "")
        if name and name != "Guest":
            self.say(f"Goodbye, {name}.", interruptible=False)
        else:
            self.say("Goodbye.", interruptible=False)
        log_info("Silva stopped by user.")
        self._shutdown()
        return False

    def _ensure_stt(self) -> SpeechToText | None:
        from silva.mic_guard import note_mic_fail, note_mic_ok, should_retry_mic

        if not self._voice_mode:
            return None
        if self._stt is not None:
            return self._stt
        if not should_retry_mic(self):
            return None
        log_info("Initializing microphone...")
        if self._voice_mode:
            time.sleep(0.15)
        try:
            self._stt = SpeechToText()
            self._stt.warmup()
            self._stt.prime_microphone()
        except Exception as exc:
            self._stt = None
            note_mic_fail(self, exc)
            return None
        note_mic_ok(self)
        log_info("Microphone ready.")
        return self._stt

    def _recover_voice_after_error(self) -> None:
        """Stay in voice mode and reopen the mic after unplug/replug or a dead stream."""
        from silva.mic_guard import note_mic_fail, note_mic_ok, should_retry_mic

        if not self._voice_mode:
            return
        if not should_retry_mic(self):
            return
        try:
            from silva.media.devices import poll_audio_devices, set_capture_active

            set_capture_active(False)
            poll_audio_devices(force=True)
        except Exception:
            pass
        if self._stt is not None:
            try:
                if self._stt.recover_microphone():
                    note_mic_ok(self)
                    return
            except Exception as exc:
                log_error("Microphone recover failed", exc=exc)
        self._stt = None
        if self._ensure_stt() is None:
            note_mic_fail(self)

    def say(
        self,
        text: str,
        *,
        also_print: bool = True,
        log: bool = True,
        interruptible: bool | None = None,
        immediate: bool = False,
    ) -> bool:
        if interruptible is None:
            interruptible = len(text) >= get_interrupt_min_chars()

        if not text:
            return True

        from silva.conversation.attitude import style_reply
        from silva.conversation.crosschat_memory import remember_last_reply
        from silva.conversation.echo_guard import remember_spoken
        from silva.conversation.safety import apply_safety

        user_id = self._user_id()
        text = apply_safety(style_reply(text, user_id))
        remember_spoken(text)
        remember_last_reply(text, user_id=user_id)

        if also_print:
            print(f"Silva: {text}")
        if log:
            log_response(text)

        if not self._voice_mode:
            return True

        if self._speaking or self._parallel_command_active:
            label = self._readback_label(text)
            with self._followup_lock:
                self._pending_readbacks.append((label, text))
            log_info(f"Queued silent readback for {label}: {text[:80]}")
            return True

        if immediate:
            self._speaking = True
            try:
                spoken = self._tts.speak(text)
            finally:
                self._speaking = False
            if spoken is False:
                log_error(f"Speech failed for response: {text[:120]}")
            return True

        result = self._say_interruptible(text)
        self._discard_pending_readbacks()
        return result

    def _readback_label(self, text: str) -> str:
        lowered = text.lower()
        if "forecast" in lowered:
            return "the forecast"
        if "weather" in lowered or "fahrenheit" in lowered or "humidity" in lowered:
            return "the weather"
        if "news" in lowered or "briefing" in lowered:
            return "the news"
        return "that result"

    def _discard_pending_readbacks(self) -> None:
        with self._followup_lock:
            pending = list(self._pending_readbacks)
            self._pending_readbacks.clear()
        if pending:
            labels = " and ".join(item[0] for item in pending)
            log_info(f"Dropped silent readback (no prompt) for: {labels}")

    def _enqueue_parallel_command(self, text: str) -> None:
        log_info(f"Queued parallel command: {text[:120]}")
        self._parallel_queue.put(text)

    def _dispatch_overlay_command(self, text: str) -> None:
        from silva.interrupt_listen import dispatch_overlay_command_impl

        dispatch_overlay_command_impl(self, text)

    def _parallel_worker(self) -> None:
        while True:
            text = self._parallel_queue.get()
            if not text:
                continue
            self._parallel_command_active = True
            try:
                self._handle_input(text)
            except Exception as exc:
                log_error("Parallel command failed", exc=exc)
            finally:
                self._parallel_command_active = False

    def _speak_now(self, text: str) -> None:
        """Speak without leaving sleep mode if Silva is already asleep."""
        if not text:
            return
        if self._asleep:
            self._say_while_asleep(text)
            return
        self.say(text, interruptible=False)

    def _say_while_asleep(self, text: str) -> None:
        """Speak a sleep message fully, then stay in sleep mode."""
        if not text:
            return

        from silva.conversation.attitude import style_reply
        from silva.conversation.safety import apply_safety

        user_id = self._user_id()
        text = apply_safety(style_reply(text, user_id), user_id=user_id)
        print(f"Silva: {text}")
        log_response(text)

        if not self._voice_mode:
            return

        was_asleep = self._asleep
        self._speaking = True
        try:
            config = load_config()
            self._tts.note_mic_used()
            handoff = float(config.get("sleep_tts_post_mic_delay_seconds", 0.45))
            if handoff > 0:
                time.sleep(handoff)
            self._tts.speak(text)
            settle = float(config.get("sleep_tts_post_speak_delay_seconds", 0.35))
            if settle > 0:
                time.sleep(settle)
        finally:
            self._speaking = False
            if was_asleep:
                self._asleep = True

    def _say_interruptible(self, text: str) -> bool:
        monitor = InterruptMonitor(
            voice_mode=self._voice_mode,
            stt=self._ensure_stt(),
            show_bar=False,
            on_parallel_command=self._enqueue_parallel_command,
        )
        self._speaking = True
        monitor.start()
        try:
            completed = self._tts.speak_interruptible(text, monitor.stop_event)
        finally:
            self._speaking = False
            monitor.stop()

        if monitor.was_interrupted() or not completed:
            self._last_interruption_at = time.time()
            close_all()
            self._tts.stop()
            log_info("Silva output interrupted")
            priority = monitor.priority_command
            if priority and not is_interrupt_command(priority):
                log_info(f"Running priority command after interrupt: {priority[:80]}")
                self._handle_input(priority)
                return False
            self.say(self.STOPPED_MESSAGE, immediate=True)
            return False

        return True

    def _is_yes(self, text: str) -> bool:
        return bool(_YES_RE.match(text.strip()))

    def _is_no(self, text: str) -> bool:
        return bool(_NO_RE.match(text.strip()))

    def _requires_secure_access(self, target: dict) -> bool:
        tier = normalize_tier(target.get("tier", 1))
        return requires_face_for_tier(tier)

    def _try_secure_profile_switch(
        self,
        user_id: str,
        name: str,
        score: float,
        reason: str,
    ) -> bool:
        if bypass_security_checks():
            identify_and_set_active(user_id)
            log_info(f"Main system owner mode — switched to {name} without remote security checks.")
            return True

        actor = get_active_user()
        actor_id = actor.get("id", "guest")
        store = load_store()
        target = store["users"].get(user_id, {})
        tier = normalize_tier(target.get("tier", 1))

        if is_blocked(actor_id, user_id):
            self.say("Access to that profile is blocked on this system.", interruptible=False)
            return False

        grant = get_active_grant(actor_id, user_id)
        if grant:
            identify_and_set_active(user_id)
            self._temp_grant_actor = actor_id
            self.say(
                f"Temporary access granted for {name}. Time limit is active.",
                interruptible=False,
            )
            return True

        attempt_id = log_access_attempt(
            target_user_id=user_id,
            target_name=name,
            target_tier=tier,
            actor_id=actor_id,
            actor_name=actor.get("name", "Guest"),
            reason=reason,
            voice_score=score,
            status="pending",
        )

        if not self._requires_secure_access(target):
            identify_and_set_active(user_id)
            update_attempt_status(attempt_id, "verified", face_passed=None)
            return True

        if not has_face_enrolled(user_id):
            if tier >= MAX_TIER:
                block_actor(actor_id, user_id, reason="owner_face_not_enrolled")
                update_attempt_status(attempt_id, "denied", face_passed=False)
                self.say(
                    f"The owner profile requires face enrollment before access. "
                    f"The owner has been notified of this attempt.",
                    interruptible=False,
                )
                return False
            identify_and_set_active(user_id)
            update_attempt_status(attempt_id, "verified", face_passed=None)
            return True

        self.say(
            f"Face verification required for {name}. Look at the camera.",
            interruptible=False,
        )
        scan = run_face_verify(user_id, name)
        if scan.passed:
            identify_and_set_active(user_id)
            update_attempt_status(attempt_id, "verified", face_passed=True)
            self.say(f"Verified. Welcome, {name}.", interruptible=False)
            return True

        block_actor(actor_id, user_id, reason="face_verification_failed")
        update_attempt_status(attempt_id, "denied", face_passed=False)
        self.say(
            "Face verification failed. Access denied. The owner has been notified.",
            interruptible=False,
        )
        if tier >= 4:
            self.say(notify_owner_message(), interruptible=False)
        return False

    def _on_profile_confirm(self, result) -> None:
        pending = self._pending_profile_switch
        self._pending_profile_switch = None
        if not result.confirmed or pending is None:
            identify_and_set_active(None)
            log_info("Profile switch declined")
            return
        self._try_secure_profile_switch(
            pending["user_id"],
            pending["name"],
            pending.get("score", 0.0),
            pending.get("reason", "voice_confirm_popup"),
        )

    def _request_profile_switch(
        self,
        user_id: str,
        name: str,
        score: float,
        *,
        reason: str = "ambiguous_voice_match",
    ) -> None:
        self._pending_profile_switch = {
            "user_id": user_id,
            "name": name,
            "score": score,
            "reason": reason,
        }
        confirm_profile_switch(
            user_id,
            name,
            score,
            on_result=self._on_profile_confirm,
        )
        target = load_store()["users"].get(user_id, {})
        from silva.yes_no_prompt import KIND_PROFILE, claim as claim_yes_no

        claim_yes_no(self, KIND_PROFILE)
        if self._requires_secure_access(target):
            self.say(
                f"I detected {name}. Say yes to continue — face verification will be required. "
                "Say no to stay as guest.",
                interruptible=False,
            )
        else:
            self.say(
                f"I detected {name}. Say yes to switch to that profile, or say no to stay as guest.",
                interruptible=False,
            )

    def _check_access_sessions(self) -> None:
        if is_main_owner_system():
            self._ensure_main_owner_session()
            return
        expired = expire_sessions()
        active = get_active_user()
        for entry in expired:
            if active.get("id") == entry.get("target_user_id"):
                identify_and_set_active(None)
                self.say(
                    "Your temporary access has expired. You have been switched to guest "
                    "and blocked from that profile until the owner allows it again.",
                    interruptible=False,
                )

    def _identify_speaker(self, audio) -> dict | None:
        from silva.security.owner_reconfirm import record_voice_identity, reset_voice_identity
        from silva.users.test_accounts import is_test_session_active

        reset_voice_identity()
        if audio is None:
            return None
        if is_test_session_active():
            return get_active_user()

        from silva.users.guest_demo import (
            activate_guest_for_unknown_voice,
            end_guest_demo,
            guest_demo_active,
            guest_demo_owner_id,
        )

        if guest_demo_active():
            store = load_store()
            owner_id = guest_demo_owner_id()
            owner = store["users"].get(owner_id) if owner_id else None
            if owner and owner.get("voice_enrolled"):
                ranked = rank_voice_matches(audio, {owner_id: owner})
                if ranked and ranked[0][0] == owner_id:
                    end_guest_demo(reason="owner_voice")
                    self._guest_demo_owner_returned = True
                    return get_active_user()
            activate_guest_for_unknown_voice()
            return get_active_user()

        if self._pending_profile_switch or self._permission_flow or self._appointment_flow or self._weather_feedback_flow or self._weather_forecast_flow or self._news_flow or self._notes_flow or self._camera_setup_flow:
            return get_active_user()

        if is_main_owner_system():
            owner = get_owner()
            store = load_store()
            enrolled = {uid: u for uid, u in store["users"].items() if u.get("voice_enrolled")}
            if enrolled:
                ranked = rank_voice_matches(audio, enrolled)
                owner_id = owner["id"]
                owner_match = next((item for item in ranked if item[0] == owner_id), None)
                record_voice_identity(owner_id, ranked, bool(owner_match))
                if owner_match:
                    user_id, score = owner_match
                    identify_and_set_active(user_id)
                    self._main_detection_failures = 0
                    log_info(f"Main system voice match for {owner['name']} (score {score:.2f}).")
                    return get_active_user()
                if ranked:
                    self._record_main_detection_failure("voice_not_owner")
                else:
                    self._record_main_detection_failure("voice_no_match")
            self._ensure_main_owner_session()
            return get_active_user()

        store = load_store()
        enrolled = {uid: u for uid, u in store["users"].items() if u.get("voice_enrolled")}
        if not enrolled:
            return get_active_user()

        ranked = rank_voice_matches(audio, enrolled)
        if not ranked:
            record_voice_identity(get_owner()["id"], ranked, False)
            return get_active_user()

        owner_id = get_owner()["id"]
        record_voice_identity(owner_id, ranked, ranked[0][0] == owner_id)
        if len(ranked) == 1 or not is_ambiguous_match(ranked):
            user_id, score = ranked[0]
            target = store["users"][user_id]
            name = target.get("name", user_id)
            if self._requires_secure_access(target):
                log_info(f"Secure voice match for {name} (score {score:.2f})")
                self._try_secure_profile_switch(
                    user_id,
                    name,
                    score,
                    "high_tier_voice_match",
                )
                return get_active_user()
            user = identify_and_set_active(user_id)
            log_info(f"Voice identified as {user['name']} tier {user.get('tier')} (score {score:.2f})")
            return user

        user_id, score = ranked[0]
        name = store["users"][user_id].get("name", user_id)
        log_info(f"Ambiguous voice match for {name} (score {score:.2f}), asking for confirmation")
        self._request_profile_switch(user_id, name, score, reason="ambiguous_voice_match")
        return get_active_user()

    def _handle_profile_switch_reply(self, text: str) -> bool:
        pending = self._pending_profile_switch
        if pending is None:
            return False

        if self._is_yes(text):
            from silva.yes_no_prompt import KIND_PROFILE, clear as clear_yes_no

            pending = self._pending_profile_switch
            self._pending_profile_switch = None
            clear_yes_no(self, KIND_PROFILE)
            if pending:
                self._try_secure_profile_switch(
                    pending["user_id"],
                    pending["name"],
                    pending.get("score", 0.0),
                    pending.get("reason", "voice_confirm"),
                )
            return True

        if self._is_no(text):
            from silva.yes_no_prompt import KIND_PROFILE, clear as clear_yes_no

            if is_main_owner_system():
                self._pending_profile_switch = None
                clear_yes_no(self, KIND_PROFILE)
                self._ensure_main_owner_session()
                return True
            identify_and_set_active(None)
            self._pending_profile_switch = None
            clear_yes_no(self, KIND_PROFILE)
            self.say("Staying on guest access.", interruptible=False)
            return True

        return False

    def _deny_permission(self, permission: str, action_label: str) -> None:
        if bypass_security_checks() and is_owner(get_active_user()):
            return
        self._load_conversation_context()
        self._conversation_context.note_denial(
            "I'm sorry, I can't help with that. You don't have permission for that."
        )
        self._save_conversation_context()
        self.say(
            "I'm sorry, I can't help with that. You don't have permission for that.",
            interruptible=False,
        )
        self._permission_flow = {
            "phase": "ask_apply",
            "permission": permission,
            "action_label": action_label,
        }
        self.say(
            "Would you like to apply for permission or an admin position? Say yes or no.",
            interruptible=False,
        )

    def _deny_feature(self, user: dict, feature: str, label: str) -> None:
        user_id = user.get("id", "guest")
        msg, offer = record_feature_ask(user_id, feature)
        self._load_conversation_context()
        self._conversation_context.note_denial(msg)
        self._save_conversation_context()
        self.say(msg, interruptible=False)
        if offer:
            self._feature_request_flow = {
                "phase": "ask",
                "feature": feature,
                "label": label,
            }
            self.say(
                "Would you like me to send a feature request to the admins? "
                "Say yes to speak it, or no to type it.",
                interruptible=False,
            )

    def _maybe_offer_feature_request(self, text: str, user: dict) -> bool:
        if not _FEATURE_REQUEST_ASK_RE.search(text):
            return False
        user_id = user.get("id", "guest")
        if not feature_offer_pending(user_id):
            return False
        mark_feature_offer_made(user_id)
        self._feature_request_flow = {
            "phase": "ask",
            "feature": "general_feature_request",
            "label": text.strip()[:80],
        }
        self._speak_now(
            "I don't have that yet. Would you like me to send a feature request to the admins? "
            "Say yes to speak it, or no to type it."
        )
        return True

    def _feature_request_submitted(self, _reason: str) -> None:
        self._speak_now(
            "Your feature request was sent to the admins. "
            "Please wait for the new patch once they approve it."
        )

    def _open_feature_request_popup(self, user: dict, flow: dict) -> None:
        from silva.gui.feature_request_popup import show_feature_request_popup

        self._feature_request_flow = None
        show_feature_request_popup(
            user,
            flow.get("feature", ""),
            flow.get("label", "that feature"),
            on_submitted=self._feature_request_submitted,
        )
        self._speak_now("Open the text box to type your request.")

    def _handle_feature_request_flow(self, text: str, user: dict) -> bool:
        flow = self._feature_request_flow
        if flow is None:
            return False

        phase = flow.get("phase")
        if phase == "ask":
            if self._is_no(text):
                self._open_feature_request_popup(user, flow)
                return True
            if not self._is_yes(text):
                self._speak_now("Say yes to speak it, or no to type it.")
                return True
            self._feature_request_flow["phase"] = "await_reason"
            self._speak_now("Go ahead. Tell me what you want added.")
            return True

        if phase == "await_reason":
            if self._is_no(text):
                self._open_feature_request_popup(user, flow)
                return True
            reason = text.strip()
            if len(reason) < 5:
                self._speak_now("Please give a little more detail.")
                return True
            submit_feature_request(user, flow["feature"], reason=reason)
            self._feature_request_flow = None
            self._feature_request_submitted(reason)
            return True

        return False

    def _handle_permission_flow(self, text: str) -> bool:
        flow = self._permission_flow
        if flow is None:
            return False

        phase = flow.get("phase")
        user = get_active_user()
        user_id = user.get("id", "guest")

        if phase == "ask_apply":
            if self._is_no(text):
                self._permission_flow = None
                self.say("Okay.", interruptible=False)
                return True
            if not self._is_yes(text):
                return True

            if not can_submit_request(user_id):
                self._permission_flow = None
                self.say(
                    "I'm sorry, you ran out of requests this week. "
                    "Please wait until it refreshes next week.",
                    interruptible=False,
                )
                return True

            remaining = requests_remaining(user_id)
            self._permission_flow["phase"] = "await_reason"
            self.say(
                f"Tell me why you need this access. You have {remaining} request"
                f"{'s' if remaining != 1 else ''} left this week.",
                interruptible=False,
            )
            return True

        if phase == "await_reason":
            reason = text.strip()
            if len(reason) < 8:
                self.say("Please give a little more detail about why you need this.", interruptible=False)
                return True

            form = run_permission_request_form(flow["action_label"], prefill=reason)
            if not form.submitted:
                self._permission_flow = None
                self.say("Request cancelled.", interruptible=False)
                return True

            submit_access_request(
                user,
                reason=form.reason,
                requested_action=flow["action_label"],
                permission=flow["permission"],
            )
            self._permission_flow = None
            self.say(
                "Your request was sent to the owner for review.",
                interruptible=False,
            )
            return True

        return False

    def _handle_appointment_flow(self, text: str, user: dict) -> bool:
        flow = self._appointment_flow
        if flow is None:
            return False

        user_id = user.get("id", "guest")
        msg, next_flow = continue_appointment_flow(user_id, text, flow)
        self._appointment_flow = next_flow
        self.say(msg, interruptible=False)
        return True

    def _check_appointment_reminders(self) -> None:
        if self._scheduled_alerts_paused():
            return
        user = get_active_user()
        if not feature_allowed(user, FEATURE_APPOINTMENTS):
            return
        for message in check_due_reminders(user.get("id", "guest")):
            self.say(message, interruptible=False)

    def _check_note_reminders(self) -> None:
        if self._scheduled_alerts_paused():
            return
        user = get_active_user()
        if not feature_allowed(user, FEATURE_NOTES):
            return
        for message in check_due_note_reminders(user.get("id", "guest")):
            self._speak_now(message)

    def _check_todo_nags(self) -> None:
        from silva.commands.todo_nags import announce_todo_nags

        announce_todo_nags(self)

    def _queue_say(self, text: str) -> None:
        if not text or not str(text).strip():
            return
        with self._followup_lock:
            self._followup_speech.append(str(text).strip())

    def _drain_followup_speech(self) -> None:
        with self._followup_lock:
            pending = list(self._followup_speech)
            self._followup_speech.clear()
        for message in pending:
            self.say(message, interruptible=True)

    def _weather_startup_grace_active(self) -> bool:
        return time.time() < self._weather_grace_until

    def _daily_routine_grace_active(self) -> bool:
        try:
            grace_until = float(getattr(self, "_daily_routine_grace_until", 0.0))
        except (TypeError, ValueError):
            return False
        return time.time() < grace_until

    def _post_startup_weather_check(self) -> None:
        if self._weather_post_startup_done:
            return
        self._weather_post_startup_done = True
        self._weather_grace_until = 0.0
        log_info("Startup grace finished — running deferred weather checks.")
        try:
            if self._asleep:
                return
            self._silent_weather_refresh(force=True)
            self._check_scheduled_weather_display()
        except Exception as exc:
            log_error("Deferred weather check failed", exc=exc)

    def _silent_weather_refresh(self, *, force: bool = False) -> None:
        if self._scheduled_alerts_paused() and not force:
            return
        if self._weather_startup_grace_active() and not force:
            return
        if self._asleep:
            return
        user = get_active_user()
        if not feature_allowed(user, FEATURE_WEATHER):
            return
        from silva.commands.weather_monitor import silent_weather_refresh

        silent_weather_refresh(force=force)

    def _scheduled_alerts_paused(self) -> bool:
        """Timed popups and nags stay off while a live update is applying."""
        return bool(self._update_apply_in_progress)

    def _is_heavy_task_active(self) -> bool:
        if self._scheduled_alerts_paused():
            return True
        if self._speaking:
            return True
        if any(
            flow is not None
            for flow in (
                self._pending_profile_switch,
                self._permission_flow,
                self._feature_request_flow,
                self._appointment_flow,
                self._weather_feedback_flow,
                self._weather_forecast_flow,
                self._news_flow,
                self._notes_flow,
                self._camera_setup_flow,
            )
        ):
            return True
        from silva.commands.news_monitor import news_refresh_in_flight

        if news_refresh_in_flight():
            return True
        return False

    def _check_scheduled_weather_display(self) -> None:
        if self._scheduled_alerts_paused():
            return
        if self._weather_startup_grace_active() or self._daily_routine_grace_active():
            return
        if self._asleep:
            return
        user = get_active_user()
        if not feature_allowed(user, FEATURE_WEATHER):
            return
        from silva.commands.weather_schedule import check_scheduled_weather_display

        check_scheduled_weather_display(
            user_id=user.get("id", "guest"),
            is_busy=self._is_heavy_task_active,
        )

    def _check_weather_alerts(self) -> None:
        if self._scheduled_alerts_paused():
            return
        user = get_active_user()
        if not feature_allowed(user, FEATURE_WEATHER):
            return
        from silva.commands.weather_alerts import check_weather_alerts

        check_weather_alerts(asleep=self._asleep)

    def _check_live_dev_update(self) -> None:
        from silva.dev.live_update import apply_pending_update, reload_flag_pending

        if getattr(self, "_update_apply_in_progress", False):
            return
        if not reload_flag_pending(self._last_dev_reload_applied):
            return

        ok, message = apply_pending_update()
        self._last_dev_reload_applied = time.time()
        if ok:
            log_info(f"Dev live update applied: {message}")
            if not self._asleep and not self._speaking:
                self._notify_update_complete(message)
        else:
            log_info(f"Dev live update skipped or failed: {message}")

    def _should_skip_update_prompts(self) -> bool:
        from silva.dev.auto_update import skips_desktop_update_ui

        return skips_desktop_update_ui()

    def _log_terminal_update_status_for_owner(self) -> None:
        from silva.dev.panel_update import format_scan_report, scan_panel_changes

        scan = scan_panel_changes()
        if scan.has_changes:
            log_info(format_scan_report(scan))
        else:
            log_info("Owner terminal update: no manual changes detected since the last update.")

    def _maybe_check_for_updates(self, *, force: bool = False, silent: bool = False) -> None:
        from silva.dev.auto_update import (
            auto_update_enabled,
            run_update_check_async,
            update_check_interval_seconds,
        )

        if not auto_update_enabled():
            return
        if self._should_skip_update_prompts():
            from silva.dev.panel_update import scan_panel_changes
            from silva.dev.update_scanner import compute_code_fingerprint

            scan = scan_panel_changes()
            fingerprint = compute_code_fingerprint()
            if scan.has_changes and fingerprint != self._last_code_notice_fp:
                self._last_code_notice_fp = fingerprint
                self._log_terminal_update_status_for_owner()
            return
        now = time.time()
        if not force and now - self._last_update_check < update_check_interval_seconds():
            return
        self._last_update_check = now
        if silent:
            run_update_check_async(on_result=self._handle_silent_update_scan)
            return
        run_update_check_async(on_result=self._handle_update_scan_result)

    def _handle_silent_update_scan(self, scan) -> None:
        from silva.dev.update_check import check_update_status
        from silva.dev.update_scanner import version_newer

        status = check_update_status()
        if not status.needs_update:
            log_info("Update scan: no file changes; already on the newest update.")
            return
        if not scan.available:
            log_info(f"Update scan: Silva is up to date ({scan.installed_version}).")
            return
        if not version_newer(scan.version, scan.installed_version) and not scan.pending_reload:
            log_info("Update scan: no newer version detected.")
            return
        log_info(f"Update scan: newer version {scan.version} available (installed {scan.installed_version}).")
        if self._should_skip_update_prompts():
            return
        self._handle_update_scan_result(scan)

    def _handle_update_scan_result(self, scan) -> None:
        from silva.dev.auto_update import (
            spoken_change_summary,
            notify_users_update_available,
            should_notify_update_available,
            should_show_desktop_update_popup,
            should_speak_update_offer,
        )
        from silva.dev.update_check import check_update_status
        from silva.dev.update_scanner import version_newer

        status = check_update_status()
        if not status.needs_update:
            log_info("Update scan: no file changes; already on the newest update.")
            return
        scan.version = status.available_version or scan.version
        scan.changes = list(status.changes or scan.changes)
        if not scan.available:
            return
        if not version_newer(scan.version, scan.installed_version) and not scan.pending_reload:
            return
        if self._should_skip_update_prompts():
            return
        if self._update_offer and self._update_offer.get("version") == scan.version:
            return
        if scan.version == self._update_notify_version and self._update_offer is None:
            return
        if self._update_apply_in_progress:
            return

        user = get_active_user()
        self._update_offer = {
            "version": scan.version,
            "changes": list(scan.changes),
            "scan": scan,
        }
        self._update_notify_version = scan.version

        if should_notify_update_available(user):
            notify_users_update_available(scan)

        if should_show_desktop_update_popup(user):
            from silva.gui.update_popup import show_update_available_popup

            show_update_available_popup(scan, on_choice=self._on_update_popup_choice)

        if should_speak_update_offer(user) and not self._asleep and not self._speaking:
            self.say(spoken_change_summary(scan), interruptible=True)

    def _on_update_popup_choice(self, accepted: bool) -> None:
        if accepted:
            self._start_update_apply(publish=False)
        else:
            log_info("Silva update postponed by user.")

    def _start_update_apply(self, *, publish: bool, features: list[str] | None = None) -> None:
        from silva.commands.update_handler import apply_live_now
        from silva.dev.auto_update import apply_update_async
        from silva.dev.panel_update import scan_panel_changes
        from silva.dev.update_check import check_update_status
        from silva.dev.update_permissions import can_apply_update, update_permission_message

        if self._update_apply_in_progress:
            return
        if not can_apply_update(get_active_user()):
            self.say(update_permission_message(), interruptible=False)
            return
        status = check_update_status()
        if not status.needs_update and not publish:
            version = status.available_version or status.current_version
            self.say(f"Already on the newest update, {version}. No new files were added.", interruptible=False)
            return
        panel = scan_panel_changes()
        if panel.has_changes and not publish:
            apply_live_now(self)
            return
        offer = self._update_offer or {}
        scan = offer.get("scan")
        if scan is None:
            from silva.dev.update_scanner import scan_for_updates

            scan = scan_for_updates()
            if not scan.available and not publish:
                self.say("Silva is already up to date.", interruptible=False)
                return

        self._update_apply_in_progress = True
        self._speak_now("Updating Silva now. This only takes a moment.")

        def on_done(ok: bool, message: str, applied_scan) -> None:
            self._update_apply_in_progress = False
            if ok:
                self._update_offer = None
                if self._asleep:
                    self._speak_now("The update is live.")
                else:
                    self._notify_update_complete(message, applied_scan)
            else:
                self._speak_now(message)

        apply_update_async(
            scan,
            skip_tests=not publish,
            publish=publish,
            features=features,
            on_done=on_done,
        )

    def _notify_update_complete(self, message: str, applied_scan=None) -> None:
        from silva.dev.auto_update import (
            notify_users_update_complete,
            should_notify_update_available,
            should_show_desktop_update_popup,
            should_speak_update_offer,
        )
        from silva.gui.update_popup import show_update_complete_popup

        log_info(message)
        if self._should_skip_update_prompts():
            self._print_terminal_message(message)
            return

        version = ""
        changes: list[str] = []
        if applied_scan is not None:
            version = getattr(applied_scan, "version", "") or ""
            changes = list(getattr(applied_scan, "changes", []) or [])
        user = get_active_user()
        if version and should_notify_update_available(user):
            notify_users_update_complete(version, changes)

        if should_show_desktop_update_popup(user):
            show_update_complete_popup(
                message,
                on_close=lambda: self._speak_update_complete(message),
            )
        elif should_speak_update_offer(user) and not self._asleep:
            self._speak_update_complete(message)

    def _speak_update_complete(self, message: str) -> None:
        if self._asleep:
            return
        self.say(message, interruptible=False)

    def _handle_update_speech(self, text: str) -> bool:
        from silva.commands.update_handler import handle_update_speech

        return handle_update_speech(self, text)

    def _check_news_briefing(self) -> None:
        if self._asleep or self._daily_routine_grace_active():
            return
        from silva.yes_no_prompt import check_news_briefing

        check_news_briefing(self)

    def _handle_news_flow(self, text: str) -> bool:
        from silva.yes_no_prompt import handle_news_flow

        return handle_news_flow(self, text)

    def _handle_game_lookup_command(self, text: str, user: dict) -> bool:
        if not is_game_lookup(text):
            return False
        if not feature_allowed(user, FEATURE_WIKIPEDIA):
            self._deny_feature(user, FEATURE_WIKIPEDIA, "game lookup")
            return True
        if not user_can(user, PERM_CONVERSATION):
            return True
        user_id = user.get("id", "guest")
        msg = handle_game_lookup_speech(text, user_id=user_id)
        if msg is None:
            return False
        self.say(msg, interruptible=True)
        return True

    def _handle_knowledge_command(self, text: str, user: dict) -> bool:
        if not is_knowledge_command(text):
            return False
        if not feature_allowed(user, FEATURE_WIKIPEDIA):
            self._deny_feature(user, FEATURE_WIKIPEDIA, "lookups")
            return True
        if not user_can(user, PERM_CONVERSATION):
            return True
        user_id = user.get("id", "guest")
        msg = handle_knowledge_speech(user_id, text)
        if not msg:
            return False
        self.say(msg, interruptible=True)
        return True

    def _handle_system_panel_command(self, text: str, user: dict) -> bool:
        from silva.commands.system_panel_commands import handle_system_panel_speech

        return handle_system_panel_speech(self, text, user)

    def _handle_reference_image_command(self, text: str) -> bool:
        from silva.media.reference_image_handler import handle_reference_image_speech

        return handle_reference_image_speech(self, text)

    def _handle_image_generation_command(self, text: str) -> bool:
        from silva.media.image_generator_handler import handle_image_generation_speech

        return handle_image_generation_speech(self, text)

    def _handle_visual_guide_command(self, text: str, user: dict) -> bool:
        from silva.commands.visual_guide_handler import is_visual_guide_enabled

        if not is_visual_guide_enabled():
            return False
        if not feature_allowed(user, FEATURE_VISUAL_GUIDE):
            return False
        if self._visual_guide_flow and self._visual_guide_flow.get("phase") == "step_active":
            msg, flow = handle_visual_guide_speech(text)
            if msg is not None:
                self._visual_guide_flow = flow
                self.say(msg, interruptible=False)
                return True
        msg, flow = handle_visual_guide_speech(text)
        if msg is None:
            return False
        self._visual_guide_flow = flow
        self.say(msg, interruptible=False)
        return True

    def _handle_news_command(self, text: str, user: dict) -> bool:
        if not is_news_command(text):
            return False

        if not can_use_news_briefing(user):
            self.say(deny_message(), interruptible=False)
            return True

        if not user_can(user, PERM_CONVERSATION):
            return True

        msg, flow = handle_news_speech(text, user)
        if msg is None:
            return False

        self._news_flow = flow
        self.say(msg, interruptible=True)
        return True

    def _handle_appointment_command(self, text: str, user: dict) -> bool:
        if not is_appointment_command(text):
            return False

        if not feature_allowed(user, FEATURE_APPOINTMENTS):
            self._deny_feature(user, FEATURE_APPOINTMENTS, "appointments")
            return True

        if not user_can(user, PERM_CONVERSATION):
            return True

        user_id = user.get("id", "guest")
        msg, flow = handle_appointment_speech(user_id, text)
        if msg is None:
            return False

        self._appointment_flow = flow
        self.say(msg, interruptible=False)
        return True

    def _apply_notes_gui_flow(self, user_id: str, msg: str | None, flow: dict | None) -> bool:
        if flow is None:
            return False
        phase = flow.get("phase")
        if phase == "open_type":
            from silva.gui.notes_type_popup import show_notes_type_popup

            kind = "todo" if flow.get("kind") == "todo" else "note"

            def on_saved(body: str, saved_kind: str = kind) -> None:
                self._queue_say("Saved.")

            def on_closed() -> None:
                self._notes_typing = False

            self._notes_typing = True
            show_notes_type_popup(
                user_id,
                kind,
                on_saved=on_saved,
                on_closed=on_closed,
                replace_id=str(flow.get("replace_id") or "") or None,
            )
            self._notes_flow = None
            if msg:
                self._speak_now(msg)
            return True
        if phase == "open_todo":
            from silva.gui.todo_popup import show_todo_popup

            show_todo_popup(user_id)
            self._notes_flow = None
            if msg:
                self._speak_now(msg)
            return True
        if phase == "close_todo":
            from silva.gui.todo_popup import close_todo_popup

            close_todo_popup()
            self._notes_flow = None
            if msg:
                self._speak_now(msg)
            return True
        return False

    def _handle_notes_flow(self, text: str, user: dict) -> bool:
        flow = self._notes_flow
        if flow is None:
            return False

        from silva.commands.intent import is_action_command
        from silva.commands.math_phrases import is_math_command

        keeping_todo = str(flow.get("kind") or "") in {
            "todo",
            "daily_todo",
            "confirm_todo",
            "daily_time",
            "note",
            "pick_todo",
            "pick_reminder",
        }
        if (
            is_action_command(text)
            and not is_notes_command(text)
            and not (keeping_todo and is_math_command(text))
        ):
            self._notes_flow = None
            return False

        user_id = user.get("id", "guest")
        msg, next_flow = continue_notes_flow(user_id, text, flow)
        if self._apply_notes_gui_flow(user_id, msg, next_flow):
            return True
        self._notes_flow = next_flow
        if msg:
            self._speak_now(msg)
        return True

    def _handle_background_command(self, text: str) -> bool:
        from silva.gui.background_mode import hide_console, minimize_console, show_console_front

        if is_show_console_command(text):
            show_console_front()
            self.say("Here's the command window. Close it to stop me, or say hide the console to tuck it away.", interruptible=False)
            return True
        if is_hide_console_command(text):
            hide_console()
            self.say(
                "I'll stay in the background. Talk anytime, or press Control Shift S to type.",
                interruptible=False,
            )
            return True
        minimize_console()
        self.say("I'll stay in the background.", interruptible=False)
        return True

    def _handle_notes_command(self, text: str, user: dict) -> bool:
        if not is_notes_command(text):
            return False
        if not feature_allowed(user, FEATURE_NOTES):
            self._deny_feature(user, FEATURE_NOTES, "notes and to-do list")
            return True
        if not user_can(user, PERM_CONVERSATION):
            return True
        user_id = user.get("id", "guest")
        msg, flow = handle_notes_speech(user_id, text)
        if msg is None and flow is None:
            return False
        if self._apply_notes_gui_flow(user_id, msg, flow):
            return True
        self._notes_flow = flow
        if msg:
            self._speak_now(msg)
        return True

    def _handle_notes_silence(self) -> None:
        msg, flow = handle_silence_during_notes(self._notes_flow)
        if flow is None and msg is None:
            return
        user = get_active_user()
        user_id = user.get("id", "guest")
        if self._apply_notes_gui_flow(user_id, msg, flow):
            return
        self._notes_flow = flow
        if msg:
            self._speak_now(msg)

    def _apply_camera_setup_flow(self, msg: str | None, flow: dict | None) -> bool:
        if flow is None:
            self._camera_setup_flow = None
            if msg:
                self.say(msg, interruptible=False)
            return bool(msg)
        phase = flow.get("phase")
        name = str(flow.get("name") or "this camera")
        combo = bool(flow.get("is_combo"))
        if phase == "blocked":
            from silva.gui.perf_notice_popup import show_perf_notice_popup

            self._camera_setup_flow = None
            if msg:
                show_perf_notice_popup(msg)
                self.say(msg, interruptible=False)
            return True
        if phase == "open_warning":
            from silva.gui.camera_warning_popup import show_camera_warning_popup

            show_camera_warning_popup(name, on_choice=self._enqueue_camera_gui_choice)
            self._camera_setup_flow = {"phase": "await_choice", "name": name, "is_combo": combo}
            if msg:
                self.say(msg, interruptible=False)
            return True
        if phase == "open_preview":
            from silva.gui.camera_preview_popup import show_camera_preview_popup
            from silva.gui.camera_warning_popup import close_camera_warning_popup
            from silva.users.camera_access import FEATURE_CAMERA_TEST, is_camera_granted
            from silva.users.manager import get_active_user

            user = get_active_user()
            if not is_camera_granted(str(user.get("id") or "guest"), FEATURE_CAMERA_TEST):
                self._pending_camera_command = "__camera_test__"
                self._camera_setup_flow = dict(flow)
                self._ask_camera_access(FEATURE_CAMERA_TEST)
                return True

            close_camera_warning_popup()
            seconds = int(flow.get("seconds") or 30)
            show_camera_preview_popup(
                name,
                seconds=seconds,
                combo=combo,
                on_finished=self._enqueue_camera_gui_choice,
            )
            self._camera_setup_flow = {
                "phase": "preview",
                "name": name,
                "is_combo": combo,
                "seconds": seconds,
            }
            if msg:
                self.say(msg, interruptible=False)
            return True
        self._camera_setup_flow = flow
        if msg:
            self.say(msg, interruptible=False)
        return True

    def _ask_camera_access(self, feature: str) -> None:
        from silva.users.camera_access import active_user_id, request_camera_access

        self.say("Check the popup to allow camera access for that.", interruptible=False)
        request_camera_access(active_user_id(), feature, on_result=self._enqueue_camera_access)

    def _enqueue_camera_access(self, allowed: bool) -> None:
        self._camera_gui_queue.put("camera_yes" if allowed else "camera_no")

    def _enqueue_camera_gui_choice(self, choice: str) -> None:
        if choice:
            self._camera_gui_queue.put(str(choice))

    def _drain_camera_gui_queue(self) -> None:
        while True:
            try:
                choice = self._camera_gui_queue.get_nowait()
            except queue.Empty:
                break
            if choice == "camera_no":
                pending = self._pending_camera_command
                self._pending_camera_command = None
                if pending == "__camera_test__":
                    self._camera_setup_flow = None
                self._queue_say("Okay, I won't use the camera for that.")
                continue
            if choice == "camera_yes":
                pending = self._pending_camera_command
                self._pending_camera_command = None
                if pending == "__camera_test__" and self._camera_setup_flow:
                    flow = dict(self._camera_setup_flow)
                    flow["phase"] = "open_preview"
                    self._apply_camera_setup_flow("", flow)
                elif pending:
                    self._handle_input(pending)
                continue
            if choice in {"skip", "skipped"}:
                from silva.gui.camera_preview_popup import close_camera_preview_popup
                from silva.gui.camera_warning_popup import close_camera_warning_popup
                from silva.commands.camera_setup_handler import SKIP_TEST_MESSAGE
                from silva.yes_no_prompt import KIND_CAMERA_TEST, clear as clear_yes_no

                close_camera_warning_popup()
                close_camera_preview_popup()
                self._camera_setup_flow = None
                clear_yes_no(self, KIND_CAMERA_TEST)
                self._queue_say(SKIP_TEST_MESSAGE)
                continue
            if choice == "saved":
                self._camera_setup_flow = None
                self._queue_say("Saved. I'll use that camera.")
                continue
            if choice == "error":
                self._camera_setup_flow = None
                self._queue_say("I couldn't open that camera for a test.")
                continue
            if choice == "too_heavy":
                from silva.gui.perf_notice_popup import show_perf_notice_popup
                from silva.media.perf_guard import CAMERA_LAG_REFUSAL

                self._camera_setup_flow = None
                show_perf_notice_popup(CAMERA_LAG_REFUSAL)
                self._queue_say(CAMERA_LAG_REFUSAL)
                continue
            if choice in {"30", "60"} and self._camera_setup_flow:
                seconds = 30 if choice == "30" else 60
                offer = {
                    "name": str(self._camera_setup_flow.get("name") or "this camera"),
                    "is_combo": bool(self._camera_setup_flow.get("is_combo")),
                }
                msg, flow = start_camera_test(offer, seconds)
                self._apply_camera_setup_flow(msg, flow)

    def _offer_plugged_in_camera(self) -> None:
        from silva.yes_no_prompt import offer_plugged_in_camera

        offer_plugged_in_camera(self)

    def _handle_camera_setup_flow(self, text: str) -> bool:
        from silva.yes_no_prompt import handle_camera_setup_flow

        return handle_camera_setup_flow(self, text)

    def _handle_camera_access_command(self, text: str) -> bool:
        from silva.users.camera_access import FEATURE_PROFILE_FACE, is_camera_access_phrase

        if not is_camera_access_phrase(text):
            return False
        self._pending_camera_command = None
        self._ask_camera_access(FEATURE_PROFILE_FACE)
        return True

    def _handle_camera_setup_command(self, text: str) -> bool:
        from silva.yes_no_prompt import handle_camera_setup_command

        return handle_camera_setup_command(self, text)

    def _handle_weather_feedback_flow(self, text: str, user: dict) -> bool:
        flow = self._weather_feedback_flow
        if flow is None:
            return False

        user_id = user.get("id", "guest")
        msg, next_flow = continue_weather_feedback_flow(user_id, text, flow)
        self._weather_feedback_flow = next_flow
        self.say(msg, interruptible=False)
        return True

    def _handle_weather_feedback_command(self, text: str, user: dict) -> bool:
        if not is_weather_feedback_command(text):
            return False

        if not feature_allowed(user, FEATURE_WEATHER):
            self._deny_feature(user, FEATURE_WEATHER, "weather")
            return True

        if not user_can(user, PERM_CONVERSATION):
            return True

        user_id = user.get("id", "guest")
        msg, flow = handle_weather_feedback(user_id, text)
        if msg is None:
            return False

        self._weather_feedback_flow = flow
        self.say(msg, interruptible=False)
        return True

    def _handle_weather_forecast_flow(self, text: str) -> bool:
        flow = self._weather_forecast_flow
        if flow is None:
            return False

        msg, next_flow = continue_forecast_flow(
            text,
            flow,
            is_yes=self._is_yes(text),
            is_no=self._is_no(text),
        )
        self._weather_forecast_flow = next_flow
        self.say(msg, interruptible=False)
        return True

    def _handle_weather_forecast_command(self, text: str, user: dict) -> bool:
        if not is_weather_forecast_command(text):
            return False

        if not feature_allowed(user, FEATURE_WEATHER):
            self._deny_feature(user, FEATURE_WEATHER, "weather")
            return True

        if not user_can(user, PERM_CONVERSATION):
            return True

        msg, flow = handle_forecast_speech(text)
        self._weather_forecast_flow = flow
        self.say(msg, interruptible=False)
        return True

    def _handle_math_command(self, text: str, user: dict) -> bool:
        if not is_math_command(text):
            return False

        if not feature_allowed(user, FEATURE_MATH):
            self._deny_feature(user, FEATURE_MATH, "math")
            return True

        if not user_can(user, PERM_CONVERSATION):
            return True

        try:
            msg = handle_math_speech(user.get("id", "guest"), text)
        except ValueError as exc:
            self.say(str(exc), interruptible=False)
            return True

        if msg is None:
            return False

        self.say(msg, interruptible=False)
        return True

    def _handle_measurement_command(self, text: str, user: dict) -> bool:
        if not is_measurement_command(text):
            return False

        if not feature_allowed(user, FEATURE_MEASUREMENT):
            self._deny_feature(user, FEATURE_MEASUREMENT, "measurement")
            return True

        if not user_can(user, PERM_CONVERSATION):
            return True

        from silva.commands.measurement_phrases import match_measurement_speech
        from silva.users.camera_access import FEATURE_MEASUREMENT, is_camera_granted

        speech = match_measurement_speech(text)
        if (
            speech is not None
            and speech.action == "measure"
            and speech.source == "camera"
            and not is_camera_granted(str(user.get("id") or "guest"), FEATURE_MEASUREMENT)
        ):
            self._pending_camera_command = text
            self._ask_camera_access(FEATURE_MEASUREMENT)
            return True

        msg, _flow = handle_measurement_speech(user.get("id", "guest"), text)
        if msg is None:
            return False

        self.say(msg, interruptible=False)
        return True

    def _handle_audio_command(self, text: str, user: dict) -> bool:
        if not is_audio_command(text):
            return False

        if not feature_allowed(user, FEATURE_AUDIO_CONTROL):
            self._deny_feature(user, FEATURE_AUDIO_CONTROL, "app audio control")
            return True

        if not user_can(user, PERM_CONVERSATION):
            return True

        msg = handle_audio_speech(user.get("id", "guest"), text)
        if msg is None:
            return False

        self.say(msg, interruptible=False)
        return True

    def _handle_playback_command(self, text: str, user: dict) -> bool:
        if not is_playback_command(text):
            return False

        if not feature_allowed(user, FEATURE_MEDIA_PLAYBACK):
            self._deny_feature(user, FEATURE_MEDIA_PLAYBACK, "video playback")
            return True

        if not user_can(user, PERM_CONVERSATION):
            return True

        msg = handle_playback_speech(user.get("id", "guest"), text)
        if msg is None:
            return False

        self.say(msg, interruptible=False)
        return True

    def _handle_phrase_recorder_command(self, text: str, user: dict) -> bool:
        if not is_phrase_recorder_command(text):
            return False

        if user.get("id") in {None, "", "guest"}:
            self.say(
                "Open your profile first, or say who am I so I know which profile to save phrase recordings to.",
                interruptible=False,
            )
            return True

        self.say(
            "Opening the phrase recorder. Choose what the phrase means, tap the white button to record, "
            "tap again when finished to save. You can save multiple recordings for the same phrase.",
            interruptible=False,
        )
        if not show_phrase_record_popup(user):
            self.say("I could not open the phrase recorder. Please try again.", interruptible=False)
        return True

    def _user_id(self) -> str:
        return get_active_user().get("id", "guest")

    def _note_transition_tone(self, text: str, audio=None) -> None:
        if not text or getattr(self, "_silva_last_tone_text", "") == text:
            return
        from silva.conversation.attitude import note_user_text

        note_user_text(
            self._user_id(),
            text,
            audio=audio if audio is not None else getattr(self, "_last_audio", None),
        )
        self._silva_last_tone_text = text

    def _load_conversation_context(self) -> None:
        self._conversation_context = load_context(self._user_id())

    def _save_conversation_context(self) -> None:
        save_context(self._user_id(), self._conversation_context)

    def _say_conversation(self, text: str, user_text: str, *, category: str | None = None) -> None:
        self.say(text, interruptible=False)
        user_id = self._user_id()
        from silva.conversation.crosschat_memory import remember_reply_context

        remember_reply_context(user_text, text, user_id=user_id)
        cat = category or self._conversation_context.category

        def _record() -> None:
            record_conversation_turn(
                user_id,
                user_text=user_text,
                ai_text=text,
                category=cat,
            )

        threading.Thread(target=_record, name="silva-convo-log", daemon=True).start()

    def _handle_wiki_and_recall(self, text: str, user: dict) -> bool:
        normalized = text.strip().lower()
        user_id = user.get("id", "guest")

        recall_kind = is_recall_request(text)
        if recall_kind:
            self.say(recall_history(user_id, kind=recall_kind))
            return True

        if normalized in {"resume guide", "continue my guide", "pick up where i left off"}:
            self.say(resume_guide(user_id))
            return True

        if normalized.startswith("resume guide for ") or normalized.startswith("continue guide for "):
            hint = normalized.split(" for ", 1)[-1].strip()
            self.say(resume_guide(user_id, hint))
            return True

        guide_result = handle_guide_control(user_id, text)
        if guide_result is not None:
            self.say(guide_result, interruptible=False)
            return True

        return False

    def _run_wikipedia(self, text: str, query: str, user: dict) -> bool:
        if not feature_allowed(user, FEATURE_WIKIPEDIA):
            self.say("Wikipedia is not enabled for your profile.", interruptible=False)
            return True

        user_id = user.get("id", "guest")
        log_command("wikipedia", query=query)
        try:
            if is_crafting_query(text):
                result = start_guide(user_id, query)
            else:
                result = search_wikipedia(query, user_id=user_id)
            self.say(result, interruptible=True)
        except Exception as exc:
            log_error(f"Wikipedia command failed", exc=exc)
            self.say(f"Sorry, something went wrong: {exc}")
        return True

    def _is_blocked_admin_command(self, normalized: str, user: dict) -> bool:
        if user_can(user, PERM_MANAGE_USERS) or can_use_voice_control(user, "users"):
            return False
        return any(
            normalized == cmd or normalized.startswith(cmd + " ")
            for cmd in _ADMIN_COMMANDS
        )

    def _confirm_admin_action(self, action: str) -> bool:
        from silva.security.owner_reconfirm import require_owner_confirmation

        return require_owner_confirmation(self, action=action)

    def _listen_once(self) -> str | None:
        self._last_audio = None
        self._last_input_receding = False
        if self._voice_mode:
            stt = self._ensure_stt()
            if stt is None:
                self._recover_voice_after_error()
                time.sleep(0.5)
                return None
            awaiting_news = bool(
                self._news_flow and self._news_flow.get("phase") == "await_show_choice"
            )
            phrase_limit = 8.0 if awaiting_news else None
            box: dict = {}

            def _listen_job() -> None:
                try:
                    box["result"] = stt.listen_with_audio(
                        skip_continuation=awaiting_news,
                        phrase_limit=phrase_limit,
                    )
                except Exception as exc:
                    box["error"] = exc

            worker = threading.Thread(target=_listen_job, name="silva-listen", daemon=True)
            worker.start()
            worker.join(stt.listen_deadline(phrase_limit=phrase_limit))
            if worker.is_alive():
                log_error("Microphone listen hung; rebuilding the mic so Silva can hear again")
                self._stt = None
                time.sleep(0.3)
                self._recover_voice_after_error()
                return None
            if "error" in box:
                log_error("Voice input failed", exc=box["error"])
                self._recover_voice_after_error()
                time.sleep(0.4)
                return None
            result = box.get("result") or (None, None)
            text, audio = result
            if getattr(stt, "last_device_error", False):
                self._recover_voice_after_error()
                time.sleep(0.4)
                return None
            self._last_audio = audio
            if audio is not None:
                from silva.stt_speech_guard import detect_receding_audio

                self._last_input_receding = bool(
                    getattr(stt, "last_receding_audio", False)
                ) or detect_receding_audio(audio)
            if text:
                print(f"You: {text}")
                log_input(text, mode="voice")
                self._tts.note_mic_used()
                if audio is not None and not self._asleep:
                    self._identify_speaker(audio)
            return text

        text = input("You: ").strip()
        if text:
            log_input(text, mode="typed")
        return text or None

    def _run_background_tasks(self) -> None:
        """Silent maintenance tasks safe to run while another app has focus."""
        try:
            from silva.keep_alive import beat

            beat()
        except Exception:
            pass
        if not self._asleep:
            try:
                from silva.media.devices import poll_audio_devices

                poll_audio_devices()
                from silva.media.camera import poll_camera_devices

                poll_camera_devices()
            except Exception:
                pass
        self._check_live_dev_update()
        self._monitor_screen_activity()
        if self._scheduled_alerts_paused():
            return
        if not self._should_skip_update_prompts():
            self._maybe_check_for_updates(silent=True)
        if not self._weather_startup_grace_active():
            self._check_weather_alerts()
        self._check_sleep_mode_alerts()
        if self._asleep:
            return
        if not self._weather_startup_grace_active():
            self._silent_weather_refresh()
            self._check_scheduled_weather_display()

    def _monitor_screen_activity(self) -> None:
        from silva.dev.screen_monitor import capture_activity

        capture_activity(asleep=self._asleep)

    def _check_sleep_mode_alerts(self) -> None:
        """Keep weather/news monitoring and logging active even while Silva is asleep."""
        if self._scheduled_alerts_paused():
            return
        if not bool(load_config().get("protection_sleep_alerts_enabled", True)):
            return
        owner = get_owner()
        if can_use_news_briefing(owner):
            built = refresh_daily_briefing(
                user_id=owner.get("id", "guest"),
                user_name=owner.get("name", "Owner"),
            )
            if built and not self._asleep:
                from silva.alerts.category_log import log_category_alert
                from silva.commands.news_briefing import load_latest_briefing

                briefing = load_latest_briefing() or {}
                headline = str(briefing.get("spoken_summary", "Daily news briefing ready"))[:400]
                log_category_alert(
                    "news",
                    "Daily news briefing generated",
                    detail=headline,
                    asleep=False,
                )

    def _run_interactive_background_tasks(self) -> None:
        """Tasks that speak or open flows — run on the main thread only."""
        self._process_typed_command_queue()
        if self._scheduled_alerts_paused():
            return
        self._check_todo_nags()
        if self._asleep:
            return
        if self._defer_owner_startup:
            self._defer_owner_startup = False
            self._owner_startup_setup()
        if not self._startup_checks_done:
            self._startup_checks_done = True
            from silva.config import load_config

            if bool(load_config().get("auto_update_check_on_startup", True)):
                if self._should_skip_update_prompts():
                    self._log_terminal_update_status_for_owner()
                else:
                    self._maybe_check_for_updates(force=True, silent=True)
        self._check_access_sessions()
        self._check_appointment_reminders()
        self._check_note_reminders()
        self._offer_plugged_in_camera()
        self._drain_camera_gui_queue()
        self._drain_followup_speech()
        self._check_news_briefing()

    def _handle_protection_speech(self, text: str, user: dict) -> bool:
        command = classify_protection_command(text)
        if command is None:
            return False

        if command == "owner_override":
            if not is_owner(user):
                self.say("Owner override is not available for this profile.", interruptible=False)
                return True
            monitor_id = protection_enabled_for_monitor_user()
            if not monitor_id:
                self.say("Protection protocol is not active.", interruptible=False)
                return True
            mark_session_verified(monitor_id)
            self._protection_flow = None
            from silva.alerts.category_log import log_category_alert

            log_category_alert("protection", "Owner override accepted", detail=text[:120])
            self.say("Owner override accepted. Protection session restored.", interruptible=False)
            return True

        if not can_enable_protection(user):
            self.say("Protection protocol is only available for the owner and admins.", interruptible=False)
            return True

        user_id = user.get("id", "guest")
        if command == "activate":
            activate_protection(user_id)
            from silva.alerts.category_log import log_category_alert

            log_category_alert(
                "protection",
                f"Protection protocol activated by {user.get('name', user_id)}",
            )
            self.say(
                "Protection protocol is now active. I will verify your face and voice, "
                "log weather and news alerts while asleep, and challenge unknown users.",
                interruptible=False,
            )
            return True

        if command == "deactivate":
            target_id = user_id
            monitor = protection_enabled_for_monitor_user()
            if is_owner(user) and monitor:
                target_id = monitor
            elif not is_owner(user) and user_id != monitor:
                self.say("Only the user who enabled protection can turn it off.", interruptible=False)
                return True
            if not monitor and not is_protection_enabled_for_user(target_id):
                self.say("Protection protocol is not active.", interruptible=False)
                return True
            deactivate_protection(target_id)
            self._protection_flow = None
            from silva.alerts.category_log import log_category_alert

            log_category_alert(
                "protection",
                f"Protection protocol deactivated by {user.get('name', user_id)}",
            )
            self.say("Protection protocol is off.", interruptible=False)
            return True

        return False

    def _run_protection_challenge(self, reason: str) -> bool:
        from silva.alerts.category_log import log_category_alert
        from silva.notifications.dispatch import notify_user_protection_async
        from silva.security.protection_protocol import format_verification_code, generate_verification_code

        owner = get_owner()
        digits = generate_verification_code()
        code_spoken = format_verification_code(digits)
        self._protection_flow = {"digits": digits, "reason": reason}
        log_category_alert(
            "security",
            "Verification challenge issued",
            detail=f"{reason}; code spoken to owner",
        )
        notify_user_protection_async(
            owner,
            f"Silva security code: {code_spoken}. Enter it on the machine to continue.",
            reason="verification_challenge",
            force=True,
        )
        self.say(
            f"Security verification required. The code is {code_spoken}. "
            "Enter it in the popup to continue.",
            interruptible=False,
        )
        result = run_protection_verification(
            subtitle="Enter the 8-digit verification code Silva spoke.",
            digits=digits,
            allow_owner_close=is_owner(get_active_user()),
        )
        self._protection_flow = None
        if result.passed:
            monitor_id = protection_enabled_for_monitor_user()
            if monitor_id:
                mark_session_verified(monitor_id)
            log_category_alert("protection", "Verification challenge passed")
            self.say("Verified. You may continue.", interruptible=False)
            return True
        log_category_alert("security", "Verification challenge failed", detail=result.reason)
        self.say("Verification failed. Access remains blocked.", interruptible=False)
        return False

    def _enforce_protection(self, text: str) -> bool:
        if not is_protection_active():
            return True
        if self._protection_flow is not None:
            return False

        now = time.time()
        if now - self._last_protection_check < 2.0:
            return True
        self._last_protection_check = now

        check = check_protection_access(audio=self._last_audio, asleep=self._asleep)
        if check.allowed:
            return True
        if not check.needs_verification:
            return True

        return self._run_protection_challenge(check.reason)

    def _enter_sleep(self, *, quiet: bool = False, text: str = "") -> None:
        self._note_transition_tone(text or getattr(self, "_pending_transition_text", ""))
        self._asleep = True
        self._sleep_reminder_index = 0
        self._sleep_idle_reminder_index = 0
        self._last_sleep_reminder_at = 0.0
        now = time.time()
        self._sleep_started_at = now
        self._last_idle_sleep_reminder_at = now
        try:
            from silva.keep_alive import mark_sleep_active, start_watchdog

            mark_sleep_active()
            start_watchdog(os.getpid())
        except Exception:
            pass
        log_info("Silva entered sleep mode")
        if not quiet:
            self._say_while_asleep(self.SLEEP_MESSAGE)

    def _idle_sleep_reminder_due(self) -> bool:
        return False

    def _sleep_wake_only(self) -> bool:
        return bool(load_config().get("sleep_wake_only_enabled", True))

    def _remind_asleep(self, *, reason: str = "command", text: str = "") -> None:
        from silva.sleep_prompts import remind_asleep

        remind_asleep(self, reason=reason, text=text)

    def _maybe_idle_sleep_reminder(self) -> None:
        from silva.sleep_prompts import maybe_idle_sleep_reminder

        maybe_idle_sleep_reminder(self)

    def _wake_up(self, *, source: str, silent: bool = False) -> None:
        self._note_transition_tone(getattr(self, "_pending_transition_text", ""))
        self._asleep = False
        grace = float(load_config().get("daily_routine_wake_grace_seconds", 300))
        self._daily_routine_grace_until = time.time() + max(30.0, grace)
        try:
            from silva.keep_alive import clear_sleep_active

            clear_sleep_active()
        except Exception:
            pass
        log_info(f"Silva woke up ({source}, silent={silent})")
        if silent:
            print("Silva is awake (silent — listening without speaking).")
            return
        self.say(wake_greeting_for_user(), interruptible=False)

    def _wait_for_wake(self) -> None:
        from silva.sleep_prompts import looks_like_user_attempt

        while self._asleep and not self._stop_requested:
            try:
                try:
                    from silva.keep_alive import beat

                    beat()
                except Exception:
                    pass
                self._process_typed_command_queue()
                self._check_todo_nags()
                if self._stop_requested:
                    return
                if not self._asleep:
                    return
                if self._voice_mode:
                    from silva.mic_guard import retry_wait_seconds, should_retry_mic

                    if not should_retry_mic(self):
                        time.sleep(retry_wait_seconds(self))
                        continue
                    stt = self._ensure_stt()
                    if stt is None:
                        self._recover_voice_after_error()
                        time.sleep(retry_wait_seconds(self))
                        continue
                    wake_timeout = wake_listen_timeout()
                    try:
                        text, audio = stt.listen_with_audio(
                            timeout=wake_timeout,
                            announce=False,
                        )
                    except (OSError, RuntimeError) as exc:
                        log_error("Wake listen failed", exc=exc)
                        self._recover_voice_after_error()
                        time.sleep(0.4)
                        continue
                    if getattr(stt, "last_device_error", False):
                        self._recover_voice_after_error()
                        time.sleep(0.4)
                        continue
                    if not text:
                        self._maybe_idle_sleep_reminder()
                        self._handle_notes_silence()
                        continue
                    from silva.close_phrases import is_close_command

                    if is_close_command(text):
                        print(f"You: {text}")
                        log_input(text, mode="voice-sleep-close")
                        self._close_like_exit()
                        return
                    self._note_transition_tone(text, audio)
                    from silva.room_speech import check_turn as check_room_turn

                    room_check = check_room_turn(self, text, audio)
                    if room_check.decision == "hold":
                        log_info("Held sleep-mode reply until the room is clear")
                        continue
                    if room_check.decision == "reply":
                        print(f"You: {text}")
                        log_input(text, mode="voice-sleep-room")
                        self._say_while_asleep(room_check.reply)
                        continue
                    wake_only = self._sleep_wake_only()
                    if not wake_only:
                        from silva.dev.screen_monitor import handle_screen_monitor_speech

                        if handle_screen_monitor_speech(self, text, asleep=True):
                            continue
                    decision = evaluate_wake(text)
                    if decision.action == "ignore" and audio is not None:
                        resolved, used = resolve_text_with_phrase_audio(
                            text,
                            audio,
                            active_user_id=get_active_user().get("id"),
                            phrase_kinds={"wake"},
                        )
                        if used and resolved:
                            decision = evaluate_wake(resolved)
                            if decision.action != "ignore":
                                text = resolved
                    if decision.action == "ignore":
                        if wake_only:
                            continue
                        if self._notes_flow is not None or is_notes_command(text):
                            print(f"You: {text}")
                            log_input(text, mode="voice-sleep-notes")
                            if audio is not None:
                                self._identify_speaker(audio)
                            if self._notes_flow is not None:
                                self._handle_notes_flow(text, get_active_user())
                            else:
                                self._handle_notes_command(text, get_active_user())
                            continue
                        from silva.commands.pronunciation_phrases import is_pronunciation_command
                        from silva.commands.pronunciation_handler import handle_pronunciation_speech
                        from silva.commands.location_handler import handle_location_speech
                        from silva.commands.crash_report_handler import handle_crash_report_speech
                        from silva.commands.crash_report_phrases import is_crash_report_ask
                        from silva.commands.update_phrases import is_update_speech

                        if (
                            is_pronunciation_command(text)
                            or handle_location_speech(self, text)
                            or is_crash_report_ask(text)
                            or is_update_speech(text)
                        ):
                            print(f"You: {text}")
                            log_input(text, mode="voice-sleep-command")
                            if audio is not None:
                                self._identify_speaker(audio)
                            if is_update_speech(text):
                                self._handle_update_speech(text)
                            elif is_pronunciation_command(text):
                                handle_pronunciation_speech(self, text)
                            elif is_crash_report_ask(text):
                                handle_crash_report_speech(self, text)
                            continue
                        if looks_like_user_attempt(text):
                            print(f"You: {text}")
                            log_info(f"Speech while asleep: {text[:120]}")
                            self._remind_asleep(reason="voice", text=text)
                        continue

                    print(f"You: {text}")
                    log_input(text, mode="voice-wake-candidate")

                    if decision.action == "pending":
                        from silva.console_view import is_clean_console

                        if not is_clean_console():
                            print("Silva heard you. Waiting a moment in case you're talking with someone else...")
                        if not wait_for_clear_moment():
                            continue
                        silent = decision.silent or (
                            decision.reason.endswith("_busy")
                            and bool(load_config().get("wake_silent_when_busy", True))
                        )
                    else:
                        silent = decision.silent

                    if audio is not None:
                        self._identify_speaker(audio)
                    if is_protection_active():
                        check = check_protection_access(audio=audio, asleep=True)
                        if not check.allowed and check.needs_verification:
                            self._run_protection_challenge(check.reason)
                            continue
                    log_input(text, mode="voice-wake")
                    self._pending_transition_text = text
                    self._wake_up(source="voice", silent=silent)
                    return

                self._maybe_idle_sleep_reminder()
                text = input("You: ").strip()
                if not text:
                    continue
                print(f"You: {text}")
                from silva.close_phrases import is_close_command

                if is_close_command(text):
                    log_input(text, mode="typed-sleep-close")
                    self._close_like_exit()
                    return
                wake_decision = evaluate_wake(text)
                if wake_decision.action in {"wake", "pending"}:
                    log_input(text, mode="typed-wake")
                    self._pending_transition_text = text
                    self._wake_up(source="typed")
                    return
                if self._sleep_wake_only():
                    continue
                if self._notes_flow is not None or is_notes_command(text):
                    log_input(text, mode="typed-sleep-notes")
                    if self._notes_flow is not None:
                        self._handle_notes_flow(text, get_active_user())
                    else:
                        self._handle_notes_command(text, get_active_user())
                    continue
                from silva.commands.update_phrases import is_update_speech

                if is_update_speech(text):
                    log_input(text, mode="typed-sleep-command")
                    self._handle_update_speech(text)
                    continue
                self._remind_asleep(reason="typed")
            except (KeyboardInterrupt, EOFError):
                try:
                    from silva.keep_alive import mark_clean_stop

                    mark_clean_stop()
                except Exception:
                    pass
                raise
            except Exception as exc:
                log_error("Sleep wait failed; staying asleep", exc=exc)
                time.sleep(1.0)

    def _is_settings_request(self, text: str) -> bool:
        normalized = text.strip().lower()
        return any(
            p in normalized
            for p in ("change settings", "update settings", "change config", "modify settings")
        )

    def _pause_listening_for_profile(self) -> None:
        stt = self._stt
        if stt is not None:
            try:
                stt.release_microphone()
            except Exception:
                pass
            self._stt = None
        log_info("Microphone released for profile voice and face setup.")

    def _resume_listening_after_profile(self) -> None:
        if self._voice_mode:
            self._ensure_stt()
        log_info("Microphone restored after profile panel.")

    def _identify_for_profile_panel(self) -> dict | None:
        stt = self._ensure_stt()
        if stt is None:
            return None
        audio = stt.capture_audio(timeout=6.0, phrase_limit=8.0)
        try:
            stt.release_microphone()
        except Exception:
            pass
        self._stt = None
        if audio is None:
            return None
        return self._identify_speaker(audio)

    def _speak_startup(self) -> None:
        greeting = startup_greeting()
        if not load_config().get("startup_greeting_speak", True):
            print(f"Silva: {greeting}")
            return
        self.say(greeting, interruptible=False)

    def _send_owner_startup_sms(self) -> None:
        user = get_active_user()
        if not is_owner(user):
            return
        try:
            from silva.notifications.sms import may_send_startup_sms, send_owner_sms_async

            if not may_send_startup_sms():
                return
            name = user.get("name", "Owner")
            send_owner_sms_async(
                f"Silva is online for {name}. Weather alerts will text here when configured.",
                reason="startup_ping",
                force=True,
            )
        except Exception as exc:
            log_error("Startup SMS failed", exc=exc)

    def _maybe_show_onboarding(self) -> None:
        from silva.users.manager import (
            mark_first_run_setup_done,
            mark_onboarding_done,
            needs_first_run_setup,
            needs_onboarding,
            record_first_run_choices,
        )

        user = get_active_user()
        basic = needs_first_run_setup(user)
        admin = needs_onboarding(user, admin=True)
        if not basic and not admin:
            return
        user_id = user.get("id", "guest")

        def _complete(payload: dict | None) -> None:
            try:
                if payload and basic:
                    updated = record_first_run_choices(user_id, **payload)
                    mark_first_run_setup_done(str(updated.get("id") or user_id))
                elif basic:
                    mark_first_run_setup_done(user_id)
                if admin:
                    mark_onboarding_done(user_id, admin=True)
            except Exception as exc:
                log_error("First-run setup save failed", exc=exc)

        from silva.gui.onboarding_popup import show_onboarding_popup

        show_onboarding_popup(user, _complete)
        if not self._asleep:
            self._speak_now("I opened a quick getting started guide.")

    def _is_private_contact_request(self, text: str, user: dict) -> bool:
        normalized = text.strip().lower()
        if not normalized:
            return False
        private_terms = (
            "phone number",
            "cell number",
            "text number",
            "telegram",
            "chat id",
            "home address",
            "my address",
            "where do i live",
            "where do you live",
            "protection settings",
            "protection protocol",
            "security number",
            "alert number",
            "owner phone",
            "kevin number",
            "kevin phone",
            "kevin address",
            "kevin location",
        )
        if any(term in normalized for term in private_terms):
            return True
        if "call me" in normalized or "phone call" in normalized or "dial me" in normalized:
            return True
        if "what is your number" in normalized or "whats your number" in normalized:
            return True
        if "kevin" in normalized and any(word in normalized for word in ("number", "phone", "address", "location")):
            return True
        return False

    def _handle_private_contact_request(self, text: str, user: dict) -> bool:
        if not self._is_private_contact_request(text, user):
            return False
        normalized = text.strip().lower()
        if "call" in normalized:
            self.say(
                "I do not place phone calls unless you explicitly set that up later. "
                "I can send text alerts to the owner when configured.",
                interruptible=False,
            )
            return True
        if not owner_may_reveal_private(user, normalized):
            self.say("That contact and security information is private.", interruptible=False)
            return True
        from silva.notifications.owner_secrets import phone_visible_to_user

        if phone_visible_to_user(user):
            self.say("Your alert number is configured in owner settings.", interruptible=False)
        else:
            self.say(
                "Your alert contacts are configured privately. "
                "Say show my phone number if you want to hear it aloud.",
                interruptible=False,
            )
        return True

    def _open_profile_panel(
        self,
        *,
        startup: bool = False,
        panel_mode: str = "owner",
        self_user_id: str | None = None,
    ) -> None:
        self._pause_listening_for_profile()
        try:
            run_profile_panel(
                startup=startup,
                panel_mode=panel_mode,
                self_user_id=self_user_id,
                on_identify=self._identify_for_profile_panel if self._voice_mode else None,
            )
        finally:
            self._resume_listening_after_profile()

    def _open_profile_for_user(self, user: dict, *, startup: bool = False) -> bool:
        mode = profile_mode_for_user(user)
        if mode == "owner":
            self._open_profile_panel(startup=startup, panel_mode="owner")
            return True
        if mode == "admin":
            self._open_profile_panel(startup=startup, panel_mode="admin")
            return True
        if mode == "self":
            self._open_profile_panel(
                startup=startup,
                panel_mode="self",
                self_user_id=user.get("id"),
            )
            return True
        self.say(
            "You can only set up your own profile after you are registered. "
            "Ask the owner to add you.",
            interruptible=False,
        )
        return True

    def _owner_startup_setup(self) -> None:
        if is_main_owner_system():
            log_info("Main owner system — skipping startup profile panel.")
            return
        if not owner_auto_profile_enabled():
            return
        if is_remote_system():
            log_info("Remote system — starting as guest; owner profile panel deferred until verified.")
            return
        owner = startup_owner_user()
        identify_and_set_active(owner["id"])
        log_info(f"Owner startup profile panel for {owner['name']}")
        self._open_profile_panel(startup=True, panel_mode="owner")
        identify_and_set_active(None)

    def _handle_set_voice(self) -> bool:
        user = get_active_user()
        if (
            not user_can(user, PERM_ENROLL_VOICE)
            and normalize_tier(user.get("tier")) < MAX_TIER
            and user.get("id") == "guest"
        ):
            self._deny_permission(PERM_ENROLL_VOICE, "voice enrollment")
            return True

        target = user if user.get("id") not in {"", "guest"} else get_owner()
        self._pause_listening_for_profile()
        try:
            record_result = run_audio_record_blocking(target)
        finally:
            self._resume_listening_after_profile()
        if record_result.cancelled or not record_result.saved:
            return True

        from silva.gui.voice_panel import SetVoiceResult

        enrolled = apply_voice_enrollment(
            SetVoiceResult(
                saved=True,
                name=record_result.name,
                user_id=record_result.user_id,
                wav_file=record_result.wav_file,
                cancelled=False,
            )
        )
        if enrolled is None:
            self.say("Only the owner can create new user profiles.", interruptible=False)
            return True

        log_info(f"Voice profile saved: {record_result.wav_file} for {enrolled['name']}")
        self.say(
            f"Voice set for {enrolled['name']}. I will recognize you automatically when you speak.",
            interruptible=False,
        )
        return True

    def _handle_profile_speech(self, user: dict, kind: str) -> bool:
        if kind == "self":
            if can_open_self_profile(user):
                return self._open_profile_for_user(user)
            self.say(
                "You need to be registered before setting up your profile.",
                interruptible=False,
            )
            return True

        if can_open_control_panel(user):
            return self._open_profile_for_user(user)
        if can_open_self_profile(user):
            return self._open_profile_for_user(user)
        self.say(
            "Only the owner or tier 4 admins can open the control panel. "
            "Say my profile to set up your own.",
            interruptible=False,
        )
        return True

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

        from silva.cache import lookup_route

        route_hint = lookup_route(text)
        if route_hint is not None:
            log_info(f"Cache route: {route_hint.route_type}:{route_hint.name or 'quick'}")

        normalized = text.strip().lower()
        if not normalized:
            return True

        if getattr(self, "_guest_demo_owner_returned", False):
            self._guest_demo_owner_returned = False
            owner = get_active_user()
            self.say(
                f"Welcome back, {owner.get('name', 'Owner')}. Owner profile restored.",
                interruptible=False,
            )
            return True

        from silva.users.guest_demo import handle_guest_demo_speech

        if handle_guest_demo_speech(self, text, get_active_user()):
            return True

        from silva.close_phrases import is_close_command

        if is_close_command(text):
            return self._close_like_exit()

        from silva.conversation.complete_sentence import should_ignore_after_interruption

        if should_ignore_after_interruption(text, interrupted_at=float(getattr(self, "_last_interruption_at", 0.0) or 0.0)):
            log_info(f"Ignored incomplete speech after interruption: {text[:120]}")
            return True

        from silva.conversation.correction_repair import (
            handle_correction_repair,
            handle_exact_repeat,
        )

        if handle_exact_repeat(self, text):
            return True
        if handle_correction_repair(self, text):
            return True

        from silva.conversation.attitude import handle_attitude_speech, note_user_text
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

        echo_decision = evaluate_input(text)
        if echo_decision == "self_echo":
            log_info(f"Ignored Silva's own speaker echo: {text[:120]}")
            return True
        if echo_decision == "other_ai":
            log_info(f"Other-AI speaker reply allowed: {text[:120]}")

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
            note_user_text(self._user_id(), text, audio=getattr(self, "_last_audio", None))
            observe_speech(text, user_id=self._user_id())
            self._silva_last_tone_text = text

        if not self._asleep and is_wake_command(text):
            log_info(f"Already awake; acknowledged wake phrase: {text[:120]}")
            self.say("I'm already awake. Listening.", interruptible=False)
            return True

        from silva.commands.intent import is_action_command as _is_action

        log_info(f"Utterance route: {'command' if _is_action(text) else 'conversation'} | {text[:120]}")

        user = get_active_user()
        if not _phrase_retry and self._voice_mode and self._last_audio is not None:
            resolved, used = resolve_text_with_phrase_audio(
                text,
                self._last_audio,
                active_user_id=user.get("id"),
            )
            if used and resolved and resolved.strip().lower() != normalized:
                log_info(f"Using phrase recording instead of speech text: {resolved[:120]}")
                return self._handle_input(resolved, _phrase_retry=True)

        from silva.dev.speech_training import is_blocked_phrase

        if is_blocked_phrase(text, self._user_id()):
            log_info(f"Ignored trained don't-say phrase: {text[:120]}")
            return True

        if self._handle_private_contact_request(text, user):
            return True

        from silva.commands.crash_report_handler import handle_crash_report_speech

        if handle_crash_report_speech(self, text):
            return True

        if self._handle_reference_image_command(text):
            return True

        if self._handle_system_panel_command(text, user):
            return True

        if self._handle_image_generation_command(text):
            return True

        if is_sleep_command(text):
            self._pending_transition_text = text
            self._enter_sleep()
            return True

        from silva.room_speech import check_turn as check_room_turn

        room_check = check_room_turn(self, text, self._last_audio)
        if room_check.decision == "hold":
            log_info("Held reply until the room is clear")
            return True
        if room_check.decision == "reply":
            self.say(room_check.reply, interruptible=False)
            return True

        if handle_help_speech(self, text):
            return True

        from silva.commands.live_chat_commands import handle_live_chat_speech

        if handle_live_chat_speech(self, text, user):
            return True

        from silva.commands.pronunciation_handler import handle_pronunciation_speech
        from silva.commands.location_handler import handle_location_speech
        from silva.yes_no_prompt import dispatch as dispatch_yes_no

        if handle_pronunciation_speech(self, text):
            return True

        if handle_location_speech(self, text):
            return True

        if dispatch_yes_no(self, text):
            return True

        if handle_learned_speech(self, text):
            return True

        if is_background_command(text):
            return self._handle_background_command(text)

        if self._handle_update_speech(text):
            return True

        if self._handle_phrase_recorder_command(text, user):
            return True

        if self._handle_game_lookup_command(text, user):
            return True

        if self._handle_knowledge_command(text, user):
            return True

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

        if self._handle_visual_guide_command(text, user):
            return True

        profile_kind = classify_profile_speech(text)
        if profile_kind is not None:
            self._pending_profile_switch = None
            self._permission_flow = None
            log_info(f"Profile speech command ({profile_kind}): {text[:80]}")
            return self._handle_profile_speech(user, profile_kind)

        if self._handle_profile_switch_reply(text):
            return True

        if self._permission_flow and self._handle_permission_flow(text):
            return True

        if self._handle_feature_request_flow(text, user):
            return True

        if self._maybe_offer_feature_request(text, user):
            return True

        if self._appointment_flow and self._handle_appointment_flow(text, user):
            return True

        if self._notes_flow and self._handle_notes_flow(text, user):
            return True

        if self._camera_setup_flow and self._handle_camera_setup_flow(text):
            return True

        if self._weather_feedback_flow and self._handle_weather_feedback_flow(text, user):
            return True

        if self._weather_forecast_flow and self._handle_weather_forecast_flow(text):
            return True

        if self._news_flow and self._handle_news_flow(text):
            return True

        user = get_active_user()

        if normalized in {
            "security",
            "security panel",
            "show security",
            "security alerts",
            "access alerts",
        }:
            if not (is_owner(user) or can_use_voice_control(user, "security")):
                self._deny_permission(PERM_APPROVE_ACTIONS, "security panel")
                return True
            if not self._confirm_admin_action("security panel"):
                return True
            run_security_panel()
            self.say(notify_owner_message(), interruptible=False)
            return True

        if normalized in {
            "set voice",
            "set my voice",
            "save my voice",
            "record my voice",
            "enroll my voice",
            "register my voice",
            "remember my voice",
            "train my voice",
        }:
            return self._handle_set_voice()

        observe_input(text)
        self._apply_adaptive_voice()

        if is_interrupt_command(text):
            from silva.dev.screen_monitor import stop_video_watch
            from silva.interrupt_listen import interrupt_now

            active = bool(
                self._speaking
                or self._parallel_command_active
                or self._pending_readbacks
                or not self._parallel_queue.empty()
            )
            interrupt_now("input", command=text, tts=self._tts)
            if active:
                close_all()
                with self._followup_lock:
                    self._pending_readbacks.clear()
                while True:
                    try:
                        self._parallel_queue.get_nowait()
                    except Exception:
                        break
            for _ in range(40):
                if not self._speaking:
                    break
                time.sleep(0.02)
            if self._speaking:
                try:
                    self._tts.stop()
                except Exception:
                    pass
                self._speaking = False
            with self._followup_lock:
                self._pending_readbacks.clear()
            user_id = self._user_id() if callable(getattr(self, "_user_id", None)) else "guest"
            stop_video_watch(user_id)
            self.say(self.STOPPED_MESSAGE, immediate=True)
            return True

        if self._is_settings_request(text):
            if not user_can(user, PERM_CHANGE_SETTINGS) and not can_use_voice_control(user, "settings"):
                self._deny_permission(PERM_CHANGE_SETTINGS, "change settings")
                return True
            if not self._confirm_admin_action("change settings"):
                return True

        if self._is_blocked_admin_command(normalized, user):
            self._deny_permission(PERM_MANAGE_USERS, normalized)
            return True
        if normalized in _ADMIN_COMMANDS or any(
            normalized.startswith(cmd + " ") for cmd in _ADMIN_COMMANDS
        ):
            if not self._confirm_admin_action("user management"):
                return True

        user_result = try_user_command(text, audio=self._last_audio)
        if user_result is not None:
            self.say(user_result)
            return True

        if normalized in {"show logs", "open logs", "view logs", "where are logs"}:
            if not user_can(user, PERM_VIEW_LOGS) and not can_use_voice_control(user, "logs"):
                self._deny_permission(PERM_VIEW_LOGS, "view logs")
                return True
            if not self._confirm_admin_action("view logs"):
                return True
            self.say(f"Your Silva logs are saved at {log_path()}")
            return True

        if normalized in {"report bug", "bug report", "report a bug", "i found a bug"}:
            if not feature_allowed(user, FEATURE_BUG_REPORT):
                self.say("Bug reports are not enabled for your profile.", interruptible=False)
                return True
            run_bug_report_dialog(user)
            self.say("Bug report window opened. Review your message and press Send.", interruptible=False)
            return True

        if is_silva_bug_report(text):
            if not feature_allowed(user, FEATURE_BUG_REPORT):
                return True
            run_bug_report_dialog(user, initial_text=text.strip())
            self.say("I opened a Silva bug report so you can review and send it.", interruptible=False)
            return True

        if self._handle_wiki_and_recall(text, user):
            return True

        if self._handle_weather_feedback_command(text, user):
            return True

        if self._handle_weather_forecast_command(text, user):
            return True

        if self._handle_camera_access_command(text):
            return True

        if self._handle_camera_setup_command(text):
            return True

        if self._handle_notes_command(text, user):
            return True

        if self._handle_appointment_command(text, user):
            return True

        if self._handle_math_command(text, user):
            return True

        if self._handle_measurement_command(text, user):
            return True

        if self._handle_audio_command(text, user):
            return True

        if self._handle_playback_command(text, user):
            return True

        if self._handle_news_command(text, user):
            return True

        match = match_command(text)
        if match is not None:
            if match.name == "weather" and not feature_allowed(user, FEATURE_WEATHER):
                self._deny_feature(user, FEATURE_WEATHER, "weather")
                return True
            if match.name == "wikipedia":
                return self._run_wikipedia(text, match.query or "", user)
            if match.name not in {"weather", "wikipedia"} and not user_can(user, PERM_RUN_COMMANDS):
                self._deny_permission(PERM_RUN_COMMANDS, match.name)
                return True
            if user_can(user, PERM_USE_NEW_FEATURES) and normalize_tier(user.get("tier")) == 4:
                log_info(f"Tier 4 command {match.name} may require owner approval")
            log_command(match.name, query=match.query)
            try:
                if match.name == "weather":
                    result = get_weather(user_id=user.get("id", "guest"))
                else:
                    result = run_command(match)
                self.say(result)
            except Exception as exc:
                log_error(f"Command '{match.name}' failed", exc=exc)
                self.say(f"Sorry, something went wrong: {exc}")
            return True

        from silva.commands.intent import is_action_command

        leftover_detail = feature_detail_reply_for_user(text, user)
        if leftover_detail:
            self.say(leftover_detail, interruptible=True)
            return True

        from silva.commands.unknown_information import handle_unknown_information_speech

        if handle_unknown_information_speech(self, text):
            return True

        if is_action_command(text):
            log_info(f"Action command had no remaining handler: {text[:120]}")
            return True

        tier_chat = try_tier_conversation(text, user)
        if tier_chat is not None:
            self.say(tier_chat)
            return True

        if not user_can(user, PERM_CONVERSATION):
            return True

        self._load_conversation_context()
        chat, self._conversation_context, confidence = try_conversation_with_context(
            text, self._conversation_context, user_id=self._user_id()
        )
        if not chat:
            from silva.conversation.vocabulary import vocabulary_fallback

            chat = vocabulary_fallback(text, self._conversation_context.response_indices or {})
            self._conversation_context.category = "fallback"
            self._conversation_context.follow_up = "talk_more"
        if chat:
            log_info(f"Conversation route: {text[:120]}")
            self._say_conversation(chat, text)
            self._save_conversation_context()
            return True

        log_info(f"No match for input, staying silent: {text[:120]}")
        return True

    def _submit_typed_terminal_command(self, line: str) -> None:
        from silva.interrupt_listen import submit_typed_terminal_command_impl

        submit_typed_terminal_command_impl(self, line)

    def _process_typed_command_queue(self) -> None:
        from silva.dev.typed_command_access import validate_typed_command
        from silva.wake_context import evaluate_wake

        while True:
            try:
                text = self._typed_command_queue.get_nowait()
            except queue.Empty:
                break

            user = get_active_user()
            ok, message = validate_typed_command(user, text)
            if not ok:
                self._print_terminal_message(message)
                continue

            print(f"You (typed): {text}")
            log_input(text, mode="typed-terminal")

            if self._asleep:
                from silva.close_phrases import is_close_command
                from silva.commands.update_phrases import is_update_speech

                if is_close_command(text):
                    self._close_like_exit()
                    continue
                if self._notes_flow is not None or is_notes_command(text):
                    user = get_active_user()
                    if self._notes_flow is not None:
                        self._handle_notes_flow(text, user)
                    else:
                        self._handle_notes_command(text, user)
                    continue
                if is_update_speech(text):
                    self._handle_update_speech(text)
                    continue
                wake_decision = evaluate_wake(text)
                if wake_decision.action in {"wake", "pending"}:
                    self._wake_up(source="typed-terminal")
                elif not is_sleep_command(text):
                    self._wake_up(source="typed-terminal", silent=True)

            user = get_active_user()
            if self._handle_protection_speech(text, user):
                continue
            if not self._enforce_protection(text):
                self._print_terminal_message("That command needs verification first.")
                continue
            self._handle_input(text)

    def _print_terminal_message(self, message: str) -> None:
        print()
        print(message)
        print()
        log_info(f"Terminal command result: {message[:200]}")

    def _run_terminal_update(self) -> None:
        def worker() -> None:
            from silva.dev.terminal_update import run_terminal_update

            result = run_terminal_update()
            self._print_terminal_message(result.message)
            if result.ok:
                self._stt = None
            if result.ok and not self._asleep:
                if is_main_owner_system():
                    self.say(
                        "Update finished. Please check that everything is working. "
                        "If not, type revert in the terminal.",
                        interruptible=False,
                    )
                else:
                    self.say(
                        "Update finished. Please check that everything is working. "
                        "If not, type revert in the terminal or contact the owner or an admin.",
                        interruptible=False,
                    )

        threading.Thread(target=worker, name="silva-terminal-update", daemon=True).start()

    def run(self) -> None:
        from silva.console_view import enable_clean_console
        from silva.instance import acquire_silva_instance, ensure_console, handoff_to_running

        if not acquire_silva_instance():
            handoff_to_running()
            return
        ensure_console()
        enable_clean_console(True)
        try:
            from silva.keep_alive import (
                clear_sleep_active,
                install_console_stop_handler,
                mark_running,
                start_watchdog,
            )

            install_console_stop_handler()
            try:
                from silva.crash_record import record_session_start

                record_session_start(resumed_sleep=bool(self._resume_sleep))
            except Exception:
                pass
            mark_running()
            if not self._resume_sleep:
                clear_sleep_active()
            start_watchdog(os.getpid())
        except Exception:
            pass
        preload_router_cache()
        from silva.conversation.vocabulary import preload_vocabulary

        preload_vocabulary()
        if self._resume_sleep:
            log_info("Stay-active restart: resuming sleep mode.")
        else:
            self._speak_startup()
        if self._voice_mode:
            time.sleep(0.2)
            self._ensure_stt()
        self._load_conversation_context()
        if not self._resume_sleep:
            self._send_owner_startup_sms()
        self._background_runner.start()
        typed_enabled = bool(load_config().get("typed_terminal_commands_enabled", True))
        start_terminal_listener(
            on_message=self._print_terminal_message,
            on_typed_command=self._submit_typed_terminal_command if typed_enabled else None,
        )
        from silva.dev.auto_update import should_show_terminal_update_button
        from silva.gui.display_host import start_display_host

        start_display_host()
        if not self._resume_sleep:
            threading.Timer(1.0, self._maybe_show_onboarding).start()
        if should_show_terminal_update_button():
            from silva.gui.terminal_update_button import start_terminal_update_button

            start_terminal_update_button(on_update=self._run_terminal_update)
        from silva.gui.background_mode import start_background_mode
        from silva.gui.quick_command_popup import show_quick_command_popup

        start_background_mode(
            on_type_hotkey=lambda: show_quick_command_popup(self._dispatch_overlay_command)
        )
        grace_wait = max(0.0, self._weather_grace_until - time.time())
        threading.Timer(grace_wait, self._post_startup_weather_check).start()
        self._defer_owner_startup = (
            owner_auto_profile_enabled()
            and not is_main_owner_system()
            and not is_remote_system()
            and not self._resume_sleep
        )
        if self._resume_sleep:
            self._enter_sleep(quiet=True)

        try:
            while True:
                try:
                    if self._stop_requested:
                        break
                    if self._asleep:
                        self._wait_for_wake()
                        if self._stop_requested:
                            break
                        continue

                    if self._notes_typing:
                        self._run_interactive_background_tasks()
                        time.sleep(0.2)
                        continue

                    text = self._listen_once()
                    if text is None:
                        self._handle_notes_silence()
                        self._run_interactive_background_tasks()
                        continue

                    self._run_interactive_background_tasks()
                    user = get_active_user()
                    if self._handle_protection_speech(text, user):
                        continue
                    if not self._enforce_protection(text):
                        continue
                    if not self._handle_input(text):
                        break
                except (KeyboardInterrupt, EOFError):
                    print()
                    self.say("Goodbye.", interruptible=False)
                    log_info("Silva stopped.")
                    self._shutdown()
                    break
                except RuntimeError as exc:
                    log_error("Voice input failed", exc=exc)
                    self._recover_voice_after_error()
                    time.sleep(0.4)
                    continue
                except Exception as exc:
                    log_error("Unexpected assistant error", exc=exc)
                    try:
                        from silva.crash_record import record_command_error

                        record_command_error(exc)
                    except Exception:
                        pass
                    continue
        finally:
            if not self._shutdown_done:
                log_info("Silva process ending.")
                self._shutdown()


def main(voice_mode: bool = True) -> None:
    SilvaAssistant(voice_mode=voice_mode).run()
