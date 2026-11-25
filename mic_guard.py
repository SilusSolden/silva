"""Backoff when the microphone disappears so sleep mode cannot crash PortAudio."""

from __future__ import annotations

import time

from silva.logger import log_error, log_info

_MAX_DELAY = 30.0
_MIN_DELAY = 1.0


def should_retry_mic(assistant) -> bool:
    return time.time() >= float(getattr(assistant, "_next_mic_retry", 0.0) or 0.0)


def retry_wait_seconds(assistant) -> float:
    remain = float(getattr(assistant, "_next_mic_retry", 0.0) or 0.0) - time.time()
    if remain <= 0:
        return 0.5
    return min(5.0, max(0.5, remain))


def note_mic_ok(assistant) -> None:
    assistant._mic_fail_delay = _MIN_DELAY
    assistant._next_mic_retry = 0.0
    assistant._mic_fail_logged = False


def note_mic_fail(assistant, exc: BaseException | None = None) -> None:
    delay = min(_MAX_DELAY, max(_MIN_DELAY, float(getattr(assistant, "_mic_fail_delay", _MIN_DELAY) or _MIN_DELAY)))
    assistant._next_mic_retry = time.time() + delay
    assistant._mic_fail_delay = min(_MAX_DELAY, delay * 2)
    if not getattr(assistant, "_mic_fail_logged", False):
        log_error("Could not open the microphone; waiting for it to come back", exc=exc)
        assistant._mic_fail_logged = True
    else:
        log_info(f"Microphone still missing; retrying in {delay:.0f}s")
