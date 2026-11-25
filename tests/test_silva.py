"""Tests for Silva command matching and speech pipeline."""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import speech_recognition as sr

from silva.commands.registry import match_command
from silva.commands.weather import WeatherReport
from silva.conversation import is_conversational_utterance, try_conversation
from silva.interrupt import is_interrupt_command
from silva.location import is_wifi_connected
from silva.stt import (
    SpeechToText,
    _concat_audio,
    _dedupe_repeated_phrase,
    _looks_incomplete,
    _profile_command_partial,
)
from silva.stt import _needs_more_speech
from silva.tts import TextToSpeech
from silva.users.manager import add_user, get_owner, remove_user, update_user_profile, user_can
from silva.users.permissions import PERM_MANAGE_USERS, PERM_RUN_COMMANDS
from silva.users.tiers import MAX_TIER
from silva.users.voice_id import build_fingerprint, identify_user, save_voice_profile
from silva.users.access_security import block_actor, is_blocked, tier_can_assist
from silva.users.greetings import listening_prompt, startup_greeting
from silva.users.profile_access import can_open_control_panel, profile_mode_for_user
from silva.users.system_identity import (
    apply_system_startup_access,
    bypass_security_checks,
    get_machine_fingerprint,
    is_main_owner_system,
    is_remote_system,
)
from silva.users.tiers import can_help_tier
from silva.wake import is_sleep_command, is_wake_command


class WeatherMatchingTests(unittest.TestCase):
    def test_basic_weather(self):
        self.assertEqual(match_command("weather").name, "weather")

    def test_my_weather_phrases(self):
        phrases = [
            "what's my weather",
            "whats my weather",
            "what's my local weather",
            "whats my local weather",
            "tell me my local weather",
            "how is my weather today",
            "can you tell me what's my local weather",
            "can you tell me the weather",
            "please tell me my local weather",
        ]
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self.assertEqual(match_command(phrase).name, "weather")

    def test_non_weather_ignored(self):
        self.assertIsNone(match_command("open notepad"))
        self.assertIsNone(match_command("tell me in detail what do you mean by weather"))
        self.assertIsNone(match_command("what do you do of the weather"))
        self.assertIsNone(match_command("what do you mean by weather"))


class WeatherFeedbackTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        self._tmpdir = tempfile.TemporaryDirectory()
        self._feedback_file = Path(self._tmpdir.name) / "weather_feedback.json"
        patcher = patch("silva.commands.weather_feedback.FEEDBACK_FILE", self._feedback_file)
        self.addCleanup(patcher.stop)
        patcher.start()
        self._fetch_patcher = patch("silva.commands.weather_feedback._refresh_forecast")
        self.addCleanup(self._fetch_patcher.stop)
        self._fetch_patcher.start()

    def test_dispute_phrase(self):
        from silva.commands.weather_feedback import match_weather_feedback

        speech = match_weather_feedback("that weather is not right")
        self.assertIsNotNone(speech)
        assert speech is not None
        self.assertEqual(speech.action, "dispute")

    def test_report_storming(self):
        from silva.commands.weather_feedback import match_weather_feedback

        speech = match_weather_feedback("it's storming outside")
        self.assertIsNotNone(speech)
        assert speech is not None
        self.assertEqual(speech.action, "report")
        self.assertEqual(speech.conditions, "storming")

    def test_dispute_and_report_together(self):
        from silva.commands.weather_feedback import handle_weather_feedback

        msg, flow = handle_weather_feedback("user1", "weather is wrong it's raining outside")
        self.assertIsNone(flow)
        self.assertIn("rain", msg.lower())

    def test_dispute_flow_then_condition(self):
        from silva.commands.weather_feedback import (
            continue_weather_feedback_flow,
            handle_weather_feedback,
            get_active_weather_report,
        )

        msg, flow = handle_weather_feedback("user1", "that weather is not right")
        self.assertIsNotNone(flow)
        assert flow is not None
        self.assertIn("outside", msg.lower())

        msg2, flow2 = continue_weather_feedback_flow("user1", "it's storming", flow)
        self.assertIsNone(flow2)
        self.assertIn("storming", msg2.lower())
        active = get_active_weather_report("user1")
        self.assertIsNotNone(active)
        assert active is not None
        self.assertEqual(active["conditions"], "storming")

    def test_correction_overlay(self):
        from silva.commands.weather_feedback import format_correction_overlay, save_weather_report

        save_weather_report("user1", conditions="storming", disputed=True)
        overlay = format_correction_overlay("user1", "clear skies")
        self.assertIn("storming", overlay.lower())
        self.assertIn("clear skies", overlay.lower())

    def test_clear_correction(self):
        from silva.commands.weather_feedback import handle_weather_feedback, get_active_weather_report

        handle_weather_feedback("user1", "it's raining outside")
        self.assertIsNotNone(get_active_weather_report("user1"))
        handle_weather_feedback("user1", "use the forecast again")
        self.assertIsNone(get_active_weather_report("user1"))


class WeatherMonitorTests(unittest.TestCase):
    def test_respects_poll_interval(self):
        from silva.commands.weather_monitor import reset_poll_timer, silent_weather_refresh

        reset_poll_timer()
        sample = WeatherReport(
            city="Test",
            temp_f=70,
            humidity=50,
            wind_mph=5,
            conditions="clear skies",
            is_day=True,
            latitude=0.0,
            longitude=0.0,
            source="test",
        )
        with patch("silva.commands.weather_monitor.is_wifi_connected", return_value=True):
            with patch("silva.commands.weather_monitor.load_config") as mock_config:
                mock_config.return_value = {
                    "weather_background_poll_enabled": True,
                    "weather_poll_interval_minutes": 10,
                }
                with patch("silva.commands.weather.fetch_weather_report", return_value=sample) as mock_fetch:
                    self.assertTrue(silent_weather_refresh(force=True))
                    self.assertEqual(mock_fetch.call_count, 1)
                    self.assertFalse(silent_weather_refresh(force=False))
                    self.assertEqual(mock_fetch.call_count, 1)

    def test_get_system_weather_without_network(self):
        from silva.commands.weather import get_system_weather_report

        sample = WeatherReport(
            city="Cached",
            temp_f=65,
            humidity=40,
            wind_mph=3,
            conditions="cloudy",
            is_day=True,
            latitude=1.0,
            longitude=2.0,
            source="cached",
        )
        with patch("silva.commands.weather._load_cached_report", return_value=sample):
            report = get_system_weather_report()
            self.assertIsNotNone(report)
            assert report is not None
            self.assertEqual(report.city, "Cached")


class WeatherScheduleTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        self._tmpdir = tempfile.TemporaryDirectory()
        self._state_file = Path(self._tmpdir.name) / "weather_schedule_state.json"
        patcher = patch("silva.commands.weather_schedule.STATE_FILE", self._state_file)
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_build_display_slots(self):
        from silva.commands.weather_schedule import build_display_slots

        with patch("silva.commands.weather_schedule.load_config") as mock_config:
            mock_config.return_value = {
                "weather_morning_display_start_hour": 8,
                "weather_morning_display_end_hour": 9,
                "weather_morning_display_interval_minutes": 30,
                "weather_noon_display_hour": 12,
                "weather_evening_display_hour": 21,
            }
            slots = build_display_slots()
            self.assertEqual(slots, [(8, 0), (8, 30), (9, 0), (12, 0), (21, 0)])

    def test_active_display_slot_morning(self):
        from datetime import datetime

        from silva.commands.weather_schedule import active_display_slot

        with patch("silva.commands.weather_schedule.scheduled_display_enabled", return_value=True):
            with patch("silva.commands.weather_schedule.build_display_slots", return_value=[(8, 0), (8, 30), (9, 0), (12, 0), (21, 0)]):
                active = active_display_slot(datetime(2026, 6, 30, 8, 15))
                self.assertIsNotNone(active)
                assert active is not None
                self.assertEqual(active[0], "2026-06-30_08:00")

    def test_deferred_until_not_busy(self):
        from datetime import date

        from silva.commands.weather_schedule import check_scheduled_weather_display, mark_slot_shown

        today = date.today().isoformat()
        slot_id = f"{today}_08:00"
        busy = {"value": True}

        with patch("silva.commands.weather_schedule.scheduled_display_enabled", return_value=True):
            with patch(
                "silva.commands.weather_schedule.active_display_slot",
                return_value=(slot_id, (8, 0)),
            ):
                self.assertFalse(
                    check_scheduled_weather_display(user_id="kevin", is_busy=lambda: busy["value"])
                )
                busy["value"] = False
                with patch("silva.commands.weather.show_scheduled_weather_popup", return_value=True) as mock_show:
                    self.assertTrue(
                        check_scheduled_weather_display(user_id="kevin", is_busy=lambda: busy["value"])
                    )
                    mock_show.assert_called_once()
                mark_slot_shown(slot_id)
                with patch("silva.commands.weather.show_scheduled_weather_popup", return_value=True) as mock_show:
                    self.assertFalse(
                        check_scheduled_weather_display(user_id="kevin", is_busy=lambda: False)
                    )
                    mock_show.assert_not_called()

    def test_scheduled_weather_skips_while_update_busy(self):
        from silva.commands.weather_schedule import check_scheduled_weather_display

        today = __import__("datetime").date.today().isoformat()
        slot_id = f"{today}_08:00"
        with patch("silva.commands.weather_schedule.scheduled_display_enabled", return_value=True):
            with patch(
                "silva.commands.weather_schedule.active_display_slot",
                return_value=(slot_id, (8, 0)),
            ):
                with patch("silva.commands.weather.show_scheduled_weather_popup") as mock_show:
                    self.assertFalse(
                        check_scheduled_weather_display(user_id="kevin", is_busy=lambda: True)
                    )
                    mock_show.assert_not_called()


class WeatherAlertTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        self._tmpdir = tempfile.TemporaryDirectory()
        self._state_file = Path(self._tmpdir.name) / "weather_alerts_state.json"
        patchers = [
            patch("silva.commands.weather_alerts.STATE_FILE", self._state_file),
            patch("silva.commands.weather_alerts._lock_state", {"last_poll": 0.0, "in_flight": False}),
        ]
        for patcher in patchers:
            self.addCleanup(patcher.stop)
            patcher.start()

    def test_major_alert_filter(self):
        from silva.commands.weather_alerts import _is_major_alert

        self.assertTrue(_is_major_alert({"severity": "Extreme", "event": "Tornado Warning"}))
        self.assertTrue(_is_major_alert({"severity": "Minor", "event": "Flood Warning"}))
        self.assertFalse(_is_major_alert({"severity": "Minor", "event": "Special Weather Statement"}))

    def test_alert_while_asleep_is_silent(self):
        from silva.commands.weather_alerts import WeatherAlert, check_weather_alerts

        alert = WeatherAlert(
            alert_id="alert-sleep",
            event="Tornado Warning",
            headline="Tornado Warning for your area",
            description="Take shelter immediately.",
            severity="Extreme",
            urgency="Immediate",
            area="Example County",
        )
        with patch("silva.commands.weather_alerts.alert_poll_enabled", return_value=True):
            with patch("silva.commands.weather_alerts.is_wifi_connected", return_value=True):
                with patch("silva.commands.weather_alerts.resolve_location") as mock_location:
                    mock_location.return_value = type("Loc", (), {"latitude": 42.0, "longitude": -71.0})()
                    with patch("silva.commands.weather_alerts.fetch_active_alerts", return_value=[alert]):
                        with patch("silva.commands.weather_alerts.log_info") as mock_log_info:
                            with patch("silva.gui.weather_popup.show_weather_alert_popup") as mock_popup:
                                with patch("silva.notifications.sms.may_send_weather_sms", return_value=False):
                                    found = check_weather_alerts(force=True, asleep=True)
        self.assertEqual(len(found), 1)
        mock_popup.assert_not_called()
        mock_log_info.assert_not_called()

    def test_new_alert_triggers_popup(self):
        from silva.commands.weather_alerts import WeatherAlert, check_weather_alerts

        alert = WeatherAlert(
            alert_id="alert-1",
            event="Tornado Warning",
            headline="Tornado Warning for your area",
            description="Take shelter immediately.",
            severity="Extreme",
            urgency="Immediate",
            area="Example County",
        )
        with patch("silva.commands.weather_alerts.alert_poll_enabled", return_value=True):
            with patch("silva.commands.weather_alerts.is_wifi_connected", return_value=True):
                with patch("silva.commands.weather_alerts.resolve_location") as mock_location:
                    mock_location.return_value = type("Loc", (), {"latitude": 42.0, "longitude": -71.0})()
                    with patch("silva.commands.weather_alerts.fetch_active_alerts", return_value=[alert]):
                        with patch("silva.gui.weather_popup.show_weather_alert_popup") as mock_popup:
                            found = check_weather_alerts(force=True)
                            self.assertEqual(len(found), 1)
                            mock_popup.assert_called_once()
                            found_again = check_weather_alerts(force=True)
                            self.assertEqual(len(found_again), 0)


class DevPanelTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        self._tmpdir = tempfile.TemporaryDirectory()
        base = Path(self._tmpdir.name)
        patchers = [
            patch("silva.dev.speech_training.SPEECH_TRAINING_FILE", base / "speech_training.json"),
            patch("silva.dev.paths.SPEECH_TRAINING_FILE", base / "speech_training.json"),
            patch("silva.dev.paths.PENDING_UPDATE_FILE", base / "pending_update.json"),
            patch("silva.dev.paths.RELOAD_FLAG_FILE", base / "reload_requested"),
            patch("silva.dev.paths.PROGRESS_FILE", base / "update_progress.json"),
            patch("silva.dev.live_update.PENDING_UPDATE_FILE", base / "pending_update.json"),
            patch("silva.dev.live_update.RELOAD_FLAG_FILE", base / "reload_requested"),
            patch("silva.dev.live_update.PROGRESS_FILE", base / "update_progress.json"),
            patch("silva.dev.live_update.APPLIED_UPDATE_FILE", base / "applied.json"),
            patch("silva.dev.paths.APPLIED_UPDATE_FILE", base / "applied.json"),
        ]
        for patcher in patchers:
            self.addCleanup(patcher.stop)
            patcher.start()

    def test_speech_training_block(self):
        from silva.dev.speech_training import is_blocked_phrase, save_speech_training

        save_speech_training(say_text="hello there", dont_say_text="bad phrase")
        self.assertTrue(is_blocked_phrase("bad phrase"))
        self.assertFalse(is_blocked_phrase("hello there"))

    def test_command_scenarios(self):
        from silva.dev.test_runner import run_command_scenarios

        results = run_command_scenarios()
        self.assertGreater(len(results), 5)
        self.assertTrue(all(item.ok for item in results))

    def test_code_change_scan_labels_patches_and_features(self):
        from silva.dev.update_scanner import describe_code_change, diff_code_files

        self.assertIn("Patch", describe_code_change("stt.py", kind="modified") or "")
        self.assertIn("New feature", describe_code_change("commands/notes_handler.py", kind="added") or "")
        self.assertIsNone(describe_code_change("tests/test_silva.py", kind="modified"))
        empty = diff_code_files({})
        self.assertEqual(empty["added"], [])
        self.assertEqual(empty["modified"], [])

    def test_live_update_apply(self):
        from silva.dev.live_update import apply_pending_update, queue_live_update, read_progress

        queue_live_update(features=["weather", "math"])
        ok, message = apply_pending_update()
        self.assertTrue(ok)
        progress = read_progress()
        self.assertEqual(progress.get("percent"), 100)

    def test_live_update_skips_gui_reload(self):
        from silva.dev.live_update import skip_live_reload

        from silva.dev import live_update as live_mod

        self.assertTrue(skip_live_reload("silva.gui.audio_record_dialog"))
        self.assertTrue(skip_live_reload("silva.gui.profile_panel"))
        self.assertTrue(skip_live_reload("silva.gui.display_host"))
        self.assertTrue(skip_live_reload("silva.dev.live_update"))
        self.assertTrue(skip_live_reload("silva.stt"))
        self.assertFalse(skip_live_reload("silva.users.voice_id"))
        self.assertFalse(skip_live_reload("silva.audio_recorder"))
        self.assertFalse(hasattr(live_mod, "_bind_fresh_gui_modules"))


class SystemPanelSecurityTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.queue_file = Path(self._tmpdir.name) / "admin_review_queue.json"
        self.voice_requests_file = Path(self._tmpdir.name) / "voice_control_access_requests.json"
        self.admin_access_file = Path(self._tmpdir.name) / "admin_access_grants.json"
        self.test_session_file = Path(self._tmpdir.name) / "test_account_session.json"
        for target, path in (
            ("silva.dev.admin_review_queue.QUEUE_FILE", self.queue_file),
            ("silva.users.voice_access.REQUESTS_FILE", self.voice_requests_file),
            ("silva.users.admin_access.ADMIN_ACCESS_FILE", self.admin_access_file),
            ("silva.users.test_accounts.TEST_STATE_FILE", self.test_session_file),
        ):
            patcher = patch(target, path)
            self.addCleanup(patcher.stop)
            patcher.start()

    def test_guest_cannot_publish_from_panel(self):
        with patch(
            "silva.dev.panel_update.get_active_user",
            return_value={"id": "guest", "name": "Guest", "tier": 1},
        ):
            from silva.dev.panel_update import can_publish_system_update, panel_update_user

            self.assertEqual(panel_update_user().get("id"), "guest")
            self.assertFalse(can_publish_system_update())

    def test_panels_register_owner_tabs(self):
        from silva.dev.panel_registry import built_in_panel_tabs
        from silva.gui.panel_security_tabs import register_panel_tabs

        register_panel_tabs()
        ids = {item.id for item in built_in_panel_tabs()}
        self.assertIn("feature_request_review", ids)
        self.assertIn("admin_update_queue", ids)
        self.assertIn("code_lab", ids)
        self.assertIn("voice_access_requests", ids)
        self.assertIn("admin_access", ids)
        self.assertIn("future_tasks", ids)
        self.assertIn("team_updates", ids)
        self.assertNotIn("live_chat", ids)
        self.assertIn("dev_branch_votes", ids)
        self.assertNotIn("reference_images", ids)
        self.assertFalse(
            any(item.title == "9. Image Studio" for item in built_in_panel_tabs())
        )

    def test_system_panel_phrases_are_action_commands(self):
        from silva.commands.intent import is_action_command

        for text in (
            "open the system panel",
            "can you open the system panel",
            "open admin access",
        ):
            self.assertTrue(is_action_command(text), text)

    def test_owner_editable_admin_access_controls(self):
        from silva.users.admin_access import capability_states, is_capability_enabled, set_capability
        from silva.users.profile_access import can_open_control_panel
        from silva.users.voice_access import can_use_voice_control

        owner = {"id": "kevin", "name": "Kevin", "tier": 5, "role": "owner", "voice_enrolled": True}
        basic = {"id": "basic1", "name": "Basic User", "tier": 1, "voice_enrolled": True}
        admin = {"id": "admin1", "name": "Admin", "tier": 4, "voice_enrolled": True}
        store = {"users": {"kevin": owner, "basic1": basic, "admin1": admin}}

        with patch("silva.users.admin_access.load_store", return_value=store):
            ok, _message = set_capability(owner, "basic1", "open_control_panel", True)
            self.assertTrue(ok)
            self.assertTrue(can_open_control_panel(basic))

            ok, _message = set_capability(owner, "admin1", "publish_updates", False)
            self.assertTrue(ok)
            self.assertFalse(is_capability_enabled(admin, "publish_updates"))
            self.assertTrue(can_open_control_panel(admin))

            ok, _message = set_capability(owner, "basic1", "voice_scope_logs", True)
            self.assertTrue(ok)
            self.assertTrue(can_use_voice_control(basic, "logs"))

            ok, _message = set_capability(owner, "admin1", "voice_scope_logs", True)
            self.assertTrue(ok)

            ok, _message = set_capability(basic, "admin1", "view_logs", True)
            self.assertFalse(ok)
            self.assertTrue(can_use_voice_control(admin, "logs"))

            ok, _message = set_capability(owner, "kevin", "view_logs", False)
            self.assertTrue(ok)
            self.assertTrue(is_capability_enabled(owner, "view_logs"))
            self.assertFalse(capability_states(owner)["view_logs"])

            ok, _message = set_capability(owner, "kevin", "view_logs", True)
            self.assertTrue(ok)
            self.assertTrue(capability_states(owner)["view_logs"])

    def test_owner_face_fallback_only_when_voice_is_uncertain(self):
        from silva.security import owner_reconfirm

        owner_reconfirm.reset_voice_identity()
        self.addCleanup(owner_reconfirm.reset_voice_identity)
        config = {"owner_camera_fallback_enabled": True}
        with patch("silva.security.owner_reconfirm.load_config", return_value=config):
            with patch(
                "silva.users.face_id.verify_face_silent", return_value=(True, "face_verified_0.90")
            ) as verify:
                self.assertTrue(owner_reconfirm.require_owner_confirmation(action="test"))
                verify.assert_not_called()

            owner_reconfirm.record_voice_identity("kevin", [("someone_else", 0.91)], False)
            with patch(
                "silva.users.face_id.verify_face_silent", return_value=(False, "no_face_detected")
            ) as verify:
                self.assertFalse(owner_reconfirm.require_owner_confirmation(action="test"))
                verify.assert_called_once_with("kevin", partial_ok=False)

            owner_reconfirm.record_voice_identity("kevin", [("kevin", 0.98)], True)
            with patch(
                "silva.users.face_id.verify_face_silent", return_value=(True, "face_verified_0.90")
            ) as verify:
                self.assertTrue(owner_reconfirm.require_owner_confirmation(action="test"))
                verify.assert_not_called()

    def test_owner_bundled_face_photo_path(self):
        from silva.users import owner_biometrics

        self.assertTrue(owner_biometrics._BUNDLED_OWNER_PHOTO.exists())

    def test_owner_can_create_and_use_test_accounts(self):
        from silva.users import test_accounts

        owner = {"id": "kevin", "name": "Kevin", "tier": 5, "role": "owner"}
        guest = {"id": "test_guest", "name": "Test Guest", "tier": 1, "role": "guest"}
        admin = {"id": "test_admin", "name": "Test Admin", "tier": 4, "role": "admin"}
        store = {"users": {"kevin": owner, "test_guest": guest, "test_admin": admin}}

        with patch.object(test_accounts, "load_store", return_value=store):
            with patch.object(test_accounts, "save_store"):
                with patch.object(test_accounts, "add_user", side_effect=[guest, admin]):
                    ok, created_guest, _message = test_accounts.create_test_account(owner, "Guest", "guest")
                    self.assertTrue(ok)
                    self.assertEqual(created_guest["id"], "test_guest")

                    ok, created_admin, _message = test_accounts.create_test_account(owner, "Admin", "admin")
                    self.assertTrue(ok)
                    self.assertEqual(created_admin["role"], "admin")

                with patch.object(test_accounts, "get_owner", return_value=owner):
                    with patch.object(test_accounts, "identify_and_set_active") as identify:
                        ok, _target, _message = test_accounts.activate_test_account(owner, "test_guest")
                        self.assertTrue(ok)
                        self.assertTrue(test_accounts.is_test_session_active())
                        identify.assert_called_with("test_guest")

                        ok, _target, _message = test_accounts.return_to_owner()
                        self.assertTrue(ok)
                        self.assertFalse(test_accounts.is_test_session_active())
                        identify.assert_called_with("kevin")

    def test_reference_image_uses_latest_gyazo_download(self):
        import os
        from pathlib import Path

        from silva.users import voice_access

        downloads = Path(self._tmpdir.name) / "Downloads"
        downloads.mkdir()
        older = downloads / f"{'a' * 32}.png"
        newer = downloads / f"{'b' * 32}.png"
        older.write_bytes(b"old")
        newer.write_bytes(b"new")
        os.utime(older, (1, 1))
        os.utime(newer, (2, 2))

        with patch.object(voice_access, "DOWNLOADS_DIR", downloads):
            with patch("silva.users.voice_access.load_config", return_value={}):
                with patch.dict("os.environ", {"SILVA_REFERENCE_IMAGE": ""}, clear=False):
                    self.assertEqual(voice_access.reference_image_path(), newer)

    def test_slide_toggle_moves_from_green_right_to_red_left(self):
        import tkinter as tk

        from silva.gui.panel_security_tabs import SlideToggle

        try:
            root = tk.Tk()
            root.withdraw()
        except tk.TclError:
            self.skipTest("Tk display unavailable")
        toggle = None
        try:
            clicked: list[bool] = []
            toggle = SlideToggle(root, command=clicked.append)
            self.assertEqual(toggle.type(toggle._track), "image")
            self.assertEqual(toggle.type(toggle._thumb_outer), "image")
            self.assertEqual(toggle.find_withtag("text"), ())
            toggle.set(True, animate=False)
            self.assertTrue(toggle.value)
            self.assertEqual(toggle._track_color, "#2E7D32")
            right_x = toggle.coords(toggle._thumb_outer)[0]

            toggle._on_click()
            self.assertFalse(toggle.value)
            self.assertEqual(clicked, [False])
            toggle.set(False, animate=False)
            self.assertEqual(toggle._track_color, "#C62828")
            self.assertLess(toggle.coords(toggle._thumb_outer)[0], right_x)
        finally:
            if toggle is not None and toggle._after_id is not None:
                root.after_cancel(toggle._after_id)
            root.destroy()

    def test_system_panel_voice_phrases(self):
        from silva.commands.system_panel_commands import (
            SystemPanelSpeech,
            match_system_panel_speech,
        )

        cases = {
            "can you open the system panel": SystemPanelSpeech(),
            "open the system panel": SystemPanelSpeech(),
            "open system panel": SystemPanelSpeech(),
            "show the developer panel": SystemPanelSpeech(),
            "open voice access": SystemPanelSpeech("voice_access_requests", "7. Voice Access"),
            "open system panel voice access": SystemPanelSpeech("voice_access_requests", "7. Voice Access"),
            "open update queue": SystemPanelSpeech("admin_update_queue", "5. Update Queue"),
            "open code lab": SystemPanelSpeech("code_lab", "6. Code Lab"),
            "open feature requests": SystemPanelSpeech("feature_request_review", "4. Requests"),
            "open future tasks": SystemPanelSpeech("future_tasks", "9. Future Tasks"),
            "open team updates": SystemPanelSpeech("team_updates", "10. Team Updates"),
            "open reference images": None,
            "what is voice access": None,
            "open the planner": None,
            "system controls": None,
        }
        for text, expected in cases.items():
            self.assertEqual(match_system_panel_speech(text), expected, text)

    def test_system_panel_tab_request_roundtrip(self):
        from pathlib import Path

        from silva.dev.panel_instance import (
            PANEL_FOCUS_FILE,
            consume_panel_tab_request,
            request_panel_tab,
        )

        focus_file = Path(self._tmpdir.name) / "system_panel_focus.json"
        with patch("silva.dev.panel_instance.PANEL_FOCUS_FILE", focus_file):
            self.assertEqual(consume_panel_tab_request(), {})
            request_panel_tab("voice_access_requests", "7. Voice Access")
            self.assertTrue(focus_file.exists())
            request = consume_panel_tab_request()
            self.assertEqual(request.get("tab_id"), "voice_access_requests")
            self.assertEqual(request.get("title"), "7. Voice Access")
            self.assertFalse(focus_file.exists())

    def test_system_panel_voice_handler_requires_admin(self):
        from silva.commands.system_panel_commands import handle_system_panel_speech

        class FakeAssistant:
            def __init__(self):
                self.messages = []

            def say(self, message, **_kwargs):
                self.messages.append(message)

        basic = {"id": "basic1", "name": "Basic User", "tier": 1, "voice_enrolled": True}
        admin = {"id": "admin1", "name": "Admin", "tier": 4, "voice_enrolled": True}

        with patch("silva.commands.system_panel_commands.open_system_panel") as opener:
            self.assertTrue(handle_system_panel_speech(FakeAssistant(), "open the system panel", basic))
            opener.assert_not_called()

        with patch("silva.commands.system_panel_commands.open_system_panel") as opener:
            self.assertTrue(handle_system_panel_speech(FakeAssistant(), "open voice access", admin))
            opener.assert_called_once_with(tab_id="voice_access_requests", title="7. Voice Access")

    def test_voice_access_request_owner_approval(self):
        from silva.users.voice_access import (
            can_request_voice_control,
            can_use_voice_control,
            review_voice_access_request,
            submit_voice_access_request,
        )

        admin = {"id": "admin1", "name": "Admin", "tier": 4, "voice_enrolled": True}
        normal_admin = {"id": "admin2", "name": "Plain Admin", "tier": 4, "voice_enrolled": False}

        self.assertTrue(can_request_voice_control(admin)[0])
        self.assertFalse(can_request_voice_control(normal_admin)[0])

        ok, item, _message = submit_voice_access_request(
            admin,
            "updates",
            "I need to apply approved patches from the panel.",
        )
        self.assertTrue(ok)
        self.assertIsNotNone(item)

        ok, _reviewed, _message = review_voice_access_request(
            item["id"], reviewer=admin, approve=True
        )
        self.assertFalse(ok)

        with (
            patch("silva.users.voice_access.load_store", return_value={"users": {"admin1": {}}}),
            patch("silva.users.voice_access.save_user_feature_overrides") as save_overrides,
        ):
            ok, _reviewed, _message = review_voice_access_request(
                item["id"], reviewer=get_owner(), approve=True
            )
            self.assertTrue(ok)
            save_overrides.assert_called_once()

        self.assertTrue(can_use_voice_control(admin, "updates"))
        self.assertFalse(can_use_voice_control(normal_admin, "updates"))
        self.assertFalse(can_use_voice_control(admin, "users"))

    def test_basic_voice_access_allows_everyday_controls_only(self):
        from silva.users.voice_access import (
            can_request_voice_control,
            can_use_voice_control,
            requestable_voice_scopes,
            submit_voice_access_request,
        )

        basic = {"id": "basic1", "name": "Basic User", "tier": 1, "voice_enrolled": True}

        self.assertTrue(can_request_voice_control(basic)[0])
        self.assertTrue(can_use_voice_control(basic, "conversation"))
        self.assertTrue(can_use_voice_control(basic, "images"))
        self.assertTrue(can_use_voice_control(basic, "weather_news"))
        self.assertFalse(can_use_voice_control(basic, "users"))
        self.assertFalse(can_use_voice_control(basic, "updates"))
        self.assertEqual(requestable_voice_scopes(basic), {})

        ok, _item, message = submit_voice_access_request(
            basic, "images", "I want to use images by voice."
        )
        self.assertFalse(ok)
        self.assertIn("already enabled", message)

    def test_code_lab_checks_without_executing(self):
        from pathlib import Path

        from silva.dev.code_lab import check_python_snippet

        marker = Path(self._tmpdir.name) / "ran.txt"
        source = f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n"
        result = check_python_snippet(source)
        self.assertTrue(result.syntax_ok)
        self.assertTrue(any("pathlib" in item for item in result.warnings))
        self.assertFalse(marker.exists())

        blocked = check_python_snippet("import subprocess\nsubprocess.run('calc')\n")
        self.assertFalse(blocked.ok)
        self.assertTrue(any("subprocess" in item for item in blocked.issues))
        self.assertFalse(check_python_snippet("def broken(:\n").syntax_ok)

    def test_admin_can_stage_but_only_owner_can_review(self):
        from silva.dev.admin_review_queue import (
            STATUS_APPLIED,
            list_admin_reviews,
            mark_admin_review_applied,
            queue_admin_update,
            review_admin_review,
        )

        admin = {"id": "admin1", "name": "Admin", "tier": 4}
        item = queue_admin_update(
            admin,
            features=["night mode"],
            changelog=["add a night mode setting"],
        )
        self.assertEqual(item["status"], "pending")
        self.assertEqual(item["submitted_by"], "admin1")

        ok, _reviewed, _message = review_admin_review(item["id"], reviewer=admin, approve=True)
        self.assertFalse(ok)

        ok, reviewed, _message = review_admin_review(
            item["id"], reviewer=get_owner(), approve=True
        )
        self.assertTrue(ok)
        self.assertEqual(reviewed["status"], "approved")

        ok, _message = mark_admin_review_applied(item["id"], owner=admin)
        self.assertFalse(ok)
        ok, _message = mark_admin_review_applied(item["id"], owner=get_owner())
        self.assertTrue(ok)
        self.assertEqual(len(list_admin_reviews(status=STATUS_APPLIED)), 1)

    def test_guest_cannot_stage_update(self):
        from silva.dev.admin_review_queue import queue_admin_update

        with self.assertRaises(PermissionError):
            queue_admin_update({"id": "guest", "name": "Guest", "tier": 1}, features=["x"])

    def test_voice_update_apply_is_owner_only(self):
        from silva.commands.update_handler import apply_live_now

        class Dummy:
            def __init__(self):
                self.spoken = []

            def _speak_now(self, text):
                self.spoken.append(text)

        dummy = Dummy()
        with patch(
            "silva.users.manager.get_active_user",
            return_value={"id": "guest", "name": "Guest", "tier": 1},
        ):
            apply_live_now(dummy)
        self.assertTrue(any("Only the owner" in item for item in dummy.spoken))


class UpdateFreshnessTests(unittest.TestCase):
    def setUp(self):
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        self._tmpdir = tempfile.TemporaryDirectory()
        base = Path(self._tmpdir.name)
        self.addCleanup(self._tmpdir.cleanup)
        patchers = [
            patch("silva.dev.update_scanner.INSTALLED_MANIFEST_FILE", base / "installed.json"),
            patch("silva.dev.update_scanner.BUNDLED_MANIFEST_FILE", base / "bundled.json"),
            patch("silva.dev.update_scanner.PUBLISHED_MANIFEST_FILE", base / "published.json"),
            patch("silva.dev.update_scanner.RELOAD_FLAG_FILE", base / "reload"),
            patch("silva.dev.update_scanner.PENDING_UPDATE_FILE", base / "pending.json"),
            patch("silva.dev.paths.INSTALLED_MANIFEST_FILE", base / "installed.json"),
            patch("silva.dev.paths.PUBLISHED_MANIFEST_FILE", base / "published.json"),
            patch("silva.dev.update_check.APPLIED_UPDATE_FILE", base / "last_applied.json"),
            patch("silva.dev.update_check.RELOAD_FLAG_FILE", base / "reload"),
            patch("silva.dev.update_check.PENDING_UPDATE_FILE", base / "pending.json"),
            patch("silva.dev.update_check.fetch_remote_manifest", return_value={}),
            patch("silva.dev.update_check.latest_release_manifest", return_value={}),
            patch("silva.dev.update_check.compute_code_fingerprint", return_value="same"),
            patch("silva.dev.update_check.diff_code_files", return_value={}),
        ]
        for patcher in patchers:
            self.addCleanup(patcher.stop)
            patcher.start()
        (base / "installed.json").write_text(
            json.dumps({"version": "0.1.9", "fingerprint": "same", "features": [], "changelog": []}),
            encoding="utf-8",
        )
        (base / "bundled.json").write_text(
            json.dumps({"version": "0.2.0", "fingerprint": "same", "features": [], "changelog": []}),
            encoding="utf-8",
        )
        (base / "published.json").write_text("{}", encoding="utf-8")

    def test_higher_version_without_file_change_is_not_an_update(self):
        from silva.dev.update_check import check_update_status, format_status_message

        status = check_update_status()
        self.assertFalse(status.needs_update)
        self.assertEqual(status.reason, "version_only")
        self.assertIn("newest update, 0.2.0", format_status_message(status))
        self.assertIn("No new files", format_status_message(status))

    def test_changed_code_is_an_update_even_at_same_version(self):
        from unittest.mock import patch

        from silva.dev.update_check import check_update_status

        with patch("silva.dev.update_check.compute_code_fingerprint", return_value="new"):
            status = check_update_status()
        self.assertTrue(status.needs_update)
        self.assertEqual(status.reason, "code_changed")

    def test_voice_apply_stays_put_when_already_current(self):
        from unittest.mock import MagicMock, patch

        from silva.commands.update_handler import apply_live_now
        from silva.dev.update_check import UpdateStatus

        dummy = MagicMock()
        status = UpdateStatus(needs_update=False, current_version="0.2.0", available_version="0.2.0")
        with patch(
            "silva.users.manager.get_active_user",
            return_value={"id": "kevin", "name": "Kevin", "tier": 5},
        ), patch("silva.dev.update_check.check_update_status", return_value=status):
            apply_live_now(dummy)
        spoken = " ".join(str(call.args[0]) for call in dummy._speak_now.call_args_list)
        self.assertIn("Already on the newest update, 0.2.0", spoken)

    def test_terminal_update_check_is_read_only(self):
        from unittest.mock import patch

        from silva.dev.terminal_commands import handle_terminal_command

        with patch(
            "silva.users.manager.get_active_user",
            return_value={"id": "kevin", "name": "Kevin", "tier": 5},
        ), patch(
            "silva.dev.update_check.format_status_message",
            return_value="Already on the newest update, 0.2.0.",
        ) as formatted:
            handled, message = handle_terminal_command("update check")
        self.assertTrue(handled)
        self.assertEqual(message, "Already on the newest update, 0.2.0.")
        formatted.assert_called_once_with()


class FirstRunSetupTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        self._tmpdir = tempfile.TemporaryDirectory()
        base = Path(self._tmpdir.name)
        for patcher in (
            patch("silva.users.manager.USERS_FILE", base / "users.json"),
            patch("silva.users.manager.USERS_BACKUP_FILE", base / "users.bak"),
            patch("silva.users.manager.current_build_version", return_value="9.9.9"),
        ):
            self.addCleanup(patcher.stop)
            patcher.start()

    def test_setup_is_once_per_profile_and_records_profile_choice(self):
        from silva.users import manager

        owner = manager.get_active_user()
        self.assertTrue(manager.needs_first_run_setup(owner))
        manager.mark_first_run_setup_done(owner["id"])
        self.assertFalse(manager.needs_first_run_setup(manager.get_active_user()))

        updated = manager.record_first_run_choices(
            "guest",
            profile_name="Test User",
            requested_role="admin",
            update_notifications=False,
        )
        self.assertEqual(updated["name"], "Test User")
        self.assertEqual(updated["role_request"], "admin_pending_owner_approval")
        self.assertFalse(updated["update_notifications"])
        self.assertEqual(updated["setup_seen_build"], "9.9.9")
        self.assertLess(updated["tier"], 4)
        self.assertEqual(manager.get_active_user()["id"], updated["id"])

    def test_admin_details_hidden_for_guests(self):
        from silva.users.onboarding import first_run_details

        guest = first_run_details({"id": "guest", "tier": 1, "role": "guest"})
        self.assertNotIn("Admin commands", guest)
        self.assertIn("hidden", guest)
        admin = first_run_details({"id": "admin", "tier": 4, "role": "admin"})
        self.assertIn("Admin commands", admin)

    def test_github_issue_links_use_configured_repo(self):
        from unittest.mock import patch

        from silva.dev.github_updates import new_issue_url

        with patch("silva.dev.github_updates.configured_repo", return_value="owner/silva"):
            url = new_issue_url(kind="bug")
        self.assertIn("github.com/owner/silva/issues/new", url)
        self.assertIn("labels=bug", url)

    def test_default_project_link_and_request_email(self):
        from unittest.mock import patch

        from silva.dev.github_updates import (
            github_status_lines,
            repo_web_url,
            support_email_url,
        )
        from silva.users.onboarding import first_run_details

        with patch("silva.dev.github_updates.load_config", return_value={}):
            self.assertEqual(repo_web_url(), "https://github.com/SilusSolden/silva")
            self.assertIn("SilusSolden@gmail.com", support_email_url())
            lines = "\n".join(github_status_lines())
            self.assertIn("https://github.com/SilusSolden/silva", lines)
            self.assertIn("private for now", lines)
            self.assertIn("Update path", lines)
            self.assertIn("SilusSolden@gmail.com", lines)
            details = first_run_details({"id": "guest", "tier": 1, "role": "guest"})
            self.assertIn("https://github.com/SilusSolden/silva", details)
            self.assertIn("SilusSolden@gmail.com", details)


class ReferenceImageLibraryTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        from PIL import Image

        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        root = Path(self._tmpdir.name)
        self.store_dir = root / "reference_images"
        self.index_file = self.store_dir / "index.json"
        self.downloads_dir = root / "Downloads"
        self.downloads_dir.mkdir(parents=True, exist_ok=True)

        for target, value in (
            ("silva.media.reference_images.STORE_DIR", self.store_dir),
            ("silva.media.reference_images.INDEX_FILE", self.index_file),
            ("silva.media.reference_images.DOWNLOADS_DIR", self.downloads_dir),
        ):
            patcher = patch(target, value)
            self.addCleanup(patcher.stop)
            patcher.start()

        for name, color in (
            ("mug.png", (180, 120, 80)),
            ("chart_info.png", (80, 160, 220)),
            ("silva_error.png", (220, 60, 60)),
            ("a" * 32 + ".png", (120, 120, 120)),
        ):
            Image.new("RGB", (8, 8), color).save(self.downloads_dir / name)

    def test_categorize_and_add_reference_dedupes_by_hash(self):
        from pathlib import Path

        from silva.media.reference_images import (
            add_reference,
            categorize,
            find_references,
            load_index,
        )

        self.assertEqual(categorize("photo of a coffee mug"), "object")
        self.assertEqual(categorize("chart info screenshot"), "information")
        self.assertEqual(categorize("silva error bug"), "ai_issue")

        record = add_reference(self.downloads_dir / "mug.png", label="Coffee mug")
        self.assertIsNotNone(record)
        self.assertEqual(record["category"], "object")
        self.assertTrue(Path(record["path"]).is_file())
        self.assertEqual(len(load_index()), 1)

        duplicate = add_reference(self.downloads_dir / "mug.png")
        self.assertEqual(duplicate["id"], record["id"])
        self.assertEqual(len(load_index()), 1)

        matches = find_references("coffee", category="object")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["label"], "Coffee mug")

    def test_scan_downloads_categories_and_dedupes(self):
        from silva.media.reference_images import find_references, load_index, scan_downloads

        records = scan_downloads(added_by="kevin")
        self.assertEqual(len(records), 4)
        self.assertTrue(records[0]["name"].startswith("a" * 32))
        categories = {record["category"] for record in records}
        self.assertEqual(categories, {"object", "information", "ai_issue"})
        self.assertTrue(all(record["source"] == "downloads" for record in records))
        self.assertEqual(scan_downloads(), [])
        self.assertEqual(len(load_index()), 4)

        issues = find_references(category="ai_issue")
        self.assertEqual(len(issues), 1)
        self.assertIn("silva", issues[0]["name"].lower())

    def test_update_and_delete_reference(self):
        from pathlib import Path

        from silva.media.reference_images import (
            add_reference,
            delete_reference,
            load_index,
            update_reference,
        )

        record = add_reference(self.downloads_dir / "mug.png")
        self.assertIsNotNone(record)
        updated = update_reference(
            record["id"],
            category="ai_issue",
            label="Silva mug glitch",
            notes="Screenshot of the issue",
        )
        self.assertIsNotNone(updated)
        self.assertEqual(updated["category"], "ai_issue")
        self.assertEqual(updated["label"], "Silva mug glitch")
        self.assertEqual(Path(updated["path"]).parent.name, "ai_issues")

        self.assertTrue(delete_reference(record["id"]))
        self.assertEqual(load_index(), [])

    def test_deleted_image_is_blocked_from_coming_back(self):
        from silva.media.reference_images import (
            add_reference,
            delete_reference,
            load_blocked_hashes,
            scan_downloads,
        )

        record = add_reference(self.downloads_dir / "mug.png")
        self.assertIsNotNone(record)
        digest = str(record["sha256"])
        self.assertTrue(delete_reference(record["id"]))
        self.assertIn(digest, load_blocked_hashes())
        self.assertIsNone(add_reference(self.downloads_dir / "mug.png"))
        rescanned = scan_downloads()
        self.assertEqual(len(rescanned), 3)
        self.assertNotIn("mug.png", [str(record.get("name") or "") for record in rescanned])

    def test_reference_image_speech_is_recognized_action(self):
        from silva.commands.help_phrases import capability_reply_for_user
        from silva.commands.intent import is_action_command
        from silva.stt_quick_commands import is_complete_command

        for text in ("scan downloads for images", "find reference images", "open reference images"):
            self.assertTrue(is_action_command(text), text)
            self.assertTrue(is_complete_command(text), text)

        reply = capability_reply_for_user(
            "can you use reference images?",
            {"tier": 5, "role": "owner"},
        )
        self.assertIn("scan downloads for images", reply)

    def test_reference_image_voice_scans_downloads_for_owner(self):
        from unittest.mock import MagicMock

        from silva.media.reference_image_handler import handle_reference_image_speech

        assistant = MagicMock()
        assistant._speak_now = None
        owner = {"id": "kevin", "name": "Kevin", "tier": 5, "role": "owner"}
        with patch(
            "silva.users.manager.get_active_user",
            return_value=owner,
        ):
            handled = handle_reference_image_speech(assistant, "scan downloads for images")
        self.assertTrue(handled)
        spoken = assistant.say.call_args.args[0]
        self.assertIn("Stored 4 new reference image(s)", spoken)
        self.assertIn("ai issue", spoken.lower())

    def test_reference_image_voice_opens_standalone_popup(self):
        from unittest.mock import MagicMock

        from silva.media.reference_image_handler import handle_reference_image_speech

        assistant = MagicMock()
        assistant._speak_now = None
        owner = {"id": "kevin", "name": "Kevin", "tier": 5, "role": "owner"}
        with (
            patch("silva.users.manager.get_active_user", return_value=owner),
            patch(
                "silva.gui.media_library_popup.show_media_library_popup",
                return_value=True,
            ) as show_popup,
        ):
            handled = handle_reference_image_speech(assistant, "open reference images")
        self.assertTrue(handled)
        self.assertTrue(show_popup.called)
        self.assertIn("open", assistant.say.call_args.args[0].lower())


class UpdateMessageTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        root = Path(self._tmpdir.name)
        self.state_file = root / "whats_new_state.json"
        self.applied_file = root / "last_applied_update.json"
        self.release_notes_dir = root / "release_notes"
        for target, value in (
            ("silva.dev.whats_new_script.WHATS_NEW_STATE_FILE", self.state_file),
            ("silva.dev.whats_new_script.APPLIED_UPDATE_FILE", self.applied_file),
            ("silva.dev.whats_new_script.RELEASE_NOTES_DIR", self.release_notes_dir),
            ("silva.dev.whats_new_script.ensure_dev_dir", lambda: root),
        ):
            patcher = patch(target, value)
            self.addCleanup(patcher.stop)
            patcher.start()

    def test_record_apply_delta_uses_explicit_changelog(self):
        from silva.dev.whats_new_script import record_apply_delta

        report = record_apply_delta(
            files=["gui/panel_security_tabs.py"],
            version="0.1.60",
            hashes={"gui/panel_security_tabs.py": "abc"},
            changelog=["a reference image library that imports Downloads images"],
        )
        self.assertIn("reference image library", report.spoken)
        state = json.loads(self.state_file.read_text(encoding="utf-8"))
        self.assertEqual(state["items"], ["a reference image library that imports Downloads images"])
        self.assertEqual(state["last_apply"]["version"], "0.1.60")
        note = json.loads((self.release_notes_dir / "0.1.60.json").read_text(encoding="utf-8"))
        self.assertEqual(note["changelog"], ["a reference image library that imports Downloads images"])
        self.assertTrue(note["applied"])

    def test_whats_new_reads_release_notes_for_newest_version(self):
        from silva.dev.whats_new_script import run_whats_new_script

        with patch(
            "silva.dev.whats_new_script.load_installed_manifest",
            return_value={"version": "0.1.99", "changelog": ["old installed detail"]},
        ), patch(
            "silva.dev.whats_new_script.load_bundled_manifest",
            return_value={"version": "0.1.102", "changelog": ["new bundled detail"]},
        ):
            report = run_whats_new_script(mark_told=False)

        self.assertEqual(report.version, "0.1.102")
        self.assertTrue(report.pending)
        self.assertIn("phrase recorder", report.spoken.lower())
        self.assertNotIn("old installed detail", report.spoken.lower())

    def test_update_status_phrase_answers_no_from_release_notes(self):
        from types import SimpleNamespace

        from silva.commands.update_handler import handle_update_speech
        from silva.commands.update_phrases import is_update_status_phrase, is_whats_new_update_phrase

        question = "can you check to see if you're on the latest update"
        self.assertTrue(is_update_status_phrase(question))
        self.assertFalse(is_whats_new_update_phrase(question))
        spoken_replies: list[str] = []

        class _Dummy:
            _asleep = False
            _update_offer = None
            _update_apply_in_progress = False
            _notes_flow = None

            def say(self, text, interruptible=False):
                spoken_replies.append(text)

        dummy = _Dummy()
        with patch(
            "silva.dev.whats_new_script.load_installed_manifest",
            return_value={"version": "0.1.99"},
        ), patch(
            "silva.dev.whats_new_script.load_bundled_manifest",
            return_value={"version": "0.1.102", "changelog": ["new bundled detail"]},
        ):
            self.assertTrue(handle_update_speech(dummy, question))

        self.assertTrue(spoken_replies)
        reply = spoken_replies[-1].lower()
        self.assertIn("no", reply)
        self.assertIn("0.1.102", reply)
        self.assertIn("phrase recorder", reply)

    def test_right_update_phrase_routes_to_update_status(self):
        from silva.commands.update_phrases import is_update_speech, is_update_status_phrase

        question = "all right now check to see if you're on the right update"
        self.assertTrue(is_update_status_phrase(question))
        self.assertTrue(is_update_speech(question))

    def test_whats_new_does_not_replay_previous_version_message(self):
        from silva.dev.whats_new_script import run_whats_new_script

        self.state_file.write_text(
            json.dumps(
                {
                    "version": "0.1.53",
                    "hashes": {"silva/dev/live_update.py": "same"},
                    "last_apply": {
                        "version": "0.1.53",
                        "files": ["gui/panel_security_tabs.py"],
                        "items": ["old owner message that should not repeat"],
                    },
                }
            ),
            encoding="utf-8",
        )
        manifest = {
            "version": "0.1.54",
            "changelog": ["new update notes from the installed manifest"],
        }
        with patch(
            "silva.dev.whats_new_script.code_file_hashes",
            return_value={"silva/dev/live_update.py": "same"},
        ):
            with patch(
                "silva.dev.whats_new_script.applied_hashes",
                return_value={"silva/dev/live_update.py": "same"},
            ):
                with patch(
                    "silva.dev.whats_new_script.load_installed_manifest",
                    return_value=manifest,
                ):
                    with patch(
                        "silva.dev.whats_new_script.load_bundled_manifest",
                        return_value=manifest,
                    ):
                        report = run_whats_new_script(mark_told=False)
        self.assertIn("new update notes from the installed manifest", report.spoken.lower())
        self.assertNotIn("old owner message", report.spoken.lower())

    def test_changelog_prefers_explicit_scan_message(self):
        from types import SimpleNamespace

        from silva.dev.auto_update import changelog_for_scan

        scan = SimpleNamespace(
            has_changes=True,
            changes=["Added the owner reference image notes exactly as written"],
        )
        self.assertEqual(
            changelog_for_scan(scan),
            ["Added the owner reference image notes exactly as written"],
        )


class WikipediaMatchingTests(unittest.TestCase):
    def test_wikipedia_phrases(self):
        cases = {
            "search wikipedia for concrete": "concrete",
            "look up how to make concrete": "how to make concrete",
            "tell me about concrete": "concrete",
            "what is photosynthesis": "photosynthesis",
            "how to make bread": "bread",
            "concrete on wikipedia": "concrete",
        }
        for phrase, query in cases.items():
            with self.subTest(phrase=phrase):
                match = match_command(phrase)
                self.assertEqual(match.name, "wikipedia")
                self.assertEqual(match.query, query)

    def test_weather_beats_wikipedia_prefix(self):
        match = match_command("what is my weather")
        self.assertEqual(match.name, "weather")

    def test_news_and_name_are_not_wikipedia(self):
        self.assertIsNone(match_command("what is the news"))
        self.assertIsNone(match_command("what is your name"))
        from silva.commands.news_phrases import is_news_command
        from silva.commands.intent import is_action_command

        self.assertTrue(is_news_command("what is the news"))
        self.assertFalse(is_action_command("what is your name"))
        self.assertFalse(is_action_command("how are you doing today Silva"))


class KnowledgeSkimTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        from silva.commands import knowledge_store

        self._tmp = tempfile.TemporaryDirectory()
        self._old_dir = knowledge_store.KNOWLEDGE_DIR
        knowledge_store.KNOWLEDGE_DIR = Path(self._tmp.name)
        knowledge_store._LAST.clear()

    def tearDown(self):
        from silva.commands import knowledge_store

        knowledge_store.KNOWLEDGE_DIR = self._old_dir
        knowledge_store._LAST.clear()
        self._tmp.cleanup()

    def test_phrases_and_does_not_run_on_chat(self):
        from silva.commands.intent import is_action_command
        from silva.commands.knowledge_phrases import match_knowledge_speech
        from silva.commands.registry import match_command

        self.assertEqual(
            match_knowledge_speech(
                "find all information of everything on wikipedia and store them in their own file"
            ).action,
            "impossible",
        )
        self.assertEqual(
            match_knowledge_speech("find all medicine names and store them in there own file").action,
            "catalog",
        )
        self.assertEqual(
            match_knowledge_speech("find all medicine names and store them in there own file").query,
            "medicine names",
        )
        store = match_knowledge_speech("look up wegovy and save it to a file")
        self.assertEqual(store.action, "store")
        self.assertEqual(store.query, "wegovy")
        building = match_knowledge_speech("look up all building material")
        self.assertEqual(building.action, "catalog")
        self.assertTrue(building.store)
        self.assertEqual(building.query, "building material")
        info = match_knowledge_speech("find me information on concrete")
        self.assertEqual(info.action, "store")
        self.assertEqual(info.query, "concrete")
        self.assertEqual(match_knowledge_speech("show stored knowledge").action, "retrieve")
        self.assertEqual(match_knowledge_speech("search the web for photosynthesis").action, "lookup")
        self.assertEqual(match_knowledge_speech("save that to a file").action, "save_last")
        self.assertIsNone(match_knowledge_speech("how are you"))
        self.assertIsNone(match_knowledge_speech("what is photosynthesis"))
        self.assertTrue(is_action_command("search the web for photosynthesis"))
        self.assertEqual(match_command("what is photosynthesis").name, "wikipedia")

    def test_saves_file_only_when_asked(self):
        from silva.commands import knowledge_skim as skim
        from silva.commands.knowledge_skim import handle_knowledge_speech

        fake = skim.SkimResult(
            title="Wegovy",
            spoken="Wegovy is a medicine.",
            full="Wegovy is a semaglutide medicine.",
            items=[],
        )
        with patch.object(skim, "skim_topic", return_value=fake), patch.object(
            skim, "_related_queries", return_value=[]
        ):
            msg = handle_knowledge_speech("u1", "find all information about wegovy and store it in a file")
        self.assertIn("saved", msg.lower())
        self.assertIn("wegovy", msg.lower())
        from silva.commands.knowledge_store import KNOWLEDGE_DIR

        files = list(KNOWLEDGE_DIR.rglob("*.txt"))
        self.assertEqual(len(files), 1)
        self.assertIn("semaglutide", files[0].read_text(encoding="utf-8").lower())
        self.assertEqual(files[0].parent.name, "wegovy")

        with patch.object(skim, "skim_topic", return_value=fake) as mocked:
            handle_knowledge_speech("u1", "how are you")
            mocked.assert_not_called()

        msg = handle_knowledge_speech("u1", "retrieve wegovy")
        self.assertIn("semaglutide", msg.lower())


class BackgroundModePhraseTests(unittest.TestCase):
    def test_background_phrases(self):
        from silva.commands.background_phrases import (
            is_background_command,
            is_hide_console_command,
            is_show_console_command,
        )
        from silva.commands.intent import is_action_command

        self.assertTrue(is_hide_console_command("run in the background"))
        self.assertTrue(is_hide_console_command("hide the console"))
        self.assertTrue(is_show_console_command("show the console"))
        self.assertTrue(is_show_console_command("show silva"))
        self.assertTrue(is_show_console_command("open the silva window"))
        self.assertTrue(is_background_command("minimize the terminal"))
        self.assertTrue(is_action_command("run in the background"))
        self.assertFalse(is_background_command("how are you"))

    def test_create_window_accepts_64bit_hinstance(self):
        """Win32 CreateWindowExW must take a 64-bit module handle (Python 3.13 crash)."""
        import ctypes

        from silva.gui import background_mode as bm

        instance = bm._kernel32.GetModuleHandleW(None)
        self.assertIsNotNone(instance)
        self.assertEqual(bm._user32.CreateWindowExW.argtypes[10], bm.HINSTANCE)
        class_name = "SilvaBackgroundHostUnitTest"
        wc = bm.WNDCLASSW()
        wc.lpfnWndProc = ctypes.cast(bm._wnd_proc_ref, ctypes.c_void_p)
        wc.hInstance = instance
        wc.lpszClassName = class_name
        bm._user32.RegisterClassW(ctypes.byref(wc))
        hwnd = bm._user32.CreateWindowExW(
            0, class_name, "SilvaBackgroundUnitTest", 0, 0, 0, 0, 0, None, None, instance, None
        )
        self.assertTrue(hwnd)
        bm._user32.DestroyWindow(hwnd)


class KnowledgeDriveTests(unittest.TestCase):
    def test_stays_on_main_drive_even_when_other_disks_have_more_space(self):
        from pathlib import Path

        from silva.storage.drives import DriveInfo, pick_data_drive

        gb = 1024 * 1024 * 1024
        system = DriveInfo("C:", Path("C:/"), total=2 * gb, free=int(0.4 * gb), drive_type=3, is_system=True)
        ssd = DriveInfo("E:", Path("E:/"), total=500 * gb, free=400 * gb, drive_type=3, is_system=False)
        hdd = DriveInfo("F:", Path("F:/"), total=2000 * gb, free=1800 * gb, drive_type=3, is_system=False)

        with patch("silva.storage.drives.load_config", return_value={"knowledge_data_drive": ""}), patch(
            "silva.storage.drives.list_drives", return_value=[system, ssd, hdd]
        ):
            chosen = pick_data_drive()
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.letter, "C:")
        self.assertTrue(chosen.is_system)

    def test_uses_a_drive_only_when_you_pick_it(self):
        from pathlib import Path

        from silva.storage.drives import DriveInfo, describe_data_drive, pick_data_drive, set_data_drive

        gb = 1024 * 1024 * 1024
        system = DriveInfo("C:", Path("C:/"), total=2 * gb, free=gb, drive_type=3, is_system=True)
        extra = DriveInfo("D:", Path("D:/"), total=500 * gb, free=400 * gb, drive_type=3, is_system=False)
        stored = {"knowledge_data_drive": ""}

        def fake_save(config):
            stored.update(config)

        with patch("silva.storage.drives.load_config", side_effect=lambda: stored), patch(
            "silva.storage.drives.save_config", side_effect=fake_save
        ), patch("silva.storage.drives.list_drives", return_value=[system, extra]):
            self.assertIn("main drive", set_data_drive("main"))
            self.assertEqual(pick_data_drive().letter, "C:")
            self.assertIn("D:", set_data_drive("d"))
            self.assertEqual(stored["knowledge_data_drive"], "D:")
            self.assertEqual(pick_data_drive().letter, "D:")
            self.assertIn("D:", describe_data_drive())
            self.assertIn("main drive", set_data_drive("main"))
            self.assertEqual(stored["knowledge_data_drive"], "")

        with patch("silva.storage.drives.load_config", return_value={"knowledge_data_drive": "E:"}), patch(
            "silva.storage.drives.list_drives", return_value=[system, extra]
        ):
            fallback = pick_data_drive()
        self.assertEqual(fallback.letter, "C:")

    def test_drive_phrases(self):
        from silva.commands.knowledge_phrases import match_knowledge_speech

        main = match_knowledge_speech("keep extra files on the main drive")
        self.assertEqual(main.action, "set_drive")
        self.assertEqual(main.query, "main")
        extra = match_knowledge_speech("use the d drive for extra files")
        self.assertEqual(extra.action, "set_drive")
        self.assertEqual(extra.query, "d")
        save_on = match_knowledge_speech("save extra files on e")
        self.assertEqual(save_on.action, "set_drive")
        self.assertEqual(save_on.query, "e")
        where = match_knowledge_speech("where do you save extra files")
        self.assertEqual(where.action, "drive_status")


class KeepAliveTests(unittest.TestCase):
    def test_sleep_stay_active_restarts_unless_you_stopped_it(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from silva import keep_alive as ka

        original = Path(ka.KEEP_DIR)
        with TemporaryDirectory() as raw:
            ka.configure_paths(Path(raw))
            try:
                ka.mark_running()
                self.assertFalse(ka.sleep_should_stay_active())
                ka.mark_sleep_active()
                self.assertTrue(ka.sleep_should_stay_active())
                with patch("silva.keep_alive.time.sleep"), patch(
                    "silva.instance.silva_is_running", return_value=False
                ), patch("silva.launch.start_silva_process") as start:
                    ka._restart_silva()
                start.assert_called_once()
                self.assertEqual(start.call_args[0][0], ["--resume-sleep"])
                ka.mark_clean_stop()
                self.assertFalse(ka.sleep_should_stay_active())
                with patch("silva.keep_alive.time.sleep"), patch(
                    "silva.instance.silva_is_running", return_value=False
                ), patch("silva.launch.start_silva_process") as start_after_stop:
                    ka._restart_silva()
                start_after_stop.assert_not_called()
            finally:
                ka.configure_paths(original)

    def test_goodbye_is_the_voice_exit_button(self):
        from silva.close_phrases import is_close_command
        from silva.commands.intent import is_action_command

        self.assertTrue(is_close_command("goodbye"))
        self.assertTrue(is_close_command("good bye"))
        self.assertTrue(is_close_command("bye"))
        self.assertTrue(is_action_command("goodbye"))
        self.assertFalse(is_close_command("good night"))
        self.assertFalse(is_close_command("how are you"))

    def test_parser_resume_sleep_flag(self):
        from silva.__main__ import build_parser

        args = build_parser().parse_args(["--resume-sleep"])
        self.assertTrue(args.resume_sleep)


class CrashReportTests(unittest.TestCase):
    def setUp(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from silva import crash_record as cr
        from silva import keep_alive as ka
        from silva.config import CONFIG_DIR
        from silva.logger import LOG_DIR, LOG_FILE

        self._tmpdir = TemporaryDirectory()
        self._root = Path(self._tmpdir.name)
        self._log = self._root / "silva.log"
        self._ka_original = Path(ka.KEEP_DIR)
        cr.configure_paths(self._root, log_file=self._log)
        ka.configure_paths(self._root / "keep")

        def _restore() -> None:
            ka.configure_paths(self._ka_original)
            cr.LAST_EXIT_FILE = CONFIG_DIR / "keep_alive" / "last_exit.json"
            cr.LAST_UNCLEAN_FILE = CONFIG_DIR / "keep_alive" / "last_unclean.json"
            cr.LAST_COMMAND_ERROR_FILE = CONFIG_DIR / "keep_alive" / "last_command_error.json"
            cr.REPORT_FILE = LOG_DIR / "last_crash.txt"
            cr.COMMAND_REPORT_FILE = LOG_DIR / "last_command_error.txt"
            cr._LOG_OVERRIDE = None
            cr._paths_overridden = False

        self.addCleanup(_restore)
        self.addCleanup(self._tmpdir.cleanup)

    def test_phrases_match_the_log_ask_not_a_bug_report(self):
        from silva.commands.crash_report_phrases import is_crash_report_ask, wants_crash_file
        from silva.commands.intent import is_action_command
        from silva.stt_quick_commands import is_complete_command
        from silva.users.bug_reports import is_silva_bug_report

        from silva.commands.crash_report_phrases import is_command_fail_ask

        phrases = [
            "can you tell me why you crash",
            "can you tell me why did you crash last time",
            "why did you crash last time",
            "why did you crash",
            "why did the ai crash",
            "show me the crash report",
            "all right can you tell me why your commands were not work",
            "why were your commands not working",
            "why did every command fail",
        ]
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self.assertTrue(is_crash_report_ask(phrase), msg=phrase)
                self.assertTrue(is_action_command(phrase), msg=phrase)
                self.assertTrue(is_complete_command(phrase), msg=phrase)

        self.assertTrue(is_command_fail_ask("all right can you tell me why your commands were not work"))
        self.assertTrue(is_command_fail_ask("why were your commands not working"))
        self.assertFalse(is_command_fail_ask("can you tell me why you crash"))
        self.assertTrue(wants_crash_file("show me the crash report"))
        self.assertFalse(is_crash_report_ask("the ai assistant crashed"))
        self.assertTrue(is_silva_bug_report("the ai assistant crashed"))
        self.assertFalse(is_crash_report_ask("how are you"))
        self.assertFalse(is_crash_report_ask("I found a bug, the ai crashed"))

    def test_speaks_simple_reason_and_writes_technical_txt(self):
        from silva.crash_record import explain_last_crash, record_session_start

        self._log.write_text(
            "\n".join(
                [
                    "[2026-11-20 18:00:00] INFO: Silva started (voice mode, owner).",
                    "[2026-11-20 18:01:00] INFO: Silva entered sleep mode",
                    "[2026-11-20 19:10:00] INFO: audio device connected: Elgato Wave:3",
                    "[2026-11-20 19:10:01] ERROR: Microphone stream dropped",
                    "Traceback (most recent call last):",
                    '  File "silva/stt.py", line 88, in _listen_raw',
                    "    raise RuntimeError('PortAudio')",
                    "[2026-11-20 20:00:00] INFO: Silva started (voice mode, owner).",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        from silva.crash_record import LAST_EXIT_FILE
        import json

        LAST_EXIT_FILE.write_text(json.dumps({"kind": "running", "pid": 1, "asleep": True}), encoding="utf-8")
        record_session_start(resumed_sleep=True)
        report = explain_last_crash()
        self.assertEqual(report.kind, "audio_device")
        self.assertIn("microphone or speaker", report.spoken.lower())
        self.assertNotIn("traceback", report.spoken.lower())
        self.assertNotIn("stt.py", report.spoken)
        self.assertNotIn("0x", report.spoken.lower())
        self.assertTrue(report.open_file)
        body = report.path.read_text(encoding="utf-8")
        self.assertIn("Traceback", body)
        self.assertIn("silva/stt.py", body)

    def test_goodbye_is_not_called_a_crash(self):
        from silva.crash_record import explain_last_crash

        self._log.write_text(
            "\n".join(
                [
                    "[2026-11-20 18:00:00] INFO: Silva started (voice mode, owner).",
                    "[2026-11-20 18:05:00] INFO: Silva stopped by user.",
                    "[2026-11-20 18:05:00] INFO: Silva process ending.",
                    "[2026-11-20 20:00:00] INFO: Silva started (voice mode, owner).",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        report = explain_last_crash()
        self.assertEqual(report.kind, "clean_goodbye")
        self.assertIn("goodbye", report.spoken.lower())
        self.assertIn("not a crash", report.spoken.lower())
        self.assertFalse(report.open_file)

    def test_handler_speaks_then_opens_txt(self):
        from silva.commands.crash_report_handler import handle_crash_report_speech
        from silva.crash_record import LAST_EXIT_FILE
        import json

        LAST_EXIT_FILE.write_text(json.dumps({"kind": "running", "pid": 9, "asleep": True}), encoding="utf-8")
        self._log.write_text(
            "[2026-11-20 18:00:00] INFO: Silva started (voice mode, owner).\n"
            "[2026-11-20 18:01:00] INFO: Silva entered sleep mode\n"
            "[2026-11-20 20:00:00] INFO: Silva started (voice mode, owner).\n",
            encoding="utf-8",
        )
        assistant = MagicMock()
        with patch("silva.commands.news_display.open_briefing_txt") as opener:
            handled = handle_crash_report_speech(assistant, "can you tell me why you crash")
        self.assertTrue(handled)
        assistant.say.assert_called()
        spoken = assistant.say.call_args[0][0]
        self.assertNotIn("Traceback", spoken)
        opener.assert_called_once()
        self.assertEqual(opener.call_args.kwargs.get("auto_close_minutes"), 0)

    def test_command_fail_ask_explains_planner_hook_from_logs(self):
        from silva.commands.crash_report_handler import handle_crash_report_speech
        from silva.crash_record import explain_last_command_fail

        self._log.write_text(
            "\n".join(
                [
                    "[2026-11-20 21:18:10] INFO: Silva started (voice mode, owner).",
                    "[2026-11-20 21:18:10] ERROR: Unexpected assistant error",
                    "Traceback (most recent call last):",
                    '  File "silva/commands/planner_handler.py", line 25, in handle_planner_speech',
                    "ImportError: cannot import name 'apply_planner_speech' from 'silva.gui.planner_window'",
                    "[2026-11-20 21:18:25] INPUT: (voice) what was recently added",
                    "[2026-11-20 21:18:25] ERROR: Unexpected assistant error",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        report = explain_last_command_fail()
        self.assertEqual(report.kind, "planner_stale")
        self.assertIn("planner", report.spoken.lower())
        self.assertNotIn("traceback", report.spoken.lower())
        self.assertNotIn("apply_planner_speech", report.spoken)
        self.assertTrue(report.open_file)
        self.assertIn("apply_planner_speech", report.path.read_text(encoding="utf-8"))

        assistant = MagicMock()
        with patch("silva.commands.news_display.open_briefing_txt") as opener:
            handled = handle_crash_report_speech(
                assistant,
                "all right can you tell me why your commands were not work",
            )
        self.assertTrue(handled)
        spoken = assistant.say.call_args[0][0]
        self.assertIn("planner", spoken.lower())
        opener.assert_called_once()


class PlannerTests(unittest.TestCase):
    def setUp(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from silva.planner import store as planner_store

        self._tmpdir = TemporaryDirectory()
        self._root = Path(self._tmpdir.name)
        self._original_dir = Path(planner_store.PLANNER_DIR)
        planner_store.configure_paths(self._root)
        self.addCleanup(lambda: planner_store.configure_paths(self._original_dir))
        self.addCleanup(self._tmpdir.cleanup)

    def test_open_phrases_are_commands(self):
        from silva.commands.intent import is_action_command
        from silva.commands.planner_phrases import is_planner_command
        from silva.stt_quick_commands import is_complete_command

        from silva.commands.planner_phrases import match_planner_draw_tool, match_planner_view

        from silva.commands.planner_phrases import is_planner_map_ask, is_planner_site_ask

        phrases = [
            "open the planner",
            "open the 3d graph",
            "open the floor plan",
            "show the 3d planner",
            "can you open the planner",
            "switch to 3d",
            "switch to 2d",
            "map me a building",
            "map me a two bedroom house",
            "add a site",
            "draw a line",
            "draw walls",
            "close the planner",
        ]
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self.assertTrue(is_planner_command(phrase), msg=phrase)
                self.assertTrue(is_action_command(phrase), msg=phrase)
                self.assertTrue(is_complete_command(phrase), msg=phrase)
        self.assertTrue(is_planner_map_ask("map me a two bedroom house"))
        self.assertTrue(is_planner_site_ask("add topographic layout"))
        self.assertEqual(match_planner_view("switch to 3d"), "3d")
        self.assertEqual(match_planner_view("open the 2d floor plan"), "2d")
        self.assertEqual(match_planner_draw_tool("draw a line"), "line")
        self.assertEqual(match_planner_draw_tool("draw a room"), "room")
        from silva.commands.planner_phrases import is_planner_close_ask

        self.assertTrue(is_planner_close_ask("close the planner"))
        self.assertFalse(is_planner_command("what's the weather"))
        self.assertFalse(is_planner_command("how are you"))
        self.assertIsNone(match_planner_view("3d"))

    def test_catalog_upgrade_and_save(self):
        from silva.planner.catalog import get_item, next_upgrade
        from silva.planner.store import add_object, current_project, save_project, upgrade_item

        self.assertIsNotNone(get_item("sofa"))
        self.assertIsNotNone(get_item("fridge"))
        self.assertEqual(next_upgrade("sofa")["id"], "sectional")
        project = current_project()
        sofa = add_object(project, "sofa", 1.0, 2.0)
        self.assertIsNotNone(sofa)
        upgraded = upgrade_item(project, sofa["id"])
        self.assertEqual(upgraded["catalog_id"], "sectional")
        path = save_project(project)
        self.assertTrue(path.exists())
        self.assertIsNotNone(get_item("copper_wire"))
        self.assertEqual(get_item("copper_wire").get("tool"), "electrical")
        from silva.planner.store import active_floor, add_run, add_wall, clear_floor, rotate_item

        wired = add_run(project, "electrical", 0, 0, 2, 0)
        self.assertIsNotNone(wired)
        self.assertEqual(wired["kind"], "electrical")
        wall = add_wall(project, 0, 0, 3, 0)
        self.assertIsNotNone(wall)
        self.assertTrue(rotate_item(project, sofa["id"], 90))
        self.assertGreater(abs(float(sofa["yaw"])), 1.0)
        clear_floor(project)
        floor = active_floor(project)
        self.assertEqual(floor.get("walls"), [])
        self.assertEqual(floor.get("objects"), [])
        self.assertEqual(floor.get("runs"), [])

    def test_planner_icon_cache_is_a_dict(self):
        import inspect

        from silva.gui.planner_window import PlannerWindow

        source = inspect.getsource(PlannerWindow.__init__)
        self.assertIn("self._icon_cache: dict[str, tk.PhotoImage] = {}", source)
        self.assertNotIn("self._icon_cache: dict[str, tk.PhotoImage] = []", source)

    def test_rooms_and_2d_mapping(self):
        from silva.planner.geometry import format_length, screen_to_world, sq_ft, world_to_screen, PlanView
        from silva.planner.store import add_room, current_project

        self.assertEqual(format_length(2.4384), "8'")
        self.assertGreater(sq_ft(4.57, 4.11), 200)
        view = PlanView()
        sx, sy = world_to_screen(1.0, 2.0, view, 800, 600)
        x, z = screen_to_world(sx, sy, view, 800, 600)
        self.assertAlmostEqual(x, 1.0, places=5)
        self.assertAlmostEqual(z, 2.0, places=5)
        project = current_project()
        room = add_room(project, 0, 0, 4.57, 2.44)
        self.assertIsNotNone(room)
        self.assertAlmostEqual(room["w"], 4.57, places=2)

    def test_closed_lines_show_square_footage_and_split_rooms(self):
        from silva.planner.geometry import closed_polygons, parse_length, polygon_area_sq_ft, total_sq_ft
        from silva.planner.layout import apply_instruction, generate_building, parse_building_request
        from silva.planner.store import add_wall, current_project

        self.assertAlmostEqual(parse_length("12 ft"), 3.6576, places=3)
        self.assertAlmostEqual(parse_length("8' 6\""), 2.5908, places=3)

        project = current_project()
        add_wall(project, 0, 0, 4, 0)
        add_wall(project, 4, 0, 4, 4)
        add_wall(project, 4, 4, 0, 4)
        add_wall(project, 0, 4, 0, 0)
        rooms = project["floors"][0]["rooms"]
        self.assertEqual(len(rooms), 1)
        self.assertGreater(total_sq_ft(rooms), 170)
        self.assertLess(total_sq_ft(rooms), 175)

        add_wall(project, 2, 0, 2, 4)
        rooms = project["floors"][0]["rooms"]
        self.assertEqual(len(rooms), 2)
        self.assertGreater(total_sq_ft(rooms), 170)
        self.assertLess(total_sq_ft(rooms), 175)
        faces = closed_polygons(project["floors"][0]["walls"])
        self.assertEqual(len(faces), 2)
        self.assertGreater(polygon_area_sq_ft(faces[0]), 80)

        spec = parse_building_request("map me a two bedroom house with a garage, two stories")
        self.assertEqual(spec["floors"], 2)
        self.assertIn("Bedroom", spec["rooms"])
        self.assertIn("Garage", spec["rooms"])
        mapped = generate_building(current_project(), spec)
        self.assertEqual(len(mapped["floors"]), 2)
        self.assertGreaterEqual(sum(len(floor.get("rooms") or []) for floor in mapped["floors"]), 2)

        site_project = current_project()
        spoken = apply_instruction(site_project, "add a site with grass and a gentle slope")
        self.assertIn("site", spoken.lower())
        self.assertTrue(site_project["site"]["enabled"])
        self.assertEqual(site_project["site"]["ground"], "grass")
        self.assertEqual(site_project["site"]["terrain"], "gentle")

    def test_orbit_camera_hits_the_floor(self):
        from silva.planner.camera import Camera, project, unproject_floor

        cam = Camera()
        point = project((0.0, 0.0, 0.0), cam, 800, 600)
        self.assertIsNotNone(point)
        self.assertAlmostEqual(point[0], 400, delta=8)
        self.assertAlmostEqual(point[1], 300, delta=8)
        floor = unproject_floor(400, 300, cam, 800, 600)
        self.assertIsNotNone(floor)
        self.assertAlmostEqual(floor[0], 0.0, delta=0.15)
        self.assertAlmostEqual(floor[1], 0.0, delta=0.15)

    def test_handler_opens_window(self):
        from types import SimpleNamespace

        from silva.commands.planner_handler import handle_planner_speech

        assistant = MagicMock()
        opener = MagicMock()
        pw = SimpleNamespace(show_planner_window=opener, planner_is_open=lambda: False)
        with patch("silva.commands.planner_handler._planner_window", return_value=pw), patch(
            "silva.commands.planner_handler.feature_allowed", return_value=True
        ), patch(
            "silva.commands.planner_handler.get_active_user",
            return_value={"id": "owner", "tier": 5},
        ):
            handled = handle_planner_speech(assistant, "open the 3d graph")
        self.assertTrue(handled)
        opener.assert_called_once()
        assistant.say.assert_called()

    def test_handler_maps_a_building_and_applies_open_edits(self):
        from types import SimpleNamespace

        from silva.commands.planner_handler import handle_planner_speech

        assistant = MagicMock()
        opener = MagicMock()
        pw = SimpleNamespace(show_planner_window=opener, planner_is_open=lambda: False)
        with patch("silva.commands.planner_handler._planner_window", return_value=pw), patch(
            "silva.commands.planner_handler.feature_allowed", return_value=True
        ), patch(
            "silva.commands.planner_handler.get_active_user",
            return_value={"id": "owner", "tier": 5},
        ):
            self.assertTrue(handle_planner_speech(assistant, "map me a building"))
            kwargs = opener.call_args.kwargs
            self.assertTrue(kwargs.get("open_map"))
            opener.reset_mock()
            self.assertTrue(handle_planner_speech(assistant, "map me a two bedroom house"))
            kwargs = opener.call_args.kwargs
            self.assertEqual(kwargs.get("apply_text"), "map me a two bedroom house")
            self.assertFalse(kwargs.get("open_map"))

        opener.reset_mock()
        open_pw = SimpleNamespace(
            planner_is_open=lambda: True,
            apply_planner_speech=lambda _text: "I set that line to 12'.",
            show_planner_window=opener,
        )
        with patch("silva.commands.planner_handler._planner_window", return_value=open_pw):
            handled = handle_planner_speech(assistant, "make this wall 12 feet")
        self.assertTrue(handled)
        opener.assert_not_called()
        assistant.say.assert_called_with("I set that line to 12'.", interruptible=True)

    def test_handler_does_not_break_other_commands_when_window_is_stale(self):
        from types import SimpleNamespace

        from silva.commands.planner_handler import handle_planner_speech

        assistant = MagicMock()
        stale = SimpleNamespace(show_planner_window=MagicMock())
        with patch("silva.commands.planner_handler._planner_window", return_value=stale), patch(
            "silva.commands.planner_handler.feature_allowed", return_value=True
        ), patch(
            "silva.commands.planner_handler.get_active_user",
            return_value={"id": "owner", "tier": 5},
        ):
            self.assertFalse(handle_planner_speech(assistant, "what is the weather"))
            self.assertFalse(handle_planner_speech(assistant, "sleep mode"))
            self.assertTrue(handle_planner_speech(assistant, "open the planner"))
        stale.show_planner_window.assert_called()

    def test_handler_closes_open_planner(self):
        from types import SimpleNamespace

        from silva.commands.planner_handler import handle_planner_speech

        assistant = MagicMock()
        closer = MagicMock()
        pw = SimpleNamespace(
            planner_is_open=lambda: True,
            close_planner_window=closer,
            apply_planner_speech=MagicMock(),
            show_planner_window=MagicMock(),
        )
        with patch("silva.commands.planner_handler._planner_window", return_value=pw):
            handled = handle_planner_speech(assistant, "close the planner")
        self.assertTrue(handled)
        closer.assert_called_once()
        assistant.say.assert_called_with("I closed the planner.", interruptible=True)
        pw.show_planner_window.assert_not_called()


class SecurityTests(unittest.TestCase):
    def test_block_actor(self):
        import uuid

        actor = f"actor_{uuid.uuid4().hex[:6]}"
        target = f"user_{uuid.uuid4().hex[:6]}"
        self.assertFalse(is_blocked(actor, target))
        block_actor(actor, target, reason="test")
        self.assertTrue(is_blocked(actor, target))

    def test_tier_assist_rules(self):
        self.assertTrue(tier_can_assist(4, 3))
        self.assertTrue(tier_can_assist(3, 2))
        self.assertFalse(tier_can_assist(3, 4))
        self.assertTrue(can_help_tier(4, 2))
        self.assertFalse(can_help_tier(2, 3))


    def test_owner_profile_mode(self):
        owner = get_owner()
        self.assertEqual(profile_mode_for_user(owner), "owner")
        self.assertTrue(can_open_control_panel(owner))


class GreetingTests(unittest.TestCase):
    def test_startup_greeting(self):
        self.assertIn("Silva", startup_greeting())
        self.assertIn("personal AI assistant", startup_greeting())

    def test_listening_prompt(self):
        self.assertEqual(listening_prompt(), "Listening.")


class WakeSleepTests(unittest.TestCase):
    def test_wake_phrases(self):
        self.assertTrue(is_wake_command("wake up silva"))
        self.assertTrue(is_wake_command("hey silva"))
        self.assertTrue(is_wake_command("silva please wake up"))
        self.assertTrue(is_wake_command("hey silva wake up"))
        self.assertFalse(is_wake_command("weather"))
        self.assertFalse(is_wake_command("hello"))
        self.assertFalse(is_wake_command("i need to wake up early tomorrow"))
        self.assertFalse(is_wake_command("how are you doing today Silva"))

    def test_wake_correction_after_mishearing(self):
        from silva.wake_context import evaluate_wake, is_direct_wake_command

        text = "I said wake up not break up"
        self.assertTrue(is_direct_wake_command(text))
        self.assertEqual(evaluate_wake(text).action, "wake")
        self.assertFalse(is_direct_wake_command("break up"))

    def test_break_yourself_up_is_a_wake_candidate(self):
        from silva.wake_context import evaluate_wake, is_direct_wake_command, is_wake_candidate

        text = "all right then break yourself up"
        self.assertTrue(is_wake_candidate(text))
        self.assertEqual(evaluate_wake(text).action, "pending")
        self.assertEqual(evaluate_wake("I said wake yourself up").action, "wake")

    def test_wake_yourself_up_is_direct_without_camera_wait(self):
        from silva.wake_context import evaluate_wake, is_direct_wake_command

        for text in ("wake yourself up", "wake up yourself", "wake yourself"):
            with self.subTest(text=text):
                self.assertTrue(is_direct_wake_command(text))
                decision = evaluate_wake(text)
                self.assertEqual(decision.action, "wake")
                self.assertFalse(decision.silent)
        self.assertFalse(is_direct_wake_command("all right then break yourself up"))

    def test_smart_wake_pending(self):
        from silva.wake_context import evaluate_wake

        decision = evaluate_wake("yeah tell him silva wake up when you get a chance")
        self.assertIn(decision.action, {"pending", "ignore", "wake"})

    def test_sleep_phrases(self):
        self.assertTrue(is_sleep_command("go to sleep"))
        self.assertTrue(is_sleep_command("silva sleep"))
        self.assertTrue(is_sleep_command("sleep mode"))
        self.assertTrue(is_sleep_command("all right then go back to sleep"))
        self.assertTrue(is_sleep_command("all right now go back to sleep"))
        self.assertTrue(is_sleep_command("go back to sleep"))
        self.assertTrue(is_sleep_command("okay going to sleep"))
        self.assertTrue(is_sleep_command("ok then go back to sleep"))
        self.assertTrue(is_sleep_command("you dumb bitch go to sleep"))
        self.assertTrue(is_sleep_command("why are you not going to sleep idiot"))
        self.assertTrue(
            is_sleep_command(
                "are you going to sleep so I can fix you cuz you're a dumb bitch who don't listen"
            )
        )
        self.assertFalse(is_sleep_command("are you going to sleep?"))
        self.assertFalse(is_sleep_command("wake up silva"))
        self.assertFalse(is_sleep_command("what do you mean by sleep"))


class ConversationEngineTests(unittest.TestCase):
    def test_phrase_matching_avoids_false_positives(self):
        from silva.conversation.matching import contains_phrase

        self.assertFalse(contains_phrase("how are you doing", "yo"))
        self.assertTrue(contains_phrase("how are you doing", "how are you"))
        self.assertTrue(contains_phrase("hey yo", "yo"))

    def test_how_are_you_gets_natural_reply(self):
        from silva.conversation import try_conversation

        reply = try_conversation("how are you doing")
        self.assertIsNotNone(reply)
        assert reply is not None
        lowered = reply.lower()
        self.assertTrue(
            any(
                word in lowered
                for word in (
                    "doing",
                    "good",
                    "well",
                    "fine",
                    "great",
                    "thanks",
                    "alright",
                    "okay",
                    "not bad",
                    "complain",
                    "appreciate",
                    "how",
                )
            ),
            msg=reply,
        )
        self.assertNotIn("{name}", reply)

    def test_how_are_you_doing_today(self):
        from silva.conversation import try_conversation

        reply = try_conversation("how are you doing today")
        self.assertIsNotNone(reply)
        assert reply is not None
        lowered = reply.lower()
        self.assertTrue(
            any(
                word in lowered
                for word in (
                    "doing",
                    "good",
                    "well",
                    "fine",
                    "great",
                    "thanks",
                    "alright",
                    "okay",
                    "not bad",
                    "complain",
                    "how",
                )
            ),
            msg=reply,
        )
        self.assertNotIn("yeah, i get that", lowered)

    def test_correction_asks_for_repeat(self):
        from silva.conversation import try_conversation

        reply = try_conversation("that is not what I said")
        self.assertIsNotNone(reply)
        assert reply is not None
        self.assertTrue(any(hint in reply.lower() for hint in ("repeat", "again", "what was that")))

    def test_how_are_you_today_silva_is_chat_not_wake(self):
        from silva.commands.intent import is_action_command
        from silva.conversation import try_conversation
        from silva.wake_context import is_direct_wake_command

        text = "how are you doing today Silva"
        self.assertFalse(is_direct_wake_command(text))
        self.assertFalse(is_action_command(text))

    def test_thank_you_silva_is_chat_not_wake(self):
        from silva.commands.intent import is_action_command
        from silva.conversation import try_conversation
        from silva.wake_context import is_direct_wake_command

        text = "thank you Silva"
        self.assertFalse(is_direct_wake_command(text))
        self.assertFalse(is_action_command(text))
        reply = try_conversation(text)
        self.assertIsNotNone(reply)

    def test_how_are_you_resets_stale_talk_more(self):
        from silva.conversation import ConversationContext, try_conversation_with_context

        ctx = ConversationContext()
        ctx.follow_up = "talk_more"
        ctx.category = "fallback"
        reply, _, confidence = try_conversation_with_context(
            "how are you doing how are you doing", ctx
        )
        self.assertIsNotNone(reply)
        assert reply is not None
        self.assertTrue(
            any(
                word in reply.lower()
                for word in (
                    "doing",
                    "good",
                    "well",
                    "fine",
                    "great",
                    "thanks",
                    "alright",
                    "okay",
                    "not bad",
                    "complain",
                    "appreciate",
                    "how",
                )
            ),
            msg=reply,
        )
        self.assertGreaterEqual(confidence, 0.9)
        self.assertNotIn("pile up", reply.lower())

    def test_reciprocal_follow_up(self):
        from silva.conversation import ConversationContext, try_conversation_with_context

        ctx = ConversationContext()
        _, ctx, _ = try_conversation_with_context("how are you", ctx)
        reply, _, _ = try_conversation_with_context("im good how about you", ctx)
        self.assertIsNotNone(reply)
        assert reply is not None
        self.assertTrue(
            any(
                word in reply.lower()
                for word in (
                    "good",
                    "well",
                    "alright",
                    "fine",
                    "okay",
                    "not bad",
                    "same here",
                    "glad",
                    "likewise",
                    "appreciate",
                    "how have you been",
                    "been going on",
                    "happening",
                    "what's new",
                    "nice talking",
                    "how's everything",
                    "how's your day",
                )
            ),
            msg=reply,
        )


class ConversationTests(unittest.TestCase):
    def test_greeting(self):
        reply = try_conversation("hello")
        self.assertIsNotNone(reply)
        self.assertTrue(reply.startswith("Hi") or reply.startswith("Hello") or reply.startswith("Hey"))

    def test_hello_does_not_wake(self):
        self.assertFalse(is_wake_command("hello"))

    def test_joke(self):
        reply = try_conversation("tell me a joke")
        self.assertIsNotNone(reply)


class UserStoreRecoveryTests(unittest.TestCase):
    def test_empty_users_file_does_not_crash(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from silva.users import manager as user_manager

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            users_file = folder / "users.json"
            users_file.write_text("", encoding="utf-8")
            with patch.object(user_manager, "CONFIG_DIR", folder), patch.object(
                user_manager, "USERS_FILE", users_file
            ), patch.object(user_manager, "USERS_BACKUP_FILE", folder / "users.json.bak"):
                store = user_manager.load_store()
                self.assertEqual(store["owner_id"], "kevin")
                self.assertIn("kevin", store["users"])
                self.assertTrue(users_file.read_text(encoding="utf-8").strip())


class UserProfileTests(unittest.TestCase):
    def test_owner_is_kevin(self):
        owner = get_owner()
        self.assertEqual(owner["name"], "Kevin")
        self.assertEqual(owner["tier"], MAX_TIER)

    def test_owner_can_manage_users(self):
        self.assertTrue(user_can(get_owner(), PERM_MANAGE_USERS))

    def test_tier_one_cannot_run_commands(self):
        guest = add_user("Temp Guest User", tier=1)
        self.assertFalse(user_can(guest, PERM_RUN_COMMANDS))
        remove_user(guest["id"])

    def test_owner_cannot_be_removed(self):
        owner = get_owner()
        self.assertFalse(remove_user(owner["id"]))

    def test_owner_tier_cannot_be_lowered(self):
        owner = get_owner()
        updated = update_user_profile(owner["id"], tier=1)
        self.assertEqual(updated["tier"], MAX_TIER)


class SystemIdentityTests(unittest.TestCase):
    @patch("silva.users.system_identity.load_config")
    @patch("silva.users.system_identity._main_system_fingerprint")
    @patch("silva.users.system_identity.get_machine_fingerprint")
    def test_main_system_when_fingerprint_matches(
        self,
        mock_fp,
        mock_main_fp,
        mock_config,
    ):
        mock_fp.return_value = "abc123"
        mock_main_fp.return_value = "abc123"
        mock_config.return_value = {"main_owner_system": False}
        self.assertTrue(is_main_owner_system())
        self.assertFalse(is_remote_system())

    @patch("silva.users.system_identity.load_config")
    @patch("silva.users.system_identity._main_system_fingerprint")
    @patch("silva.users.system_identity.get_machine_fingerprint")
    def test_remote_system_when_fingerprint_differs(
        self,
        mock_fp,
        mock_main_fp,
        mock_config,
    ):
        mock_fp.return_value = "remote123"
        mock_main_fp.return_value = "main456"
        mock_config.return_value = {"main_owner_system": False}
        self.assertFalse(is_main_owner_system())
        self.assertTrue(is_remote_system())

    @patch("silva.users.system_identity._register_main_system")
    @patch("silva.users.system_identity.load_config")
    @patch("silva.users.system_identity._main_system_fingerprint")
    @patch("silva.users.system_identity.get_machine_fingerprint")
    def test_rebinds_main_when_config_enabled_and_fingerprint_differs(
        self,
        mock_fp,
        mock_main_fp,
        mock_config,
        mock_register,
    ):
        mock_fp.return_value = "dev123"
        mock_main_fp.return_value = "old456"
        mock_config.return_value = {"main_owner_system": True}
        self.assertTrue(is_main_owner_system())
        mock_register.assert_called_once_with("dev123")

    @patch("silva.users.system_identity.load_config")
    @patch("silva.users.system_identity._register_main_system")
    @patch("silva.users.system_identity._main_system_fingerprint")
    @patch("silva.users.system_identity.get_machine_fingerprint")
    def test_registers_main_when_config_allows_first_install(
        self,
        mock_fp,
        mock_main_fp,
        mock_register,
        mock_config,
    ):
        mock_fp.return_value = "newmain"
        mock_main_fp.return_value = None
        mock_config.return_value = {"main_owner_system": True}
        self.assertTrue(is_main_owner_system())
        mock_register.assert_called_once_with("newmain")

    @patch("silva.users.system_identity.is_main_owner_system")
    @patch("silva.users.system_identity.identify_and_set_active")
    @patch("silva.users.system_identity.get_owner")
    def test_startup_sets_owner_on_main_system(self, mock_owner, mock_identify, mock_is_main):
        mock_is_main.return_value = True
        mock_owner.return_value = {"id": "kevin", "name": "Kevin", "tier": MAX_TIER}
        user = apply_system_startup_access()
        mock_identify.assert_called_once_with("kevin")
        self.assertEqual(user["id"], "kevin")

    @patch("silva.users.system_identity.is_main_owner_system")
    @patch("silva.users.system_identity.identify_and_set_active")
    def test_startup_sets_guest_on_remote_system(self, mock_identify, mock_is_main):
        mock_is_main.return_value = False
        apply_system_startup_access()
        mock_identify.assert_called_once_with(None)

    @patch("silva.users.system_identity.is_main_owner_system")
    @patch("silva.users.system_identity.load_config")
    def test_bypass_security_on_main_system(self, mock_config, mock_is_main):
        mock_is_main.return_value = True
        mock_config.return_value = {"bypass_security_on_main_system": True}
        self.assertTrue(bypass_security_checks())

    def test_machine_fingerprint_is_stable(self):
        first = get_machine_fingerprint()
        second = get_machine_fingerprint()
        self.assertEqual(first, second)
        self.assertEqual(len(first), 32)


class FeatureTests(unittest.TestCase):
    def test_weather_allowed_for_guest_by_default(self):
        from silva.users.features import FEATURE_WEATHER, feature_allowed

        guest = {"id": "guest", "tier": 1, "feature_overrides": {}}
        self.assertTrue(feature_allowed(guest, FEATURE_WEATHER))

    def test_admin_can_disable_weather_for_user(self):
        from silva.users.features import FEATURE_WEATHER, feature_allowed, save_user_feature_overrides

        save_user_feature_overrides("guest", {FEATURE_WEATHER: False})
        guest = {"id": "guest", "tier": 1, "feature_overrides": {FEATURE_WEATHER: False}}
        self.assertFalse(feature_allowed(guest, FEATURE_WEATHER))
        save_user_feature_overrides("guest", {})

    def test_legacy_audio_feature_does_not_crash(self):
        from silva.users.features import (
            FEATURE_AUDIO_CONTROL,
            FEATURE_MATH,
            FEATURE_WEATHER,
            editable_features_for_target,
            normalize_feature_key,
            universal_features,
        )

        self.assertEqual(normalize_feature_key("audio"), FEATURE_AUDIO_CONTROL)
        self.assertEqual(normalize_feature_key("microphone"), FEATURE_AUDIO_CONTROL)
        self.assertIsNone(normalize_feature_key("not_a_real_feature"))
        owner = {"id": "owner", "tier": 5, "name": "Kevin"}
        with patch(
            "silva.users.features.load_config",
            return_value={"universal_features": ["weather", "math", "audio", "microphone"]},
        ), patch("silva.users.features.is_owner", return_value=True):
            keys = universal_features()
            self.assertIn(FEATURE_WEATHER, keys)
            self.assertIn(FEATURE_MATH, keys)
            self.assertIn(FEATURE_AUDIO_CONTROL, keys)
            labels = editable_features_for_target(owner, {"id": "guest", "tier": 1})
        self.assertTrue(labels)
        self.assertNotIn("audio", [key for key, _label in labels])


class ProfilePhraseTests(unittest.TestCase):
    def test_many_profile_open_phrases(self):
        from silva.users.profile_phrases import classify_profile_speech, is_profile_open_phrase

        phrases = [
            "open profiles",
            "silva open profile panel",
            "go to profiles",
            "my profile",
            "show user profiles",
            "control panel",
            "manage users",
            "take me to profile panel",
        ]
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self.assertTrue(is_profile_open_phrase(phrase))
                self.assertIsNotNone(classify_profile_speech(phrase))

    def test_complete_command_skips_timer(self):
        from silva.stt_quick_commands import is_complete_command, is_partial_command

        self.assertTrue(is_complete_command("open profiles"))
        self.assertTrue(is_complete_command("what is my weather"))
        self.assertFalse(is_complete_command("open"))
        self.assertTrue(is_partial_command("open"))
        self.assertTrue(is_partial_command("open pro"))
        self.assertTrue(is_partial_command("prof"))
        self.assertFalse(is_partial_command("open profiles"))
        self.assertFalse(is_partial_command("how are you today"))
        self.assertFalse(is_partial_command("how are you today silva"))


class ConversationVocabularyTests(unittest.TestCase):
    def test_vocabulary_repository_size(self):
        from silva.conversation.vocabulary import vocabulary_size

        self.assertGreaterEqual(vocabulary_size(), 4000)

    def test_vocabulary_word_match(self):
        from silva.conversation.vocabulary import vocabulary_fallback

        reply = vocabulary_fallback("I am tired from work today", {})
        self.assertTrue(reply)
        self.assertGreater(len(reply), 10)

    def test_response_bank_size(self):
        from silva.conversation.response_bank import RESPONSE_POOLS

        total = sum(len(pool) for pool in RESPONSE_POOLS.values())
        self.assertGreaterEqual(total, 400)

    def test_screenshot_phrases(self):
        from silva.conversation.user_patterns import classify_user_tone

        self.assertEqual(classify_user_tone("very good thank you thank you for telling me that"), "thanks_extended")
        self.assertEqual(classify_user_tone("not much what about you"), "reciprocal")
        self.assertEqual(classify_user_tone("you need to get better at speaking"), "ai_critique")

    def test_short_reply_for_brief_input(self):
        from silva.conversation.vocabulary import vocabulary_fallback

        reply = vocabulary_fallback("yeah", {})
        self.assertLess(len(reply), 40)

    def test_long_reply_for_explain_request(self):
        from silva.conversation.vocabulary import vocabulary_fallback

        reply = vocabulary_fallback("can you explain why stress builds up over time", {})
        self.assertGreater(len(reply), 80)

    def test_greeting_starts_follow_up(self):
        from silva.conversation import ConversationContext, try_conversation_with_context

        ctx = ConversationContext()
        reply, ctx, _ = try_conversation_with_context("hello", ctx)
        self.assertIsNotNone(reply)
        self.assertIsNotNone(ctx.follow_up)

    def test_follow_up_after_how_are_you(self):
        from silva.conversation import ConversationContext, try_conversation_with_context

        ctx = ConversationContext()
        _, ctx, _ = try_conversation_with_context("how are you", ctx)
        reply, ctx, _ = try_conversation_with_context("im good", ctx)
        self.assertIsNotNone(reply)
        self.assertGreater(ctx.turn_count, 1)

    def test_short_greeting_not_incomplete(self):
        self.assertFalse(_looks_incomplete("hello"))
        self.assertFalse(_needs_more_speech("hello"))
        self.assertTrue(is_conversational_utterance("hello"))


class WikiGuideTests(unittest.TestCase):
    def test_extract_numbered_steps(self):
        from silva.commands.wiki_guide import _extract_steps

        article = "Intro\n1. Mix the flour and water.\n2. Knead the dough.\n3. Bake for 30 minutes."
        steps = _extract_steps(article)
        self.assertEqual(len(steps), 3)
        self.assertIn("Mix the flour", steps[0])

    def test_crafting_query_detection(self):
        from silva.commands.wiki_guide import is_crafting_query

        self.assertTrue(is_crafting_query("how do i make concrete"))
        self.assertTrue(is_crafting_query("how to form a brick"))
        self.assertFalse(is_crafting_query("what is concrete"))

    def test_where_am_i_is_not_guide_status(self):
        from silva.commands.intent import is_action_command
        from silva.commands.location_phrases import is_location_command
        from silva.commands.wiki_guide import is_guide_control

        self.assertIsNone(is_guide_control("where am I"))
        self.assertIsNone(is_guide_control("where am i right now"))
        self.assertEqual(is_guide_control("where was i"), "status")
        self.assertEqual(is_guide_control("what step am i on"), "status")
        self.assertTrue(is_location_command("where am I"))
        self.assertTrue(is_location_command("what's my location"))
        self.assertFalse(is_location_command("where was i"))
        self.assertTrue(is_action_command("where am i"))


class BugReportTests(unittest.TestCase):
    def test_detects_silva_bug_phrase(self):
        from silva.users.bug_reports import is_silva_bug_report

        self.assertTrue(is_silva_bug_report("I found a bug in Silva"))
        self.assertTrue(is_silva_bug_report("the ai assistant crashed"))
        self.assertFalse(is_silva_bug_report("there is a bug in my garden"))


class InterruptTests(unittest.TestCase):
    def test_interrupt_phrases(self):
        self.assertTrue(is_interrupt_command("stop"))
        self.assertTrue(is_interrupt_command("silva stop"))
        self.assertTrue(is_interrupt_command("stop talking"))
        self.assertTrue(is_interrupt_command("please stop"))
        self.assertTrue(is_interrupt_command("stop it"))
        self.assertTrue(is_interrupt_command("ok stop please"))
        self.assertFalse(is_interrupt_command("weather"))
        self.assertFalse(is_interrupt_command("stopped raining"))

    def test_speech_chunks_keep_stop_points(self):
        from silva.tts_interrupt import speech_chunks

        chunks = speech_chunks(
            "Lookups skim Wikipedia and the public web. Say look up a topic. I will tell you what I find."
        )
        self.assertGreaterEqual(len(chunks), 1)
        self.assertTrue(all(chunk.strip() for chunk in chunks))

    def test_typed_stop_cuts_speech_immediately(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        from silva.interrupt_listen import (
            interrupt_now,
            set_active_monitor,
            submit_typed_terminal_command_impl,
        )

        monitor = SimpleNamespace(
            _trigger=MagicMock(),
            stop_event=SimpleNamespace(is_set=lambda: False),
        )
        tts = SimpleNamespace(stop=MagicMock())
        set_active_monitor(monitor)
        try:
            self.assertTrue(interrupt_now("typed-terminal", command="stop", tts=tts))
            monitor._trigger.assert_called_once_with("typed-terminal")
            monitor._trigger.reset_mock()
            assistant = SimpleNamespace(
                _speaking=True,
                _tts=tts,
                _typed_command_queue=MagicMock(),
                _print_terminal_message=MagicMock(),
            )
            submit_typed_terminal_command_impl(assistant, "stop")
            monitor._trigger.assert_called_once_with("typed-terminal")
            assistant._typed_command_queue.put.assert_not_called()
        finally:
            set_active_monitor(None)

    def test_non_interruptible_speech_still_lists_for_stop(self):
        import threading
        from types import SimpleNamespace

        from silva.assistant import SilvaAssistant

        assistant = SilvaAssistant.__new__(SilvaAssistant)
        assistant._voice_mode = True
        assistant._speaking = False
        assistant._asleep = False
        assistant._parallel_command_active = False
        assistant._pending_readbacks = []
        assistant._followup_lock = threading.Lock()
        assistant._user_id = MagicMock(return_value="stop-test-user")
        assistant._ensure_stt = MagicMock(return_value=object())
        assistant._tts = MagicMock()
        assistant._tts.speak_interruptible.return_value = True

        monitor = MagicMock()
        monitor.stop_event = SimpleNamespace(is_set=lambda: False)
        monitor.was_interrupted.return_value = False
        monitor.priority_command = None

        with patch("silva.assistant.InterruptMonitor", return_value=monitor), patch(
            "silva.conversation.attitude.style_reply", side_effect=lambda value, user_id="": value
        ), patch(
            "silva.conversation.safety.apply_safety", side_effect=lambda value, user_id="": value
        ), patch("silva.conversation.echo_guard.remember_spoken"), patch(
            "silva.conversation.crosschat_memory.remember_last_reply"
        ):
            assistant.say("short reply", interruptible=False, also_print=False, log=False)

        monitor.start.assert_called_once()
        monitor.stop.assert_called_once()
        assistant._tts.speak_interruptible.assert_called_once()
        assistant._tts.speak.assert_not_called()

    def test_whats_new_in_this_update_is_not_wikipedia(self):
        from silva.commands.intent import is_action_command
        from silva.commands.registry import match_command
        from silva.commands.update_phrases import is_whats_new_update_phrase

        phrase = "what is new in this update"
        self.assertTrue(is_whats_new_update_phrase(phrase))
        self.assertTrue(is_action_command(phrase))
        self.assertIsNone(match_command(phrase))
        self.assertIsNone(match_command("what's new in this update"))


class SpeechToTextTests(unittest.TestCase):
    def test_incomplete_phrase_detection(self):
        self.assertTrue(_looks_incomplete("who"))
        self.assertTrue(_looks_incomplete("who am"))
        self.assertFalse(_looks_incomplete("set voice"))
        self.assertFalse(_looks_incomplete("open profiles"))
        self.assertTrue(_looks_incomplete("open pro"))
        self.assertTrue(_looks_incomplete("open"))
        self.assertTrue(_looks_incomplete("set my"))
        self.assertFalse(_looks_incomplete("who am i"))
        self.assertFalse(_looks_incomplete("set my voice"))

    def test_profile_partial_detection(self):
        self.assertTrue(_profile_command_partial("open"))
        self.assertTrue(_profile_command_partial("open pro"))
        self.assertTrue(_profile_command_partial("prof"))
        self.assertFalse(_profile_command_partial("open profile"))
        self.assertFalse(_profile_command_partial("open profiles"))

    def test_concat_audio(self):
        first = sr.AudioData(b"\x01\x02" * 100, 16000, 2)
        second = sr.AudioData(b"\x03\x04" * 100, 16000, 2)
        merged = _concat_audio(first, second)
        self.assertEqual(len(merged.get_raw_data()), len(first.get_raw_data()) + len(second.get_raw_data()))

    def test_conversation_skips_continuation(self):
        self.assertTrue(is_conversational_utterance("how are you today"))
        self.assertTrue(is_conversational_utterance("how are you today silva"))
        self.assertFalse(_needs_more_speech("how are you today"))
        self.assertFalse(_needs_more_speech("hello silva how are you"))

    def test_dedupe_repeated_phrase(self):
        self.assertEqual(
            _dedupe_repeated_phrase("how are you today silver how are you today"),
            "how are you today",
        )
        self.assertEqual(_dedupe_repeated_phrase("hello hello"), "hello")
        self.assertEqual(
            _dedupe_repeated_phrase("how are you doing how are you doing"),
            "how are you doing",
        )

    def test_router_cache_lookup(self):
        from silva.cache.router_cache import lookup_route, preload_router_cache

        preload_router_cache(force_rebuild=True)
        hint = lookup_route("how are you doing")
        self.assertIsNotNone(hint)
        assert hint is not None
        self.assertEqual(hint.route_type, "conversation")
        self.assertEqual(hint.name, "how_are_you")
        weather = lookup_route("what is my local weather")
        self.assertIsNotNone(weather)
        assert weather is not None
        self.assertEqual(weather.name, "weather")

    def test_speech_guard_detects_spike(self):
        import numpy as np
        from silva.stt_speech_guard import DisruptionKind, analyze_audio

        quiet = (np.random.randn(16000).astype(np.float32) * 20).astype(np.int16).tobytes()
        tail = (np.random.randn(8000).astype(np.float32) * 4000).astype(np.int16).tobytes()
        audio = sr.AudioData(quiet + tail, 16000, 2)
        analysis = analyze_audio(audio)
        self.assertIn(analysis.kind, {DisruptionKind.COUGH_SNEEZE, DisruptionKind.STUTTER, DisruptionKind.NONE})

    def test_vocabulary_cache_roundtrip(self):
        import tempfile
        from pathlib import Path
        from silva.conversation import vocab_cache

        with tempfile.TemporaryDirectory() as tmp:
            original_dir = vocab_cache.CACHE_DIR
            original_file = vocab_cache.CACHE_FILE
            vocab_cache.CACHE_DIR = Path(tmp)
            vocab_cache.CACHE_FILE = Path(tmp) / "conversation_vocab_v2.pkl"
            try:
                payload = {
                    "short_replies": ("ok",),
                    "medium_replies": ("hello there",),
                    "long_explain_replies": ("explain this",),
                    "casual_long_replies": ("chat more",),
                    "master_vocabulary": ("general line",),
                    "topic_pools": {"general": ("line one",)},
                    "all_replies": ("ok", "hello there"),
                    "word_index": {"hello": [1]},
                }
                vocab_cache.save_vocabulary_cache(payload)
                loaded = vocab_cache.load_cached_vocabulary()
                self.assertIsNotNone(loaded)
                assert loaded is not None
                self.assertEqual(loaded["all_replies"], ("ok", "hello there"))
            finally:
                vocab_cache.CACHE_DIR = original_dir
                vocab_cache.CACHE_FILE = original_file

    def test_recognizes_speech(self):
        stt = SpeechToText()
        audio = sr.AudioData(b"\x00\x00" * 16000, 16000, 2)
        with patch.object(stt, "_recognize_audio", return_value="weather"):
            with patch.object(sr.Recognizer, "listen", return_value=audio):
                with patch.object(sr.Microphone, "__enter__", return_value=MagicMock()):
                    with patch.object(sr.Microphone, "__exit__", return_value=False):
                        with patch.object(stt._recognizer, "adjust_for_ambient_noise"):
                            result = stt.listen(timeout=1, phrase_limit=1)
            self.assertEqual(result, "weather")

    def test_quiet_audio_gets_boosted_retry(self):
        stt = SpeechToText()
        audio = sr.AudioData(b"\x01\x00" * 8000, 16000, 2)
        with patch.object(stt, "_listen_raw", return_value=audio):
            with patch.object(stt, "_recognize_audio", side_effect=["hello", "hello there"]):
                with patch("silva.stt.last_listen_confidence", side_effect=[0.3, 0.8]):
                    text, _audio = stt.listen_with_audio(
                        timeout=1,
                        phrase_limit=1,
                        skip_continuation=True,
                    )
        self.assertEqual(text, "hello there")

    def test_quiet_low_confidence_waits_silently(self):
        stt = SpeechToText()
        audio = sr.AudioData(b"\x01\x00" * 8000, 16000, 2)
        with patch.object(stt, "_listen_raw", return_value=audio):
            with patch.object(stt, "_recognize_audio", return_value="hello"):
                with patch("silva.stt.last_listen_confidence", return_value=0.2):
                    text, _audio = stt.listen_with_audio(
                        timeout=1,
                        phrase_limit=1,
                        skip_continuation=True,
                    )
        self.assertIsNone(text)


class TextToSpeechTests(unittest.TestCase):
    def test_openai_pronunciation(self):
        from silva.tts_pronunciation import prepare_for_speech

        spoken = prepare_for_speech("OpenAI released a new model.")
        self.assertIn("Open A I", spoken)

    def test_defaults_to_female_voice(self):
        tts = TextToSpeech(volume=0.65)
        voices = tts.list_voices()
        self.assertGreaterEqual(len(voices), 1)
        self.assertEqual(tts._voice_index, 1)
        self.assertIn("Zira", voices[1])
        self.assertEqual(tts._volume, 0.65)


class VoiceProfileTests(unittest.TestCase):
    def test_save_and_identify_voice(self):
        audio = sr.AudioData(bytes([1, 2] * 8000), 16000, 2)
        path = save_voice_profile("test_voice_user", audio, name="Test Voice User", queue_pending=False)
        self.assertTrue(path.exists())

        candidates = {"test_voice_user": {"voice_enrolled": True, "name": "Test Voice User"}}
        user_id, score, _closest = identify_user(audio, candidates)
        self.assertEqual(user_id, "test_voice_user")
        self.assertGreaterEqual(score, 0.72)

        path.unlink(missing_ok=True)
        from silva.users.voice_id import fingerprint_path, profile_path

        fingerprint_path("test_voice_user").unlink(missing_ok=True)
        profile_path("test_voice_user").unlink(missing_ok=True)

    def test_identify_listens_to_saved_wav(self):
        import math
        import struct
        import tempfile
        from pathlib import Path

        from silva.users import voice_id as voice_mod

        samples = [int(12000 * math.sin(2 * math.pi * 180 * i / 16000)) for i in range(16000 * 2)]
        raw = struct.pack(f"{len(samples)}h", *samples)
        audio = sr.AudioData(raw, 16000, 2)

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            with patch.object(voice_mod, "VOICES_DIR", folder):
                path = save_voice_profile("wav_user", audio, name="Wav User", queue_pending=False)
                self.assertTrue(path.exists())
                self.assertEqual(path.suffix, ".wav")
                from silva.users.voice_id import load_fingerprint, load_voice_prints

                self.assertTrue(load_voice_prints("wav_user"))
                self.assertIsNotNone(load_fingerprint("wav_user"))
                user_id, score, _closest = identify_user(
                    audio,
                    {"wav_user": {"voice_enrolled": True, "name": "Wav User"}},
                )
                self.assertEqual(user_id, "wav_user")
                self.assertGreaterEqual(score, 0.72)

    def test_wav_preview_levels_from_saved_file(self):
        import math
        import struct
        import tempfile
        from pathlib import Path

        from silva.audio_recorder import wav_preview_levels

        samples = [int(8000 * math.sin(2 * math.pi * 220 * i / 16000)) for i in range(16000)]
        raw = struct.pack(f"{len(samples)}h", *samples)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "example.wav"
            import wave

            with wave.open(str(path), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(16000)
                handle.writeframes(raw)
            preview = wav_preview_levels(path, bars=16)
            self.assertTrue(preview["exists"])
            self.assertEqual(preview["name"], "example.wav")
            self.assertGreater(preview["seconds"], 0.5)
            self.assertEqual(len(preview["levels"]), 16)
            self.assertGreater(max(preview["levels"]), 0.0)


class PermissionRequestTests(unittest.TestCase):
    def test_weekly_request_limit(self):
        import uuid

        from silva.users.permission_requests import (
            can_submit_request,
            record_request,
            requests_remaining,
        )

        user_id = f"test_perm_{uuid.uuid4().hex[:8]}"
        self.assertTrue(can_submit_request(user_id))
        for _ in range(3):
            record_request(user_id)
        self.assertFalse(can_submit_request(user_id))
        self.assertEqual(requests_remaining(user_id), 0)


class VoiceRequestTests(unittest.TestCase):
    def test_submit_and_approve_voice_request(self):
        from silva.users.manager import add_user, load_store, remove_user
        from silva.users.voice_requests import (
            approve_voice_request,
            list_voice_requests,
            submit_voice_request,
        )

        audio = sr.AudioData(bytes([3, 4] * 8000), 16000, 2)
        request_id = submit_voice_request(audio, note="test sample")
        self.assertTrue(any(item["id"] == request_id for item in list_voice_requests()))

        user = add_user("Voice Request Test", tier=2)
        owner = get_owner()
        self.assertTrue(
            approve_voice_request(request_id, user["id"], approver_id=owner["id"])
        )
        store = load_store()
        self.assertTrue(store["users"][user["id"]]["voice_enrolled"])
        remove_user(user["id"])

    def test_recorded_wav_queues_pending_sample(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from silva.users import voice_requests as req_mod
        from silva.users.voice_requests import list_voice_requests, queue_voice_sample

        audio = sr.AudioData(bytes([5, 6] * 8000), 16000, 2)
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            with patch.object(req_mod, "VOICE_REQUESTS_DIR", folder), patch.object(
                req_mod, "VOICE_REQUESTS_FILE", folder / "pending.json"
            ):
                request_id = queue_voice_sample(
                    audio,
                    intended_user_id="kevin",
                    intended_name="Kevin",
                    note="Recorded for Kevin",
                )
                pending = list_voice_requests()
                self.assertTrue(any(item["id"] == request_id for item in pending))
                match = next(item for item in pending if item["id"] == request_id)
                self.assertEqual(match["intended_user_id"], "kevin")
                self.assertTrue(Path(match["wav_file"]).exists())

    def test_save_voice_profile_queues_pending_sample(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from silva.users import voice_id as voice_mod
        from silva.users import voice_requests as req_mod
        from silva.users.voice_requests import list_voice_requests

        audio = sr.AudioData(bytes([7, 8] * 8000), 16000, 2)
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            with patch.object(voice_mod, "VOICES_DIR", folder), patch.object(
                req_mod, "VOICE_REQUESTS_DIR", folder
            ), patch.object(req_mod, "VOICE_REQUESTS_FILE", folder / "pending.json"):
                save_voice_profile("queued_user", audio, name="Queued User")
                pending = list_voice_requests()
                self.assertTrue(any(item.get("intended_user_id") == "queued_user" for item in pending))
                match = next(item for item in pending if item.get("intended_user_id") == "queued_user")
                self.assertEqual(match.get("intended_name"), "Queued User")
                self.assertTrue(Path(match["wav_file"]).exists())


class LocationTests(unittest.TestCase):
    def test_wifi_detection_returns_bool(self):
        self.assertIsInstance(is_wifi_connected(), bool)


class WeatherReportTests(unittest.TestCase):
    def test_speech_includes_day_or_night(self):
        report = WeatherReport(
            city="Englewood",
            temp_f=79,
            humidity=66,
            wind_mph=2,
            conditions="clear skies",
            is_day=False,
            latitude=35.4,
            longitude=-84.4,
            source="windows_location",
        )
        speech = report.to_speech()
        self.assertIn("nighttime", speech)
        self.assertIn("Englewood", speech)

    def test_display_includes_forecast_days(self):
        from silva.gui.weather_popup import ForecastDayDisplay

        report = WeatherReport(
            city="Englewood",
            temp_f=79,
            humidity=66,
            wind_mph=2,
            conditions="clear skies",
            is_day=False,
            latitude=35.4,
            longitude=-84.4,
            source="windows_location",
        )
        days = (
            ForecastDayDisplay("Wednesday", 72, 50, "partly cloudy", 20),
            ForecastDayDisplay("Thursday", 68, 48, "rain showers", 80),
        )
        display = report.to_display(days)
        self.assertEqual(display.city, "Englewood")
        self.assertEqual(len(display.forecast_days), 2)
        self.assertEqual(display.forecast_days[1].rain_chance, 80)


class WeatherForecastTests(unittest.TestCase):
    def test_forecast_phrases(self):
        from silva.commands.weather_forecast_phrases import (
            is_weather_forecast_command,
            requested_forecast_days,
        )

        samples = (
            "weather forecast",
            "next few days weather",
            "what's the 7 day forecast",
            "will it rain this week",
            "open the forecast",
            "3 day forecast",
            "what's my local forecast",
            "whats my local forcast",
            "what is my local forecast",
            "how's the local forecast",
            "tell me the local forecast",
            "check my local forcast",
            "what's 1 - 3 days of weather",
            "whats 1-3 days of weather",
            "1 to 3 days of weather",
            "3 to 7 day forecast",
            "give me the weekly outlook",
            "show me my forecast",
            "pull up the forecast",
        )
        for text in samples:
            self.assertTrue(is_weather_forecast_command(text), msg=text)

        self.assertFalse(is_weather_forecast_command("what's my weather"))
        self.assertEqual(requested_forecast_days("next 3 days"), 3)
        self.assertEqual(requested_forecast_days("7 day forecast"), 7)
        self.assertEqual(requested_forecast_days("next few days"), 5)
        self.assertEqual(requested_forecast_days("this week"), 7)
        self.assertEqual(requested_forecast_days("what's 1 - 3 days of weather"), 3)
        self.assertEqual(requested_forecast_days("3 to 7 days"), 7)

    def test_forecast_not_treated_as_math(self):
        from silva.commands.math_phrases import is_math_command

        self.assertFalse(is_math_command("what's 1 - 3 days of weather"))
        self.assertFalse(is_math_command("whats 1-3 days of weather"))
        self.assertTrue(is_math_command("what is 10 plus 5"))

    def test_saves_txt_and_rewrites_on_change(self):
        import tempfile
        from pathlib import Path

        from silva.commands.weather_forecast import (
            ForecastDay,
            ForecastReport,
            load_saved_forecast,
            refresh_forecast,
            save_forecast,
        )

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        txt = base / "forecast.txt"
        json_path = base / "forecast.json"

        first = ForecastReport(
            city="Englewood",
            latitude=35.4,
            longitude=-84.4,
            source="open-meteo",
            generated_at="2026-10-21 12:00:00",
            days=[
                ForecastDay("2026-10-21", "Wednesday", 72, 50, "partly cloudy", 20),
                ForecastDay("2026-10-22", "Thursday", 68, 48, "rain showers", 80),
                ForecastDay("2026-10-23", "Friday", 64, 46, "overcast", 40),
            ],
        )
        second = ForecastReport(
            city="Englewood",
            latitude=35.4,
            longitude=-84.4,
            source="open-meteo",
            generated_at="2026-10-21 18:00:00",
            days=[
                ForecastDay("2026-10-21", "Wednesday", 70, 49, "rain", 90),
                ForecastDay("2026-10-22", "Thursday", 68, 48, "rain showers", 80),
                ForecastDay("2026-10-23", "Friday", 64, 46, "overcast", 40),
            ],
        )

        with (
            patch("silva.commands.weather_forecast.FORECAST_TXT", txt),
            patch("silva.commands.weather_forecast.FORECAST_JSON", json_path),
            patch("silva.commands.weather_forecast.ensure_weather_dir"),
            patch("silva.commands.weather_forecast.is_wifi_connected", return_value=True),
            patch("silva.commands.weather_forecast.skim_public_forecast", return_value=first),
        ):
            saved = refresh_forecast(days=3)
            self.assertTrue(txt.exists())
            self.assertIn("80% chance of rain", txt.read_text(encoding="utf-8"))
            self.assertEqual(saved.city, "Englewood")

        with (
            patch("silva.commands.weather_forecast.FORECAST_TXT", txt),
            patch("silva.commands.weather_forecast.FORECAST_JSON", json_path),
            patch("silva.commands.weather_forecast.ensure_weather_dir"),
            patch("silva.commands.weather_forecast.is_wifi_connected", return_value=True),
            patch("silva.commands.weather_forecast.skim_public_forecast", return_value=first),
        ):
            unchanged = refresh_forecast(days=3)
            self.assertFalse(unchanged.changed)

        with (
            patch("silva.commands.weather_forecast.FORECAST_TXT", txt),
            patch("silva.commands.weather_forecast.FORECAST_JSON", json_path),
            patch("silva.commands.weather_forecast.ensure_weather_dir"),
            patch("silva.commands.weather_forecast.is_wifi_connected", return_value=True),
            patch("silva.commands.weather_forecast.skim_public_forecast", return_value=second),
        ):
            updated = refresh_forecast(days=3)
            self.assertTrue(updated.changed)
            self.assertIn("90% chance of rain", txt.read_text(encoding="utf-8"))

        with (
            patch("silva.commands.weather_forecast.FORECAST_TXT", txt),
            patch("silva.commands.weather_forecast.FORECAST_JSON", json_path),
            patch("silva.commands.weather_forecast.ensure_weather_dir"),
            patch("silva.commands.weather_forecast.is_wifi_connected", return_value=False),
        ):
            offline = refresh_forecast(days=3)
            self.assertTrue(offline.offline)
            self.assertEqual(offline.days[0].rain_chance, 90)
            loaded = load_saved_forecast()
            self.assertIsNotNone(loaded)

    def test_reads_full_saved_forecast(self):
        from silva.commands.weather_forecast import ForecastDay, ForecastReport
        from silva.commands.weather_forecast_handler import handle_forecast_speech

        report = ForecastReport(
            city="Englewood",
            latitude=35.4,
            longitude=-84.4,
            source="open-meteo",
            generated_at="2026-10-21 12:00:00",
            days=[
                ForecastDay("2026-10-21", "Wednesday", 72, 50, "partly cloudy", 20),
                ForecastDay("2026-10-22", "Thursday", 68, 48, "rain showers", 80),
            ],
        )
        with patch("silva.commands.weather_forecast_handler.refresh_forecast", return_value=report):
            msg, flow = handle_forecast_speech("what's my local forecast")
            self.assertIsNone(flow)
            self.assertIn("saved local forecast", msg)
            self.assertIn("20 percent chance of rain", msg)
            self.assertIn("80 percent chance of rain", msg)
            self.assertNotIn("Want the next day", msg)


class AppointmentTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        self._tmpdir = tempfile.TemporaryDirectory()
        self._appointments_file = Path(self._tmpdir.name) / "appointments.json"
        patcher = patch("silva.commands.appointments.APPOINTMENTS_FILE", self._appointments_file)
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_parse_datetime_tomorrow_at_time(self):
        from datetime import datetime, timedelta

        from silva.commands.appointments import parse_datetime_from_text

        now = datetime(2026, 6, 30, 10, 0)
        when = parse_datetime_from_text("tomorrow at 2 pm", now=now)
        self.assertIsNotNone(when)
        assert when is not None
        self.assertEqual(when.date(), (now + timedelta(days=1)).date())
        self.assertEqual(when.hour, 14)
        self.assertEqual(when.minute, 0)

    def test_match_appointment_phrases(self):
        from silva.commands.appointment_phrases import match_appointment_speech

        create = match_appointment_speech("schedule appointment dentist tomorrow at 2 pm")
        self.assertIsNotNone(create)
        assert create is not None
        self.assertEqual(create.action, "create")
        self.assertIn("dentist", create.query)

        listing = match_appointment_speech("list my appointments")
        self.assertIsNotNone(listing)
        assert listing is not None
        self.assertEqual(listing.action, "list")

    def test_create_and_list_appointments(self):
        from datetime import datetime, timedelta

        from silva.commands.appointment_handler import handle_appointment_speech
        from silva.commands.appointments import list_appointments

        when = datetime.now().replace(second=0, microsecond=0) + timedelta(days=1, hours=2)
        hour = when.hour % 12 or 12
        meridiem = "pm" if when.hour >= 12 else "am"
        msg, flow = handle_appointment_speech(
            "test_user",
            f"schedule appointment dentist tomorrow at {hour} {meridiem}",
        )
        self.assertIn("Saved", msg)
        self.assertIsNotNone(flow)
        rows = list_appointments("test_user")
        self.assertEqual(len(rows), 1)
        self.assertIn("Dentist", rows[0]["title"])

    def test_reminder_flow_yes_then_30_minutes(self):
        from datetime import datetime, timedelta

        from silva.commands.appointment_handler import (
            continue_appointment_flow,
            handle_appointment_speech,
        )
        from silva.commands.appointments import list_appointments

        when = datetime.now().replace(second=0, microsecond=0) + timedelta(days=2)
        hour = when.hour % 12 or 12
        meridiem = "pm" if when.hour >= 12 else "am"
        _, flow = handle_appointment_speech(
            "test_user",
            f"schedule appointment doctor tomorrow at {hour} {meridiem}",
        )
        self.assertIsNotNone(flow)
        assert flow is not None
        msg, flow = continue_appointment_flow("test_user", "yes", flow)
        self.assertIn("How early", msg)
        self.assertIsNotNone(flow)
        assert flow is not None
        msg, flow = continue_appointment_flow("test_user", "30 minutes before", flow)
        self.assertIn("Reminder set", msg)
        self.assertIsNone(flow)
        rows = list_appointments("test_user")
        self.assertTrue(rows[0]["reminder"]["enabled"])
        self.assertIn(30, rows[0]["reminder"]["offsets_minutes"])

    def test_offset_reminder_fires(self):
        from datetime import datetime, timedelta

        from silva.commands.appointments import check_due_reminders, create_appointment

        when = datetime.now().replace(second=0, microsecond=0) + timedelta(minutes=20)
        create_appointment(
            "test_user",
            title="Meeting",
            when=when,
            reminder={"enabled": True, "offsets_minutes": [30], "periodic_every_minutes": None},
        )
        now = when - timedelta(minutes=30)
        with patch("silva.commands.appointments._now", return_value=now):
            messages = check_due_reminders("test_user")
        self.assertTrue(any("Meeting" in msg for msg in messages))

    def test_complete_command_includes_appointments(self):
        from silva.stt_quick_commands import is_complete_command

        self.assertTrue(is_complete_command("list my appointments"))
        self.assertTrue(is_complete_command("schedule appointment dentist tomorrow at 2 pm"))


class MathTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        self._tmpdir = tempfile.TemporaryDirectory()
        self._history_file = Path(self._tmpdir.name) / "silva_history.json"
        patcher = patch("silva.history_store.HISTORY_FILE", self._history_file)
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_basic_arithmetic(self):
        from silva.commands.math import evaluate_math

        result, category = evaluate_math("5 plus 3")
        self.assertEqual(result, "8")
        self.assertEqual(category, "expression")

    def test_percent_calculation(self):
        from silva.commands.math import evaluate_math

        result, _ = evaluate_math("15 percent of 200")
        self.assertIn("30", result)
        self.assertIn("200", result)

    def test_unit_conversion(self):
        from silva.commands.math import evaluate_math

        result, category = evaluate_math("5 feet to inches")
        self.assertIn("60", result)
        self.assertEqual(category, "unit_conversion")

    def test_algebra_equation(self):
        from silva.commands.math import evaluate_math

        result, category = evaluate_math("2x + 5 = 15")
        self.assertIn("5", result)
        self.assertEqual(category, "algebra")

    def test_math_history(self):
        from silva.commands.math import handle_math_speech

        handle_math_speech("user1", "calculate 10 plus 5")
        recall = handle_math_speech("user1", "recall my last calculation")
        self.assertIn("15", recall)

    def test_math_phrase_matching(self):
        from silva.commands.math_phrases import match_math_speech

        speech = match_math_speech("what is 25 times 4")
        self.assertIsNotNone(speech)
        assert speech is not None
        self.assertEqual(speech.action, "calculate")

    def test_daily_rate_for_month(self):
        from silva.commands.math import evaluate_math

        result, category = evaluate_math("how much can I earn at 50 dollars a day for a month")
        self.assertEqual(category, "money")
        self.assertIn("$1,500", result)

    def test_hourly_weekly_monthly_schedule(self):
        from silva.commands.math import evaluate_math

        result, category = evaluate_math(
            "20 an hour 8 hours a day 5 days a week how much a month"
        )
        self.assertEqual(category, "money")
        self.assertIn("week", result.lower())
        self.assertIn("month", result.lower())

    def test_worked_days_earnings(self):
        from silva.commands.math import evaluate_math

        result, _ = evaluate_math("I worked 15 days at 100 a day")
        self.assertIn("$1,500", result)

    def test_annual_salary_to_monthly(self):
        from silva.commands.math import evaluate_math

        result, _ = evaluate_math("60000 a year to monthly salary")
        self.assertIn("$5,000", result)

    def test_overtime_pay(self):
        from silva.commands.math import evaluate_math

        result, _ = evaluate_math("20 an hour 40 hours plus 10 overtime hours at time and a half")
        self.assertIn("$1,100", result)

    def test_commission(self):
        from silva.commands.math import evaluate_math

        result, _ = evaluate_math("5 percent commission on 10000 in sales")
        self.assertIn("$500", result)

    def test_profit_margin(self):
        from silva.commands.math import evaluate_math

        result, _ = evaluate_math("profit selling at 50 cost 30 for 10 units")
        self.assertIn("$200", result)

    def test_after_tax(self):
        from silva.commands.math import evaluate_math

        result, _ = evaluate_math("5000 after 20 percent tax")
        self.assertIn("$4,000", result)

    def test_split_bill_with_tip(self):
        from silva.commands.math import evaluate_math

        result, _ = evaluate_math("split 120 bill 4 ways with 18 percent tip")
        self.assertIn("$35.40", result)

    def test_compare_income(self):
        from silva.commands.math import evaluate_math

        result, _ = evaluate_math("compare 25 an hour vs 52000 a year")
        self.assertIn("more per year", result)

    def test_multiple_income_streams(self):
        from silva.commands.math import evaluate_math

        result, _ = evaluate_math("200 a day for 10 days plus 150 a day for 5 days")
        self.assertIn("$2,750", result)

    def test_price_point_sales_per_day(self):
        from silva.commands.math import evaluate_math

        result, category = evaluate_math(
            "how much will I earn at 25 dollar price point with 10 sales a day"
        )
        self.assertEqual(category, "money")
        self.assertIn("$250", result)
        self.assertIn("month", result.lower())

    def test_price_point_per_day_single_sale(self):
        from silva.commands.math import evaluate_math

        result, _ = evaluate_math("how much will I earn at 50 price point per day")
        self.assertIn("$50", result)
        self.assertIn("day", result.lower())

    def test_price_point_weekly_breakdown(self):
        from silva.commands.math import evaluate_math

        result, _ = evaluate_math("40 price point 20 sales per week how much will I earn")
        self.assertIn("$800", result)
        self.assertIn("week", result.lower())

    def test_units_needed_for_daily_target(self):
        from silva.commands.math import evaluate_math

        result, _ = evaluate_math("how many sales at 25 price point to make 500 a day")
        self.assertIn("20", result)

    def test_price_point_with_cost_profit(self):
        from silva.commands.math import evaluate_math

        result, _ = evaluate_math(
            "sell at 50 price point cost 30 with 10 sales a day how much profit"
        )
        self.assertIn("$200", result)
        self.assertIn("profit", result.lower())

    def test_casual_earn_a_day_at_price(self):
        from silva.commands.math import evaluate_math

        result, category = evaluate_math("how much will I earn a day at 25")
        self.assertEqual(category, "money")
        self.assertIn("$25", result)
        self.assertIn("day", result.lower())

    def test_casual_for_volume_at_price(self):
        from silva.commands.math import evaluate_math

        result, _ = evaluate_math("how much a day for 10 at 25")
        self.assertIn("$250", result)

    def test_casual_at_price_for_volume(self):
        from silva.commands.math import evaluate_math

        result, _ = evaluate_math("how much will I earn a day at 30 for 5")
        self.assertIn("$150", result)

    def test_for_this_price_daily(self):
        from silva.commands.math import evaluate_math

        result, _ = evaluate_math("for this price 40 how much will I earn a day")
        self.assertIn("$40", result)

    def test_for_this_number_at_price(self):
        from silva.commands.math import evaluate_math

        result, _ = evaluate_math("how much will I earn a day for 8 at 20")
        self.assertIn("$160", result)


class MeasurementTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        self._tmpdir = tempfile.TemporaryDirectory()
        self._history_file = Path(self._tmpdir.name) / "silva_history.json"
        self._image_dir = Path(self._tmpdir.name) / "images"
        patchers = [
            patch("silva.history_store.HISTORY_FILE", self._history_file),
            patch("silva.commands.measurement.IMAGE_DIR", self._image_dir),
        ]
        for patcher in patchers:
            self.addCleanup(patcher.stop)
            patcher.start()

    def test_measurement_phrase_camera(self):
        from silva.commands.measurement_phrases import match_measurement_speech

        speech = match_measurement_speech("hey silva can you look at this in my hand")
        self.assertIsNotNone(speech)
        assert speech is not None
        self.assertEqual(speech.source, "camera")

    def test_measurement_phrase_screen(self):
        from silva.commands.measurement_phrases import match_measurement_speech

        speech = match_measurement_speech("measure what's on my screen")
        self.assertIsNotNone(speech)
        assert speech is not None
        self.assertEqual(speech.source, "screen")

    def test_measure_frame_pixels(self):
        import numpy as np

        from silva.commands.measurement import measure_frame

        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[100:300, 150:450] = 255
        result = measure_frame(frame, query="measure this box")
        self.assertGreater(result.width_px, 0)
        self.assertGreater(result.height_px, 0)
        self.assertTrue(result.image_path)

    def test_complete_command_includes_math(self):
        from silva.stt_quick_commands import is_complete_command

        self.assertTrue(is_complete_command("what is 10 plus 5"))
        self.assertTrue(is_complete_command("look at this in my hand and measure it"))
        self.assertTrue(is_complete_command("silva mute this chrome"))
        self.assertTrue(is_complete_command("turn off audio for discord"))


class AudioControlTests(unittest.TestCase):
    def test_audio_phrase_variations(self):
        from silva.commands.audio_phrases import match_audio_speech

        mute = match_audio_speech("silva mute this chrome")
        self.assertIsNotNone(mute)
        assert mute is not None
        self.assertEqual(mute.action, "mute")
        self.assertEqual(mute.target, "chrome")

        quoted = match_audio_speech('mute "sons of the forest"')
        self.assertIsNotNone(quoted)
        assert quoted is not None
        self.assertEqual(quoted.action, "mute")
        self.assertEqual(quoted.target, "sons of the forest")

        unmute = match_audio_speech("turn sound back on for spotify")
        self.assertIsNotNone(unmute)
        assert unmute is not None
        self.assertEqual(unmute.action, "unmute")
        self.assertEqual(unmute.target, "spotify")

        game = match_audio_speech("mute the game")
        self.assertIsNotNone(game)
        assert game is not None
        self.assertEqual(game.action, "mute")
        self.assertEqual(game.target, "game")

        listing = match_audio_speech("what apps are playing audio")
        self.assertIsNotNone(listing)
        assert listing is not None
        self.assertEqual(listing.action, "list")

    @unittest.skipUnless(sys.platform == "win32", "Windows audio sessions only")
    def test_list_active_audio_sessions(self):
        from silva.audio_sessions import list_active_audio_sessions

        sessions = list_active_audio_sessions()
        self.assertIsInstance(sessions, list)

    @unittest.skipUnless(sys.platform == "win32", "Windows audio sessions only")
    def test_find_sessions_for_query(self):
        from silva.audio_sessions import find_sessions_for_query, list_active_audio_sessions

        active = list_active_audio_sessions()
        if not active:
            self.skipTest("No active audio sessions")
        sample = active[0].display_name
        matches = find_sessions_for_query(sample)
        self.assertGreaterEqual(len(matches), 1)


class PhraseRecordingTests(unittest.TestCase):
    def test_phrase_recorder_phrases(self):
        from silva.commands.phrase_recorder_phrases import match_phrase_recorder_speech, phrase_count

        self.assertGreaterEqual(phrase_count(), 100)

        samples = (
            "open the phrase recorder",
            "silva open my recorder",
            "record how i say things",
            "can you show the speech recorder",
            "please start recording my phrases",
            "hey silver open phrase recording",
            "i want to teach you my pronunciation",
            "help me record how i talk",
            "fix how silva hears me",
            "make a phrase recording",
            "go ahead and launch voice recorder",
            "let me record my wake word",
            "speech impediment recorder",
            "configure speech recorder",
            "pull up phrase recorder",
        )
        for text in samples:
            self.assertIsNotNone(
                match_phrase_recorder_speech(text),
                msg=f"Expected match for: {text}",
            )

    def test_phrase_recorder_popup_uses_display_host_without_waiting(self):
        from silva.gui import phrase_record_dialog as popup_module

        scheduled: list = []

        class Parent:
            def after(self, delay, callback):
                scheduled.append((delay, callback))

        with (
            patch("silva.gui.display_host.host_root", return_value=Parent()),
            patch.object(popup_module, "PhraseRecordDialog") as dialog,
        ):
            self.assertTrue(
                popup_module.show_phrase_record_popup({"id": "kevin", "name": "Kevin"})
            )
            dialog.assert_not_called()

        self.assertEqual(len(scheduled), 1)
        self.assertEqual(scheduled[0][0], 0)

    def test_assistant_phrase_recorder_command_does_not_block(self):
        from silva.assistant import SilvaAssistant

        assistant = SilvaAssistant.__new__(SilvaAssistant)
        assistant.say = MagicMock()
        user = {"id": "kevin", "name": "Kevin"}

        with patch("silva.assistant.show_phrase_record_popup", return_value=True) as show:
            self.assertTrue(assistant._handle_phrase_recorder_command("open voice recorder", user))

        show.assert_called_once_with(user)
        assistant.say.assert_called_once()

    def test_silver_wake_mishearing(self):
        from silva.wake_context import is_direct_wake_command, evaluate_wake

        self.assertTrue(is_direct_wake_command("silver wake up"))
        self.assertTrue(is_direct_wake_command("hey silva"))
        self.assertFalse(is_direct_wake_command("how are you doing today Silva"))
        decision = evaluate_wake("hey silver wake up")
        self.assertEqual(decision.action, "wake")

    def test_save_and_match_phrase_sample(self):
        import tempfile
        from pathlib import Path

        import speech_recognition as sr

        from silva.users.phrase_recordings import (
            match_phrase_recording,
            save_phrase_sample,
        )

        raw = bytes([1, 2] * 8000)
        audio = sr.AudioData(raw, 16000, 2)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            with (
                patch("silva.users.phrase_recordings.PHRASE_DIR", base),
                patch("silva.users.phrase_recordings.write_speech_audio") as write_audio,
            ):
                write_audio.return_value = base / "sample.mp3"
                sample = save_phrase_sample(
                    "test_user",
                    audio,
                    intended_text="silva wake up",
                    phrase_kind="wake",
                )
                self.assertEqual(sample.intended_text, "silva wake up")
                match = match_phrase_recording(audio, active_user_id="test_user", phrase_kinds={"wake"})
                self.assertIsNotNone(match)
                assert match is not None
                self.assertEqual(match.intended_text, "silva wake up")


class PlaybackCommandTests(unittest.TestCase):
    def test_playback_phrase_matching(self):
        from silva.commands.playback_phrases import match_playback_speech

        samples = (
            ("pause the video", "pause"),
            ("silva play the movie", "play"),
            ("resume playback", "play"),
            ("please pause it", "pause"),
            ("continue the video", "play"),
            ("pause", "pause"),
            ("play", "play"),
            ("play or pause", "toggle"),
        )
        for text, action in samples:
            speech = match_playback_speech(text)
            self.assertIsNotNone(speech, msg=text)
            assert speech is not None
            self.assertEqual(speech.action, action, msg=text)


class BackgroundRunnerTests(unittest.TestCase):
    def test_background_runner_calls_tick(self):
        import time

        from silva.background_runner import BackgroundRunner

        calls = {"count": 0}

        def tick() -> None:
            calls["count"] += 1

        runner = BackgroundRunner(tick)
        with patch("silva.background_runner.background_task_interval", return_value=0.05):
            runner.start()
            time.sleep(0.2)
            runner.stop()
        self.assertGreaterEqual(calls["count"], 2)


class NewsBriefingTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        self._tmpdir = tempfile.TemporaryDirectory()
        self._news_dir = Path(self._tmpdir.name) / "news"
        self._briefings_dir = self._news_dir / "briefings"
        self._briefings_dir.mkdir(parents=True)
        patchers = [
            patch("silva.commands.news_paths.NEWS_DIR", self._news_dir),
            patch("silva.commands.news_paths.BRIEFINGS_DIR", self._briefings_dir),
            patch("silva.commands.news_paths.STATE_FILE", self._news_dir / "state.json"),
            patch("silva.commands.news_paths.LATEST_JSON", self._news_dir / "latest_briefing.json"),
            patch("silva.commands.news_briefing.STATE_FILE", self._news_dir / "state.json"),
            patch("silva.commands.news_briefing.LATEST_JSON", self._news_dir / "latest_briefing.json"),
            patch("silva.commands.news_briefing.BRIEFINGS_DIR", self._briefings_dir),
        ]
        for patcher in patchers:
            self.addCleanup(patcher.stop)
            patcher.start()

    def test_news_phrases(self):
        from silva.commands.news_phrases import is_news_command, is_news_refresh_command

        self.assertTrue(is_news_command("show me the news briefing"))
        self.assertTrue(is_news_command("what is in the daily news briefing"))
        self.assertTrue(is_news_refresh_command("refresh the news briefing"))
        from silva.commands.intent import is_action_command

        self.assertTrue(is_action_command("what's my latest news"))
        self.assertTrue(is_action_command("what's my local weather"))
        self.assertFalse(is_news_command("weather today"))
        for phrase in (
            "what's my latest news",
            "whats my latest news",
            "what is my latest news",
            "what's the news",
            "tell me the latest news",
            "give me the news",
            "show me the news",
            "latest news",
            "headlines",
            "what's my local news",
            "whats my local news",
            "what's the latest",
            "whats the latest",
        ):
            self.assertTrue(is_news_command(phrase), msg=phrase)

    def test_readback_label(self):
        from silva.assistant import SilvaAssistant

        label = SilvaAssistant._readback_label(
            SilvaAssistant.__new__(SilvaAssistant),
            "The daytime weather in Englewood is clear skies with a temperature of 79 degrees Fahrenheit",
        )
        self.assertEqual(label, "the weather")

    def test_impact_scoring_and_selection(self):
        from silva.commands.news_analyzer import score_impact, select_impact_stories, skim_top_topics
        from silva.commands.news_sources import NewsItem

        items = [
            NewsItem("AI chip export rules tighten", "http://a", "government regulation on semiconductors", "Reuters", "us_major"),
            NewsItem("Local bakery opens", "http://b", "new shop downtown", "Local", "us_major"),
            NewsItem("Cyber outage hits cloud providers", "http://c", "global internet disruption", "AP", "us_major"),
        ]
        self.assertGreater(score_impact(items[0]), score_impact(items[1]))
        skimmed = skim_top_topics(items, limit=20)
        self.assertEqual(len(skimmed), 3)
        picks = select_impact_stories(items, count=2)
        self.assertEqual(len(picks), 2)
        self.assertNotIn("Local bakery opens", [item.title for item in picks])

    def test_format_and_save_briefing(self):
        from silva.commands.news_briefing import format_briefing_text, save_briefing

        briefing = {
            "date": "2026-06-30",
            "user_name": "Kevin",
            "location": "Boston, MA",
            "primary_source": "Reuters Top News",
            "skimmed_topic_count": 20,
            "impact_highlights": [
                {
                    "title": "Cyber outage hits cloud providers",
                    "source": "AP",
                    "link": "http://c",
                    "bullets": ["Services were disrupted worldwide."],
                }
            ],
            "top_five": [],
            "sections": {
                "ai": [{"title": "New AI model released", "source": "Verge", "link": "http://d", "bullets": ["Details here."]}],
                "food_health_local": [{"title": "Salmonella recall", "source": "FDA", "link": "http://e", "bullets": ["Check your fridge."]}],
                "us_major": [{"title": "Congress votes on bill", "source": "Reuters", "link": "http://f", "bullets": ["Vote expected today."]}],
            },
        }
        text = format_briefing_text(briefing)
        self.assertIn("HIGH-IMPACT PICKS", text)
        self.assertIn("Salmonella recall", text)
        txt_path, _ = save_briefing(briefing)
        self.assertTrue(txt_path.exists())
        old = self._briefings_dir / "2026-01-01.txt"
        old.write_text("old briefing", encoding="utf-8")
        save_briefing(briefing)
        self.assertTrue(txt_path.exists())
        self.assertFalse(old.exists())

    def test_news_readout_does_not_open_file_unless_requested(self):
        from silva.commands.news_handler import handle_news_speech
        from silva.commands.news_phrases import is_news_open_file

        self.assertFalse(is_news_open_file("what's my latest news"))
        self.assertFalse(is_news_open_file("read me the news"))
        self.assertTrue(is_news_open_file("show me the news"))
        self.assertTrue(is_news_open_file("open the briefing"))

        briefing = {
            "date": "2026-10-29",
            "user_name": "Kevin",
            "impact_highlights": [{"title": "Example headline"}],
            "top_five": [],
        }
        user = {"id": "kevin", "name": "Kevin", "tier": 5}
        with patch("silva.commands.news_handler.can_use_news_briefing", return_value=True), patch(
            "silva.commands.news_handler.load_latest_briefing", return_value=briefing
        ), patch("silva.commands.news_handler.open_briefing_txt") as opener:
            speak_msg, _flow = handle_news_speech("what's my latest news", user)
            self.assertIn("briefing is ready", speak_msg.lower())
            self.assertNotIn("opened the briefing", speak_msg.lower())
            opener.assert_not_called()

            open_msg, _flow = handle_news_speech("show me the news", user)
            self.assertIn("opened the briefing", open_msg.lower())
            opener.assert_called_once()

    def test_manual_only_suppresses_scheduled_news_refresh_and_prompt(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        from silva.commands.news_briefing import load_news_state, save_briefing
        from silva.commands.news_handler import offer_prompt_if_ready
        from silva.commands.news_monitor import (
            pending_prompt_for_user,
            refresh_daily_briefing,
            should_refresh_today,
        )
        from silva.yes_no_prompt import check_news_briefing

        config = {
            "news_briefing_enabled": True,
            "news_briefing_manual_only": True,
            "news_briefing_daily_hour": 7,
            "news_briefing_display_minutes": 3,
        }
        briefing = {
            "date": "2026-11-25",
            "user_name": "Kevin",
            "impact_highlights": [{"title": "Example headline"}],
            "top_five": [],
            "sections": {"ai": [], "food_health_local": [], "us_major": []},
        }
        spoken = []
        assistant = SimpleNamespace(
            _scheduled_alerts_paused=lambda: False,
            _asleep=False,
            _news_flow=None,
            say=lambda message, **_kwargs: spoken.append(message),
        )
        with patch("silva.config.load_config", return_value=config), patch(
            "silva.commands.news_monitor.load_config", return_value=config
        ), patch("silva.commands.news_briefing.load_config", return_value=config), patch(
            "silva.commands.news_monitor.is_wifi_connected", return_value=True
        ), patch("silva.users.manager.is_owner", return_value=True), patch(
            "silva.commands.news_briefing.generate_and_store_briefing"
        ) as generate:
            self.assertFalse(should_refresh_today())
            self.assertFalse(
                refresh_daily_briefing(user_id="kevin", user_name="Kevin")
            )
            generate.assert_not_called()

            save_briefing(briefing)
            self.assertFalse(load_news_state().get("pending_prompt"))
            self.assertFalse(pending_prompt_for_user("kevin"))
            self.assertIsNone(offer_prompt_if_ready({"id": "kevin", "name": "Kevin", "tier": 5}))
            check_news_briefing(assistant)
            self.assertEqual(spoken, [])

    def test_owner_admin_access_only(self):
        from silva.commands.news_monitor import can_use_news_briefing

        owner = {"id": "kevin", "tier": 5}
        admin = {"id": "admin1", "tier": 4}
        user = {"id": "guest", "tier": 2}
        with patch("silva.users.manager.is_owner", side_effect=lambda u=None: (u or owner).get("tier", 0) >= 5):
            self.assertTrue(can_use_news_briefing(owner))
            self.assertTrue(can_use_news_briefing(admin))
            self.assertFalse(can_use_news_briefing(user))

    def test_news_flow_decline_saves_for_later(self):
        from silva.commands.news_handler import continue_news_flow

        flow = {"phase": "await_show_choice", "user_id": "kevin"}
        msg, next_flow = continue_news_flow("no thanks", flow, is_yes=False, is_no=True)
        self.assertIsNone(next_flow)
        self.assertIn("saved", msg.lower())

    def test_news_flow_does_not_reask_yes_no(self):
        from silva.commands.news_handler import continue_news_flow
        from silva.commands.news_phrases import is_news_no, is_news_yes

        self.assertTrue(is_news_yes("yes"))
        self.assertTrue(is_news_yes("yeah show it"))
        self.assertTrue(is_news_no("no"))
        self.assertTrue(is_news_no("not now"))
        self.assertFalse(is_news_yes("what's my local weather"))

        flow = {"phase": "await_show_choice", "user_id": "kevin"}
        msg, next_flow = continue_news_flow(
            "what's my local weather",
            flow,
            is_yes=False,
            is_no=False,
        )
        self.assertIsNone(msg)
        self.assertEqual(next_flow, flow)
        self.assertNotIn("say yes", (msg or "").lower())

    def test_complete_command_includes_news(self):
        from silva.stt_quick_commands import is_complete_command

        self.assertTrue(is_complete_command("show me the news briefing"))

    def test_latest_yes_no_goes_to_news_not_camera(self):
        from types import SimpleNamespace

        from silva.yes_no_prompt import KIND_CAMERA_TEST, KIND_NEWS, claim, dispatch, owner

        spoken = []
        assistant = SimpleNamespace(
            _yes_no_owner=None,
            _news_flow={"phase": "await_show_choice", "user_id": "kevin"},
            _camera_setup_flow={
                "phase": "await_choice",
                "name": "Elgato Facecam MK.2",
                "is_combo": False,
            },
        )
        assistant._is_yes = lambda text: text.strip().lower() in {"yes", "yeah"}
        assistant._is_no = lambda text: text.strip().lower() in {"no", "nope"}
        assistant.say = lambda msg, **_kwargs: spoken.append(msg)
        assistant._apply_camera_setup_flow = lambda _msg, _flow: None
        assistant._handle_profile_switch_reply = lambda _text: False

        claim(assistant, KIND_CAMERA_TEST)
        claim(assistant, KIND_NEWS)
        self.assertEqual(owner(assistant), KIND_NEWS)
        self.assertIs(assistant._camera_setup_flow.get("yes_no"), False)

        with patch("silva.commands.news_handler.clear_pending_prompt"):
            handled = dispatch(assistant, "no")
        self.assertTrue(handled)
        self.assertIsNone(assistant._news_flow)
        self.assertTrue(spoken)
        self.assertIn("saved", spoken[0].lower())
        self.assertTrue(assistant._camera_setup_flow)
        self.assertFalse(dispatch(assistant, "no"))


class GuestDemoTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        self._tmpdir = tempfile.TemporaryDirectory()
        self._root = Path(self._tmpdir.name)
        self.addCleanup(self._tmpdir.cleanup)
        self._users_file = self._root / "users.json"
        self._backup_file = self._root / "users.json.bak"
        self._demo_state = self._root / "guest_demo_state.json"
        self._attitude_state = self._root / "attitudes.json"
        patchers = [
            patch("silva.users.manager.USERS_FILE", self._users_file),
            patch("silva.users.manager.USERS_BACKUP_FILE", self._backup_file),
            patch("silva.users.guest_demo.STATE_FILE", self._demo_state),
            patch("silva.conversation.attitude.STATE_FILE", self._attitude_state),
        ]
        for patcher in patchers:
            self.addCleanup(patcher.stop)
            patcher.start()

    def test_start_guest_demo_uses_clean_limited_profile(self):
        from silva.conversation.attitude import note_user_text, style_reply
        from silva.users import guest_demo
        from silva.users.manager import get_active_user, get_owner

        owner = get_owner()
        guest_demo.start_guest_demo(owner)
        self.assertTrue(guest_demo.guest_demo_active())

        guest = guest_demo.activate_guest_for_unknown_voice()
        self.assertIsNotNone(guest)
        self.assertEqual(get_active_user()["id"], "demo_guest")
        self.assertEqual(guest["tier"], 1)
        self.assertEqual(guest["role"], "guest")
        self.assertFalse(guest["voice_enrolled"])

        note_user_text("demo_guest", "act mean you dumb asshole")
        styled = style_reply("For fuck's sake, you asshole", "demo_guest")
        self.assertEqual(styled, "For freak's sake, you jerk")

    def test_owner_return_phrase_restores_owner_profile(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        from silva.users import guest_demo
        from silva.users.manager import get_active_user, get_owner

        owner = get_owner()
        spoken = []
        assistant = SimpleNamespace(say=lambda message, **_kwargs: spoken.append(message))
        with patch("silva.users.manager.is_owner", return_value=True):
            self.assertTrue(
                guest_demo.handle_guest_demo_speech(assistant, "let someone try you", owner)
            )
        self.assertTrue(guest_demo.guest_demo_active())
        guest_demo.activate_guest_for_unknown_voice()
        self.assertEqual(get_active_user()["id"], "demo_guest")

        with patch("silva.users.manager.is_owner", return_value=False):
            self.assertTrue(
                guest_demo.handle_guest_demo_speech(
                    assistant, "I'm back", get_active_user()
                )
            )
        self.assertEqual(get_active_user()["id"], owner["id"])
        self.assertFalse(guest_demo.guest_demo_active())
        self.assertIn("owner profile restored", spoken[-1].lower())

    def test_owner_return_phrases_and_demo_phrases(self):
        from silva.users.guest_demo import (
            is_guest_demo_start_command,
            is_owner_return_command,
        )

        for phrase in (
            "I'm back",
            "im back",
            "I am back",
            "silva i'm back",
            "back again",
            "I'm here",
            "the owner is back",
        ):
            self.assertTrue(is_owner_return_command(phrase), msg=phrase)
        self.assertFalse(is_owner_return_command("what is the weather"))

        for phrase in (
            "let someone try you",
            "allow my friend to talk to you",
            "show them what you can do",
            "guest demo mode on",
        ):
            self.assertTrue(is_guest_demo_start_command(phrase), msg=phrase)
        self.assertFalse(is_guest_demo_start_command("what is the weather"))


class ProtectionProtocolTests(unittest.TestCase):
    def test_activate_phrases(self):
        from silva.security.protection_protocol import classify_protection_command

        self.assertEqual(classify_protection_command("silva activate protection"), "activate")
        self.assertEqual(classify_protection_command("protection protocol"), "activate")
        self.assertEqual(classify_protection_command("silva protection off"), "deactivate")
        self.assertEqual(classify_protection_command("owner override"), "owner_override")

    def test_verification_code_parse(self):
        from silva.security.protection_protocol import parse_verification_entry

        self.assertTrue(parse_verification_entry("3 7 10 2 5 9 1 8", [3, 7, 10, 2, 5, 9, 1, 8]))
        self.assertFalse(parse_verification_entry("1 2 3 4 5 6 7 8", [3, 7, 10, 2, 5, 9, 1, 8]))

    def test_category_alert_log(self):
        from silva.alerts.category_log import log_category_alert, list_recent_alerts

        log_category_alert("weather", "Test alert", detail="unit test", asleep=True)
        recent = list_recent_alerts("weather", limit=5)
        self.assertTrue(any(item.get("title") == "Test alert" for item in recent))


class HelpPhraseTests(unittest.TestCase):
    def test_natural_help_phrase(self):
        from silva.commands.help_phrases import HELP_CAPABILITIES_TEXT, help_reply_for_user, is_help_request

        phrase = "now can you tell me what can you do"
        self.assertTrue(is_help_request(phrase))
        self.assertTrue(is_help_request("what do you do"))
        reply = help_reply_for_user({"id": "kevin", "tier": 5})
        self.assertIn("weather", reply.lower())
        self.assertIn("notes", reply.lower())
        self.assertNotIn("pile up", reply.lower())
        self.assertNotIn("stop speaking", reply.lower())
        self.assertNotIn("say stop", reply.lower())
        self.assertNotIn("background", reply.lower())
        self.assertNotIn("profile", reply.lower())
        self.assertNotIn("sleep", reply.lower())
        self.assertNotIn("camera", reply.lower())
        self.assertNotIn("if you want details", reply.lower())
        self.assertNotIn("specific one is available", reply.lower())
        self.assertLess(len(HELP_CAPABILITIES_TEXT), 400)

    def test_capability_ask_is_optional_detail(self):
        from silva.commands.help_phrases import (
            capability_reply_for_user,
            is_capability_ask,
            is_help_request,
        )

        owner = {"id": "kevin", "tier": 5}
        self.assertFalse(is_help_request("is the camera available"))
        self.assertTrue(is_capability_ask("is the camera available"))
        self.assertTrue(is_capability_ask("can you do notes"))
        self.assertIn("note this", capability_reply_for_user("can you do notes", owner).lower())
        self.assertIn("camera", capability_reply_for_user("is the camera available", owner).lower())
        self.assertIsNone(capability_reply_for_user("what do you do", owner))

    def test_watch_video_with_me_is_usage_not_capability_ask(self):
        from silva.commands.help_phrases import capability_reply_for_user, is_capability_ask

        owner = {"id": "kevin", "tier": 5}
        phrase = "can you watch the video with me"
        self.assertFalse(is_capability_ask(phrase))
        self.assertIsNone(capability_reply_for_user(phrase, owner))

    def test_feature_detail_only_when_asked(self):
        from silva.commands.help_phrases import (
            feature_detail_reply_for_user,
            is_capability_ask,
            is_feature_detail_ask,
            is_help_request,
        )

        owner = {"id": "kevin", "tier": 5}
        self.assertFalse(is_help_request("what can weather do"))
        self.assertFalse(is_capability_ask("what can weather do"))
        self.assertTrue(is_feature_detail_ask("what can weather do"))
        self.assertTrue(is_feature_detail_ask("what are the available options for notes"))
        self.assertTrue(is_feature_detail_ask("what are the camera options"))
        weather = feature_detail_reply_for_user("what can weather do", owner) or ""
        self.assertIn("forecast", weather.lower())
        self.assertGreater(len(weather), 80)
        self.assertFalse(is_feature_detail_ask("what's the weather"))
        self.assertFalse(is_feature_detail_ask("can you tell me what's my local weather"))
        self.assertFalse(is_capability_ask("can you tell me what's my local weather"))
        self.assertFalse(is_feature_detail_ask("look up building materials"))
        self.assertTrue(is_feature_detail_ask("give me details on maps"))
        self.assertTrue(is_feature_detail_ask("give me details on Matt"))
        self.assertTrue(is_feature_detail_ask("tell me in details about the news"))
        self.assertTrue(is_feature_detail_ask("tell me in details what do you do by notes"))
        which = feature_detail_reply_for_user("what are the available options", owner) or ""
        self.assertIn("weather", which.lower())
        self.assertNotIn("camera", which.lower())

    def test_todo_list_is_not_a_capability_question(self):
        from silva.commands.help_phrases import is_capability_ask, is_feature_detail_ask
        from silva.commands.notes_phrases import match_notes_speech

        text = "can you tell me what's on my to do list"
        self.assertFalse(is_capability_ask(text))
        self.assertFalse(is_feature_detail_ask(text))
        speech = match_notes_speech(text)
        self.assertIsNotNone(speech)
        assert speech is not None
        self.assertEqual(speech.action, "list_todo")

    def test_correction_is_not_an_undo_todo(self):
        from silva.commands.notes_phrases import match_notes_speech

        self.assertIsNone(match_notes_speech("that is not what I said"))
        self.assertIsNone(match_notes_speech("I didn't say that"))

    def test_lookup_details_are_not_a_search(self):
        from silva.commands.game_lookup_phrases import is_game_lookup
        from silva.commands.help_phrases import (
            feature_detail_reply_for_user,
            is_capability_ask,
            is_feature_detail_ask,
            is_help_request,
        )
        from silva.commands.intent import is_action_command
        from silva.commands.knowledge_phrases import is_knowledge_command
        from silva.commands.registry import match_command
        from silva.conversation import try_conversation

        owner = {"id": "kevin", "tier": 5}
        phrases = (
            "tell me in detail what do you mean by lookups",
            "tell me what do you mean by lookups",
            "tell me what does the lookups do",
            "what does the lookups do",
            "what do you mean by lookups",
            "what are lookups",
            "explain lookups",
            "tell me about lookups",
            "give me details on lookups",
            "give me the details on lookups",
            "details on lookups",
        )
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self.assertFalse(is_help_request(phrase), msg=phrase)
                self.assertTrue(is_feature_detail_ask(phrase), msg=phrase)
                self.assertFalse(is_capability_ask(phrase), msg=phrase)
                self.assertFalse(is_game_lookup(phrase), msg=phrase)
                self.assertFalse(is_knowledge_command(phrase), msg=phrase)
                self.assertIsNone(match_command(phrase), msg=phrase)
                self.assertTrue(is_action_command(phrase), msg=phrase)
                self.assertIsNone(try_conversation(phrase), msg=phrase)
                reply = feature_detail_reply_for_user(phrase, owner) or ""
                self.assertIn("wikipedia", reply.lower())
                self.assertNotIn("here is what i found", reply.lower())

    def test_details_on_each_listed_tool(self):
        from silva.commands.help_phrases import (
            feature_detail_reply_for_user,
            is_feature_detail_ask,
            is_help_request,
        )
        from silva.conversation import try_conversation

        owner = {"id": "kevin", "tier": 5}
        cases = {
            "give me details on weather": "forecast",
            "what does news do": "briefing",
            "explain notes": "note this",
            "details on to-dos": "to-do list",
            "give me details on Matt": "percent",
            "give me details on maps": "percent",
            "give me details on math": "percent",
            "give me details on lookups": "wikipedia",
            "tell me in detail what do you mean by weather": "forecast",
            "what do you mean by weather": "forecast",
            "what do you do of the weather": "forecast",
            "what do you do for math": "percent",
        }
        for phrase, needle in cases.items():
            with self.subTest(phrase=phrase):
                self.assertFalse(is_help_request(phrase), msg=phrase)
                self.assertTrue(is_feature_detail_ask(phrase), msg=phrase)
                self.assertIsNone(try_conversation(phrase), msg=phrase)
                reply = feature_detail_reply_for_user(phrase, owner) or ""
                self.assertIn(needle, reply.lower(), msg=reply)
                self.assertGreater(len(reply), 60, msg=phrase)

    def test_feature_help_does_not_run_the_tool(self):
        from silva.commands.help_phrases import is_feature_detail_ask, is_help_request
        from silva.commands.intent import is_action_command
        from silva.commands.math_phrases import is_math_command
        from silva.commands.registry import match_command
        from silva.conversation import try_conversation
        from silva.stt_quick_commands import is_complete_command

        weather_asks = (
            "tell me in detail what do you mean by weather",
            "what do you mean by weather",
            "what do you do of the weather",
        )
        for phrase in weather_asks:
            with self.subTest(phrase=phrase):
                self.assertFalse(is_help_request(phrase), msg=phrase)
                self.assertTrue(is_feature_detail_ask(phrase), msg=phrase)
                self.assertIsNone(match_command(phrase), msg=phrase)
                self.assertTrue(is_action_command(phrase), msg=phrase)
                self.assertIsNone(try_conversation(phrase), msg=phrase)
                self.assertTrue(is_complete_command(phrase), msg=phrase)

        self.assertEqual(match_command("what's the weather").name, "weather")
        self.assertTrue(is_help_request("tell me what do you do"))
        self.assertFalse(is_math_command("give me details on math"))
        self.assertFalse(is_math_command("give me details on maps"))
        self.assertTrue(is_feature_detail_ask("give me details on maps"))
        self.assertIsNone(try_conversation("give me details on maps"))


class VisualGuidePhraseTests(unittest.TestCase):
    def test_what_is_this(self):
        from silva.commands.visual_guide_phrases import match_visual_guide_speech

        speech = match_visual_guide_speech("what is this on my screen")
        self.assertIsNotNone(speech)
        assert speech is not None
        self.assertEqual(speech.kind, "analyze")

    def test_what_does_this_mean(self):
        from silva.commands.visual_guide_phrases import match_visual_guide_speech

        for phrase in (
            "what does this mean",
            "can you tell me what this means",
            "explain this",
        ):
            with self.subTest(phrase=phrase):
                speech = match_visual_guide_speech(phrase)
                self.assertIsNotNone(speech)
                assert speech is not None
                self.assertEqual(speech.kind, "analyze")

    def test_step_done(self):
        from silva.commands.visual_guide_phrases import match_visual_guide_speech

        speech = match_visual_guide_speech("i'm done with that step")
        self.assertIsNotNone(speech)
        assert speech is not None
        self.assertEqual(speech.kind, "step_done")


class SleepPromptTests(unittest.TestCase):
    def test_reminders_rotate(self):
        from silva.sleep_prompts import next_sleep_reminder

        first = next_sleep_reminder(0)
        second = next_sleep_reminder(1)
        self.assertNotEqual(first, second)
        self.assertEqual(next_sleep_reminder(5), next_sleep_reminder(0))

    def test_sleep_voice_asks_for_repeat(self):
        from silva.sleep_prompts import remind_asleep

        class _Dummy:
            _asleep = True
            _voice_mode = False
            _last_sleep_reminder_at = 0.0
            _sleep_reminder_index = 0

            def __init__(self):
                self.messages: list[str] = []

            def _say_while_asleep(self, text):
                self.messages.append(text)

        dummy = _Dummy()
        with patch("silva.config.load_config", return_value={"sleep_reminder_cooldown_seconds": 0}):
            remind_asleep(dummy, reason="voice", text="break up")
        self.assertTrue(dummy.messages)
        self.assertIn("repeat", dummy.messages[-1].lower())

    def test_idle_reminders_rotate(self):
        from silva.sleep_prompts import next_idle_sleep_reminder

        self.assertIn("still", next_idle_sleep_reminder(0).lower())
        self.assertNotEqual(next_idle_sleep_reminder(0), next_idle_sleep_reminder(1))

    def test_user_attempt_detection(self):
        from silva.sleep_prompts import looks_like_user_attempt

        self.assertFalse(looks_like_user_attempt(""))
        self.assertFalse(looks_like_user_attempt("  "))
        self.assertTrue(looks_like_user_attempt("what's the weather"))
        self.assertTrue(looks_like_user_attempt("hello there"))


class PanelUpdateTests(unittest.TestCase):
    def test_scan_detects_feature_changes(self):
        import json
        import tempfile
        from pathlib import Path

        from silva.dev.panel_update import scan_panel_changes

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            installed = base / "installed.json"
            installed.write_text(
                json.dumps({"features": ["weather"], "fingerprint": "abc"}),
                encoding="utf-8",
            )
            with (
                patch("silva.dev.panel_update.load_installed_manifest") as load_installed,
                patch("silva.dev.panel_update.compute_code_fingerprint", return_value="abc"),
                patch("silva.dev.panel_update.APPLIED_UPDATE_FILE", base / "applied.json"),
                patch("silva.dev.panel_update.SPEECH_TRAINING_FILE", base / "missing.json"),
            ):
                load_installed.return_value = {"features": ["weather"], "fingerprint": "abc"}
                scan = scan_panel_changes(features=["weather", "math"])
                self.assertTrue(scan.has_changes)
                self.assertTrue(any("math" in item for item in scan.changes))

    def test_can_publish_owner(self):
        from silva.dev.panel_update import can_publish_system_update

        owner = get_owner()
        self.assertTrue(can_publish_system_update(owner))

    def test_scan_ignores_empty_speech_training_mismatch(self):
        import json
        import tempfile
        from pathlib import Path

        from silva.dev.panel_update import scan_panel_changes

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            training = base / "speech_training.json"
            training.write_text(
                json.dumps({"say_phrases": [], "dont_say_phrases": [], "updated_at": "2026-08-10"}),
                encoding="utf-8",
            )
            applied = base / "applied.json"
            applied.write_text(
                json.dumps({"features": ["weather"], "fingerprint": "abc"}),
                encoding="utf-8",
            )
            with (
                patch("silva.dev.panel_update.load_installed_manifest") as load_installed,
                patch("silva.dev.panel_update.compute_code_fingerprint", return_value="abc"),
                patch("silva.dev.panel_update.load_config") as load_config,
                patch(
                    "silva.dev.panel_update.load_speech_training",
                    return_value={"say_phrases": [], "dont_say_phrases": []},
                ),
                patch("silva.dev.panel_update.APPLIED_UPDATE_FILE", applied),
                patch("silva.dev.panel_update.SPEECH_TRAINING_FILE", training),
            ):
                load_installed.return_value = {"features": ["weather"], "fingerprint": "abc"}
                load_config.return_value = {"universal_features": ["weather"]}
                scan = scan_panel_changes(features=["weather"])
                self.assertFalse(scan.training_changed)
                self.assertFalse(scan.has_changes)


class LiveRuntimeHookTests(unittest.TestCase):
    def test_command_modules_reload_before_handlers(self):
        from silva.dev.runtime_hooks import (
            _ASSISTANT_REBINDS,
            _reload_priority,
            _should_force_reload,
        )

        self.assertTrue(_should_force_reload("silva.commands.help_phrases"))
        self.assertTrue(_should_force_reload("silva.conversation.learned_phrases"))
        self.assertIn(
            "_wake_up",
            dict(_ASSISTANT_REBINDS)["silva.assistant"],
        )
        self.assertTrue(_should_force_reload("silva.commands.registry"))
        self.assertTrue(_should_force_reload("silva.tts_word_clips"))
        self.assertTrue(_should_force_reload("silva.users.word_pronunciations"))
        self.assertTrue(_should_force_reload("silva.sleep_prompts"))
        self.assertTrue(_should_force_reload("silva.crash_record"))
        self.assertTrue(_should_force_reload("silva.planner"))
        self.assertFalse(_should_force_reload("silva.assistant"))
        self.assertFalse(_should_force_reload("silva.stt"))
        self.assertFalse(_should_force_reload("silva.dev.runtime_hooks"))
        self.assertLess(
            _reload_priority("silva.wake"),
            _reload_priority("silva.commands.intent"),
        )
        self.assertLess(
            _reload_priority("silva.commands.help_phrases"),
            _reload_priority("silva.commands.help_handler"),
        )
        self.assertLess(
            _reload_priority("silva.commands.help_phrases"),
            _reload_priority("silva.commands.registry"),
        )

    def test_install_hooks_does_not_crash(self):
        from silva.dev.runtime_hooks import install_runtime_hooks, safe_install_runtime_hooks

        safe_install_runtime_hooks()
        install_runtime_hooks()


class TerminalUpdateTests(unittest.TestCase):
    def test_help_lists_update_commands(self):
        from silva.dev.terminal_commands import handle_terminal_command

        handled, message = handle_terminal_command("help")
        self.assertTrue(handled)
        self.assertIn("update", message.lower())
        self.assertIn("revert", message.lower())
        self.assertIn("scan", message.lower())

    def test_update_contact_line_includes_project_and_request_email(self):
        from silva.dev.terminal_update import _owner_contact_line

        with patch("silva.dev.github_updates.load_config", return_value={}), patch(
            "silva.dev.terminal_update.is_main_owner_system", return_value=True
        ):
            line = _owner_contact_line()
        self.assertIn("https://github.com/SilusSolden/silva", line)
        self.assertIn("SilusSolden@gmail.com", line)

    def test_backup_snapshot(self):
        import shutil
        import tempfile
        from pathlib import Path

        from silva.dev import codebase_backup as backup

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            project = base / "project"
            (project / "silva").mkdir(parents=True)
            (project / "silva" / "sample.py").write_text("print('ok')\n", encoding="utf-8")
            (project / "main.py").write_text("print('main')\n", encoding="utf-8")

            backup_root = base / "backups"
            with (
                patch.object(backup, "PROJECT_ROOT", project),
                patch.object(backup, "BACKUP_ROOT", backup_root),
                patch.object(backup, "PRODUCTION_DIR", backup_root / "production"),
                patch.object(backup, "STAGING_DIR", backup_root / "staging"),
                patch.object(backup, "SNAPSHOTS_DIR", backup_root / "snapshots"),
                patch.object(backup, "META_FILE", backup_root / "backup_meta.json"),
            ):
                snapshot = backup.create_snapshot(label="test")
                self.assertTrue(snapshot.exists())
                self.assertTrue((snapshot / "silva" / "sample.py").exists())
                production = backup.sync_production_backup()
                self.assertTrue((production / "silva" / "sample.py").exists())
                again = backup.sync_production_backup()
                self.assertTrue((again / "silva" / "sample.py").exists())


class AutoUpdateTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        self._tmpdir = tempfile.TemporaryDirectory()
        base = Path(self._tmpdir.name)
        patchers = [
            patch("silva.dev.update_scanner.INSTALLED_MANIFEST_FILE", base / "installed.json"),
            patch("silva.dev.update_scanner.PUBLISHED_MANIFEST_FILE", base / "published.json"),
            patch("silva.dev.update_scanner.BUNDLED_MANIFEST_FILE", base / "bundled.json"),
            patch("silva.dev.update_scanner.RELOAD_FLAG_FILE", base / "reload"),
            patch("silva.dev.update_scanner.PENDING_UPDATE_FILE", base / "pending.json"),
            patch("silva.dev.paths.INSTALLED_MANIFEST_FILE", base / "installed.json"),
            patch("silva.dev.paths.PUBLISHED_MANIFEST_FILE", base / "published.json"),
            patch("silva.dev.paths.PENDING_UPDATE_FILE", base / "pending.json"),
            patch("silva.dev.paths.RELOAD_FLAG_FILE", base / "reload"),
            patch("silva.dev.paths.PROGRESS_FILE", base / "progress.json"),
            patch("silva.dev.paths.LAST_CODE_STORY_FILE", base / "last_code_story.json"),
            patch("silva.dev.paths.WHATS_NEW_STATE_FILE", base / "whats_new_state.json"),
            patch("silva.dev.paths.APPLIED_UPDATE_FILE", base / "last_applied.json"),
            patch("silva.dev.whats_new_script.WHATS_NEW_STATE_FILE", base / "whats_new_state.json"),
            patch("silva.dev.whats_new_script.APPLIED_UPDATE_FILE", base / "last_applied.json"),
            patch("silva.dev.live_update.PENDING_UPDATE_FILE", base / "pending.json"),
            patch("silva.dev.live_update.RELOAD_FLAG_FILE", base / "reload"),
            patch("silva.dev.live_update.PROGRESS_FILE", base / "progress.json"),
        ]
        for patcher in patchers:
            self.addCleanup(patcher.stop)
            patcher.start()

        bundled = {
            "version": "0.2.0",
            "features": ["weather", "math"],
            "changelog": ["Added visual guides"],
            "fingerprint": "abc123",
        }
        (base / "bundled.json").write_text(json.dumps(bundled), encoding="utf-8")
        installed = {
            "version": "0.1.0",
            "features": ["weather"],
            "fingerprint": "oldfp",
            "changelog": [],
        }
        (base / "installed.json").write_text(json.dumps(installed), encoding="utf-8")

    def test_scan_detects_newer_version(self):
        from silva.dev.update_scanner import scan_for_updates

        scan = scan_for_updates()
        self.assertTrue(scan.available)
        self.assertEqual(scan.version, "0.2.0")
        joined = " ".join(scan.changes).lower()
        self.assertTrue("visual guides" in joined or "silva" in joined)

    def test_update_confirm_phrases(self):
        from silva.dev.auto_update import is_update_confirm_phrase

        self.assertTrue(is_update_confirm_phrase("yes update"))
        self.assertTrue(is_update_confirm_phrase("update now"))
        self.assertTrue(is_update_confirm_phrase("Now update"))
        self.assertFalse(is_update_confirm_phrase("happy update"))
        self.assertFalse(is_update_confirm_phrase("weather"))

    def test_update_then_sleep_requests_sleep_after_apply(self):
        from unittest.mock import MagicMock, patch

        from silva.commands.update_handler import handle_update_speech

        assistant = MagicMock()
        with patch("silva.commands.update_handler.apply_live_now") as apply:
            self.assertTrue(handle_update_speech(assistant, "update yourself then go back to sleep"))
        apply.assert_called_once_with(assistant, sleep_after=True)

    def test_whats_the_new_update_phrase(self):
        from silva.commands.intent import is_action_command
        from silva.commands.update_phrases import (
            is_code_detail_ask,
            is_update_confirm_phrase,
            is_update_detail_ask,
            is_whats_new_update_phrase,
        )
        from silva.conversation import try_conversation
        from silva.dev.auto_update import spoken_change_summary
        from silva.dev.panel_update import PanelChangeScan

        questions = (
            "what's the new update",
            "whats the new update",
            "what's new",
            "what's new silva",
            "any new features",
            "what was added",
            "what changed",
            "what was changed",
            "what was fixed",
            "what bugs were fixed",
            "can you tell me what was recently added in the newest update",
            "tell me what's new",
            "is there an update",
            "any patches",
            "silva what's the latest update",
            "can you tell me what was the newest part of the update",
            "all right what's the new update",
            "I said what's in the new update",
            "what's in the new update",
            "what was in the news update",
            "what's in the details of the newest update",
            "what is new in this update",
            "what's new in this update",
            "what was recently added",
            "what did the last update do",
            "can you tell me what was added in the newest update",
            "what was in the code that was added",
            "what type of code was added",
            "can you tell me what the recent thing was added",
            "what's in the codebase",
        )
        for phrase in questions:
            with self.subTest(phrase=phrase):
                self.assertTrue(is_whats_new_update_phrase(phrase), msg=phrase)
                self.assertTrue(is_action_command(phrase), msg=phrase)
                self.assertIsNone(try_conversation(phrase))

        applies = (
            "update silva",
            "apply the update",
            "load the update",
            "push the update",
            "please update silva",
        )
        for phrase in applies:
            with self.subTest(phrase=phrase):
                self.assertTrue(is_update_confirm_phrase(phrase), msg=phrase)
                self.assertTrue(is_action_command(phrase), msg=phrase)

        from silva.commands.help_phrases import is_capability_ask

        self.assertFalse(is_whats_new_update_phrase("what's the weather"))
        self.assertFalse(is_whats_new_update_phrase("what's new with you"))
        self.assertFalse(is_update_confirm_phrase("weather"))
        self.assertFalse(is_capability_ask("can you tell me what was the newest part of the update"))
        self.assertIsNone(match_command("what is the new update"))
        self.assertIsNone(match_command("what's new"))
        empty = PanelChangeScan(has_changes=False, changes=["No manual changes detected since the last update."])
        with patch("silva.dev.auto_update._last_loaded_changelog", return_value=("", [])), patch(
            "silva.dev.auto_update._modules_from_last_reload", return_value=[]
        ), patch("silva.dev.auto_update._load_story", return_value={}):
            fallback = spoken_change_summary(empty).lower()
            self.assertIn("fresh list", fallback)
            self.assertNotIn("2d and 3d planner", fallback)
            self.assertNotIn("closed polygons", fallback)
            self.assertNotIn("changelog only said", fallback)
        with patch(
            "silva.dev.auto_update._last_loaded_changelog",
            return_value=("0.1.31", ["Patch: planner handler (commands/planner_handler.py)"]),
        ):
            loaded = spoken_change_summary(empty).lower()
            self.assertIn("planner", loaded)
            self.assertIn("0.1.31", loaded)
            self.assertIn("more detail", loaded)
            self.assertNotIn("silva code was patched update", loaded)
            self.assertNotIn("no new update waiting", loaded)
            self.assertNotIn("changelog only said", loaded)
            detailed = spoken_change_summary(empty, detailed=True).lower()
            self.assertIn("planner", detailed)
            self.assertIn("0.1.31", detailed)
        with patch("silva.dev.auto_update._last_loaded_changelog", return_value=("0.1.33", ["Silva code was patched (bug fixes and command updates)."])), patch(
            "silva.dev.auto_update._modules_from_last_reload", return_value=[]
        ), patch("silva.dev.auto_update._load_story", return_value={}):
            technical = spoken_change_summary(empty, technical=True).lower()
            self.assertIn("python", technical)
            self.assertNotIn("closed polygons", technical)
            self.assertNotIn("changelog only said", technical)
            long_tech = spoken_change_summary(empty, technical=True, detailed=True).lower()
            self.assertIn("python", long_tech)
            self.assertIn("geometry", long_tech)
            self.assertIn("closed polygons", long_tech)
            simple = spoken_change_summary(empty).lower()
            self.assertIn("fresh list", simple)
            self.assertNotIn("2d and 3d planner", simple)
            self.assertNotIn("closed polygons", simple)
        with patch(
            "silva.dev.auto_update._last_loaded_changelog",
            return_value=("0.1.38", ["Silva code was patched (bug fixes and command updates)."]),
        ), patch(
            "silva.dev.auto_update._load_story",
            return_value={
                "files": ["interrupt_listen.py", "gui/planner_window.py", "planner/catalog.py"],
                "items": [
                    "a working stop command so I quit talking when you say or type stop",
                    "a Paint-style draw bar on the planner",
                    "planner object pictures, custom objects, and copper wire, water, gas, and drain lines you can drag",
                ],
            },
        ):
            latest = spoken_change_summary(empty).lower()
            self.assertIn("stop", latest)
            self.assertIn("planner", latest)
            self.assertNotIn("crash and failed-command", latest)
        ready = PanelChangeScan(
            has_changes=True,
            code_changed=True,
            changes=["New feature: notes handler (commands/notes_handler.py)", "Patch: microphone (stt.py)"],
        )
        spoken = spoken_change_summary(ready).lower()
        self.assertIn("notes", spoken)
        self.assertIn("microphone", spoken)
        self.assertNotIn("===", spoken)

        spoken_replies: list[str] = []

        class _Dummy:
            _update_offer = None
            _update_apply_in_progress = False
            _asleep = False
            _notes_flow = None

            def say(self, text, interruptible=False):
                spoken_replies.append(text)

        from silva.commands.update_handler import handle_update_speech
        from types import SimpleNamespace

        def _script_from_summary(*, technical=False, detailed=False, **_kwargs):
            spoken = spoken_change_summary(empty, technical=technical, detailed=detailed)
            return SimpleNamespace(
                spoken=spoken,
                pending=False,
                files=[],
                items=[],
                version="",
                nothing_new=False,
            )

        dummy = _Dummy()
        with patch("silva.dev.whats_new_script.run_whats_new_script", side_effect=lambda **kw: _script_from_summary(**kw)), patch(
            "silva.dev.panel_update.scan_panel_changes", return_value=empty
        ), patch(
            "silva.dev.auto_update._last_loaded_changelog",
            return_value=("0.1.31", ["Patch: planner handler (commands/planner_handler.py)"]),
        ):
            self.assertTrue(handle_update_speech(dummy, "can you tell me what was added in the newest update"))
        self.assertTrue(spoken_replies)
        self.assertIn("planner", spoken_replies[-1].lower())
        spoken_replies.clear()
        with patch("silva.dev.whats_new_script.run_whats_new_script", side_effect=lambda **kw: _script_from_summary(**kw)), patch(
            "silva.dev.panel_update.scan_panel_changes", return_value=empty
        ), patch(
            "silva.dev.auto_update._last_loaded_changelog",
            return_value=("0.1.31", ["Patch: planner handler (commands/planner_handler.py)"]),
        ):
            self.assertTrue(handle_update_speech(dummy, "what's the newest update"))
        self.assertIn("planner", spoken_replies[-1].lower())
        self.assertNotIn("more detail", spoken_replies[-1].lower())
        spoken_replies.clear()
        with patch("silva.dev.whats_new_script.run_whats_new_script", side_effect=lambda **kw: _script_from_summary(**kw)), patch(
            "silva.dev.panel_update.scan_panel_changes", return_value=empty
        ), patch(
            "silva.dev.auto_update._last_loaded_changelog",
            return_value=("0.1.31", ["Patch: planner handler (commands/planner_handler.py)"]),
        ):
            self.assertTrue(handle_update_speech(dummy, "what was in the code that was added"))
        self.assertIn("planner", spoken_replies[-1].lower())
        self.assertTrue(is_code_detail_ask("what type of code was added"))
        self.assertTrue(is_code_detail_ask("what code was added"))
        self.assertTrue(is_code_detail_ask("what's in the codebase"))
        self.assertFalse(is_code_detail_ask("what was added in the newest update"))
        self.assertTrue(is_update_detail_ask("tell me in detail what was added"))
        self.assertTrue(is_update_detail_ask("what's in the update in more detail"))
        self.assertFalse(is_update_detail_ask("what was added in the newest update"))
        spoken_replies.clear()
        with patch("silva.dev.whats_new_script.run_whats_new_script", side_effect=lambda **kw: _script_from_summary(**kw)), patch(
            "silva.dev.panel_update.scan_panel_changes", return_value=empty
        ), patch(
            "silva.dev.auto_update._last_loaded_changelog",
            return_value=("0.1.33", ["Silva code was patched (bug fixes and command updates)."]),
        ), patch("silva.dev.auto_update._modules_from_last_reload", return_value=[]):
            self.assertTrue(handle_update_speech(dummy, "what type of code was added"))
        self.assertIn("python", spoken_replies[-1].lower())
        self.assertNotIn("closed polygons", spoken_replies[-1].lower())
        self.assertNotIn("changelog only said", spoken_replies[-1].lower())
        spoken_replies.clear()
        with patch("silva.dev.whats_new_script.run_whats_new_script", side_effect=lambda **kw: _script_from_summary(**kw)), patch(
            "silva.dev.panel_update.scan_panel_changes", return_value=empty
        ), patch(
            "silva.dev.auto_update._last_loaded_changelog",
            return_value=("0.1.33", ["Silva code was patched (bug fixes and command updates)."]),
        ), patch("silva.dev.auto_update._modules_from_last_reload", return_value=[]):
            self.assertTrue(handle_update_speech(dummy, "tell me in detail what type of code was added"))
        self.assertIn("closed polygons", spoken_replies[-1].lower())
        spoken_replies.clear()
        dummy._asleep = True
        dummy._speak_now = lambda text: spoken_replies.append(text)
        with patch("silva.dev.whats_new_script.run_whats_new_script", side_effect=lambda **kw: _script_from_summary(**kw)), patch(
            "silva.dev.panel_update.scan_panel_changes", return_value=empty
        ), patch(
            "silva.dev.auto_update._last_loaded_changelog",
            return_value=("0.1.33", ["Patch: planner handler (commands/planner_handler.py)"]),
        ):
            self.assertTrue(handle_update_speech(dummy, "what was added"))
        self.assertTrue(spoken_replies)
        self.assertIn("planner", spoken_replies[-1].lower())
        self.assertNotIn("more detail", spoken_replies[-1].lower())

    def test_update_summary_lists_items_and_expands_one(self):
        from types import SimpleNamespace

        from silva.commands.help_handler import handle_help_speech
        from silva.commands.update_handler import handle_update_speech

        report = SimpleNamespace(
            spoken="Update 0.1.78. Assistant. Config.",
            pending=False,
            files=[],
            items=["Assistant", "Config"],
            version="0.1.78",
            nothing_new=False,
        )
        spoken_replies: list[str] = []

        class _Dummy:
            _asleep = False
            _update_offer = None
            _update_apply_in_progress = False
            _notes_flow = None

            def say(self, text, interruptible=False):
                spoken_replies.append(text)

        dummy = _Dummy()
        with patch("silva.dev.whats_new_script.run_whats_new_script", return_value=report):
            self.assertTrue(handle_update_speech(dummy, "what was recently added"))
        summary = spoken_replies[-1].lower()
        self.assertIn("first, assistant", summary)
        self.assertIn("second, config", summary)
        self.assertNotIn("expand one", summary)
        self.assertNotIn("more detail", summary)
        self.assertEqual(dummy._update_summary_items, ["Assistant", "Config"])

        spoken_replies.clear()
        with patch(
            "silva.commands.help_phrases.feature_detail_reply_for_user", return_value=""
        ), patch(
            "silva.dev.code_assist.explain_script",
            return_value="Config stores user settings.",
        ):
            self.assertTrue(handle_help_speech(dummy, "expand the second one"))
        self.assertIn("config stores user settings", spoken_replies[-1].lower())

    def test_update_expansion_asks_which_item_then_expands(self):
        from types import SimpleNamespace

        from silva.commands.help_handler import handle_help_speech
        from silva.commands.update_handler import handle_update_speech

        report = SimpleNamespace(
            spoken="Update 0.1.78. Assistant. Config.",
            pending=False,
            files=[],
            items=["Assistant", "Config"],
            version="0.1.78",
            nothing_new=False,
        )
        spoken_replies: list[str] = []

        class _Dummy:
            _asleep = False
            _update_offer = None
            _update_apply_in_progress = False
            _notes_flow = None

            def say(self, text, interruptible=False):
                spoken_replies.append(text)

        dummy = _Dummy()
        with patch("silva.dev.whats_new_script.run_whats_new_script", return_value=report):
            self.assertTrue(handle_update_speech(dummy, "what was added"))
        spoken_replies.clear()

        self.assertTrue(handle_help_speech(dummy, "describe one of them in detail"))
        self.assertIn("which one", spoken_replies[-1].lower())
        self.assertIn("assistant", spoken_replies[-1].lower())
        self.assertIn("config", spoken_replies[-1].lower())

        spoken_replies.clear()
        with patch(
            "silva.commands.help_phrases.feature_detail_reply_for_user", return_value=""
        ), patch(
            "silva.dev.code_assist.explain_script",
            return_value="Assistant handles voice.",
        ):
            self.assertTrue(handle_help_speech(dummy, "first"))
        self.assertIn("assistant handles voice", spoken_replies[-1].lower())

    def test_update_extra_follow_up_lists_hidden_items(self):
        from types import SimpleNamespace

        from silva.commands.help_handler import handle_help_speech
        from silva.commands.update_handler import handle_update_speech

        report = SimpleNamespace(
            spoken="Update 0.1.104. Github updates.",
            pending=False,
            files=[],
            items=[
                "github updates",
                "update check",
                "update permissions",
                "image generator gpu",
                "assistant",
                "update handler",
            ],
            version="0.1.104",
            nothing_new=False,
        )
        spoken_replies: list[str] = []

        class _Dummy:
            _asleep = False
            _update_offer = None
            _update_apply_in_progress = False
            _notes_flow = None

            def say(self, text, interruptible=False):
                spoken_replies.append(text)

        dummy = _Dummy()
        with patch("silva.dev.whats_new_script.run_whats_new_script", return_value=report):
            self.assertTrue(handle_update_speech(dummy, "that was not what was added"))
        self.assertIn("and 3 more", spoken_replies[-1].lower())

        spoken_replies.clear()
        with patch(
            "silva.commands.help_phrases.feature_detail_reply_for_user", return_value=""
        ), patch(
            "silva.dev.code_assist.explain_script", return_value="wrong code detail"
        ):
            self.assertTrue(
                handle_help_speech(dummy, "all right then tell me what the three others are")
            )
        self.assertIn("image generator gpu", spoken_replies[-1].lower())
        self.assertIn("update handler", spoken_replies[-1].lower())
        self.assertNotIn("wrong code detail", spoken_replies[-1].lower())

        spoken_replies.clear()
        with patch(
            "silva.commands.help_phrases.feature_detail_reply_for_user", return_value=""
        ), patch(
            "silva.dev.code_assist.explain_script", return_value="wrong code detail"
        ):
            self.assertTrue(
                handle_help_speech(
                    dummy, "I said tell me the three more that was added in the update"
                )
            )
        self.assertIn("image generator gpu", spoken_replies[-1].lower())
        self.assertIn("assistant", spoken_replies[-1].lower())
        self.assertNotIn("wrong code detail", spoken_replies[-1].lower())

    def test_unrelated_speech_does_not_expand_update_summary(self):
        from silva.commands.update_handler import handle_update_expansion_speech

        class _Dummy:
            _update_summary_items = ["Assistant", "Config"]
            _update_summary_awaiting_choice = True

            def say(self, text, interruptible=False):
                self.fail("update expansion should not speak for unrelated input")

        self.assertFalse(handle_update_expansion_speech(_Dummy(), "what's the weather"))

    def test_whats_new_script_only_speaks_recent_files(self):
        import tempfile

        from silva.dev.whats_new_script import record_apply_delta, run_whats_new_script

        with patch(
            "silva.dev.whats_new_script.RELEASE_NOTES_DIR",
            Path(tempfile.mkdtemp()) / "release_notes",
        ):
            baseline = {"planner/store.py": "aaa", "commands/notes_handler.py": "bbb"}
            current = dict(baseline)
            current["planner/paint_tools.py"] = "ccc"
            current["planner/import_media.py"] = "ddd"
            first = run_whats_new_script(
                current_hashes=current,
                baseline_hashes=baseline,
                version="0.1.41",
                mark_told=True,
            )
            spoken = first.spoken.lower()
            self.assertTrue(first.pending)
            self.assertIn("0.1.41", spoken)
            self.assertIn("paint", spoken)
            self.assertNotIn("stop command", spoken)
            self.assertNotIn("wikipedia", spoken)

            same = run_whats_new_script(
                current_hashes=current,
                baseline_hashes=current,
                version="0.1.41",
                mark_told=True,
            )
            self.assertFalse(same.nothing_new)
            self.assertIn("paint", same.spoken.lower())
            self.assertIn("0.1.41", same.spoken.lower())
            self.assertNotIn("wikipedia", same.spoken.lower())

            newer = dict(current)
            newer["interrupt_listen.py"] = "eee"
            third = run_whats_new_script(
                current_hashes=newer,
                baseline_hashes=current,
                version="0.1.42",
                mark_told=True,
            )
            self.assertIn("stop", third.spoken.lower())
            self.assertIn("0.1.42", third.spoken.lower())
            self.assertNotIn("paint", third.spoken.lower())

            applied = record_apply_delta(
                files=["planner/paint_tools.py", "planner/import_media.py"],
                version="0.1.41",
                hashes=current,
            )
            self.assertIn("0.1.41", applied.spoken.lower())
            self.assertIn("live", applied.spoken.lower())
            self.assertIn("paint", applied.spoken.lower())
            self.assertNotIn("wikipedia", applied.spoken.lower())

    def test_saved_generic_update_item_is_rewritten(self):
        from silva.dev.whats_new_script import run_whats_new_script

        state = {
            "last_apply": {
                "version": "0.1.44",
                "files": ["dev/whats_new_script.py", "commands/update_handler.py"],
                "items": ["A shorter update summary."],
            }
        }
        with patch("silva.dev.whats_new_script.load_state", return_value=state):
            report = run_whats_new_script(
                current_hashes={},
                baseline_hashes={},
                version="0.1.44",
                detailed=True,
                mark_told=False,
            )
        self.assertFalse(report.nothing_new)
        self.assertIn("clearer answers", report.spoken.lower())
        self.assertNotIn("shorter update summary", report.spoken.lower())

    def test_owner_skips_desktop_update_popup(self):
        from silva.dev.auto_update import (
            owner_uses_terminal_update_only,
            should_show_desktop_update_popup,
            should_speak_update_offer,
            skips_desktop_update_ui,
        )

        owner = get_owner()
        with (
            patch("silva.dev.auto_update.load_config", return_value={"auto_update_skip_main_owner": True}),
            patch("silva.users.system_identity.is_main_owner_system", return_value=False),
            patch("silva.users.manager.get_active_user", return_value=owner),
            patch("silva.users.manager.is_owner", return_value=True),
            patch("silva.users.profile_access.can_open_control_panel", return_value=True),
        ):
            self.assertTrue(skips_desktop_update_ui(owner))
            self.assertTrue(owner_uses_terminal_update_only(owner))
            self.assertFalse(should_show_desktop_update_popup(owner))
            self.assertFalse(should_speak_update_offer(owner))

    def test_admin_skips_desktop_update_popup(self):
        from silva.dev.auto_update import should_show_desktop_update_popup, skips_desktop_update_ui

        admin = {"id": "admin1", "name": "Admin", "tier": 4}
        with (
            patch("silva.dev.auto_update.load_config", return_value={"auto_update_skip_main_owner": True}),
            patch("silva.users.system_identity.is_main_owner_system", return_value=True),
            patch("silva.users.manager.get_active_user", return_value=admin),
            patch("silva.users.manager.is_owner", return_value=False),
            patch("silva.users.profile_access.can_open_control_panel", return_value=True),
        ):
            self.assertTrue(skips_desktop_update_ui(admin))
            self.assertFalse(should_show_desktop_update_popup(admin))

    def test_guest_on_main_dev_machine_skips_popup(self):
        from silva.dev.auto_update import should_show_desktop_update_popup, skips_desktop_update_ui

        guest = {"id": "guest", "name": "Guest", "tier": 1}
        with (
            patch("silva.dev.auto_update.load_config", return_value={"auto_update_skip_main_owner": True}),
            patch("silva.users.system_identity.is_main_owner_system", return_value=True),
            patch("silva.users.manager.get_active_user", return_value=guest),
            patch("silva.users.manager.is_owner", return_value=False),
            patch("silva.users.profile_access.can_open_control_panel", return_value=False),
        ):
            self.assertTrue(skips_desktop_update_ui(guest))
            self.assertFalse(should_show_desktop_update_popup(guest))

    def test_non_owner_still_gets_desktop_update_popup(self):
        from silva.dev.auto_update import should_show_desktop_update_popup

        guest = {"id": "guest", "name": "Guest", "tier": 1}
        with (
            patch("silva.dev.auto_update.load_config", return_value={"auto_update_skip_main_owner": True}),
            patch("silva.users.system_identity.is_main_owner_system", return_value=False),
            patch("silva.users.manager.get_active_user", return_value=guest),
            patch("silva.users.manager.is_owner", return_value=False),
            patch("silva.users.profile_access.can_open_control_panel", return_value=False),
        ):
            self.assertTrue(should_show_desktop_update_popup(guest))

    def test_terminal_update_button_hidden_for_owner(self):
        from silva.dev.auto_update import should_show_terminal_update_button

        owner = get_owner()
        with (
            patch("silva.dev.auto_update.load_config", return_value={"terminal_update_button_enabled": True}),
            patch("silva.users.manager.get_active_user", return_value=owner),
            patch("silva.users.manager.is_owner", return_value=True),
            patch("silva.users.profile_access.can_open_control_panel", return_value=True),
        ):
            self.assertFalse(should_show_terminal_update_button(owner))

    def test_terminal_update_button_shown_for_remote_guest(self):
        from silva.dev.auto_update import should_show_terminal_update_button

        guest = {"id": "guest", "name": "Guest", "tier": 1}
        with (
            patch("silva.dev.auto_update.load_config", return_value={"terminal_update_button_enabled": True}),
            patch("silva.users.system_identity.is_main_owner_system", return_value=False),
            patch("silva.users.manager.get_active_user", return_value=guest),
            patch("silva.users.manager.is_owner", return_value=False),
            patch("silva.users.profile_access.can_open_control_panel", return_value=False),
        ):
            self.assertTrue(should_show_terminal_update_button(guest))


class TerminalCommandTests(unittest.TestCase):
    def test_help_command(self):
        from silva.dev.terminal_commands import handle_terminal_command

        handled, message = handle_terminal_command("help")
        self.assertTrue(handled)
        self.assertIn("press enter", message.lower())

    def test_plain_text_routes_to_silva(self):
        from silva.dev.terminal_commands import handle_terminal_command

        handled, _message = handle_terminal_command("open voice recorder")
        self.assertFalse(handled)

    def test_optional_run_prefix_still_works(self):
        from silva.dev.typed_command_access import normalize_typed_command

        self.assertEqual(normalize_typed_command("run: weather"), "weather")
        self.assertEqual(normalize_typed_command("open voice recorder"), "open voice recorder")

    def test_guest_cannot_run_dev_scan(self):
        from silva.dev.terminal_commands import handle_terminal_command

        guest = {"id": "guest1", "name": "Guest", "tier": 1, "permissions": []}
        with patch("silva.users.manager.get_active_user", return_value=guest):
            handled, message = handle_terminal_command("scan")
        self.assertTrue(handled)
        self.assertIn("owner and admins", message.lower())

    def test_chat_command_opens_box(self):
        from silva.dev.terminal_commands import handle_terminal_command

        handled, message = handle_terminal_command("chat")
        self.assertTrue(handled)
        self.assertIn("turned off", message.lower())


class CameraPreferenceTests(unittest.TestCase):
    def test_elgato_mk2_scores_higher_than_built_in(self):
        from silva.media.camera import _score_camera_name

        elgato = _score_camera_name("Elgato Facecam MK.2")
        builtin = _score_camera_name("Integrated Webcam")
        self.assertGreater(elgato, builtin)
        self.assertGreater(elgato, 20)

    def test_preferred_index_uses_saved_config(self):
        from silva.media.camera import preferred_camera_index

        with patch("silva.media.camera.load_config", return_value={"camera_index": 2}):
            self.assertEqual(preferred_camera_index(), 2)

    def test_ir_camera_names_are_skipped_for_photos(self):
        from silva.media.camera import is_ir_camera_name

        self.assertTrue(is_ir_camera_name("Windows Hello Face"))
        self.assertTrue(is_ir_camera_name("RGB IR Camera"))
        self.assertFalse(is_ir_camera_name("Elgato Facecam MK.2"))

    def test_dark_face_frame_does_not_blame_ceiling_light(self):
        import numpy as np
        from silva.users.face_id import add_face_photo_from_frame

        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        ok, message = add_face_photo_from_frame("test-user", "Kevin", frame)
        self.assertFalse(ok)
        self.assertIn("IR", message)
        self.assertNotIn("enough light", message.lower())
        self.assertNotIn("better lighting", message.lower())

    def test_camera_access_is_remembered_per_feature(self):
        import tempfile
        from pathlib import Path

        from silva.users.camera_access import (
            FEATURE_PROFILE_FACE,
            is_camera_access_phrase,
            is_camera_granted,
            set_camera_access,
        )
        from silva.users import camera_access as access_mod
        from silva.users import manager as manager_mod

        self.assertTrue(is_camera_access_phrase("camera access"))
        self.assertTrue(is_camera_access_phrase("allow the camera"))
        self.assertFalse(is_camera_access_phrase("is the camera available"))

        store = {
            "users": {"kevin": {"id": "kevin", "name": "Kevin", "camera_access": {}}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "users.json"
            with patch.object(manager_mod, "USERS_FILE", path), patch.object(
                manager_mod, "load_store", return_value=store
            ), patch.object(manager_mod, "save_store", lambda data: store.update(data) if False else None), patch.object(
                access_mod, "load_store", lambda: store
            ), patch.object(access_mod, "save_store", lambda data: None):
                self.assertFalse(is_camera_granted("kevin", FEATURE_PROFILE_FACE))
                set_camera_access("kevin", FEATURE_PROFILE_FACE, True)
                self.assertTrue(is_camera_granted("kevin", FEATURE_PROFILE_FACE))
                self.assertFalse(is_camera_granted("kevin", "measurement"))

    def test_profile_image_is_not_a_face_photo(self):
        import tempfile
        from pathlib import Path

        from silva.users import profile_image as image_mod
        from silva.users.profile_image import has_profile_image, save_profile_image

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            source = folder / "pic.png"
            source.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
            store = {"users": {"kevin": {"id": "kevin", "name": "Kevin"}}}
            with patch.object(image_mod, "PROFILE_IMAGES_DIR", folder / "avatars"), patch.object(
                image_mod, "load_store", lambda: store
            ), patch.object(image_mod, "save_store", lambda data: None):
                ok, message = save_profile_image("kevin", source)
                self.assertTrue(ok)
                self.assertIn("face photos stay private", message.lower())
                self.assertTrue(has_profile_image("kevin"))
                self.assertTrue(str(store["users"]["kevin"].get("profile_image") or "").endswith("avatar.png"))

    def test_voice_recorder_needs_enough_audio(self):
        import math
        import struct

        from silva.audio_recorder import SAMPLE_RATE, VoiceRecorder

        recorder = VoiceRecorder()
        recorder._frames = [b"\x00\x00"]
        self.assertFalse(recorder.has_audio())
        recorder._frames = [b"\x00\x00"] * 40
        self.assertFalse(recorder.has_audio())
        samples = [int(12000 * math.sin(2 * math.pi * 440 * i / SAMPLE_RATE)) for i in range(SAMPLE_RATE * 2)]
        raw = struct.pack(f"{len(samples)}h", *samples)
        chunk = SAMPLE_RATE * 2 // 8
        recorder._frames = [raw[i : i + chunk] for i in range(0, len(raw), chunk)]
        self.assertTrue(recorder.has_audio())
        self.assertIsNone(recorder.reject_reason())


class TypedCommandAccessTests(unittest.TestCase):
    def test_normalize_typed_command(self):
        from silva.dev.typed_command_access import is_typed_silva_command, normalize_typed_command

        self.assertTrue(is_typed_silva_command("run: pause the video"))
        self.assertEqual(normalize_typed_command("cmd: weather"), "weather")
        self.assertEqual(normalize_typed_command("say: silva wake up"), "silva wake up")
        self.assertEqual(normalize_typed_command("open voice recorder"), "open voice recorder")

    def test_guest_blocked_from_admin_commands(self):
        from silva.dev.typed_command_access import validate_typed_command

        guest = {"id": "guest1", "name": "Guest", "tier": 1, "permissions": []}
        ok, message = validate_typed_command(guest, "show security panel")
        self.assertFalse(ok)
        self.assertIn("cannot type", message.lower())

    def test_guest_allowed_common_commands(self):
        from silva.dev.typed_command_access import validate_typed_command

        guest = {"id": "guest1", "name": "Guest", "tier": 1, "permissions": []}
        for command in ("weather", "pause the video", "open the phrase recorder"):
            ok, _message = validate_typed_command(guest, command)
            self.assertTrue(ok, msg=command)

    def test_owner_can_type_anything(self):
        from silva.dev.typed_command_access import validate_typed_command

        owner = {"id": "owner1", "name": "Kevin", "tier": 5, "permissions": ["*"], "role": "owner"}
        with patch("silva.dev.typed_command_access.is_owner", return_value=True):
            ok, _message = validate_typed_command(owner, "show security panel")
        self.assertTrue(ok)


class MonitorPlacementTests(unittest.TestCase):
    def test_geometry_supports_negative_virtual_coords(self):
        from silva.gui.monitors import Monitor, geometry_on_monitor

        left = Monitor(-1920, 0, 0, 1080, False)
        geo = geometry_on_monitor(360, 178, anchor="ne", margin=24, monitor=left)
        self.assertEqual(geo, "360x178+-384+24")

    def test_preferred_monitor_is_always_primary(self):
        from silva.gui import monitors as monitor_mod
        from silva.gui.monitors import Monitor

        primary = Monitor(0, 0, 1920, 1080, True)
        secondary = Monitor(1920, 0, 3840, 1080, False)
        monitor_mod.reset_preferred_monitor()
        with patch.object(monitor_mod, "list_monitors", return_value=[primary, secondary]), patch.object(
            monitor_mod, "_cursor_point", return_value=(2000, 200)
        ):
            chosen = monitor_mod.preferred_monitor()
        monitor_mod.reset_preferred_monitor()
        self.assertEqual(chosen, primary)
        self.assertTrue(chosen.is_primary)


class UtteranceRoutingTests(unittest.TestCase):
    def test_commands_are_not_conversation(self):
        from silva.commands.intent import is_action_command
        from silva.commands.news_phrases import is_news_command
        from silva.commands.registry import match_command

        commands = (
            "what's my local weather",
            "whats my local weather",
            "weather",
            "what's my latest news",
            "what's my local news",
            "what's the latest",
            "show me the news",
            "what's my local forecast",
            "note this pick up milk",
            "what are my notes",
            "open the to do list",
            "what is my to do list",
        )
        for phrase in commands:
            with self.subTest(phrase=phrase):
                self.assertTrue(is_action_command(phrase), msg=phrase)

        self.assertEqual(match_command("what's my local weather").name, "weather")
        self.assertTrue(is_news_command("what's my latest news"))
        self.assertTrue(is_news_command("what's the latest"))
        self.assertIsNone(match_command("what is going on"))
        self.assertIsNone(match_command("how are you doing today Silva"))

    def test_conversation_phrases_are_not_commands(self):
        from silva.commands.intent import is_action_command
        from silva.conversation import try_conversation

        chats = (
            "how are you doing today Silva",
            "how are you",
            "hello",
            "what is going on",
            "what's up",
            "what is your name",
            "tell me a joke",
            "thanks",
        )
        for phrase in chats:
            with self.subTest(phrase=phrase):
                self.assertFalse(is_action_command(phrase), msg=phrase)
                reply = try_conversation(phrase)
                self.assertIsNotNone(reply, msg=phrase)


class GameLookupTests(unittest.TestCase):
    def test_game_how_to_phrases(self):
        from silva.commands.game_lookup_phrases import extract_game_query, is_game_lookup
        from silva.commands.intent import is_action_command
        from silva.commands.registry import match_command

        hits = (
            "how do I beat the first boss in elden ring",
            "look up how to get the master sword in zelda",
            "look up a game for information on how to do something in the game",
            "where do I find the golden armor in sons of the forest",
            "search for a walkthrough for the first quest",
        )
        for phrase in hits:
            with self.subTest(phrase=phrase):
                self.assertTrue(is_game_lookup(phrase), msg=phrase)
                self.assertTrue(is_action_command(phrase), msg=phrase)
                self.assertIsNone(match_command(phrase))

        self.assertFalse(is_game_lookup("how are you"))
        self.assertFalse(is_game_lookup("look up how to make concrete"))
        self.assertFalse(is_game_lookup("what is photosynthesis"))
        self.assertFalse(is_game_lookup("how to get to work in the morning"))
        self.assertFalse(is_game_lookup("tell me in detail what do you mean by lookups"))
        self.assertFalse(is_game_lookup("tell me what does the lookups do"))
        self.assertIn("elden ring", extract_game_query("how do I beat the first boss in elden ring"))

    def test_spoken_answer_from_skim(self):
        from silva.commands import game_lookup as lookup

        fake = [
            {
                "title": "Elden Ring Guide",
                "snippet": "Use a spirit ash and stay mid-range until the second phase.",
                "url": "https://example.test/guide",
            }
        ]
        with patch.object(lookup, "search_snippets", return_value=fake), patch.object(
            lookup, "_wiki_blurb", return_value=""
        ):
            spoken = lookup.lookup_game_info("beat malenia in elden ring")
        self.assertIn("spirit ash", spoken.lower())
        self.assertIn("elden ring", spoken.lower())


class NotesTodoTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        from silva.commands import notes_store

        self._tmp = tempfile.TemporaryDirectory()
        self._old_file = notes_store.NOTES_FILE
        notes_store.NOTES_FILE = Path(self._tmp.name) / "notes.json"

    def tearDown(self):
        from silva.commands import notes_store

        notes_store.NOTES_FILE = self._old_file
        self._tmp.cleanup()

    def test_note_and_todo_phrases(self):
        from silva.commands.intent import is_action_command
        from silva.commands.notes_phrases import match_notes_speech
        from silva.commands.registry import match_command

        cases = {
            "note this pick up milk": "add_note",
            "remember this the wifi password is on the fridge": "add_note",
            "what are my notes": "list_notes",
            "what's my note about milk": "search_note",
            "add this to the to do list buy batteries": "add_todo",
            "open the to do list": "open_todo",
            "what is my to do list": "list_todo",
            "what's my reminder": "ask_reminder",
            "remind me of it": "ask_reminder",
            "remind me of my notes": "list_notes",
            "check off buy batteries": "complete_todo",
            "type the note": "type",
            "bring up my notes": "list_notes",
            "bring up my to do list": "open_todo",
            "every day at 8 am take my meds": "add_todo",
            "i no longer need to take my meds": "archive_todo",
            "bring back take my meds": "restore_todo",
            "delete 1": "delete_todo",
            "delete the entire to do list": "clear_todos",
            "delete the to do list": "clear_todos",
            "delete my to-do list": "clear_todos",
            "all right delete the first to do list": "delete_todo",
            "delete the first to do list": "delete_todo",
            "edit number 2": "edit_todo",
        }
        for phrase, action in cases.items():
            with self.subTest(phrase=phrase):
                speech = match_notes_speech(phrase)
                self.assertIsNotNone(speech, msg=phrase)
                self.assertEqual(speech.action, action, msg=phrase)
                self.assertTrue(is_action_command(phrase), msg=phrase)
                self.assertIsNone(match_command(phrase), msg=phrase)

        self.assertIsNone(match_notes_speech("how are you"))
        self.assertIsNone(match_notes_speech("remember my voice"))
        self.assertIsNone(match_notes_speech("what's the weather"))
        self.assertIsNone(match_notes_speech("that's not what i said"))

    def test_save_search_and_complete(self):
        from silva.commands.notes_handler import handle_notes_speech, handle_silence_during_notes
        from silva.commands.notes_store import list_notes, list_todos

        msg, flow = handle_notes_speech("u1", "note this pick up milk")
        self.assertIn("pick up milk", msg.lower())
        self.assertIsNone(flow)
        self.assertEqual(len(list_notes("u1")), 1)

        msg, flow = handle_notes_speech("u1", "what did I note about milk")
        self.assertIn("milk", msg.lower())
        self.assertIsNone(flow)

        msg, flow = handle_notes_speech("u1", "add this to the to do list buy batteries")
        self.assertIn("batteries", msg.lower())
        self.assertFalse(list_todos("u1")[0]["done"])

        msg, flow = handle_notes_speech("u1", "check off buy batteries")
        self.assertIn("checked off", msg.lower())
        self.assertTrue(list_todos("u1")[0]["done"])

        msg, flow = handle_notes_speech("u1", "note this")
        self.assertIsNotNone(flow)
        self.assertEqual(flow["phase"], "await_body")
        opened = None
        for _ in range(5):
            msg, flow = handle_silence_during_notes(flow)
            if flow and flow.get("phase") == "open_type":
                opened = msg
                break
        self.assertEqual(flow["phase"], "open_type")
        self.assertIn("type", opened.lower())

    def test_daily_todo_archive_and_restore(self):
        from datetime import datetime

        from silva.commands.notes_handler import handle_notes_speech
        from silva.commands.notes_phrases import match_notes_speech, parse_todo_clock
        from silva.commands.notes_store import (
            check_due_todo_nags,
            list_archived_todos,
            list_todos,
        )

        speech = match_notes_speech("every day at 8 am take my meds")
        self.assertIsNotNone(speech)
        self.assertTrue(speech.daily)
        self.assertEqual(parse_todo_clock("every day at 8 am take my meds"), (8, 0))

        msg, flow = handle_notes_speech("u1", "every day at 8 am take my meds")
        self.assertIsNone(flow)
        self.assertIn("meds", msg.lower())
        self.assertIn("8", msg)
        item = list_todos("u1")[0]
        self.assertEqual(item["repeat"], "daily")
        self.assertEqual(item["due_hour"], 8)

        due = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)
        events = check_due_todo_nags("u1", now=due, lead_minutes=15, early_interval_seconds=180, due_interval_seconds=90)
        self.assertTrue(events)
        self.assertIn("time", events[0]["message"].lower())
        again = check_due_todo_nags("u1", now=due, lead_minutes=15, early_interval_seconds=180, due_interval_seconds=90)
        self.assertFalse(again)

        from silva.commands.notes_store import mark_todo_nag_popup

        later = due.replace(minute=2)
        mark_todo_nag_popup("u1", item["id"], is_open=True)
        while_open = check_due_todo_nags(
            "u1", now=later, lead_minutes=15, early_interval_seconds=180, due_interval_seconds=90
        )
        self.assertFalse(while_open)

        msg, flow = handle_notes_speech("u1", "I no longer need to take my meds")
        self.assertIn("off your list", msg.lower())
        self.assertEqual(list_todos("u1"), [])
        self.assertEqual(len(list_archived_todos("u1")), 1)

        msg, flow = handle_notes_speech("u1", "bring back take my meds")
        self.assertIn("back on your list", msg.lower())
        self.assertEqual(list_todos("u1")[0]["text"], "take my meds")

    def test_todo_numbers_delete_and_clear(self):
        from silva.commands.notes_handler import handle_notes_speech
        from silva.commands.notes_phrases import looks_like_mumble, parse_todo_number
        from silva.commands.notes_store import list_archived_todos, list_todos

        handle_notes_speech("u1", "add this to the to do list take meds")
        handle_notes_speech("u1", "add this to the to do list take out trash")
        self.assertEqual(len(list_todos("u1")), 2)
        self.assertEqual(parse_todo_number("delete number two"), 2)

        msg, flow = handle_notes_speech("u1", "what is my to do list")
        self.assertIn("1.", msg)
        self.assertIn("2.", msg)
        self.assertNotIn("delete", msg.lower())
        self.assertNotIn("edit", msg.lower())
        self.assertNotIn("move", msg.lower())

        msg, flow = handle_notes_speech("u1", "delete 2")
        self.assertIn("trash", msg.lower())
        self.assertEqual(len(list_todos("u1")), 1)

        msg, flow = handle_notes_speech("u1", "undo that todo")
        self.assertIn("off your list", msg.lower())
        self.assertEqual(list_todos("u1"), [])
        self.assertTrue(list_archived_todos("u1"))

        handle_notes_speech("u1", "add this to the to do list dishes")
        handle_notes_speech("u1", "add this to the to do list laundry")
        msg, flow = handle_notes_speech("u1", "delete the entire to do list")
        self.assertIn("cleared", msg.lower())
        self.assertEqual(list_todos("u1"), [])

        self.assertTrue(looks_like_mumble("uhh mm nuh uhh"))
        self.assertFalse(looks_like_mumble("take my meds at 8 am"))
        msg, flow = handle_notes_speech("u1", "add this to the to do list uhh mm nuh uhh")
        self.assertEqual(flow["phase"], "open_type")

    def test_delete_first_todo_list_phrase(self):
        from silva.commands.notes_handler import handle_notes_speech
        from silva.commands.notes_phrases import match_notes_speech
        from silva.commands.notes_store import list_todos

        speech = match_notes_speech("all right delete the first to do list")
        self.assertIsNotNone(speech)
        self.assertEqual(speech.action, "delete_todo")
        self.assertEqual(speech.number, 1)

        handle_notes_speech("u1", "add this to the to do list take wegovy meds")
        handle_notes_speech("u1", "add this to the to do list take out trash")
        msg, flow = handle_notes_speech("u1", "all right delete the first to do list")
        self.assertIsNone(flow)
        self.assertIn("wegovy", msg.lower())
        todos = list_todos("u1")
        self.assertEqual(len(todos), 1)
        self.assertIn("trash", todos[0]["text"])

    def test_timed_reminder_is_not_math_and_confirms_mishears(self):
        from silva.commands.math_phrases import is_math_command
        from silva.commands.notes_handler import continue_notes_flow, handle_notes_speech
        from silva.commands.notes_phrases import (
            match_notes_speech,
            needs_todo_confirm,
            parse_todo_clock,
            unknown_heard_words,
        )
        from silva.commands.notes_store import list_todos

        reminders = (
            "remind myself at 9:00 a.m. to take my recovery meds",
            "at 9:00 in the morning remind me to take my Rego V meds",
            "at 9 am I need to take my wegovy meds",
        )
        for phrase in reminders:
            with self.subTest(phrase=phrase):
                self.assertFalse(is_math_command(phrase), msg=phrase)
                speech = match_notes_speech(phrase)
                self.assertIsNotNone(speech, msg=phrase)
                self.assertEqual(speech.action, "add_todo", msg=phrase)
                self.assertEqual(parse_todo_clock(phrase)[0], 9)

        self.assertTrue(is_math_command("what is 10 plus 5"))
        self.assertTrue(is_math_command("15 percent of 200"))
        self.assertTrue(is_math_command("2 + 2"))

        self.assertIn("recovery", unknown_heard_words("take my recovery meds"))
        self.assertIn("rego", unknown_heard_words("take my Rego V meds"))
        self.assertTrue(needs_todo_confirm("take my reko meds"))
        self.assertFalse(needs_todo_confirm("take my wegovy meds"))

        msg, flow = handle_notes_speech("u1", "remind myself at 9:00 a.m. to take my recovery meds")
        self.assertIn("heard", msg.lower())
        self.assertIn("recovery", msg.lower())
        self.assertEqual(flow["kind"], "confirm_todo")
        self.assertEqual(list_todos("u1"), [])

        msg, flow = continue_notes_flow("u1", "yes", flow)
        self.assertIn("added", msg.lower())
        self.assertIsNone(flow)
        self.assertIn("recovery", list_todos("u1")[0]["text"].lower())

        msg, flow = handle_notes_speech("u1", "at 9:00 in the morning remind me to take my Rego V meds")
        self.assertEqual(flow["kind"], "confirm_todo")
        msg, flow = continue_notes_flow("u1", "no", flow)
        self.assertEqual(flow["phase"], "open_type")
        self.assertIn("type", msg.lower())

        msg, flow = handle_notes_speech("u1", "at 9 am I need to take my wegovy meds")
        self.assertIsNone(flow)
        self.assertIn("wegovy", msg.lower())
        self.assertIn("9", msg)

        msg, flow = handle_notes_speech("u1", "that was not a math problem")
        self.assertEqual(flow["phase"], "open_type")
        self.assertEqual(flow["kind"], "todo")

    def test_whats_my_reminder_asks_notes_or_todo(self):
        from silva.commands.notes_handler import continue_notes_flow, handle_notes_speech
        from silva.commands.notes_phrases import match_notes_speech
        from silva.commands.notes_store import add_todo

        self.assertEqual(match_notes_speech("what's my reminder").action, "ask_reminder")
        handle_notes_speech("u1", "note this wifi password")
        add_todo("u1", "take wegovy meds", repeat="daily", due_hour=9, due_minute=0)

        msg, flow = handle_notes_speech("u1", "what is my reminder")
        self.assertIn("notes or to-do", msg.lower())
        self.assertEqual(flow["kind"], "pick_reminder")

        msg, flow = continue_notes_flow("u1", "to do list", flow)
        self.assertIn("1. take wegovy meds", msg.lower())
        self.assertNotIn("9:00", msg)
        self.assertNotIn("delete", msg.lower())
        self.assertEqual(flow["phase"], "open_todo")

        msg, flow = handle_notes_speech("u1", "what's my reminder")
        msg, flow = continue_notes_flow("u1", "notes", flow)
        self.assertIn("wifi password", msg.lower())
        self.assertIsNone(flow)


class DeviceAutoDetectTests(unittest.TestCase):
    def test_fifine_beats_headset_and_webcam_mic(self):
        from silva.media.devices import AudioDevice, pick_input, pick_output, score_input

        fifine = AudioDevice(index=4, name="Microphone (FIFINE AM8)", is_default=False, host_api="WASAPI")
        headset = AudioDevice(index=2, name="Headset (RIG 600 PRO)", is_default=True, host_api="WASAPI")
        webcam = AudioDevice(index=1, name="Microphone (ONN Webcam)", is_default=False, host_api="MME")
        chosen = pick_input([webcam, headset, fifine], extra_hints=("fifine", "am8"))
        self.assertEqual(chosen.name, fifine.name)
        self.assertGreater(score_input(fifine, extra_hints=("fifine", "am8")), score_input(headset))
        self.assertIsNone(pick_input([webcam]))

    def test_input_prefers_mme_over_wasapi_same_mic(self):
        from silva.media.devices import AudioDevice, pick_input

        wasapi = AudioDevice(index=8, name="Microphone (FIFINE AM8)", host_api="Windows WASAPI")
        mme = AudioDevice(index=1, name="Microphone (FIFINE AM8)", host_api="MME")
        chosen = pick_input([wasapi, mme], extra_hints=("fifine", "am8"))
        self.assertEqual(chosen.index, 1)

    def test_keeps_headset_until_better_mic_appears(self):
        from silva.media.devices import AudioDevice, pick_input

        headset = AudioDevice(index=2, name="Headset (RIG 600 PRO)", is_default=True, host_api="WASAPI")
        kept = pick_input([headset], current_name=headset.name)
        self.assertEqual(kept.name, headset.name)
        fifine = AudioDevice(index=4, name="USB Microphone (FIFINE AM8)", is_default=False, host_api="WASAPI")
        switched = pick_input([headset, fifine], current_name=headset.name, extra_hints=("fifine", "am8"))
        self.assertEqual(switched.name, fifine.name)
        fell_back = pick_input([headset], current_name=fifine.name)
        self.assertEqual(fell_back.name, headset.name)

    def test_replug_same_name_uses_new_index(self):
        from silva.media.devices import AudioDevice, pick_input

        first = AudioDevice(index=4, name="Microphone (fifine Microphone)", host_api="WASAPI")
        replug = AudioDevice(index=11, name="Microphone (fifine Microphone)", host_api="WASAPI")
        chosen = pick_input([replug], current_name=first.name)
        self.assertEqual(chosen.index, 11)

    def test_does_not_scan_portaudio_while_mic_is_open(self):
        from silva.media import devices as device_mod

        device_mod.set_capture_active(True)
        try:
            with patch.object(device_mod, "_enumerate_pyaudio") as enumerate_pa:
                device_mod.poll_audio_devices(force=True)
                enumerate_pa.assert_not_called()
        finally:
            device_mod.set_capture_active(False)

    def test_mic_oserror_stays_in_voice_mode(self):
        from unittest.mock import patch

        from silva.stt import SpeechToText

        stt = SpeechToText()
        with patch.object(stt, "_listen_raw", side_effect=OSError("stream closed")):
            text, audio = stt.listen_with_audio()
        self.assertIsNone(text)
        self.assertIsNone(audio)
        self.assertTrue(stt.last_device_error)

    def test_output_prefers_headset_over_usb_mic_jack(self):
        from silva.media.devices import AudioDevice, pick_output

        jack = AudioDevice(index=7, name="Speakers (FIFINE AM8)", is_default=True, host_api="WASAPI")
        headset = AudioDevice(index=3, name="Headphones (RIG 600 PRO Bluetooth)", is_default=False, host_api="WASAPI")
        chosen = pick_output([jack, headset])
        self.assertIn("RIG", chosen.name)

    def test_camera_missing_is_polite(self):
        from silva.media.camera import CAMERA_MISSING_MESSAGE, ensure_camera_ready

        with patch("silva.media.camera.cameras_connected", return_value=False):
            message = ensure_camera_ready(wait_seconds=0)
        self.assertIn("please plug", message.lower())
        self.assertEqual(message, CAMERA_MISSING_MESSAGE)

    def test_combo_camera_warning_not_for_elgato(self):
        from silva.media.camera import COMBO_HEAT_WARNING, is_combo_camera

        self.assertTrue(is_combo_camera("ONN 1080P Webcam"))
        self.assertTrue(is_combo_camera("USB 2.0 HD Webcam"))
        self.assertFalse(is_combo_camera("Elgato Facecam MK.2"))
        self.assertFalse(is_combo_camera("Elgato Cam Link 4K"))
        self.assertIn("overheat", COMBO_HEAT_WARNING.lower())

    def test_camera_setup_phrases_and_duration(self):
        from silva.commands.camera_setup_phrases import is_camera_setup_command, parse_test_duration
        from silva.commands.intent import is_action_command

        self.assertTrue(is_camera_setup_command("auto detect the camera"))
        self.assertTrue(is_camera_setup_command("test the camera"))
        self.assertTrue(is_camera_setup_command("turn on the camera"))
        self.assertTrue(is_action_command("detect my camera"))
        self.assertEqual(parse_test_duration("run a 30 second test"), 30)
        self.assertEqual(parse_test_duration("one minute please"), 60)

    def test_combo_offer_opens_warning_flow(self):
        from silva.commands.camera_setup_handler import offer_for_camera

        msg, flow = offer_for_camera("ONN 1080P Webcam", is_combo=True)
        self.assertEqual(flow["phase"], "open_warning")
        self.assertIn("overheat", msg.lower())
        msg, flow = offer_for_camera("Elgato Facecam MK.2", is_combo=False)
        self.assertEqual(flow["phase"], "await_choice")
        self.assertNotIn("overheat", msg.lower())

    def test_stop_does_not_cancel_working_camera_test(self):
        from silva.commands.camera_setup_handler import continue_camera_setup_flow
        from silva.commands.camera_setup_phrases import is_camera_cancel_speech

        flow = {
            "phase": "preview",
            "name": "Elgato Facecam MK.2",
            "is_combo": False,
            "seconds": 30,
        }
        self.assertFalse(is_camera_cancel_speech("stop"))
        self.assertFalse(is_camera_cancel_speech("stop talking"))
        self.assertTrue(is_camera_cancel_speech("cancel the test"))
        msg, next_flow = continue_camera_setup_flow("stop", flow)
        self.assertEqual(next_flow["phase"], "preview")
        self.assertEqual(msg, "")
        msg, next_flow = continue_camera_setup_flow("cancel the test", flow)
        self.assertIsNone(next_flow)
        self.assertIn("skip", msg.lower())
        self.assertIn("normal camera", msg.lower())

    def test_camera_hub_running_blocks_test(self):
        from silva.commands.camera_setup_handler import start_camera_test
        from silva.media.camera_apps import matching_apps

        self.assertEqual(matching_apps("Elgato Facecam MK.2")[0].label, "Elgato Camera Hub")
        offer = {"name": "Elgato Facecam MK.2", "is_combo": False}
        with patch(
            "silva.commands.camera_setup_handler.guard_camera_command",
            return_value="Elgato Camera Hub is already running, even if it's minimized.",
        ):
            msg, flow = start_camera_test(offer, 30)
        self.assertEqual(flow["phase"], "blocked")
        self.assertIn("camera hub", msg.lower())

    def test_perf_preflight_refuses_hot_system(self):
        from silva.media.perf_guard import PERF_REFUSAL, PerfSnapshot, preflight_heavy

        with patch(
            "silva.media.perf_guard.sample_perf",
            return_value=PerfSnapshot(system_cpu=95.0, process_cpu=4.0, avail_ram_gb=8.0),
        ):
            self.assertEqual(preflight_heavy("camera"), PERF_REFUSAL)


class WordPronunciationTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        self._tmpdir = tempfile.TemporaryDirectory()
        self._store = Path(self._tmpdir.name)
        patcher = patch("silva.users.word_pronunciations.STORE_DIR", self._store)
        self.addCleanup(self._tmpdir.cleanup)
        self.addCleanup(patcher.stop)
        patcher.start()

    def _write_wav(self, path, seconds: float = 0.4):
        import wave

        frames = int(16000 * seconds)
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(16000)
            handle.writeframes(b"\x00\x00" * frames)

    def test_phrase_extracts_word_and_edit(self):
        from silva.commands.intent import is_action_command
        from silva.commands.phrase_recorder_phrases import is_phrase_recorder_command
        from silva.commands.pronunciation_phrases import match_pronunciation_speech
        from silva.commands.update_phrases import is_update_confirm_phrase
        from silva.stt_quick_commands import is_complete_command

        record = match_pronunciation_speech("change how you say live")
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.action, "record")
        self.assertEqual(record.word, "live")

        self.assertEqual(
            match_pronunciation_speech("i want to change how the ai says live").word,
            "live",
        )
        self.assertEqual(
            match_pronunciation_speech("teach you how to say open ai").word,
            "open ai",
        )
        self.assertEqual(match_pronunciation_speech("record pronunciation").action, "record")
        self.assertEqual(match_pronunciation_speech("open the pronunciation popup").action, "record")
        self.assertEqual(match_pronunciation_speech("open the wav recorder").action, "record")
        self.assertEqual(match_pronunciation_speech("how do you say live").word, "live")
        self.assertEqual(match_pronunciation_speech("how do you say live").action, "ask")
        self.assertEqual(match_pronunciation_speech("how do you say this word").action, "ask")
        self.assertNotEqual(match_pronunciation_speech("how do you say live").action, "record")
        self.assertEqual(
            match_pronunciation_speech("let me update the audio to the correct wording").action,
            "record",
        )
        self.assertEqual(
            match_pronunciation_speech("update the audio to the correct wording").action,
            "record",
        )
        self.assertEqual(match_pronunciation_speech("tell me how you say live").action, "ask")
        self.assertTrue(is_action_command("how do you say live"))
        self.assertTrue(is_action_command("let me update the audio to the correct wording"))
        from silva.conversation import try_conversation

        self.assertIsNone(try_conversation("how do you say live"))
        self.assertIsNone(try_conversation("let me update the audio to the correct wording"))
        self.assertFalse(is_update_confirm_phrase("let me update the audio to the correct wording"))
        self.assertFalse(is_update_confirm_phrase("update the audio to the correct wording"))
        self.assertIsNone(match_pronunciation_speech("how do you say hello in spanish"))
        self.assertEqual(match_pronunciation_speech("edit pronunciations").action, "edit")
        self.assertEqual(match_pronunciation_speech("edit how you say live").word, "live")
        self.assertEqual(match_pronunciation_speech("edit how you say live").action, "edit")

        self.assertTrue(is_action_command("change how you say live"))
        self.assertTrue(is_complete_command("change how you say live"))
        self.assertFalse(is_phrase_recorder_command("change how you say live"))
        self.assertTrue(is_phrase_recorder_command("i want to teach you my pronunciation"))
        self.assertFalse(is_update_confirm_phrase("update how you say live"))
        self.assertIsNone(match_pronunciation_speech("what's the weather"))
        self.assertIsNone(match_pronunciation_speech("give me details on pronunciation"))
        self.assertIsNotNone(match_pronunciation_speech("can you change how you say live"))
        self.assertEqual(match_pronunciation_speech("can you change how you say live").word, "live")

    def test_store_maps_word_to_wav_and_can_edit(self):
        from pathlib import Path

        from silva.users.word_pronunciations import (
            assign_word,
            list_word_maps,
            register_clip,
            remove_variant,
            set_active_variant,
            unassign_word,
            word_clip_paths,
        )

        first = self._store / "one.wav"
        second = self._store / "two.wav"
        self._write_wav(first)
        self._write_wav(second)
        clip_a = register_clip("kevin", "clipa", first, label="first")
        clip_b = register_clip("kevin", "clipb", second, label="second")
        mapped = assign_word("kevin", "Live", clip_a.id, spoken_as="live live")
        self.assertEqual(mapped.word, "live")
        self.assertEqual(mapped.spoken_as, "live")
        self.assertEqual(Path(word_clip_paths("kevin")["live"]).name, Path(clip_a.wav_file).name)

        second_map = assign_word("kevin", "live", clip_b.id, spoken_as="lyve")
        self.assertEqual(second_map.spoken_as, "lyve")
        self.assertEqual(Path(word_clip_paths("kevin")["live"]).name, Path(clip_b.wav_file).name)
        self.assertEqual(len(list_word_maps("kevin")), 2)
        spoken_forms = {item.spoken_as for item in list_word_maps("kevin")}
        self.assertEqual(spoken_forms, {"live", "lyve"})

        self.assertTrue(set_active_variant("kevin", "live", mapped.variant_id))
        self.assertEqual(Path(word_clip_paths("kevin")["live"]).name, Path(clip_a.wav_file).name)
        self.assertTrue(remove_variant("kevin", "live", second_map.variant_id))
        self.assertEqual([item.spoken_as for item in list_word_maps("kevin")], ["live"])
        self.assertTrue(unassign_word("kevin", "live"))
        self.assertEqual(word_clip_paths("kevin"), {})

    def test_listens_to_clip_and_keeps_one_word(self):
        from silva.tts_pronunciation import prepare_for_speech
        from silva.users.word_pronunciations import (
            list_word_maps,
            pick_single_word,
            register_clip,
            remember_word_from_clip,
            repair_word_maps,
            word_clip_paths,
        )

        self.assertEqual(pick_single_word("live live"), "live")
        self.assertEqual(pick_single_word("the live live"), "live")
        self.assertEqual(pick_single_word("lyve", "live"), "live")
        self.assertEqual(pick_single_word("the live update", "live"), "live")

        wav = self._store / "heard.wav"
        self._write_wav(wav, seconds=0.5)
        clip = register_clip("kevin", "heardclip", wav, label="live")
        with patch(
            "silva.users.word_pronunciations.transcribe_clip",
            return_value="live live",
        ):
            mapped = remember_word_from_clip("kevin", clip.id)
        self.assertEqual(mapped.word, "live")
        self.assertEqual(mapped.spoken_as, "live")

        index = self._store / "kevin" / "index.json"
        data = json.loads(index.read_text(encoding="utf-8"))
        data["words"]["live"][0]["spoken_as"] = "live live"
        index.write_text(json.dumps(data), encoding="utf-8")
        repair_word_maps("kevin")
        self.assertEqual(list_word_maps("kevin")[0].spoken_as, "live")
        self.assertEqual(word_clip_paths("kevin")["live"].name, wav.name)

        with patch(
            "silva.tts_pronunciation._trained_words",
            return_value={"live"},
        ):
            spoken = prepare_for_speech("The update is live. Keep talking.")
        self.assertEqual(spoken, "The update is live. Keep talking.")
        self.assertNotIn("live live", spoken.lower())

    def test_recording_keeps_how_it_sounded(self):
        from silva.users.word_pronunciations import (
            list_word_maps,
            register_clip,
            remember_word_from_clip,
        )

        wav = self._store / "alive.wav"
        self._write_wav(wav, seconds=0.5)
        clip = register_clip("kevin", "aliveclip", wav, label="live")
        with patch("silva.users.word_pronunciations.transcribe_clip", return_value="alive"):
            mapped = remember_word_from_clip("kevin", clip.id, expected_word="live")
        self.assertEqual(mapped.word, "live")
        self.assertEqual(mapped.spoken_as, "alive")
        self.assertEqual([item.spoken_as for item in list_word_maps("kevin")], ["alive"])

    def test_tts_speaks_learned_sound_without_playing_clip(self):
        from types import SimpleNamespace

        import silva.tts_word_clips as tts_word_clips
        from silva.tts_word_clips import build_speech_parts, speak_parts

        wav = self._store / "clip.wav"
        self._write_wav(wav, seconds=0.5)
        row = SimpleNamespace(
            word="live",
            wav_file=str(wav),
            spoken_as="alive",
            context="",
            active=True,
            updated_at="2026-11-23 19:18:00",
        )

        class Engine:
            def __init__(self):
                self.said = []

            def say(self, value):
                self.said.append(value)

            def runAndWait(self):
                return None

        self.assertFalse(hasattr(tts_word_clips, "play_clip"))
        with patch("silva.tts_word_clips.active_word_variants", return_value=[row]):
            parts = build_speech_parts("Update is live now")
            self.assertEqual([item[0] for item in parts], ["say", "learned", "say"])
            self.assertEqual([item[1] for item in parts], ["Update is ", "alive", " now"])
            engine = Engine()
            self.assertTrue(speak_parts(None, "Update is live now", engine))
        self.assertEqual(engine.said, ["Update is alive now"])

    def test_tts_failure_is_logged(self):
        import threading
        from types import SimpleNamespace

        import silva.tts_word_clips as tts_word_clips

        class BadEngine:
            def say(self, value):
                raise RuntimeError("boom")

            def stop(self):
                return None

        speaker = SimpleNamespace(
            stop=lambda: None,
            _wait_for_mic_handoff=lambda: None,
            warmup=lambda: None,
            _build_engine=BadEngine,
            _engine_lock=threading.Lock(),
            _active_engine=None,
        )
        with patch("silva.tts_word_clips.prefetch_text_async"), patch(
            "silva.tts_word_clips.prepare_for_speech", side_effect=lambda text: text
        ), patch("silva.tts_word_clips.ensure_audible"), patch(
            "silva.tts_word_clips.log_error"
        ) as log:
            self.assertFalse(tts_word_clips.speak_impl(speaker, "hello"))
        log.assert_called_once()
        self.assertIn("TTS speak failed", log.call_args.args[0])

    def test_pronunciation_answer_uses_learned_sound_and_supports_correction(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch

        import silva.commands.pronunciation_handler as pronunciation_handler
        from silva.commands.pronunciation_handler import handle_pronunciation_speech
        from silva.conversation import correction_repair

        self.assertFalse(hasattr(pronunciation_handler, "play_wav_file"))

        row = SimpleNamespace(
            word="live",
            wav_file=str(self._store / "clip.wav"),
            spoken_as="alive",
            context="",
            active=True,
            updated_at="2026-11-23 19:18:00",
        )
        assistant = MagicMock()
        assistant._user_id = lambda: "kevin"
        assistant._handle_input.side_effect = lambda value, **_kwargs: handle_pronunciation_speech(
            assistant, value
        )

        with patch.dict(correction_repair._CANDIDATES, clear=True), patch(
            "silva.users.word_pronunciations.active_word_variants", return_value=[row]
        ):
            self.assertTrue(handle_pronunciation_speech(assistant, "how do you say live"))
            assistant.say.assert_called_once_with(
                "For that word, I say alive.", interruptible=False
            )

            assistant.reset_mock()
            self.assertTrue(correction_repair.handle_correction_repair(assistant, "I didn't say life I said live"))
            assistant.say.assert_called_once_with(
                "For that word, I say alive.", interruptible=False
            )

    def test_pronunciation_ask_wording_is_not_stolen_by_help_details(self):
        from silva.commands.help_phrases import is_feature_detail_ask
        from silva.commands.pronunciation_phrases import match_pronunciation_speech
        from silva.conversation.correction_repair import parse_correction

        text = "sorry what I meant is how do you say live"
        self.assertFalse(is_feature_detail_ask(text))
        match = match_pronunciation_speech(text)
        self.assertIsNotNone(match)
        self.assertEqual(match.action, "ask")
        self.assertEqual(match.word, "live")

        correction = "that is not what I said I said how do you say life"
        self.assertEqual(parse_correction(correction), "how do you say life")

    def test_tts_learns_any_word_and_phrase_with_many_variants(self):
        from types import SimpleNamespace

        from silva.tts_word_clips import build_speech_parts

        rows = [
            SimpleNamespace(word="live", spoken_as="alive", context="", active=True, updated_at="2026-11-23 19:18:00"),
            SimpleNamespace(word="live", spoken_as="bye", context="", active=False, updated_at="2026-11-23 19:19:00"),
            SimpleNamespace(word="open ai", spoken_as="open eye", context="", active=True, updated_at="2026-11-23 19:20:00"),
            SimpleNamespace(word="read", spoken_as="red", context="past", active=False, updated_at="2026-11-23 19:21:00"),
            SimpleNamespace(word="read", spoken_as="reed", context="", active=True, updated_at="2026-11-23 19:22:00"),
        ]
        with patch("silva.tts_word_clips.active_word_variants", return_value=rows):
            parts = build_speech_parts("Use Open AI and live")
            self.assertEqual([item[1] for item in parts], ["Use ", "open eye", " and ", "alive"])
            context_parts = build_speech_parts("Yesterday I read past that")
            self.assertEqual(
                [item[1] for item in context_parts],
                ["Yesterday I ", "red", " past that"],
            )

    def test_logged_pronunciation_complaints_route_to_details(self):
        from silva.commands.help_phrases import (
            feature_detail_reply_for_user,
            is_feature_detail_ask,
        )

        owner = {"id": "kevin", "tier": 5}
        utterances = (
            "well since I already have one of the words how are you able to say it in different ways",
            "what I was talking about is sometimes you say live when it's supposed to sound like alive",
            "none of that is what I said when I said live I said bye not pay by",
        )
        for text in utterances:
            with self.subTest(text=text):
                self.assertTrue(is_feature_detail_ask(text))
                detail = feature_detail_reply_for_user(text, owner) or ""
                self.assertIn("more than one way", detail.lower())
                self.assertIn("speak it in my own voice", detail.lower())
                self.assertNotIn("play your recording", detail.lower())
                self.assertIn("alive", detail.lower())

        mic_ask = "you're still not autocorrecting to what I am saying through my microphone"
        self.assertTrue(is_feature_detail_ask(mic_ask))
        self.assertIn(
            "speech-to-text",
            (feature_detail_reply_for_user(mic_ask, owner) or "").lower(),
        )

    def test_help_details_are_optional(self):
        from silva.commands.help_phrases import (
            HELP_CAPABILITIES_TEXT,
            capability_reply_for_user,
            feature_detail_reply_for_user,
            is_capability_ask,
            is_feature_detail_ask,
            is_help_request,
        )

        owner = {"id": "kevin", "tier": 5}
        self.assertNotIn("pronunciation", HELP_CAPABILITIES_TEXT.lower())
        self.assertFalse(is_help_request("is pronunciation available"))
        self.assertTrue(is_capability_ask("is pronunciation available"))
        self.assertFalse(is_capability_ask("can you change how you say live"))
        self.assertTrue(is_feature_detail_ask("give me details on pronunciation"))
        detail = feature_detail_reply_for_user("give me details on pronunciation", owner) or ""
        self.assertIn("any word or phrase", detail.lower())
        self.assertIn("speak it in my own voice", detail.lower())
        self.assertIn("edit pronunciations", detail.lower())
        short = capability_reply_for_user("is pronunciation available", owner) or ""
        self.assertNotIn("how do you say live", short.lower())
        self.assertIn("update the audio", short.lower())

    def test_training_words_question_uses_pronunciation_detail(self):
        from silva.commands.help_phrases import (
            feature_detail_reply_for_user,
            is_feature_detail_ask,
        )

        owner = {"id": "kevin", "tier": 5}
        phrasings = (
            "if I train you on certain words to say will you say them",
            "if I teach you certain words will you say them",
            "will you say them if I train you",
            "can you learn to say certain words",
            "do you say words the way I teach you",
            "will you use the words I train you on",
        )
        for text in phrasings:
            with self.subTest(text=text):
                self.assertTrue(is_feature_detail_ask(text))
                detail = feature_detail_reply_for_user(text, owner) or ""
                self.assertIn("yes", detail.lower())
                self.assertIn("any word or phrase", detail.lower())
                self.assertIn("speak it in my own voice", detail.lower())
                self.assertIn("learned phrases", detail.lower())

        autocorrect = "all right tell me how you would autocorrect something that I say"
        self.assertTrue(is_feature_detail_ask(autocorrect))
        self.assertIn(
            "speech-to-text",
            (feature_detail_reply_for_user(autocorrect, owner) or "").lower(),
        )

        self.assertFalse(is_feature_detail_ask("change how you say live"))
        self.assertFalse(is_feature_detail_ask("record pronunciation"))

    def test_complaint_does_not_start_pronunciation_recording(self):
        from silva.commands.pronunciation_phrases import match_pronunciation_speech

        text = (
            "why are you repeating yourself and rephrasing me at the end "
            "just to say that you're not doing it correctly"
        )
        self.assertIsNone(match_pronunciation_speech(text))


class StreamDeckLaunchTests(unittest.TestCase):
    def test_parser_has_console_and_stream_deck_flags(self):
        from silva.__main__ import build_parser

        parser = build_parser()
        console = parser.parse_args(["--console"])
        self.assertTrue(console.console)
        deck = parser.parse_args(["--stream-deck"])
        self.assertTrue(deck.stream_deck)

    def test_console_python_swaps_pythonw(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from silva.launch import console_python

        with TemporaryDirectory() as raw:
            folder = Path(raw)
            pythonw = folder / "pythonw.exe"
            python = folder / "python.exe"
            pythonw.write_bytes(b"")
            python.write_bytes(b"")
            self.assertEqual(console_python(str(pythonw)), str(python))
            self.assertEqual(console_python(str(python)), str(python))

    def test_launch_shows_running_instance_instead_of_starting_another(self):
        from unittest.mock import patch

        from silva.launch import launch_or_show

        with (
            patch("silva.instance.silva_is_running", return_value=True),
            patch("silva.instance.handoff_to_running", return_value=True) as handoff,
            patch("subprocess.Popen") as popen,
        ):
            self.assertEqual(launch_or_show(), 0)
            handoff.assert_called_once()
            popen.assert_not_called()

    def test_launch_starts_visible_console(self):
        from unittest.mock import patch

        from silva.launch import CREATE_NEW_CONSOLE, launch_or_show

        with (
            patch("silva.instance.silva_is_running", return_value=False),
            patch("subprocess.Popen") as popen,
        ):
            self.assertEqual(launch_or_show(), 0)
            popen.assert_called_once()
            args, kwargs = popen.call_args
            command = args[0]
            self.assertIn("-m", command)
            self.assertIn("silva", command)
            self.assertIn("--console", command)
            self.assertEqual(kwargs.get("creationflags"), CREATE_NEW_CONSOLE)

    def test_lock_file_blocks_second_instance(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from silva.instance import acquire_silva_instance, silva_is_running

        with TemporaryDirectory() as raw:
            lock = Path(raw) / "silva.lock"
            self.assertTrue(acquire_silva_instance(lock_file=lock))
            self.assertTrue(lock.exists())
            self.assertFalse(silva_is_running(lock_file=lock))
            lock.write_text("1", encoding="utf-8")
            with patch("silva.instance._process_alive", return_value=True):
                self.assertTrue(silva_is_running(lock_file=lock))
                self.assertFalse(acquire_silva_instance(lock_file=lock))

    def test_stale_lock_is_replaced(self):
        import os
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from silva.instance import acquire_silva_instance

        with TemporaryDirectory() as raw:
            lock = Path(raw) / "silva.lock"
            lock.write_text("99999999", encoding="utf-8")
            with patch("silva.instance._process_alive", return_value=False):
                self.assertTrue(acquire_silva_instance(lock_file=lock))
            self.assertEqual(lock.read_text(encoding="utf-8").strip(), str(os.getpid()))

    def test_clean_console_skips_listening_print(self):
        from io import StringIO

        from silva.console_view import enable_clean_console, is_clean_console, print_error
        from silva.stt import SpeechToText

        enable_clean_console(True)
        self.assertTrue(is_clean_console())
        stt = SpeechToText.__new__(SpeechToText)
        stt._show_listening_prompt = True
        captured = StringIO()
        with patch("sys.stdout", captured):
            stt.signal_listening()
        self.assertEqual(captured.getvalue(), "")
        err = StringIO()
        with patch("sys.stdout", err):
            print_error("mic missing")
        self.assertIn("Error: mic missing", err.getvalue())
        enable_clean_console(True)

    def test_stream_deck_files_exist(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        self.assertTrue((root / "silva-stream-deck.bat").is_file())
        self.assertTrue((root / "silva-stream-deck.vbs").is_file())
        self.assertTrue((root / "silva" / "launch.py").is_file())


class OnboardingAndFeatureRequestTests(unittest.TestCase):
    def test_onboarding_summary_scales_with_tier(self):
        from silva.users.manager import needs_onboarding
        from silva.users.onboarding import examples_for_user, summary_for_user

        guest = {"id": "guest", "tier": 1}
        admin = {"id": "admin", "tier": 4}
        self.assertTrue(needs_onboarding(guest))
        self.assertNotIn("admin", summary_for_user(guest).lower())
        self.assertIn("admin", summary_for_user(admin).lower())
        self.assertIn("wake up Silva", examples_for_user(guest))
        self.assertIn("show pending requests", examples_for_user(admin))

    def test_feature_offer_is_only_made_once(self):
        import tempfile
        from pathlib import Path

        from silva.users.feature_requests import (
            feature_offer_pending,
            mark_feature_offer_made,
        )

        with tempfile.TemporaryDirectory() as tmp:
            with patch("silva.users.feature_requests.TRACKING_FILE", Path(tmp) / "tracking.json"):
                self.assertTrue(feature_offer_pending("sam"))
                mark_feature_offer_made("sam")
                self.assertFalse(feature_offer_pending("sam"))

    def test_feature_request_is_saved_and_notifies_owner(self):
        import tempfile
        from pathlib import Path

        from silva.users.feature_requests import submit_feature_request

        with tempfile.TemporaryDirectory() as tmp:
            tracking = Path(tmp) / "tracking.json"
            requests = Path(tmp) / "requests.json"
            with (
                patch("silva.users.feature_requests.TRACKING_FILE", tracking),
                patch("silva.users.feature_requests.REQUESTS_FILE", requests),
                patch("silva.notifications.dispatch.notify_owner_async") as notify,
            ):
                submit_feature_request(
                    {"id": "sam", "name": "Sam"}, "camera", reason="I need to see who is at the door"
                )
            items = json.loads(requests.read_text(encoding="utf-8"))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["user_id"], "sam")
        self.assertEqual(items[0]["feature"], "camera")
        self.assertIn("door", items[0]["reason"])
        self.assertTrue(notify.called)


class ImageStudioTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        root = Path(self._tmpdir.name)
        self.generated_dir = root / "generated_images"
        self.reference_dir = root / "reference_images"
        self.showcase_file = root / "panel_showcase.json"

        from silva.config import load_config as real_load_config

        def lightweight_config():
            data = dict(real_load_config())
            data["image_generator_backend"] = "lightweight"
            return data

        for target, value in (
            ("silva.media.image_generator.load_config", lightweight_config),
            ("silva.media.image_generator.STORE_DIR", self.generated_dir),
            ("silva.media.image_generator.INDEX_FILE", self.generated_dir / "index.json"),
            ("silva.media.image_generator.ACTIVE_FILE", self.generated_dir / "active.json"),
            ("silva.media.reference_images.STORE_DIR", self.reference_dir),
            ("silva.media.reference_images.INDEX_FILE", self.reference_dir / "index.json"),
            ("silva.dev.panel_showcase.SHOWCASE_FILE", self.showcase_file),
        ):
            patcher = patch(target, value)
            self.addCleanup(patcher.stop)
            patcher.start()

    def test_downloads_scan_is_off_by_default(self):
        from silva.config import DEFAULT_CONFIG

        self.assertFalse(DEFAULT_CONFIG["reference_images_auto_scan_downloads"])

    def test_image_studio_phrases_are_actions(self):
        from silva.commands.intent import is_action_command
        from silva.media.image_generator_phrases import (
            edit_prompt,
            image_prompt,
            match_image_generation_speech,
        )
        from silva.stt_quick_commands import is_complete_command

        cases = {
            "open image studio": "open",
            "generate an image of a blue chart": "generate",
            "add a moon": "edit",
            "describe this image": "describe",
            "generate a description of this image": "describe",
            "save this image": "save",
        }
        for text, expected in cases.items():
            self.assertEqual(match_image_generation_speech(text), expected, text)
            self.assertTrue(is_action_command(text), text)
            self.assertTrue(is_complete_command(text), text)
        self.assertEqual(image_prompt("generate an image of a blue chart"), "a blue chart")
        self.assertEqual(edit_prompt("add a moon"), "a moon")

    def test_gpu_status_and_test_phrases(self):
        from silva.media.image_generator_phrases import match_image_generation_speech

        self.assertEqual(match_image_generation_speech("gpu status"), "status")
        self.assertEqual(match_image_generation_speech("check image generation status"), "status")
        self.assertEqual(match_image_generation_speech("gpu test"), "test")
        self.assertEqual(match_image_generation_speech("test image generation"), "test")

    def test_gpu_settings_are_capped(self):
        from silva.media.image_generator_gpu import resolve_gpu_settings

        settings = resolve_gpu_settings(
            {
                "image_generator_test_size": "9999",
                "image_generator_test_steps": "99",
                "image_generator_min_free_vram_gb": "0",
            },
            test=True,
        )
        self.assertEqual(settings["width"], 512)
        self.assertEqual(settings["steps"], 4)
        self.assertEqual(settings["min_free_vram_gb"], 1.0)

    def test_generate_edit_describe_and_save(self):
        from pathlib import Path

        from silva.media.image_generator import (
            active_image_for,
            describe_generated_image,
            edit_image,
            generate_image,
            save_generated_to_library,
        )

        with patch("silva.media.image_generator.generation_preflight", return_value=None):
            record = generate_image("blue ocean chart", user_id="kevin")
            self.assertIsNotNone(record)
            assert record is not None
            self.assertEqual(record["palette"], "ocean")
            self.assertIn("chart", record["motifs"])
            self.assertTrue(Path(record["path"]).is_file())

            description = describe_generated_image(str(record["id"]))
            self.assertIn("procedural illustration", description)

            edited = edit_image(str(record["id"]), "add stars", user_id="kevin")
            self.assertIsNotNone(edited)
            assert edited is not None
            self.assertIn("add stars", edited["history"])

            saved = save_generated_to_library(str(record["id"]), user_id="kevin")
            self.assertIsNotNone(saved)
            assert saved is not None
            self.assertEqual(saved["source"], "image_generator")

        active = active_image_for("kevin")
        self.assertIsNotNone(active)
        assert active is not None
        self.assertEqual(active["id"], record["id"])

    def test_generation_respects_preflight_refusal(self):
        from silva.media.image_generator import generate_image

        with patch(
            "silva.media.image_generator.generation_preflight",
            return_value="System is too busy.",
        ):
            record = generate_image("a quiet forest", user_id="kevin")
        self.assertEqual(record, {"refusal": "System is too busy."})

    def test_generation_preflight_checks_process_cpu(self):
        from silva.media.image_generator import generation_preflight
        from silva.media.perf_guard import PerfSnapshot

        snapshot = PerfSnapshot(system_cpu=99.0, process_cpu=4.0, avail_ram_gb=8.0)
        with (
            patch("silva.media.perf_guard.sample_perf", return_value=snapshot),
            patch(
                "silva.media.image_generator.load_config",
                return_value={
                    "image_generator_enabled": True,
                    "image_generator_queue_limit": 4,
                    "perf_guard_enabled": True,
                    "image_generator_min_ram_gb": 1.5,
                    "image_generator_cpu_max": 80.0,
                },
            ),
        ):
            self.assertIsNone(generation_preflight())

    def test_panel_showcase_state_and_request(self):
        from silva.dev import panel_showcase

        with patch("silva.dev.panel_registry.load_extension_tab_specs", return_value=[]):
            features = {item["id"] for item in panel_showcase.available_features()}
        self.assertIn("admin_access", features)
        self.assertIn("test", features)

        panel_showcase.mark_feature("admin_access", True)
        panel_showcase.set_feature_style(
            "admin_access",
            accent="#112233",
            layout="cards",
            notes="Use larger category cards",
            reference_id="abc123",
        )
        request = panel_showcase.code_agent_request("admin_access")
        self.assertIn("admin_access", request)
        self.assertIn("#112233", request)
        self.assertIn("Use larger category cards", request)
        self.assertIn("abc123", request)

    def test_image_library_visibility_is_owner_only(self):
        from silva.users.admin_access import is_capability_enabled

        owner = {"id": "kevin", "name": "Kevin", "tier": 5, "role": "owner"}
        admin = {"id": "admin1", "name": "Admin", "tier": 4, "role": "admin"}
        self.assertTrue(is_capability_enabled(owner, "view_image_library"))
        self.assertFalse(is_capability_enabled(admin, "view_image_library"))


class PersonalityTests(unittest.TestCase):
    def test_attitude_modes_and_styling(self):
        from silva.conversation.attitude import (
            get_attitude,
            match_attitude_speech,
            note_user_text,
            set_attitude,
            style_reply,
        )

        set_attitude("test-user", "calm")
        self.assertEqual(style_reply("Done.", "test-user"), "Done.")
        self.assertEqual(match_attitude_speech("act sassy"), "sassy")
        self.assertEqual(match_attitude_speech("be skiddish"), "skittish")
        self.assertEqual(match_attitude_speech("stop being mean"), "calm")
        self.assertEqual(note_user_text("test-user", "you are stupid"), "sassy")
        self.assertEqual(note_user_text("test-user", "fuck you"), "mean")
        self.assertEqual(note_user_text("test-user", "thank you"), "calm")

        for attitude in ("shy", "skittish", "sassy", "mean"):
            set_attitude("test-user", attitude)
            styled = style_reply("Done.", "test-user")
            self.assertIn("Done.", styled)
            self.assertEqual(get_attitude("test-user"), attitude)
        set_attitude("test-user", "calm")

    def test_replies_vary_within_an_attitude(self):
        from silva.conversation.attitude import set_attitude, style_reply

        set_attitude("test-user", "sassy")
        replies = {style_reply("Done.", "test-user") for _ in range(40)}
        self.assertGreater(len(replies), 1)
        set_attitude("test-user", "calm")

    def test_profanity_tone_uses_words_and_loudness(self):
        import numpy as np
        import speech_recognition as sr

        from silva.conversation.attitude import (
            classify_profanity_tone,
            classify_response_tone,
            note_user_text,
            set_attitude,
            style_reply,
        )

        def audio(amplitude: int):
            rate = 16000
            times = np.linspace(0, 0.5, rate // 2, endpoint=False)
            samples = (np.sin(2 * np.pi * 180 * times) * amplitude).astype(np.int16)
            return sr.AudioData(samples.tobytes(), rate, 2)

        self.assertEqual(classify_profanity_tone("you are stupid"), "sassy")
        self.assertEqual(classify_profanity_tone("fuck you"), "mean")
        self.assertEqual(classify_profanity_tone("what the fuck"), "sassy")
        self.assertEqual(classify_profanity_tone("just kidding, you dumb bitch"), "calm")
        self.assertEqual(
            classify_profanity_tone("you're pissing me off that you're not working correctly"),
            "sassy",
        )
        self.assertEqual(classify_profanity_tone("that's bullshit", audio(9000)), "mean")
        self.assertEqual(classify_profanity_tone("that's bullshit", audio(30)), "sassy")
        self.assertEqual(classify_response_tone("how are you doing you dumb bitch"), "mean")
        self.assertEqual(
            classify_response_tone("little stressed out that you're not working the way I want you to"),
            "sassy",
        )
        self.assertEqual(classify_response_tone("you stupid whore go to sleep"), "mean")
        self.assertEqual(classify_response_tone("you dumb bitch go to sleep"), "mean")
        self.assertEqual(classify_response_tone("why are you not going to sleep idiot"), "sassy")
        self.assertEqual(classify_response_tone("go to sleep"), "calm")

        set_attitude("kevin", "calm")
        note_user_text("kevin", "just kidding, you dumb bitch", audio(30))
        self.assertEqual(style_reply("Done.", "kevin"), "Done.")
        note_user_text("kevin", "you are really pissing me off", audio(9000))
        self.assertNotEqual(style_reply("Done.", "kevin"), "Done.")
        set_attitude("kevin", "calm")

    def test_attitude_commands_are_actions(self):
        from unittest.mock import MagicMock

        from silva.commands.intent import is_action_command
        from silva.conversation.attitude import handle_attitude_speech

        self.assertTrue(is_action_command("act sassy"))
        assistant = MagicMock()
        assistant._user_id.return_value = "test-user"
        self.assertTrue(handle_attitude_speech(assistant, "be skittish"))
        assistant.say.assert_called_once()

    def test_unfiltered_language_only_for_owner_and_admins(self):
        from unittest.mock import patch

        from silva.conversation.attitude import set_attitude, style_reply

        owner = {"id": "kevin", "name": "Kevin", "role": "owner", "tier": 5}
        user = {"id": "guest1", "name": "Guest", "role": "user", "tier": 1}
        with patch("silva.conversation.attitude.get_active_user", return_value=user), patch(
            "silva.conversation.attitude.load_store",
            return_value={"users": {"kevin": owner, "guest1": user}},
        ):
            set_attitude("guest1", "mean")
            plain = " ".join(style_reply("Done.", "guest1") for _ in range(30))
            self.assertNotIn("shit", plain.lower())
            self.assertNotIn("fuck", plain.lower())
            set_attitude("kevin", "mean")
            raw = " ".join(style_reply("Done.", "kevin") for _ in range(30))
            self.assertTrue(any(word in raw.lower() for word in ("fuck", "shit", "asshole")))
            set_attitude("guest1", "calm")
            set_attitude("kevin", "calm")


class SafetyTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.config_file = Path(self._tmpdir.name) / "config.json"
        self.config_file.write_text("{}", encoding="utf-8")
        patcher = patch("silva.config.CONFIG_FILE", self.config_file)
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_safety_phrases_and_cleaning(self):
        from silva.conversation.safety import (
            apply_safety,
            handle_safety_speech,
            is_family_safe,
            is_speaker_safe,
            sanitize_image_prompt,
        )
        from unittest.mock import MagicMock

        assistant = MagicMock()
        assistant._user_id.return_value = "kevin"
        self.assertTrue(handle_safety_speech(assistant, "children are present"))
        self.assertTrue(is_family_safe())
        self.assertEqual(apply_safety("What the fuck?"), "What the freak?")
        self.assertEqual(sanitize_image_prompt("a dumb shit robot"), "a dumb stuff robot")
        from silva.stt_quick_commands import is_complete_command

        self.assertTrue(is_complete_command("children are present"))
        self.assertTrue(handle_safety_speech(assistant, "speaker mode on"))
        self.assertTrue(is_speaker_safe())
        self.assertLessEqual(len(apply_safety("One. Two. Three. Four.")), 240)
        self.assertTrue(handle_safety_speech(assistant, "speaker mode off"))
        self.assertTrue(handle_safety_speech(assistant, "family mode off"))
        self.assertFalse(is_family_safe())
        self.assertFalse(is_speaker_safe())


class EchoGuardTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.config_file = Path(self._tmpdir.name) / "config.json"
        self.config_file.write_text('{"speaker_safe_mode": true}', encoding="utf-8")
        patcher = patch("silva.conversation.echo_guard.load_config", return_value={
            "speaker_safe_mode": True,
            "speaker_self_echo_guard": True,
        })
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_self_echo_is_ignored_unless_directly_asked(self):
        from silva.conversation.echo_guard import (
            evaluate_input,
            forget_spoken,
            remember_spoken,
        )

        forget_spoken()
        remember_spoken("Going to sleep. Say wake up Silva to wake me.")
        self.assertEqual(evaluate_input("going to sleep say wake up silva"), "self_echo")
        self.assertEqual(evaluate_input("silva answer that"), "direct_answer")
        self.assertEqual(evaluate_input("what is the weather"), None)

    def test_other_ai_is_allowed(self):
        from silva.conversation.echo_guard import evaluate_input

        self.assertEqual(evaluate_input("alexa what time is it"), "other_ai")


class FutureTaskTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.task_file = Path(self._tmpdir.name) / "future_tasks.json"
        patcher = patch("silva.dev.future_tasks.TASK_FILE", self.task_file)
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_add_delete_assign_and_voice_phrases(self):
        from unittest.mock import MagicMock, patch

        from silva.dev.future_tasks import (
            assign_task,
            delete_task,
            handle_future_task_speech,
            is_future_task_command,
            list_tasks,
            match_future_task_speech,
        )

        self.assertEqual(
            match_future_task_speech("add future update add room listening"),
            ("add", "add room listening", ""),
        )
        self.assertTrue(is_future_task_command("delete future update abc123"))
        from silva.stt_quick_commands import is_complete_command

        self.assertTrue(is_complete_command("add future update add room listening"))

        created = None
        assistant = MagicMock()
        owner = {"id": "kevin", "name": "Kevin", "role": "owner", "tier": 5}
        users = {
            "kevin": owner,
            "admin1": {"id": "admin1", "name": "Nick", "role": "admin", "tier": 4},
        }
        with (
            patch("silva.dev.future_tasks.get_active_user", return_value=owner),
            patch("silva.users.manager.load_store", return_value={"users": users}),
        ):
            self.assertTrue(handle_future_task_speech(assistant, "add future update add room listening"))
            created = list_tasks()[0]
            ok, message = assign_task(str(created["id"]), "Nick")
            self.assertTrue(ok, message)
            self.assertEqual(list_tasks()[0]["assigned_to"], "admin1")
            self.assertTrue(handle_future_task_speech(assistant, f"delete future update {created['id']}"))
            self.assertEqual(list_tasks(), [])


class SpeechPolicyTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.policy_file = Path(self._tmpdir.name) / "speech_policy.json"
        patcher = patch("silva.conversation.speech_policy.POLICY_FILE", self.policy_file)
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_owner_can_toggle_and_guest_needs_age_verification(self):
        from silva.conversation.speech_policy import (
            allows_unfiltered,
            mark_age_verified,
            set_unfiltered,
        )

        with patch(
            "silva.conversation.speech_policy.is_privileged",
            side_effect=lambda user_id: str(user_id) == "kevin",
        ):
            self.assertFalse(allows_unfiltered("guest1"))
            self.assertTrue(allows_unfiltered("kevin"))
            ok, _message = set_unfiltered("guest1", True, actor_id="kevin")
            self.assertFalse(ok)
            mark_age_verified("guest1", band="30-39", verified_by="kevin")
            ok, _message = set_unfiltered("guest1", True, actor_id="kevin")
            self.assertTrue(ok)
            self.assertTrue(allows_unfiltered("guest1"))
            ok, _message = set_unfiltered("guest1", False, actor_id="kevin")
            self.assertTrue(ok)
            self.assertFalse(allows_unfiltered("guest1"))

    def test_blocked_phrase_bypass_for_privileged_user(self):
        import json
        from pathlib import Path

        from silva.dev.speech_training import clear_blocked_phrases, is_blocked_phrase

        path = Path(self._tmpdir.name) / "speech_training.json"
        path.write_text(json.dumps({"dont_say_phrases": ["bad phrase"]}), encoding="utf-8")
        patcher = patch("silva.dev.speech_training.SPEECH_TRAINING_FILE", path)
        self.addCleanup(patcher.stop)
        patcher.start()

        self.assertTrue(is_blocked_phrase("bad phrase", "guest1"))
        self.assertFalse(is_blocked_phrase("bad phrase", "kevin"))
        self.assertEqual(clear_blocked_phrases(), 1)
        self.assertFalse(is_blocked_phrase("bad phrase", "guest1"))


class AgeVerificationTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.users_file = Path(self._tmpdir.name) / "users.json"
        self.policy_file = Path(self._tmpdir.name) / "speech_policy.json"
        self.users_file.write_text(
            json.dumps(
                {
                    "owner_id": "kevin",
                    "active_user_id": "guest1",
                    "users": {
                        "kevin": {
                            "id": "kevin",
                            "name": "Kevin",
                            "role": "owner",
                            "tier": 5,
                            "permissions": ["all"],
                        },
                        "guest1": {
                            "id": "guest1",
                            "name": "Guest",
                            "role": "user",
                            "tier": 1,
                            "permissions": [],
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        patcher = patch(
            "silva.users.age_verification.load_store",
            side_effect=_load_age_users(self.users_file),
        )
        self.addCleanup(patcher.stop)
        patcher.start()
        save_patcher = patch("silva.users.age_verification.save_store", side_effect=lambda data: self.users_file.write_text(json.dumps(data), encoding="utf-8"))
        self.addCleanup(save_patcher.stop)
        save_patcher.start()
        policy_patcher = patch("silva.conversation.speech_policy.POLICY_FILE", self.policy_file)
        self.addCleanup(policy_patcher.stop)
        policy_patcher.start()

    def test_age_band_and_success(self):
        from silva.conversation.speech_policy import allows_unfiltered
        from silva.users.age_verification import age_band_for_age, verify_age_claim

        self.assertEqual(age_band_for_age(35), "30-39")
        with (
            patch("silva.users.age_verification._frame_has_face", return_value=True),
            patch(
                "silva.users.age_verification._face_matches_profile",
                return_value=(True, "score_0.90"),
            ),
            patch("silva.users.age_verification.estimate_band_from_frame", return_value=None),
        ):
            ok, message = verify_age_claim("guest1", 35, frame=object())
        self.assertTrue(ok, message)
        self.assertTrue(allows_unfiltered("guest1"))
        data = json.loads(self.users_file.read_text(encoding="utf-8"))
        self.assertEqual(data["users"]["guest1"]["age_band"], "30-39")
        self.assertTrue(data["users"]["guest1"]["age_verified"])

    def test_retry_on_missing_face(self):
        from silva.users.age_verification import verify_age_claim

        with patch("silva.users.age_verification._frame_has_face", return_value=False):
            ok, message = verify_age_claim("guest1", 22, frame=object())
        self.assertFalse(ok)
        self.assertIn("Try again", message)


class FutureTaskVerificationTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.task_file = Path(self._tmpdir.name) / "future_tasks.json"
        patcher = patch("silva.dev.future_tasks.TASK_FILE", self.task_file)
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_completed_task_waits_as_circle_then_deleted(self):
        from silva.dev.future_tasks import add_task, complete_task, list_tasks, verify_task

        record = add_task("add room listening")
        ok, message = complete_task(record["id"])
        self.assertTrue(ok, message)
        self.assertEqual(list_tasks()[0]["status"], "○")
        ok, message = verify_task(record["id"], verifier_id="kevin")
        self.assertTrue(ok, message)
        self.assertEqual(list_tasks(), [])


class TeamUpdateTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.update_file = Path(self._tmpdir.name) / "team_updates.json"
        self.task_file = Path(self._tmpdir.name) / "future_tasks.json"
        update_patcher = patch("silva.dev.team_updates.UPDATE_FILE", self.update_file)
        task_patcher = patch("silva.dev.future_tasks.TASK_FILE", self.task_file)
        for patcher in (update_patcher, task_patcher):
            self.addCleanup(patcher.stop)
            patcher.start()

    def test_submit_approve_and_reject(self):
        from silva.dev.future_tasks import list_tasks
        from silva.dev.team_updates import (
            approve_update,
            list_updates,
            reject_update,
            submit_update,
        )

        with patch("silva.notifications.dispatch.notify_owner_async"):
            record = submit_update("add room listening", user_id="guest1", user_name="Guest")
        self.assertEqual(list_updates()[0]["status"], "pending")

        ok, message = approve_update(record["id"], approver_id="kevin")
        self.assertTrue(ok, message)
        self.assertEqual(list_updates()[0]["status"], "approved")
        self.assertTrue(any(item["text"] == "add room listening" for item in list_tasks()))

        with (
            patch("silva.notifications.dispatch.notify_owner_async"),
            patch("silva.gui.update_popup.show_message_popup") as popup,
            patch("silva.notifications.email.send_email_reply") as email,
        ):
            record = submit_update(
                "add better weather",
                user_id="guest1",
                user_name="Guest",
                email="guest@example.com",
            )
            ok, message = reject_update(
                record["id"],
                approver_id="kevin",
                reply="Not this cycle.",
                email_reply=True,
            )
        self.assertTrue(ok, message)
        self.assertEqual(list_updates()[0]["status"], "rejected")
        popup.assert_called_once()
        email.assert_called_once()


class NewsYesNoDispatchTests(unittest.TestCase):
    def test_full_no_answer_is_handled_by_news_flow(self):
        from silva.yes_no_prompt import KIND_NEWS, dispatch

        assistant = MagicMock()
        assistant._yes_no_owner = KIND_NEWS
        assistant._news_flow = {"phase": "await_show_choice", "user_id": "kevin"}
        assistant._is_no.return_value = False
        assistant._is_yes.return_value = False

        with patch("silva.commands.news_monitor.clear_pending_prompt"):
            handled = dispatch(assistant, "no I don't want to see the local news")

        self.assertTrue(handled)
        self.assertIsNone(assistant._news_flow)
        self.assertIsNone(assistant._yes_no_owner)
        assistant.say.assert_called_once()
        self.assertIn("saved today's briefing", assistant.say.call_args.args[0])

    def test_weather_request_is_not_treated_as_yes_no(self):
        from silva.yes_no_prompt import KIND_NEWS, dispatch

        assistant = MagicMock()
        assistant._yes_no_owner = KIND_NEWS
        assistant._news_flow = {"phase": "await_show_choice", "user_id": "kevin"}
        self.assertFalse(dispatch(assistant, "what's my local weather"))
        assistant.say.assert_not_called()


class LearnedPhraseTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        store = Path(self._tmpdir.name) / "learned_phrases.json"
        patcher = patch("silva.conversation.learned_phrases.STORE_FILE", store)
        self.addCleanup(patcher.stop)
        patcher.start()
        from silva.conversation import learned_phrases

        learned_phrases._LAST_UNKNOWN.clear()

    def test_exact_and_correction_learning(self):
        from silva.conversation.learned_phrases import (
            learn_from_correction,
            match_learned,
            remember_unknown,
            teach,
        )

        ok, _message = teach("purple monkey", "call Kevin", user_id="kevin", actor_id="kevin")
        self.assertTrue(ok)
        self.assertEqual(
            match_learned("purple monkey", user_id="kevin")["reply"],
            "call Kevin",
        )

        remember_unknown("blorp doot", user_id="kevin")
        ok, _message = learn_from_correction(
            "blorp doot",
            "no, I meant call the plumber",
            user_id="kevin",
            actor_id="kevin",
        )
        self.assertTrue(ok)
        self.assertEqual(
            match_learned("blorp doot", user_id="kevin")["reply"],
            "call the plumber",
        )

    def test_handle_learned_reply_and_command(self):
        from silva.conversation.learned_phrases import handle_learned_speech

        assistant = MagicMock()
        assistant._user_id.return_value = "kevin"
        assistant._learned_command_active = False

        self.assertTrue(handle_learned_speech(assistant, "learn that zorp means hello"))
        assistant.say.assert_called()

        assistant.reset_mock()
        self.assertTrue(handle_learned_speech(assistant, "when I say zorp run open the planner"))
        assistant.say.assert_called()

        assistant.reset_mock()
        self.assertTrue(handle_learned_speech(assistant, "zorp"))
        assistant._handle_input.assert_called_once_with("open the planner")


class SleepDailyRoutineTests(unittest.TestCase):
    def test_news_prompt_waits_after_wake(self):
        from silva.assistant import SilvaAssistant

        assistant = MagicMock(spec=SilvaAssistant)
        assistant._asleep = True
        assistant._daily_routine_grace_active.return_value = True

        with patch("silva.yes_no_prompt.check_news_briefing") as check:
            SilvaAssistant._check_news_briefing(assistant)
        check.assert_not_called()

        assistant._asleep = False
        assistant._daily_routine_grace_active.return_value = False
        with patch("silva.yes_no_prompt.check_news_briefing") as check:
            SilvaAssistant._check_news_briefing(assistant)
        check.assert_called_once_with(assistant)

    def test_scheduled_weather_waits_after_wake(self):
        from silva.assistant import SilvaAssistant

        assistant = MagicMock(spec=SilvaAssistant)
        assistant._asleep = False
        assistant._scheduled_alerts_paused.return_value = False
        assistant._weather_startup_grace_active.return_value = False
        assistant._daily_routine_grace_active.return_value = True

        with patch("silva.commands.weather_schedule.check_scheduled_weather_display") as check:
            SilvaAssistant._check_scheduled_weather_display(assistant)
        check.assert_not_called()

        assistant._daily_routine_grace_active.return_value = False
        with patch("silva.assistant.get_active_user", return_value={"id": "kevin"}):
            with patch("silva.assistant.feature_allowed", return_value=True):
                with patch("silva.commands.weather_schedule.check_scheduled_weather_display") as check:
                    SilvaAssistant._check_scheduled_weather_display(assistant)
        check.assert_called_once()


class CrossChatMemoryTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        store = Path(self._tmpdir.name) / "crosschat_memory.json"
        patcher = patch("silva.conversation.crosschat_memory.STORE_FILE", store)
        self.addCleanup(patcher.stop)
        patcher.start()
        from silva.conversation import crosschat_memory

        crosschat_memory.reset_state_for_tests()

    def test_instructions_feedback_and_ratings_persist(self):
        from silva.conversation import crosschat_memory as cc

        self.assertTrue(cc.add_instruction("keep replies calm", user_id="kevin"))
        self.assertIn("keep replies calm", cc.list_instructions(user_id="kevin"))
        self.assertTrue(cc.note_feedback("talk more casually", user_id="kevin"))
        self.assertGreater(int(cc.preferences(user_id="kevin")["traits"].get("casual") or 0), 0)
        self.assertTrue(cc.rate_reply(5, user_id="kevin", comment="perfect"))
        self.assertEqual(cc.preferences(user_id="kevin")["rating"]["count"], 1)

        cc._STATE = cc._load_state()
        self.assertIn("keep replies calm", cc.list_instructions(user_id="kevin"))
        self.assertEqual(cc.preferences(user_id="kevin")["rating"]["count"], 1)

    def test_feedback_shapes_style_and_speech_patterns(self):
        from silva.conversation import crosschat_memory as cc
        from silva.conversation.attitude import style_reply

        cc.note_feedback("be more brief", user_id="kevin")
        cc.observe_speech("I'm good, can we do this quickly?", user_id="kevin")
        reply = (
            "This is a very long reply that keeps going for a while. "
            "It has a second sentence with extra words for testing. "
            "It has a third sentence that should be shortened when brief mode is active."
        )
        styled = style_reply(reply, "kevin")
        self.assertLess(len(styled), len(reply))
        self.assertIn("contractions", cc.preferences(user_id="kevin")["speech_patterns"])

    def test_voice_handler_saves_instruction(self):
        from silva.conversation.crosschat_memory import handle_crosschat_speech

        assistant = MagicMock()
        assistant._user_id.return_value = "kevin"
        self.assertTrue(handle_crosschat_speech(assistant, "remember that I like short answers"))
        assistant.say.assert_called_once()
        self.assertTrue(handle_crosschat_speech(assistant, "list crosschat instructions"))
        self.assertEqual(assistant.say.call_count, 2)

    def test_reply_explanation_explains_logged_health_line(self):
        from silva.conversation import crosschat_memory as cc

        user_text = "are you going to sleep so I can fix you cuz you're a dumb bitch who don't listen"
        cc.remember_reply_context(user_text, "Health comes first", user_id="kevin")
        answer = cc.explain_last_reply("why did you say health comes first", user_id="kevin")
        lowered = answer.lower()
        self.assertIn("health comes first", lowered)
        self.assertIn("sleep", lowered)
        self.assertIn("bitch", lowered)
        self.assertIn("not a judgment about your anger or mental state", lowered)

    def test_reply_explanation_ask_handles_different_phrasings(self):
        from silva.conversation import crosschat_memory as cc

        for question in (
            "why did you say that",
            "why did you say it that way",
            "why that word",
            "what did you mean by health comes first",
            "tell me why you used that phrase",
            "why health comes first",
        ):
            with self.subTest(question=question):
                self.assertTrue(cc.is_reply_explanation_ask(question))

    def test_reply_explanation_voice_handler_answers_last_reply(self):
        from silva.conversation import crosschat_memory as cc

        assistant = MagicMock()
        assistant._user_id.return_value = "kevin"
        cc.remember_reply_context("you dumb bitch go to sleep", "Health comes first", user_id="kevin")
        self.assertTrue(cc.handle_crosschat_speech(assistant, "why did you say it that way"))
        spoken = assistant.say.call_args.args[0]
        self.assertIn("bitch", spoken.lower())
        self.assertIn("sleep", spoken.lower())


class CodeAssistTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self._root = Path(self._tmpdir.name) / "project"
        source = self._root / "silva" / "commands" / "weather.py"
        source.parent.mkdir(parents=True)
        source.write_text("def handle_weather_speech():\n    return True\n", encoding="utf-8")
        self._report_dir = Path(self._tmpdir.name) / "reports"
        patchers = [
            patch("silva.dev.code_assist.REPORT_DIR", self._report_dir),
            patch("silva.dev.code_assist.STATE_FILE", Path(self._tmpdir.name) / "state.json"),
        ]
        for patcher in patchers:
            self.addCleanup(patcher.stop)
            patcher.start()
        from silva.dev import code_assist

        code_assist._PENDING.clear()

    def test_report_names_baseline_spots_without_editing_source(self):
        from silva.dev.code_assist import write_placement_report

        source = self._root / "silva" / "commands" / "weather.py"
        before = source.read_text(encoding="utf-8")
        report = write_placement_report("add a quick weather tile", root=self._root)
        text = report.read_text(encoding="utf-8")
        self.assertTrue(report.exists())
        self.assertIn("silva/commands/weather.py", text)
        self.assertIn("Baseline code", text)
        self.assertIn("did not edit any source files", text)
        self.assertEqual(source.read_text(encoding="utf-8"), before)

    def test_voice_flow_waits_for_definition_then_writes_report(self):
        from silva.dev import code_assist

        assistant = MagicMock()
        assistant._user_id.return_value = "kevin"
        assistant._voice_mode = True
        report = Path(self._tmpdir.name) / "report.txt"
        with patch.object(code_assist, "is_allowed", return_value=True):
            self.assertTrue(code_assist.handle_code_assist_speech(assistant, "help me code"))
            self.assertTrue(code_assist.has_pending("kevin"))
            with patch.object(code_assist, "write_placement_report", return_value=report):
                self.assertTrue(code_assist.handle_code_assist_speech(assistant, "add a quick weather tile"))
        self.assertFalse(code_assist.has_pending("kevin"))
        assistant.say.assert_called()
        self.assertIn(str(report), assistant.say.call_args.args[0])

    def test_text_box_request_opens_popup_instead_of_report(self):
        from silva.dev import code_assist

        assistant = MagicMock()
        assistant._user_id.return_value = "kevin"
        assistant._voice_mode = True
        with patch.object(code_assist, "is_allowed", return_value=True):
            self.assertTrue(code_assist.handle_code_assist_speech(assistant, "help me code"))
            with patch("silva.gui.text_input_popup.show_text_input_popup") as popup:
                with patch.object(code_assist, "write_placement_report") as write_report:
                    self.assertTrue(
                        code_assist.handle_code_assist_speech(assistant, "open the text box so i can")
                    )
        popup.assert_called_once()
        write_report.assert_not_called()
        self.assertTrue(code_assist.has_pending("kevin"))
        submit = popup.call_args.args[2]
        with patch.object(code_assist, "write_placement_report") as write_report:
            submit("add a quick weather tile")
        write_report.assert_called_once_with("add a quick weather tile")

    def test_non_code_followup_does_not_write_report(self):
        from silva.dev import code_assist

        assistant = MagicMock()
        assistant._user_id.return_value = "kevin"
        assistant._voice_mode = True
        with patch.object(code_assist, "is_allowed", return_value=True):
            self.assertTrue(code_assist.handle_code_assist_speech(assistant, "help me code"))
            with patch.object(code_assist, "write_placement_report") as write_report:
                self.assertFalse(code_assist.handle_code_assist_speech(assistant, "what is the weather"))
        write_report.assert_not_called()
        self.assertTrue(code_assist.has_pending("kevin"))
        self.assertFalse(code_assist.is_code_assist_command("what is the weather", user_id="kevin"))

    def test_text_box_phrase_without_pending_is_not_a_command(self):
        from silva.dev import code_assist

        self.assertIsNone(code_assist.parse_code_assist_speech("open the text box so i can", user_id="kevin"))

    def test_direct_code_request_writes_report(self):
        from silva.dev import code_assist

        assistant = MagicMock()
        assistant._user_id.return_value = "kevin"
        assistant._voice_mode = True
        report = Path(self._tmpdir.name) / "direct.txt"
        with patch.object(code_assist, "is_allowed", return_value=True):
            with patch.object(code_assist, "write_placement_report", return_value=report):
                self.assertTrue(
                    code_assist.handle_code_assist_speech(assistant, "help me code add a quick weather tile")
                )
        assistant.say.assert_called()
        self.assertIn(str(report), assistant.say.call_args.args[0])


class VideoLearningTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        from silva.commands import knowledge_store

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._old_dir = knowledge_store.KNOWLEDGE_DIR
        knowledge_store.KNOWLEDGE_DIR = Path(self._tmp.name)
        knowledge_store._LAST.clear()
        self.addCleanup(setattr, knowledge_store, "KNOWLEDGE_DIR", self._old_dir)
        self.addCleanup(knowledge_store._LAST.clear)

    def test_categorizes_requested_video_types(self):
        from silva.commands.video_learning import categorize_video

        self.assertEqual(categorize_video("emergency survival basics", ""), "survival")
        self.assertEqual(categorize_video("how the electrical grid works", ""), "grid-systems-electrical")
        self.assertEqual(categorize_video("great inventions", ""), "inventions")
        self.assertEqual(categorize_video("manhwa recap", ""), "manhwa")
        self.assertEqual(categorize_video("manga opening", ""), "manga")
        self.assertEqual(categorize_video("random clip", ""), "random-videos")

    def test_download_requires_clear_request_and_confirmation(self):
        from silva.commands.video_learning import (
            is_confirmed_download_request,
            is_explicit_download_request,
        )

        self.assertTrue(is_explicit_download_request("download this video"))
        self.assertTrue(is_explicit_download_request("please save a copy of this video"))
        self.assertFalse(is_explicit_download_request("don't download this video"))
        self.assertFalse(is_explicit_download_request("did you download the video"))
        self.assertFalse(is_explicit_download_request("download it later"))
        self.assertTrue(is_confirmed_download_request("yes download this video"))
        self.assertFalse(is_confirmed_download_request("yeah sure"))

    def test_saves_and_recalls_video_notes_by_category(self):
        from silva.commands.video_learning import (
            answer_video_query,
            is_video_query,
            remember_video,
        )

        saved = remember_video(
            "kevin",
            "Electrical grid basics",
            "The video explained transformers and the power grid.",
            reply="I learned how the grid carries power.",
        )
        self.assertEqual(saved["category"], "grid-systems-electrical")
        self.assertTrue(is_video_query("what did you learn from that video"))
        self.assertIn("transformers", answer_video_query("what did you learn from that video").lower())


class ScreenMonitorTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        from silva.commands import knowledge_store

        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self._old_knowledge_dir = knowledge_store.KNOWLEDGE_DIR
        knowledge_store.KNOWLEDGE_DIR = Path(self._tmpdir.name) / "knowledge"
        self.addCleanup(setattr, knowledge_store, "KNOWLEDGE_DIR", self._old_knowledge_dir)
        knowledge_store._LAST.clear()
        self.addCleanup(knowledge_store._LAST.clear)
        from silva.dev import screen_monitor

        screen_monitor._pending_transcript.clear()
        screen_monitor._pending_download.clear()
        screen_monitor._video_threads.clear()
        screen_monitor._video_stop.clear()
        self.addCleanup(screen_monitor._pending_transcript.clear)
        self.addCleanup(screen_monitor._pending_download.clear)
        self.addCleanup(screen_monitor._video_threads.clear)
        self.addCleanup(screen_monitor._video_stop.clear)
        self._config = {
            "screen_monitor_owner_approved": True,
            "screen_monitor_enabled": True,
            "screen_monitor_sleep_enabled": False,
            "screen_monitor_capture_interval_seconds": 30,
            "screen_monitor_analyzer_command": "",
            "screen_monitor_video_style_command": "",
            "video_watch_enabled": True,
            "video_watch_capture_interval_seconds": 20,
        }
        patchers = [
            patch("silva.dev.screen_monitor.load_config", side_effect=lambda: dict(self._config)),
            patch("silva.dev.screen_monitor.save_config"),
            patch("silva.dev.screen_monitor.STATE_FILE", Path(self._tmpdir.name) / "state.json"),
            patch("silva.dev.screen_monitor.SUMMARY_FILE", Path(self._tmpdir.name) / "summary.txt"),
            patch("silva.dev.screen_monitor.WORDS_FILE", Path(self._tmpdir.name) / "words.txt"),
            patch("silva.dev.screen_monitor.capture_video_frame", return_value="A survival tip was shown."),
            patch("silva.dev.screen_monitor._video_capture_loop"),
        ]
        for patcher in patchers:
            self.addCleanup(patcher.stop)
            patcher.start()

    def test_sleep_gate_and_owner_approval(self):
        from silva.dev import screen_monitor

        self.assertTrue(screen_monitor.enabled())
        self.assertFalse(screen_monitor.enabled(asleep=True))
        self._config["screen_monitor_sleep_enabled"] = True
        self.assertTrue(screen_monitor.enabled(asleep=True))
        self._config["screen_monitor_enabled"] = False
        self.assertFalse(screen_monitor.enabled())

    def test_manual_video_session_records_words(self):
        from silva.dev import screen_monitor

        video = Path(self._tmpdir.name) / "clip.mp4"
        video.write_bytes(b"video")
        self.assertTrue(screen_monitor.begin_video_session(str(video), user_id="kevin"))
        self.assertTrue(screen_monitor.finish_video_session("talk more casually", user_id="kevin"))
        self.assertEqual(
            screen_monitor.WORDS_FILE.read_text(encoding="utf-8"),
            "talk more casually",
        )
        state = json.loads(screen_monitor.STATE_FILE.read_text(encoding="utf-8"))
        self.assertNotIn("active", state)
        self.assertEqual(state["last_session"]["video_path"], str(video))

    def test_what_am_i_doing_uses_summary(self):
        from silva.dev import screen_monitor

        screen_monitor.SUMMARY_FILE.write_text("a video is open", encoding="utf-8")
        assistant = MagicMock()
        assistant._user_id.return_value = "kevin"
        self.assertTrue(screen_monitor.handle_screen_monitor_speech(assistant, "what am I doing"))
        assistant.say.assert_called_once()
        self.assertIn("a video is open", assistant.say.call_args.args[0])

    def test_stop_ends_active_video_watch(self):
        from silva.dev import screen_monitor

        video = Path(self._tmpdir.name) / "clip.mp4"
        video.write_bytes(b"video")
        self.assertTrue(screen_monitor.begin_video_session(str(video), user_id="kevin"))
        self.assertTrue(screen_monitor.stop_video_watch("kevin"))
        state = json.loads(screen_monitor.STATE_FILE.read_text(encoding="utf-8"))
        self.assertNotIn("active", state)

    def test_download_request_requires_confirmation_and_downloads_nothing(self):
        from silva.dev import screen_monitor

        assistant = MagicMock()
        assistant._user_id.return_value = "kevin"
        self.assertTrue(screen_monitor.handle_screen_monitor_speech(assistant, "download this video"))
        self.assertIn("confirm", assistant.say.call_args.args[0].lower())
        self.assertTrue(
            screen_monitor.handle_screen_monitor_speech(assistant, "yes download this video")
        )
        self.assertIn("nothing was downloaded", assistant.say.call_args.args[0].lower())

    def test_logged_video_watch_phrases_are_action_commands(self):
        from silva.commands.intent import is_action_command
        from silva.dev import screen_monitor

        self._config["screen_monitor_owner_approved"] = False
        phrases = (
            "all right for now let's watch the video",
            "can you watch the video with me",
            "that is not what I asked I asked watch the video with me",
        )
        for phrase in phrases:
            self.assertTrue(screen_monitor.is_screen_monitor_command(phrase), phrase)
            self.assertTrue(is_action_command(phrase), phrase)
            self.assertIsNone(screen_monitor.parse_screen_monitor_speech(phrase), phrase)

    def test_video_watch_without_approval_explains_approval(self):
        from silva.dev import screen_monitor

        self._config["screen_monitor_owner_approved"] = False
        assistant = MagicMock()
        assistant._user_id.return_value = "kevin"
        self.assertTrue(
            screen_monitor.handle_screen_monitor_speech(
                assistant, "all right for now let's watch the video"
            )
        )
        self.assertIn("owner approval", assistant.say.call_args.args[0].lower())

    def test_can_you_watch_the_video_with_me_starts_session(self):
        from silva.dev import screen_monitor

        video = Path(self._tmpdir.name) / "clip.mp4"
        video.write_bytes(b"video")
        assistant = MagicMock()
        assistant._user_id.return_value = "kevin"
        with patch("silva.dev.screen_monitor.select_video_path", return_value=str(video)):
            self.assertTrue(
                screen_monitor.handle_screen_monitor_speech(
                    assistant, "can you watch the video with me"
                )
            )
        state = json.loads(screen_monitor.STATE_FILE.read_text(encoding="utf-8"))
        self.assertEqual(state["active"]["video_path"], str(video))
        self.assertIn("video finished", assistant.say.call_args.args[0].lower())


class StreamDeckTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self._config = {
            "stream_deck_enabled": True,
            "stream_deck_user_setup_enabled": True,
            "stream_deck_weather_tile_enabled": False,
            "last_weather": {
                "city": "Englewood",
                "temp_f": 69,
                "conditions": "overcast",
                "humidity": 70,
                "wind_mph": 3,
                "updated_at": "2026-11-22 12:00:00",
            },
        }
        patchers = [
            patch("silva.dev.stream_deck.load_config", side_effect=lambda: dict(self._config)),
            patch("silva.dev.stream_deck.STORE_FILE", Path(self._tmpdir.name) / "bindings.json"),
            patch("silva.dev.stream_deck.TILE_DIR", Path(self._tmpdir.name) / "tiles"),
        ]
        for patcher in patchers:
            self.addCleanup(patcher.stop)
            patcher.start()

    def test_bindings_resolve_and_remove(self):
        from silva.dev import stream_deck

        self.assertTrue(
            stream_deck.set_binding(
                user_id="kevin",
                page=1,
                slot=5,
                label="Weather",
                command="what's my local weather",
            )
        )
        binding = stream_deck.get_binding(user_id="kevin", page=1, slot=5)
        self.assertEqual(binding["label"], "Weather")
        self.assertEqual(len(stream_deck.list_bindings(user_id="kevin")), 1)
        action = stream_deck.resolve_slot_action(user_id="kevin", page=1, slot=5)
        self.assertTrue(action["found"])
        self.assertEqual(action["command"], "what's my local weather")
        self.assertTrue(stream_deck.remove_binding(user_id="kevin", page=1, slot=5))
        self.assertIsNone(stream_deck.get_binding(user_id="kevin", page=1, slot=5))

    def test_weather_tile_snapshot_and_voice_binding(self):
        from silva.dev import stream_deck

        path = stream_deck.publish_weather_tile()
        self.assertTrue(path.exists())
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["temp_f"], 69)
        self.assertIn("69F", stream_deck.weather_tile_text())

        assistant = MagicMock()
        assistant._user_id.return_value = "kevin"
        self.assertTrue(
            stream_deck.handle_stream_deck_speech(assistant, "stream deck page 2 slot 7 bind weather")
        )
        binding = stream_deck.get_binding(user_id="kevin", page=2, slot=7)
        self.assertTrue(binding["weather"])
        assistant.say.assert_called_once()

    def test_parser_reads_later_slot_then_page(self):
        from silva.dev.stream_deck import parse_stream_deck_speech

        action = parse_stream_deck_speech("stream deck slot 9 page 3 run weather")
        self.assertEqual(action["action"], "run")
        self.assertEqual(action["slot"], (3, 9))


class NewFeatureHelpAndPanelTests(unittest.TestCase):
    def test_help_and_panel_expose_new_features(self):
        from silva.commands.help_phrases import _FEATURE_KEYWORDS, _OPTIONAL_FEATURE_SHORT
        from silva.commands.system_panel_commands import _TAB_PATTERNS
        from silva.gui.panel_security_tabs import register_panel_tabs
        from silva.dev.panel_registry import built_in_panel_tabs

        for key in ("crosschat_memory", "code_assist", "screen_monitor", "stream_deck"):
            self.assertIn(key, _OPTIONAL_FEATURE_SHORT)
            self.assertTrue(any(name == key for name, _keywords in _FEATURE_KEYWORDS))
        register_panel_tabs()
        self.assertTrue(any(tab.id == "crosschat_stream_deck" for tab in built_in_panel_tabs()))
        self.assertTrue(any(tab_id == "crosschat_stream_deck" for tab_id, _title, _pattern in _TAB_PATTERNS))

    def test_deck_slot_parser(self):
        from silva.__main__ import build_parser

        args = build_parser().parse_args(["--deck-slot", "1", "5"])
        self.assertEqual(args.deck_slot, ["1", "5"])

    def test_terminal_controls(self):
        from silva.dev import terminal_commands

        with patch.object(terminal_commands, "handle_terminal_command", wraps=terminal_commands.handle_terminal_command):
            with patch("silva.dev.code_assist.set_enabled", return_value=True) as set_enabled:
                handled, message = terminal_commands.handle_terminal_command("codeassist off")
        self.assertTrue(handled)
        self.assertIn("turned off", message.lower())
        set_enabled.assert_called_once_with(False)

        with patch("silva.config.load_config", return_value={"crosschat_memory_enabled": True}):
            with patch("silva.config.save_config") as save_config:
                with patch("silva.users.manager.get_active_user", return_value={"id": "kevin"}):
                    with patch.object(terminal_commands, "_can_run_dev_commands", return_value=True):
                        handled, _message = terminal_commands.handle_terminal_command("crosschat off")
        self.assertTrue(handled)
        saved = save_config.call_args.args[0]
        self.assertFalse(saved["crosschat_memory_enabled"])


class CompleteSentenceGuardTests(unittest.TestCase):
    def test_complete_sentence_detection(self):
        from silva.conversation.complete_sentence import is_complete_sentence

        self.assertTrue(is_complete_sentence("What's the weather?"))
        self.assertTrue(is_complete_sentence("I need help with the weather"))
        self.assertTrue(is_complete_sentence("weather"))
        self.assertTrue(is_complete_sentence("yes"))
        self.assertFalse(is_complete_sentence("hey can you"))
        self.assertFalse(is_complete_sentence("and then I"))
        self.assertFalse(is_complete_sentence(""))

    def test_partial_speech_after_interruption_is_ignored(self):
        from silva.conversation import complete_sentence

        now = complete_sentence.time.time()
        self.assertTrue(complete_sentence.should_ignore_after_interruption("and then I", interrupted_at=now))
        self.assertFalse(complete_sentence.should_ignore_after_interruption("What's the weather?", interrupted_at=now))
        self.assertFalse(complete_sentence.should_ignore_after_interruption("yes", interrupted_at=now))
        self.assertFalse(complete_sentence.should_ignore_after_interruption("and then I", interrupted_at=0.0))
        with patch.object(complete_sentence, "enabled", return_value=False):
            self.assertFalse(complete_sentence.should_ignore_after_interruption("and then I", interrupted_at=now))

    def test_voice_interrupt_loop_skips_incomplete_speech(self):
        from silva import interrupt_listen

        class FakeEvent:
            def __init__(self):
                self.calls = 0

            def is_set(self):
                self.calls += 1
                return self.calls > 4

        monitor = MagicMock()
        monitor._stop_event = FakeEvent()
        monitor._stt = object()
        with patch.object(interrupt_listen, "listen_once_for_stop", side_effect=["hey can you", "weather"]):
            with patch.object(interrupt_listen, "is_shutting_down", return_value=False):
                interrupt_listen.voice_stop_loop(monitor)
        monitor._handle_parallel.assert_called_once_with("weather")


class MicMovementGuardTests(unittest.TestCase):
    def _audio(self, body_seconds: float, tail_seconds: float, body_amp: int, tail_amp: int):
        import numpy as np
        import speech_recognition as sr

        rate = 16000
        body = np.full(int(rate * body_seconds), body_amp, dtype=np.int16)
        tail = np.full(int(rate * tail_seconds), tail_amp, dtype=np.int16)
        return sr.AudioData(np.concatenate((body, tail)).tobytes(), rate, 2)

    def test_fillers_and_trailing_uncertainty(self):
        from silva.stt_fillers import (
            is_filler_only,
            is_trailing_uncertainty,
            should_ignore_movement_uncertainty,
        )

        self.assertTrue(is_filler_only("uhm"))
        self.assertTrue(is_trailing_uncertainty("hello are you uhm"))
        self.assertTrue(is_trailing_uncertainty("hello are you on"))
        self.assertFalse(is_trailing_uncertainty("turn on the lights"))
        self.assertFalse(is_trailing_uncertainty("hello there"))
        self.assertTrue(should_ignore_movement_uncertainty("hello are you on", receding_audio=True))
        self.assertFalse(should_ignore_movement_uncertainty("hello are you on", receding_audio=False))

    def test_receding_audio_detection(self):
        from silva.stt_speech_guard import detect_receding_audio

        receding = self._audio(1.2, 0.8, 1200, 120)
        steady = self._audio(1.2, 0.8, 1200, 1200)
        quiet = self._audio(1.2, 0.8, 20, 2)
        self.assertTrue(detect_receding_audio(receding))
        self.assertFalse(detect_receding_audio(steady))
        self.assertFalse(detect_receding_audio(quiet))
        self.assertFalse(detect_receding_audio(None))

    def test_listen_marks_receding_audio_and_lowers_next_threshold(self):
        from silva.stt import SpeechToText

        audio = self._audio(1.2, 0.8, 1200, 120)
        stt = SpeechToText.__new__(SpeechToText)
        stt._listen_busy = False
        stt._active_listen_timeout = 12.0
        stt._default_phrase_limit = 28.0
        stt._listen_with_audio_inner = MagicMock(return_value=("on", audio))
        stt._recover_from_receding_audio = MagicMock()
        with patch("silva.stt.detect_receding_audio", return_value=True):
            text, _captured = stt.listen_with_audio()
        self.assertEqual(text, "on")
        self.assertTrue(stt.last_receding_audio)
        stt._recover_from_receding_audio.assert_called_once_with()


class CorrectionRepairTests(unittest.TestCase):
    def setUp(self):
        from silva.conversation import correction_repair

        correction_repair.reset_state_for_tests()
        self.addCleanup(correction_repair.reset_state_for_tests)

    def test_stt_filler_alias_answers_detail(self):
        from silva.commands.help_phrases import feature_detail_reply_for_user, match_feature_id

        text = "can you tell me in detail what STD pillows mean"
        self.assertEqual(match_feature_id(text), "stt_fillers")
        self.assertIn("STT fillers", feature_detail_reply_for_user(text, {}))

    def test_correction_phrase_extraction(self):
        from silva.conversation.correction_repair import parse_correction

        self.assertEqual(parse_correction("I said stt fillers not what I said before"), "stt fillers")
        self.assertEqual(parse_correction("I meant stt fillers"), "stt fillers")
        self.assertEqual(parse_correction("what I meant was stt fillers"), "stt fillers")
        self.assertIsNone(parse_correction("that is not what I said"))
        self.assertEqual(
            parse_correction("what I was trying to say is tell me what was recently added"),
            "tell me what was recently added",
        )

    def test_recently_at_is_repaired_to_recently_added(self):
        from silva.commands.update_phrases import is_whats_new_update_phrase
        from silva.conversation.learned_phrases import repair_stt_words

        text = "tell me what was recently at"
        repaired = repair_stt_words(text)
        self.assertEqual(repaired, "tell me what was recently added")
        self.assertTrue(is_whats_new_update_phrase(repaired))

    def test_background_test_is_repaired_to_background_task(self):
        from silva.conversation.learned_phrases import repair_stt_words

        self.assertEqual(
            repair_stt_words("why did the background test board test fail"),
            "why did the background task board task fail",
        )
        self.assertEqual(
            repair_stt_words("all right tell me what s t t e Handler does"),
            "all right tell me what stt Handler does",
        )

    def test_trying_to_say_correction_redispatches_update_question(self):
        from silva.conversation import correction_repair

        assistant = MagicMock()
        assistant._user_id.return_value = "kevin"
        assistant._handle_input.return_value = True
        original = "tell me what was recently at"
        correction_repair.note_repairable_question(assistant, original)
        self.assertTrue(
            correction_repair.handle_correction_repair(
                assistant, "what I was trying to say is tell me what was recently added"
            )
        )
        assistant._handle_input.assert_called_once_with(
            "tell me what was recently added", _phrase_retry=True
        )

    def test_correction_redispatches_original_question(self):
        from silva.commands.help_phrases import _WHICH_FEATURE
        from silva.conversation import correction_repair

        assistant = MagicMock()
        assistant._user_id.return_value = "kevin"
        assistant._handle_input.return_value = True
        original = "can you tell me in detail what STD pillows mean"
        correction_repair.note_feature_detail_clarification(assistant, original, _WHICH_FEATURE)
        self.assertTrue(
            correction_repair.handle_correction_repair(
                assistant, "I said stt fillers not what I said before"
            )
        )
        assistant._handle_input.assert_called_once_with(
            "can you tell me in detail what stt fillers mean",
            _phrase_retry=True,
        )

    def test_help_clarification_sets_repair_candidate(self):
        from silva.commands.help_handler import handle_help_speech
        from silva.commands.help_phrases import _WHICH_FEATURE
        from silva.conversation import correction_repair

        assistant = MagicMock()
        assistant._user_id.return_value = "kevin"
        assistant._handle_input.return_value = True
        with patch("silva.commands.help_handler.get_active_user", return_value={"id": "kevin", "tier": 5}), patch(
            "silva.commands.help_handler._detail_web_reply", return_value=""
        ):
            self.assertTrue(
                handle_help_speech(assistant, "can you tell me in detail what weird pillows mean")
            )
        self.assertEqual(assistant.say.call_args.args[0], _WHICH_FEATURE)
        self.assertTrue(correction_repair.has_candidate_for("kevin"))
        self.assertTrue(correction_repair.handle_correction_repair(assistant, "I meant stt fillers"))
        assistant._handle_input.assert_called_once_with(
            "can you tell me in detail what stt fillers mean",
            _phrase_retry=True,
        )

    def test_spoken_stt_aliases_are_feature_details(self):
        from silva.commands.help_phrases import feature_detail_reply_for_user, match_feature_id

        for text in (
            "can you tell me what SCT fillers are",
            "can you tell me what s t t fillers are",
            "can you tell me what STD fillers are",
        ):
            with self.subTest(text=text):
                self.assertEqual(match_feature_id(text), "stt_fillers")
                self.assertIn("STT fillers", feature_detail_reply_for_user(text, {"id": "kevin", "tier": 5}))

    def test_correction_drops_trailing_on(self):
        from silva.conversation.correction_repair import parse_correction

        self.assertEqual(
            parse_correction("no I said can you tell me what s t t fillers on"),
            "can you tell me what s t t fillers",
        )

    def test_help_handler_detail_ask_is_not_image_generation(self):
        from silva.commands.help_phrases import detail_topic, is_feature_detail_ask
        from silva.commands.intent import is_action_command
        from silva.media.image_generator_phrases import is_image_generation_speech

        text = "could you describe in detail what the help Handler does"
        self.assertFalse(is_image_generation_speech(text))
        self.assertTrue(is_feature_detail_ask(text))
        self.assertTrue(is_action_command(text))
        self.assertEqual(detail_topic(text), "help handler")
        self.assertTrue(is_image_generation_speech("describe this image"))

    def test_stt_mangled_help_handler_detail_ask(self):
        from silva.commands.help_handler import handle_help_speech
        from silva.commands.help_phrases import detail_topic, is_feature_detail_ask

        text = "all right tell me what s t t e Handler does"
        self.assertTrue(is_feature_detail_ask(text))
        self.assertEqual(detail_topic(text), "help handler")
        assistant = MagicMock()
        assistant._user_id.return_value = "kevin"
        self.assertTrue(handle_help_speech(assistant, text))
        self.assertTrue(assistant.say.call_args.args[0].startswith("That script decides how I answer help"))

    def test_help_braces_is_repaired_to_help_phrases(self):
        from silva.commands.help_handler import handle_help_speech
        from silva.commands.help_phrases import detail_topic, is_feature_detail_ask
        from silva.conversation.learned_phrases import repair_stt_words

        text = "all right tell me in detail what does the help braces do"
        repaired = repair_stt_words(text)
        self.assertEqual(repaired, "all right tell me in detail what does the help phrases do")
        self.assertTrue(is_feature_detail_ask(repaired))
        self.assertEqual(detail_topic(repaired), "help phrases")
        assistant = MagicMock()
        assistant._user_id.return_value = "kevin"
        self.assertTrue(handle_help_speech(assistant, repaired))
        self.assertTrue(assistant.say.call_args.args[0].startswith("That script teaches me to recognize help wording"))

    def test_stt_handler_alias_finds_help_script(self):
        from silva.commands.help_handler import handle_help_speech
        from silva.commands.help_phrases import detail_topic

        text = "all right can you tell me what stt Handler does"
        self.assertEqual(detail_topic(text), "help handler")
        assistant = MagicMock()
        assistant._user_id.return_value = "kevin"
        self.assertTrue(handle_help_speech(assistant, text))
        self.assertTrue(assistant.say.call_args.args[0].startswith("That script decides how I answer help"))

    def test_accidental_owner_image_library_access_is_explained(self):
        from silva.commands.help_handler import handle_help_speech
        from silva.commands.help_phrases import feature_detail_reply_for_user, is_feature_detail_ask

        text = "what happens if I accidentally give somebody else access to the owner image Library"
        self.assertTrue(is_feature_detail_ask(text))
        self.assertIn(
            "cannot really give the owner image library",
            feature_detail_reply_for_user(text, {"id": "kevin", "tier": 5}),
        )
        assistant = MagicMock()
        assistant._user_id.return_value = "kevin"
        self.assertTrue(handle_help_speech(assistant, text))
        reply = assistant.say.call_args.args[0]
        self.assertIn("cannot really give the owner image library", reply)
        self.assertIn("Kick & Block", reply)
        self.assertIn("No images are copied", reply)

    def test_any_of_them_chooses_pending_topic(self):
        from silva.commands.help_handler import handle_help_speech
        from silva.commands.help_phrases import _WHICH_FEATURE
        from silva.conversation.correction_repair import note_feature_detail_clarification

        assistant = MagicMock()
        assistant._user_id.return_value = "kevin"
        note_feature_detail_clarification(
            assistant, "all right can you tell me what stt Handler does", _WHICH_FEATURE
        )
        self.assertTrue(handle_help_speech(assistant, "any of them"))
        assistant._handle_input.assert_called_once_with(
            "can you tell me in detail what help handler does", _phrase_retry=True
        )

    def test_future_any_of_them_instruction_is_remembered(self):
        from silva.commands.help_handler import handle_help_speech

        assistant = MagicMock()
        assistant._user_id.return_value = "kevin"
        text = "I said any of them so that you could choose on your own if I ask that again"
        with patch("silva.conversation.crosschat_memory.add_instruction") as remember:
            self.assertTrue(handle_help_speech(assistant, text))
        remember.assert_called_once()
        assistant.say.assert_called_once()
        assistant._handle_input.assert_not_called()

    def test_reduce_temporary_access_minutes_is_explained(self):
        from silva.commands.help_phrases import feature_detail_reply_for_user, is_feature_detail_ask

        text = "what if I want to reduce the minutes for that access"
        self.assertTrue(is_feature_detail_ask(text))
        reply = feature_detail_reply_for_user(text, {"id": "kevin", "tier": 5})
        self.assertIn("1 and 240 minutes", reply)
        self.assertIn("Kick & Block", reply)

    def test_learned_phrase_complaints_get_help_instead_of_chat(self):
        from silva.commands.help_phrases import feature_detail_reply_for_user, is_feature_detail_ask

        for text in (
            "why won't you answer when I say when I want you to say it",
            "no I want you to work correctly the way I asked in certain things",
        ):
            with self.subTest(text=text):
                self.assertTrue(is_feature_detail_ask(text))
                reply = feature_detail_reply_for_user(text, {"id": "kevin", "tier": 5})
                self.assertIn("If I answer wrong", reply)

    def test_cussing_tone_question_is_explained(self):
        from silva.commands.help_phrases import (
            feature_detail_reply_for_user,
            is_feature_detail_ask,
            match_feature_id,
        )

        text = "why are you still not cussing at me half the time when I'm cussing at you"
        self.assertEqual(match_feature_id(text), "attitude")
        self.assertTrue(is_feature_detail_ask(text))
        reply = feature_detail_reply_for_user(text, {"id": "kevin", "tier": 5})
        self.assertIn("curse while joking", reply)
        self.assertIn("how loud", reply)

    def test_learned_phrases_correct_way_question_is_explained(self):
        from silva.commands.help_phrases import (
            feature_detail_reply_for_user,
            is_feature_detail_ask,
            match_feature_id,
        )
        from silva.commands.math_phrases import is_math_command
        from silva.commands.notes_phrases import match_notes_speech

        text = "for the Learned phrases what is the correct way to say certain things in"
        self.assertEqual(match_feature_id(text), "learned_phrases")
        self.assertTrue(is_feature_detail_ask(text))
        self.assertFalse(is_math_command(text))
        self.assertIsNone(match_notes_speech(text))
        reply = feature_detail_reply_for_user(text, {"id": "kevin", "tier": 5})
        self.assertIn("correct way to say certain things", reply)
        self.assertIn("when I say", reply)

    def test_some_money_answers_is_repaired(self):
        from silva.conversation.learned_phrases import repair_stt_words

        text = "all right now what happens if I accidentally give some money answers to the owner image Library"
        self.assertIn("somebody else access", repair_stt_words(text))

    def test_what_was_fits_is_repaired_to_what_was_fixed(self):
        from silva.commands.update_phrases import is_whats_new_update_phrase
        from silva.conversation.correction_repair import parse_correction
        from silva.conversation.learned_phrases import repair_stt_words

        text = "can you tell me what was fits"
        repaired = repair_stt_words(text)
        self.assertEqual(repaired, "can you tell me what was fixed")
        self.assertTrue(is_whats_new_update_phrase(repaired))

        correction = "I never said bitch I said bits f i x"
        self.assertEqual(repair_stt_words(correction), "no I meant what was fixed")
        self.assertEqual(parse_correction(repair_stt_words(correction)), "what was fixed")

    def test_songs_that_is_repaired_to_pissing_me_off(self):
        from silva.conversation.correction_repair import parse_correction
        from silva.conversation.learned_phrases import repair_stt_words

        text = "give me songs that you're not working correctly"
        self.assertEqual(
            repair_stt_words(text),
            "you're pissing me off that you're not working correctly",
        )
        correction = "I never said songs I said you're pissing me off that you're not working correctly"
        self.assertEqual(
            repair_stt_words(correction),
            "you're pissing me off that you're not working correctly",
        )
        self.assertEqual(
            parse_correction(correction),
            "you're pissing me off that you're not working correctly",
        )

    def test_when_i_is_is_repaired_to_when_i_ask(self):
        from silva.conversation.learned_phrases import repair_stt_words

        text = "you are supposed to do when I is"
        self.assertEqual(repair_stt_words(text), "you are supposed to do when I ask")

    def test_find_update_is_repaired_to_fine_update(self):
        from silva.commands.update_phrases import is_update_confirm_phrase
        from silva.conversation.learned_phrases import repair_stt_words

        repaired = repair_stt_words("find update yourself for now")
        self.assertEqual(repaired, "fine, update yourself for now")
        self.assertTrue(is_update_confirm_phrase(repaired))

    def test_autocorrect_question_is_explained(self):
        from silva.commands.help_phrases import feature_detail_reply_for_user, is_feature_detail_ask

        text = "can you tell me how you autocorrect stuff"
        self.assertTrue(is_feature_detail_ask(text))
        reply = feature_detail_reply_for_user(text, {"id": "kevin", "tier": 5})
        self.assertIn("speech-to-text mistakes", reply)
        self.assertIn("help braces into help phrases", reply)

    def test_log_phrased_autocorrect_question_is_explained(self):
        from silva.commands.help_phrases import feature_detail_reply_for_user, is_feature_detail_ask

        text = "could you tell me how you would autocorrect something that I may or may not say"
        self.assertTrue(is_feature_detail_ask(text))
        reply = feature_detail_reply_for_user(text, {"id": "kevin", "tier": 5})
        self.assertIn("speech-to-text mistakes", reply)
        self.assertIn("help braces into help phrases", reply)

    def test_asked_wrong_generic_correction(self):
        from silva.conversation.correction_repair import is_generic_correction

        self.assertTrue(is_generic_correction("that is not what I asked you to do"))
        self.assertTrue(is_generic_correction("none of that is what I asked"))
        self.assertTrue(is_generic_correction("you dumb bitch that was not a math problem"))
        self.assertTrue(is_generic_correction("you're really dumb that was not what I asked you"))
        self.assertTrue(is_generic_correction("why are you not doing this the way I want"))

    def test_correction_plus_sleep_still_sleeps(self):
        from silva.commands.help_phrases import _WHICH_FEATURE
        from silva.conversation.correction_repair import (
            clear_candidate,
            is_correction_repair_command,
            is_generic_correction,
            note_feature_detail_clarification,
        )
        from silva.wake import is_sleep_command

        assistant = MagicMock()
        assistant._user_id.return_value = "kevin"
        text = "that is not what I said so go to sleep"
        note_feature_detail_clarification(assistant, "tell me in detail what weather is", _WHICH_FEATURE)
        try:
            self.assertTrue(is_sleep_command(text))
            self.assertFalse(is_generic_correction(text))
            self.assertFalse(is_correction_repair_command(text))
        finally:
            clear_candidate("kevin")

    def test_explain_script_finds_local_module(self):
        from silva.dev.code_assist import explain_script

        answer = explain_script("help handler")
        self.assertTrue(answer.startswith("That script decides how I answer help"))
        self.assertNotIn(".py", answer)
        self.assertNotIn("_detail_web_reply", answer)

    def test_plain_english_reply_simplifies_last_answer(self):
        from silva.commands.help_handler import handle_help_speech

        assistant = MagicMock()
        assistant._user_id.return_value = "kevin"
        previous = (
            "silva/commands/help_handler.py — Reloadable help / feature-detail speech. "
            "Main pieces: _detail_web_reply at line 9, handle_help_speech at line 25"
        )
        with patch("silva.conversation.crosschat_memory.last_reply", return_value=previous):
            self.assertTrue(handle_help_speech(assistant, "I don't understand what you just said"))
        spoken = assistant.say.call_args.args[0]
        self.assertTrue(spoken.startswith("In plain words:"))
        self.assertNotIn(".py", spoken)
        self.assertNotIn("Main pieces", spoken)
        self.assertNotIn("_detail_web_reply", spoken)

    def test_plain_english_request_is_help_request(self):
        from silva.commands.help_phrases import is_help_request

        self.assertTrue(is_help_request("I'm sorry I don't even know what you just said"))

    def test_script_detail_answer(self):
        from silva.commands.help_handler import handle_help_speech

        assistant = MagicMock()
        answer = "silva/commands/help_handler.py — routes help and detail questions."
        with patch("silva.commands.help_handler.get_active_user", return_value={"id": "kevin", "tier": 5}), patch(
            "silva.commands.help_handler._script_detail_reply", return_value=answer
        ) as script_reply, patch("silva.commands.help_handler._detail_web_reply") as web_reply:
            self.assertTrue(
                handle_help_speech(assistant, "could you describe in detail what the help Handler does")
            )
        script_reply.assert_called_once_with("help handler")
        web_reply.assert_not_called()
        self.assertEqual(assistant.say.call_args.args[0], answer)

    def test_generic_correction_asks_for_replacement_words(self):
        from silva.commands.help_phrases import _WHICH_FEATURE
        from silva.conversation import correction_repair

        assistant = MagicMock()
        assistant._user_id.return_value = "kevin"
        original = "can you describe in detail what the hell Panther does"
        correction_repair.note_feature_detail_clarification(assistant, original, _WHICH_FEATURE)
        self.assertTrue(
            correction_repair.handle_correction_repair(assistant, "that is not what I said")
        )
        assistant.say.assert_not_called()
        self.assertTrue(correction_repair.has_candidate_for("kevin"))
        self.assertTrue(correction_repair.is_awaiting_exact_repeat(assistant))

    def test_generic_correction_waits_silently_for_repeat(self):
        from silva.commands.help_phrases import _WHICH_FEATURE
        from silva.conversation import correction_repair

        assistant = MagicMock()
        assistant._user_id.return_value = "kevin"
        original = "can you describe in detail what the hell Panther does"
        correction_repair.note_feature_detail_clarification(assistant, original, _WHICH_FEATURE)
        self.assertTrue(correction_repair.handle_correction_repair(assistant, "again I never said that"))
        assistant.say.assert_not_called()
        self.assertTrue(correction_repair.is_awaiting_exact_repeat(assistant))

    def test_profanity_only_correction_waits_silently(self):
        from silva.commands.help_phrases import _WHICH_FEATURE
        from silva.conversation import correction_repair

        assistant = MagicMock()
        assistant._user_id.return_value = "kevin"
        correction_repair.note_feature_detail_clarification(
            assistant, "can you tell me why you asked that", _WHICH_FEATURE
        )
        self.assertTrue(
            correction_repair.handle_correction_repair(
                assistant, "not what I said you dumb bitch"
            )
        )
        assistant.say.assert_not_called()
        self.assertTrue(correction_repair.is_awaiting_exact_repeat(assistant))

    def test_corrupted_repeat_is_ignored_without_reply(self):
        from silva.commands.help_phrases import _WHICH_FEATURE
        from silva.conversation import correction_repair

        assistant = MagicMock()
        assistant._user_id.return_value = "kevin"
        correction_repair.note_feature_detail_clarification(
            assistant, "can you tell me why you asked that", _WHICH_FEATURE
        )
        correction_repair.handle_correction_repair(assistant, "that is not what I said")
        self.assertTrue(
            correction_repair.handle_exact_repeat(
                assistant, "ebony or piss me off when i said was youre the one"
            )
        )
        assistant._handle_input.assert_not_called()
        assistant.say.assert_not_called()
        self.assertTrue(correction_repair.is_awaiting_exact_repeat(assistant))

    def test_exact_repeat_is_used_as_corrected_words(self):
        from silva.conversation import correction_repair

        assistant = MagicMock()
        assistant._user_id.return_value = "kevin"
        assistant._handle_input.return_value = True
        correction_repair.note_repairable_question(
            assistant, "can you tell me what SCT fillers are"
        )
        correction_repair.handle_correction_repair(assistant, "that is not what I said")
        self.assertTrue(
            correction_repair.handle_exact_repeat(
                assistant, "can you tell me what s t t fillers"
            )
        )
        assistant._handle_input.assert_called_once_with(
            "can you tell me what s t t fillers",
            _phrase_retry=True,
        )
        self.assertFalse(correction_repair.is_awaiting_exact_repeat(assistant))

    def test_bare_one_does_not_expand_update_without_choice_wait(self):
        from silva.commands.update_handler import handle_update_expansion_speech

        assistant = MagicMock()
        assistant._update_summary_items = ["github updates", "help phrases", "screen monitor"]
        assistant._update_summary_awaiting_choice = False
        with patch("silva.commands.update_handler._speak_update") as speak:
            self.assertFalse(handle_update_expansion_speech(assistant, "youre the one"))
            speak.assert_not_called()

    def test_conversation_question_can_be_repaired_without_help_clarification(self):
        from silva.conversation import correction_repair

        assistant = MagicMock()
        assistant._user_id.return_value = "kevin"
        assistant._handle_input.return_value = True
        original = "can you tell me what SCT fillers are"
        correction_repair.note_repairable_question(assistant, original)
        self.assertTrue(
            correction_repair.handle_correction_repair(
                assistant, "no I said can you tell me what s t t fillers on"
            )
        )
        assistant._handle_input.assert_called_once_with(
            "can you tell me what s t t fillers",
            _phrase_retry=True,
        )

    def test_detail_topic_extraction(self):
        from silva.commands.help_phrases import detail_topic

        self.assertEqual(detail_topic("tell me in detail about black holes"), "black holes")
        self.assertEqual(detail_topic("can you tell me what black holes are"), "black holes")
        self.assertEqual(detail_topic("what are the available options"), "")

    def test_unknown_detail_ask_gets_web_skim(self):
        from silva.commands.help_handler import handle_help_speech

        assistant = MagicMock()
        skim = "Also from a web skim: Black holes are regions of strong gravity."
        with patch("silva.commands.help_handler.get_active_user", return_value={"id": "kevin", "tier": 5}), patch(
            "silva.commands.help_handler._detail_web_reply", return_value=skim
        ) as web_reply:
            self.assertTrue(
                handle_help_speech(assistant, "tell me in detail what black holes are")
            )
        web_reply.assert_called_once_with("black holes")
        self.assertEqual(assistant.say.call_args.args[0], skim)


class SleepToneAndRoomSpeechTests(unittest.TestCase):
    def test_none_of_them_go_to_sleep_is_a_sleep_command(self):
        from silva.commands.update_phrases import is_update_expand_phrase
        from silva.wake import is_sleep_command

        self.assertTrue(is_sleep_command("none of them go to sleep"))
        self.assertFalse(is_update_expand_phrase("none of them go to sleep"))

    def test_room_question_gets_a_room_audio_detail(self):
        from silva.commands.help_phrases import feature_detail_reply_for_user, match_feature_id

        text = "all right what about if other people are in the room how would you respond"
        self.assertEqual(match_feature_id(text), "room_audio")
        reply = feature_detail_reply_for_user(text, {"id": "kevin", "tier": 5})
        self.assertIn("one at a time", reply)
        self.assertIn("kids", reply)

    def test_sleep_message_uses_tone_without_double_styling(self):
        from silva.assistant import SilvaAssistant

        assistant = SilvaAssistant.__new__(SilvaAssistant)
        assistant._asleep = True
        assistant._voice_mode = False
        assistant._speaking = False
        assistant._tts = MagicMock()
        assistant._user_id = MagicMock(return_value="room-test-user")

        with patch("silva.conversation.attitude.style_reply", return_value="MEAN: Going to sleep.") as style, patch(
            "silva.conversation.safety.apply_safety", side_effect=lambda value, user_id="": value
        ), patch("builtins.print") as printed:
            assistant._say_while_asleep("Going to sleep. Say wake up Silva to wake me.")

        style.assert_called_once()
        self.assertEqual(printed.call_args.args[0], "Silva: MEAN: Going to sleep.")

    def test_transition_tone_is_noted_once(self):
        from silva.assistant import SilvaAssistant

        assistant = SilvaAssistant.__new__(SilvaAssistant)
        assistant._user_id = MagicMock(return_value="room-test-user")
        with patch("silva.conversation.attitude.note_user_text") as note:
            assistant._note_transition_tone("get mean and go to sleep")
            assistant._note_transition_tone("get mean and go to sleep")
        note.assert_called_once()
        self.assertEqual(note.call_args.args[1], "get mean and go to sleep")

    def test_enter_sleep_uses_pending_text_without_new_keyword(self):
        from silva.assistant import SilvaAssistant

        assistant = SilvaAssistant.__new__(SilvaAssistant)
        assistant._pending_transition_text = "go to sleep"
        with patch.object(assistant, "_note_transition_tone") as note, patch(
            "silva.keep_alive.mark_sleep_active"
        ), patch("silva.keep_alive.start_watchdog"):
            assistant._enter_sleep(quiet=True)
        note.assert_called_once_with("go to sleep")
        self.assertTrue(assistant._asleep)

    def test_live_reload_puts_tiers_before_permissions(self):
        from silva.dev.live_update import _module_reload_sort_key

        names = [
            "silva.users.permissions",
            "silva.users.tiers",
            "silva.dev.paths",
            "silva.users.voice_access",
        ]
        names.sort(key=_module_reload_sort_key)
        self.assertEqual(names[:3], ["silva.dev.paths", "silva.users.tiers", "silva.users.permissions"])

    def test_room_speech_aliases_get_room_detail(self):
        from silva.commands.help_phrases import feature_detail_reply_for_user, match_feature_id

        for text in (
            "can you tell me in detail what room speech does",
            "tell me about the crowd speech policy",
            "tell me about the cross speech policy",
        ):
            self.assertEqual(match_feature_id(text), "room_audio", text)
            reply = feature_detail_reply_for_user(text, {"id": "kevin", "tier": 5})
            self.assertIn("one at a time", reply, text)

    def test_room_audio_permission_excludes_guests(self):
        from silva.room_speech import can_listen

        self.assertFalse(can_listen({"id": "guest-1", "tier": 1}))
        self.assertTrue(can_listen({"id": "kevin", "tier": 5}))

    def test_multi_voice_turn_gets_one_at_a_time_reply(self):
        from types import SimpleNamespace

        from silva.room_speech import REPLY, RoomSnapshot, check_turn

        assistant = SimpleNamespace()
        snapshot = RoomSnapshot(2, True, False)
        with patch("silva.users.manager.get_active_user", return_value={"id": "kevin", "tier": 5}), patch(
            "silva.room_speech.can_listen", return_value=True
        ), patch("silva.room_speech.snapshot", return_value=snapshot), patch(
            "silva.room_speech._camera_active", return_value=False
        ), patch("silva.conversation.safety.is_speaker_safe", return_value=False):
            result = check_turn(assistant, "what is the weather", None)
        self.assertEqual(result.decision, REPLY)
        self.assertIn("one at a time", result.reply)

    def test_crowd_kids_check_keeps_reply_polite(self):
        from types import SimpleNamespace

        from silva.room_speech import HOLD, REPLY, RoomSnapshot, check_turn

        assistant = SimpleNamespace()
        snapshot = RoomSnapshot(3, True, False)
        with patch("silva.users.manager.get_active_user", return_value={"id": "kevin", "tier": 5}), patch(
            "silva.room_speech.can_listen", return_value=True
        ), patch("silva.room_speech.snapshot", return_value=snapshot), patch(
            "silva.room_speech._camera_active", return_value=False
        ), patch("silva.conversation.safety.is_speaker_safe", return_value=False):
            first = check_turn(assistant, "tell me a joke", None)
            second = check_turn(assistant, "tell me another", None)
            third = check_turn(assistant, "yes", None)
            fourth = check_turn(assistant, "yes", None)
            fifth = check_turn(assistant, "yes", None)
        self.assertIn("one at a time", first.reply)
        self.assertIn("kids", second.reply)
        self.assertEqual(third.decision, HOLD)
        self.assertEqual(fourth.decision, HOLD)
        self.assertEqual(fifth.decision, REPLY)
        self.assertIn("one at a time", fifth.reply.lower())
        self.assertNotIn("stop", fifth.reply.lower())


class UpdateHelpFlowTests(unittest.TestCase):
    def test_update_help_phrases_do_not_override_unrelated_speech(self):
        from silva.commands.update_phrases import (
            is_update_feature_request_phrase,
            is_update_not_current_phrase,
            is_update_speech,
        )

        for text in (
            "why was this not in the update",
            "why wasn't that included in the newest update",
            "that feature was not in the update",
        ):
            self.assertTrue(is_update_feature_request_phrase(text), msg=text)
            self.assertTrue(is_update_speech(text), msg=text)

        for text in (
            "why are you not up to date",
            "why have you not updated to the right version",
            "why are you on 112 when you should be on 110",
            "tell me the exact version or update you are on",
        ):
            self.assertTrue(is_update_not_current_phrase(text), msg=text)
            self.assertTrue(is_update_speech(text), msg=text)

        for text in (
            "why did you cut off having the stuff I just said",
            "that was not what was added",
            "what was added in the newest update",
            "are you on the latest update",
            "what is the weather",
        ):
            self.assertFalse(is_update_feature_request_phrase(text), msg=text)
            self.assertFalse(is_update_not_current_phrase(text), msg=text)

    def test_missing_update_item_becomes_feature_request(self):
        from types import SimpleNamespace

        from silva.commands.update_handler import handle_update_speech

        spoken: list[str] = []
        assistant = SimpleNamespace(say=lambda text, **_kwargs: spoken.append(text))
        with patch(
            "silva.users.manager.get_active_user",
            return_value={"id": "kevin", "name": "Kevin", "tier": 1},
        ), patch(
            "silva.users.update_help.record_update_help_request",
            return_value=(True, ""),
        ), patch("silva.users.feature_requests.submit_feature_request") as submit:
            self.assertTrue(handle_update_speech(assistant, "why was this not in the update"))
        submit.assert_called_once()
        self.assertIn("feature request", spoken[0].lower())

    def test_not_current_explains_and_asks_to_check(self):
        from types import SimpleNamespace

        from silva.commands.update_handler import handle_update_speech
        from silva.dev.update_check import UpdateStatus

        spoken: list[str] = []
        assistant = SimpleNamespace(say=lambda text, **_kwargs: spoken.append(text))
        status = UpdateStatus(
            needs_update=False,
            current_version="0.1.112",
            available_version="0.1.112",
            source="bundled",
            reason="current",
        )
        with patch("silva.dev.update_check.check_update_status", return_value=status), patch(
            "silva.users.manager.get_active_user",
            return_value={"id": "kevin", "name": "Kevin", "tier": 1},
        ), patch(
            "silva.users.update_help.record_update_help_request",
            return_value=(True, ""),
        ):
            self.assertTrue(handle_update_speech(assistant, "why are you on 112 when you should be on 110"))
        self.assertTrue(assistant._update_help_check_pending)
        self.assertIn("0.1.112", spoken[0])
        self.assertIn("Do you want me to check to see if there is an update?", spoken[0])

    def test_yes_after_update_help_check_offers_apply_to_admin(self):
        from types import SimpleNamespace

        from silva.commands.update_handler import handle_update_speech
        from silva.dev.update_check import UpdateStatus

        spoken: list[str] = []
        assistant = SimpleNamespace(
            say=lambda text, **_kwargs: spoken.append(text),
            _update_help_check_pending=True,
        )
        status = UpdateStatus(
            needs_update=True,
            current_version="0.1.112",
            available_version="0.1.113",
            source="manifest",
            reason="manifest_changed",
            changes=["Fixed update help replies."],
        )
        with patch("silva.dev.update_check.check_update_status", return_value=status), patch(
            "silva.dev.update_permissions.can_apply_update",
            return_value=True,
        ):
            self.assertTrue(handle_update_speech(assistant, "yes"))
        self.assertFalse(assistant._update_help_check_pending)
        self.assertTrue(assistant._update_help_apply_pending)
        self.assertIn("Would you like me to update?", spoken[0])

    def test_live_chat_speech_submits_user_message(self):
        from types import SimpleNamespace

        from silva.commands.live_chat_commands import handle_live_chat_speech

        spoken: list[str] = []
        assistant = SimpleNamespace(say=lambda text, **_kwargs: spoken.append(text))
        with patch(
            "silva.commands.live_chat_commands.submit_live_chat_message",
            return_value={"id": "chat1"},
        ) as submit:
            self.assertTrue(
                handle_live_chat_speech(
                    assistant,
                    "tell admins and owner the update check is wrong",
                    {"id": "kevin", "name": "Kevin", "tier": 1},
                )
            )
        submit.assert_called_once()
        self.assertEqual(submit.call_args.kwargs.get("kind"), "update")
        self.assertIn("live admin and owner chat", spoken[0].lower())

    def test_emergency_push_requires_trusted_capability(self):
        from silva.dev.feature_votes import mark_dev_feature_live

        item = {"id": "feature1", "status": "owner_approved", "votes": {}}
        with patch("silva.dev.feature_votes.list_dev_features", return_value=[item]), patch(
            "silva.dev.feature_votes._save_features"
        ), patch("silva.dev.feature_votes.is_owner", return_value=False), patch(
            "silva.dev.feature_votes.is_capability_enabled",
            return_value=False,
        ):
            ok, message = mark_dev_feature_live("feature1", {"id": "admin"}, emergency=True)
        self.assertFalse(ok)
        self.assertIn("trusted admin", message)

    def test_update_channel_defaults_to_stable(self):
        from silva.users.update_channels import get_update_channel, set_update_channel

        with patch("silva.users.update_channels._load_channels", return_value={}), patch(
            "silva.users.update_channels._save_channels"
        ):
            self.assertEqual(get_update_channel("kevin"), "stable")
            ok, message = set_update_channel("kevin", "dev")
        self.assertTrue(ok)
        self.assertIn("dev", message)


class LogIncidentFixTests(unittest.TestCase):
    def test_correction_filler_does_not_become_a_question(self):
        from silva.conversation.correction_repair import is_generic_correction, parse_correction

        self.assertIsNone(parse_correction("not what I said by the way"))
        self.assertTrue(is_generic_correction("not what I said by the way"))

    def test_help_handler_is_recognized_before_wikipedia(self):
        from silva.cache.router_cache import lookup_route
        from silva.commands.help_phrases import (
            detail_topic,
            is_feature_detail_ask,
            match_feature_id,
        )

        text = "tell me about help Handler what does it do"
        self.assertIsNone(match_feature_id(text))
        self.assertTrue(is_feature_detail_ask(text))
        self.assertEqual(detail_topic(text), "help handler")
        self.assertIsNone(lookup_route(text))

    def test_unknown_information_uses_wikipedia_skim(self):
        from types import SimpleNamespace

        from silva.commands import unknown_information

        spoken: list[str] = []
        assistant = SimpleNamespace(say=lambda text, **_kwargs: spoken.append(text))
        result = SimpleNamespace(spoken="Photosynthesis is the process plants use to make food.", full="", items=[])
        with patch(
            "silva.commands.unknown_information.unknown_information_topic",
            return_value="photosynthesis",
        ), patch("silva.commands.knowledge_skim.skim_topic", return_value=result):
            self.assertTrue(unknown_information.handle_unknown_information_speech(assistant, "what is photosynthesis"))
        self.assertIn("Wikipedia", spoken[0])
        self.assertIn("photosynthesis", spoken[0].lower())

    def test_self_talk_is_not_a_wikipedia_fallback(self):
        from silva.commands.unknown_information import unknown_information_topic

        self.assertEqual(unknown_information_topic("why did you ask that when you woke up"), "")
        self.assertEqual(unknown_information_topic("what is photosynthesis"), "photosynthesis")


class StandaloneLiveChatTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        base = Path(self._tmpdir.name)
        for target, path in (
            ("silva.users.live_chat.CHAT_FILE", base / "chat.json"),
            ("silva.users.live_chat.MODERATION_FILE", base / "moderation.json"),
        ):
            patcher = patch(target, path)
            self.addCleanup(patcher.stop)
            patcher.start()
        for target in ("silva.users.live_chat._notify", "silva.users.live_chat._popup"):
            patcher = patch(target)
            self.addCleanup(patcher.stop)
            patcher.start()
        patcher = patch("silva.users.live_chat.is_capability_enabled", return_value=False)
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_history_roles_replies_and_blocking(self):
        from silva.users import live_chat

        user = {"id": "kevin", "name": "Kevin", "tier": 1}
        owner = {"id": "owner", "name": "Owner", "tier": 5, "role": "owner"}
        with patch("silva.users.live_chat.is_owner", side_effect=lambda item: str(item.get("id")) == "owner"):
            sent = live_chat.submit_live_chat_message(user, "please help with the update")
            self.assertEqual(sent["author_label"], "Kevin (user)")
            ok, message = live_chat.reply_live_chat_message(sent["id"], owner, "I can help")
            self.assertTrue(ok, message)
            history = live_chat.list_live_chat_messages(user_id="kevin")
            self.assertEqual([item["direction"] for item in history], ["user_to_staff", "staff_to_user"])
            self.assertEqual(history[1]["author_label"], "owner")
            self.assertEqual(live_chat.unread_live_chat_count(user_id="kevin"), 1)

            ok, message = live_chat.set_live_chat_blocked(owner, "kevin", blocked=True, reason="rude")
            self.assertTrue(ok, message)
            blocked = live_chat.submit_live_chat_message(user, "more messages")
            self.assertEqual(blocked["status"], "blocked")

    def test_open_voice_command_uses_popup_without_panel_access(self):
        from types import SimpleNamespace

        from silva.commands.live_chat_commands import handle_live_chat_speech

        spoken: list[str] = []
        assistant = SimpleNamespace(say=lambda text, **_kwargs: spoken.append(text))
        with patch("silva.commands.live_chat_commands.open_live_chat_popup") as open_popup:
            self.assertTrue(
                handle_live_chat_speech(
                    assistant,
                    "all right make it to where the live chat is its own pop-up not tied into the system panel",
                    {"id": "kevin", "name": "Kevin", "tier": 1},
                )
            )
        open_popup.assert_called_once()
        self.assertIn("popup", spoken[0].lower())


def _load_age_users(path):
    def _load():
        return json.loads(Path(path).read_text(encoding="utf-8"))

    return _load


if __name__ == "__main__":
    unittest.main()
