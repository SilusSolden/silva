"""Reloadable stop-while-speaking listen loop. InterruptMonitor itself is not live-reloaded."""

from __future__ import annotations

import time
from typing import Any

from silva.commands.intent import is_action_command
from silva.conversation.complete_sentence import should_handle_interruption_speech
from silva.gui.display_manager import is_shutting_down
from silva.interrupt import is_interrupt_command
from silva.logger import log_info
from silva.stt_quick_commands import is_complete_command
from silva.wake import is_sleep_command

_active_monitor: Any | None = None


def _is_end_session(text: str) -> bool:
    from silva.close_phrases import is_close_command

    return is_close_command(text)


def set_active_monitor(monitor: Any | None) -> None:
    global _active_monitor
    _active_monitor = monitor


def active_monitor():
    return _active_monitor


def interrupt_now(source: str, *, command: str | None = None, tts=None) -> bool:
    """Cut speech immediately. Safe to call from the terminal thread."""
    monitor = _active_monitor
    if monitor is not None:
        if command and not is_interrupt_command(command):
            monitor._trigger(source, command=command)
        else:
            # Plain "stop" must not be re-handled after speech ends — that was a no-op.
            monitor._trigger(source)
        log_info(f"Stop cut speech ({source})")
        return True
    if tts is not None:
        try:
            tts.stop()
        except Exception:
            pass
        log_info(f"Stop cut speech without monitor ({source})")
        return True
    return False


def listen_once_for_stop(stt) -> str | None:
    """Short listen for 'stop'. Keep the energy floor near normal so a spoken stop is heard."""
    old_base = getattr(stt, "_base_energy", 250)
    try:
        stt._base_energy = max(int(old_base), 220)
        text, _audio = stt.listen_with_audio(
            timeout=0.9,
            phrase_limit=1.0,
            announce=False,
            skip_continuation=True,
            fast_end=True,
        )
        return text
    except Exception:
        return None
    finally:
        try:
            stt._base_energy = old_base
        except Exception:
            pass


def voice_stop_loop(monitor) -> None:
    """Replace InterruptMonitor._voice_loop so live updates can rebind it."""
    set_active_monitor(monitor)
    time.sleep(0.12)
    stt = monitor._stt
    try:
        while not monitor._stop_event.is_set() and not is_shutting_down():
            try:
                text = listen_once_for_stop(stt)
                if not text or monitor._stop_event.is_set():
                    continue
                if is_interrupt_command(text):
                    print(f"You: {text}")
                    log_info(f"Heard stop while talking: {text[:80]}")
                    interrupt_now("voice", command=text)
                    return
                if is_sleep_command(text) or _is_end_session(text):
                    print(f"You: {text}")
                    interrupt_now("voice", command=text)
                    return
                if not should_handle_interruption_speech(text):
                    log_info(f"Ignored incomplete interruption speech: {text[:80]}")
                    continue
                if len(text.split()) > 8:
                    continue
                if is_action_command(text) or is_complete_command(text):
                    print(f"You: {text}")
                    monitor._handle_parallel(text)
                    continue
            except Exception as exc:
                log_info(f"Stop listen skipped a cycle: {exc}")
                time.sleep(0.12)
    finally:
        if _active_monitor is monitor:
            set_active_monitor(None)


def submit_typed_terminal_command_impl(self, line: str) -> None:
    """Typed console commands. Stop/sleep/goodbye cut speech instead of waiting in the queue."""
    from silva.close_phrases import is_close_command
    from silva.dev.typed_command_access import normalize_typed_command, validate_typed_command
    from silva.users.manager import get_active_user

    text = normalize_typed_command(line)
    if not text:
        return
    user = get_active_user()
    ok, message = validate_typed_command(user, text)
    if not ok:
        self._print_terminal_message(message)
        return

    speaking = bool(getattr(self, "_speaking", False))
    if speaking and (
        is_interrupt_command(text) or is_sleep_command(text) or is_close_command(text)
    ):
        if interrupt_now("typed-terminal", command=text, tts=getattr(self, "_tts", None)):
            return

    self._typed_command_queue.put(text)


def dispatch_overlay_command_impl(self, text: str) -> None:
    from silva.close_phrases import is_close_command
    from silva.dev.typed_command_access import normalize_typed_command, validate_typed_command
    from silva.users.manager import get_active_user

    command = normalize_typed_command(text)
    if not command:
        return
    user = get_active_user()
    ok, message = validate_typed_command(user, command)
    if not ok:
        self._print_terminal_message(message)
        return
    speaking = bool(getattr(self, "_speaking", False))
    if speaking and (
        is_interrupt_command(command) or is_sleep_command(command) or is_close_command(command)
    ):
        if interrupt_now("overlay", command=command, tts=getattr(self, "_tts", None)):
            return
    if speaking:
        self._enqueue_parallel_command(command)
        return
    self._typed_command_queue.put(command)
