"""Quick check: sleep wait loop must not print idle reminders."""

from __future__ import annotations

import io
import queue
import unittest
from unittest.mock import MagicMock, patch


class SleepWaitLoopTests(unittest.TestCase):
    def _make_assistant(self):
        from silva.assistant import SilvaAssistant

        assistant = SilvaAssistant.__new__(SilvaAssistant)
        assistant._asleep = True
        assistant._stop_requested = False
        assistant._voice_mode = True
        assistant._sleep_reminder_index = 0
        assistant._sleep_idle_reminder_index = 0
        assistant._last_sleep_reminder_at = 0.0
        assistant._last_idle_sleep_reminder_at = 0.0
        assistant._sleep_started_at = 0.0
        assistant._remind_asleep = MagicMock()
        assistant._wake_up = MagicMock()
        assistant._close_like_exit = MagicMock(
            side_effect=lambda: setattr(assistant, "_stop_requested", True)
            or setattr(assistant, "_asleep", False)
            or False
        )
        assistant._identify_speaker = MagicMock()
        assistant._run_protection_challenge = MagicMock()
        assistant._typed_command_queue = queue.Queue()
        assistant._notes_flow = None
        assistant._speaking = False
        assistant._check_todo_nags = MagicMock()
        assistant._check_note_reminders = MagicMock()
        assistant._handle_notes_silence = MagicMock()
        assistant._handle_notes_command = MagicMock(return_value=True)
        assistant._handle_notes_flow = MagicMock(return_value=True)
        assistant._stt = None
        assistant._recover_voice_after_error = MagicMock()
        return assistant

    def test_idle_listen_does_not_spam_or_remind(self):
        import time

        assistant = self._make_assistant()
        assistant._last_idle_sleep_reminder_at = time.time()
        stt = MagicMock()

        def finish_on_silence(*_args, **_kwargs):
            assistant._asleep = False
            return ("", None)

        stt.listen_with_audio.side_effect = finish_on_silence
        stt.last_device_error = False
        assistant._ensure_stt = MagicMock(return_value=stt)

        buffer = io.StringIO()
        with patch("sys.stdout", buffer):
            with patch("silva.config.load_config") as load_config:
                load_config.return_value = {"sleep_idle_reminder_minutes": 3}
                assistant._wait_for_wake()

        output = buffer.getvalue()
        self.assertNotIn("Silva is asleep. Say wake up Silva", output)
        assistant._remind_asleep.assert_not_called()

    def test_non_wake_speech_is_ignored_silently(self):
        assistant = self._make_assistant()
        stt = MagicMock()
        responses = iter([("what is the weather", None), ("", None)])

        def listen_cycle(*_args, **_kwargs):
            result = next(responses, ("", None))
            if not result[0]:
                assistant._asleep = False
            return result

        stt.listen_with_audio.side_effect = listen_cycle
        stt.last_device_error = False
        assistant._ensure_stt = MagicMock(return_value=stt)
        buffer = io.StringIO()

        with patch("sys.stdout", buffer), patch("silva.assistant.load_config", return_value={"sleep_wake_only_enabled": True}):
            with patch("silva.assistant.evaluate_wake") as evaluate_wake:
                evaluate_wake.return_value = MagicMock(action="ignore")
                assistant._wait_for_wake()

        self.assertEqual(buffer.getvalue(), "")
        assistant._remind_asleep.assert_not_called()
        assistant._wake_up.assert_not_called()

    def test_non_wake_speech_reminds_when_wake_only_disabled(self):
        assistant = self._make_assistant()
        stt = MagicMock()
        stt.listen_with_audio.return_value = ("what is the weather", None)
        stt.last_device_error = False
        assistant._ensure_stt = MagicMock(return_value=stt)

        def stop_after_remind(*_args, **_kwargs):
            assistant._asleep = False

        assistant._remind_asleep.side_effect = stop_after_remind
        with patch("silva.assistant.load_config", return_value={"sleep_wake_only_enabled": False}):
            with patch("silva.assistant.evaluate_wake") as evaluate_wake:
                evaluate_wake.return_value = MagicMock(action="ignore")
                assistant._wait_for_wake()

        assistant._remind_asleep.assert_called_once_with(reason="voice", text="what is the weather")

    def test_wake_phrase_still_wakes_in_wake_only_mode(self):
        assistant = self._make_assistant()
        stt = MagicMock()
        stt.listen_with_audio.return_value = ("wake up", None)
        stt.last_device_error = False
        assistant._ensure_stt = MagicMock(return_value=stt)

        with patch("silva.assistant.load_config", return_value={"sleep_wake_only_enabled": True}):
            with patch("silva.assistant.evaluate_wake") as evaluate_wake:
                evaluate_wake.return_value = MagicMock(action="wake", silent=False)
                assistant._wait_for_wake()

        assistant._wake_up.assert_called_once_with(source="voice", silent=False)

    def test_todo_request_while_asleep_is_ignored_in_wake_only_mode(self):
        assistant = self._make_assistant()
        stt = MagicMock()
        responses = iter([("what is my to do list", None), ("", None)])

        def listen_cycle(*_args, **_kwargs):
            result = next(responses, ("", None))
            if not result[0]:
                assistant._asleep = False
            return result

        stt.listen_with_audio.side_effect = listen_cycle
        stt.last_device_error = False
        assistant._ensure_stt = MagicMock(return_value=stt)

        with patch("silva.assistant.load_config", return_value={"sleep_wake_only_enabled": True}):
            with patch("silva.assistant.evaluate_wake") as evaluate_wake:
                evaluate_wake.return_value = MagicMock(action="ignore")
                with patch("silva.assistant.is_notes_command") as is_notes_command:
                    assistant._wait_for_wake()

        is_notes_command.assert_not_called()
        assistant._handle_notes_command.assert_not_called()
        assistant._remind_asleep.assert_not_called()
        assistant._wake_up.assert_not_called()


    def test_idle_reminder_after_interval(self):
        assistant = self._make_assistant()
        assistant._last_idle_sleep_reminder_at = 0.0
        stt = MagicMock()

        calls = {"n": 0}

        def listen_cycle(*_args, **_kwargs):
            calls["n"] += 1
            if calls["n"] >= 2:
                assistant._asleep = False
            return ("", None)

        stt.listen_with_audio.side_effect = listen_cycle
        stt.last_device_error = False
        assistant._ensure_stt = MagicMock(return_value=stt)

        with patch("silva.config.load_config") as load_config:
            load_config.return_value = {
                "sleep_idle_reminder_minutes": 0.001,
                "sleep_reminder_speak": False,
                "sleep_reminder_cooldown_seconds": 12,
            }
            assistant._wait_for_wake()

        assistant._remind_asleep.assert_not_called()


    def test_say_while_asleep_stays_asleep(self):
        from silva.assistant import SilvaAssistant

        assistant = SilvaAssistant.__new__(SilvaAssistant)
        assistant._asleep = True
        assistant._voice_mode = False
        assistant._speaking = False
        assistant._tts = MagicMock()

        assistant._say_while_asleep("Just a reminder — I'm still in sleep mode.")
        self.assertTrue(assistant._asleep)
        self.assertFalse(assistant._speaking)


    def test_idle_reminder_prints_without_speech(self):
        from silva.assistant import SilvaAssistant

        assistant = SilvaAssistant.__new__(SilvaAssistant)
        assistant._asleep = True
        assistant._sleep_idle_reminder_index = 0
        assistant._last_idle_sleep_reminder_at = 0.0
        assistant._say_while_asleep = MagicMock()

        with patch("silva.config.load_config") as load_config:
            load_config.return_value = {
                "sleep_idle_reminder_speak": False,
                "sleep_idle_reminder_print": True,
            }
            with patch("builtins.print") as print_mock:
                assistant._remind_asleep(reason="idle")

        assistant._say_while_asleep.assert_not_called()
        print_mock.assert_not_called()
        self.assertTrue(assistant._asleep)

    def test_goodbye_while_asleep_closes_like_the_exit_button(self):
        assistant = self._make_assistant()
        stt = MagicMock()
        stt.listen_with_audio.return_value = ("goodbye", None)
        stt.last_device_error = False
        assistant._ensure_stt = MagicMock(return_value=stt)

        with patch("silva.assistant.evaluate_wake") as evaluate_wake:
            assistant._wait_for_wake()
            evaluate_wake.assert_not_called()

        assistant._close_like_exit.assert_called_once()
        assistant._remind_asleep.assert_not_called()
        assistant._wake_up.assert_not_called()


if __name__ == "__main__":
    unittest.main()
