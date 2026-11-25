import re
import threading
import time

import speech_recognition as sr

from silva.config import load_config
from silva.conversation import is_conversational_utterance
from silva.conversation.matching import dedupe_repeated_phrase
from silva.stt_quick_commands import is_complete_command, is_partial_command
from silva.stt_speech_guard import _audio_samples, _frame_rms, detect_receding_audio

_LAST_CONFIDENCE = 1.0
_ACTIVE_STT = None


def last_listen_confidence() -> float:
    return _LAST_CONFIDENCE


def release_active_microphone() -> None:
    """Drop any live SpeechToText capture so Record Voice can open the mic."""
    stt = _ACTIVE_STT
    if stt is None:
        import gc

        for obj in gc.get_objects():
            if type(obj).__name__ == "SpeechToText" and hasattr(obj, "release_microphone"):
                stt = obj
                break
            if type(obj).__name__ == "SpeechToText":
                stt = obj
                break
    if stt is None:
        return
    release = getattr(stt, "release_microphone", None)
    if callable(release):
        release()
        return
    try:
        from silva.media.devices import set_capture_active

        set_capture_active(False)
    except Exception:
        pass
    try:
        stt._mic_primed = False
        stt._mic_ready = False
        stt._microphone = None
    except Exception:
        pass

# If recognition ends on these, Silva listens once more for the rest of the phrase.
INCOMPLETE_PHRASES: tuple[str, ...] = (
    "who",
    "who am",
    "what",
    "what is",
    "whats",
    "look",
        "look up",
        "look up how",
        "tell me",
        "note",
        "note this",
        "note that",
        "add to my",
        "add this to",
        "to do",
        "todo",
    "search",
    "search for",
    "how",
    "how is",
    "hows",
    "enroll",
    "enroll my",
    "set",
    "set my",
    "set voice",
    "save my",
    "record my",
    "register",
    "register my",
    "wake",
    "wake up",
    "show",
    "add user",
    "remove user",
    "go",
    "go to",
    "tell",
    "check",
    "check the",
    "get",
    "get the",
    "open",
    "launch",
    "take me to",
    "silva",
    "my",
    "the",
)

TRAILING_FRAGMENT_WORDS = {
    "who",
    "what",
    "how",
    "my",
    "the",
    "a",
    "up",
    "for",
    "is",
    "am",
    "to",
    "on",
    "in",
    "at",
    "and",
    "or",
    "open",
    "show",
    "go",
    "pro",
    "prof",
    "profile",
    "silva",
    "manage",
    "user",
    "control",
    "admin",
    "launch",
}

# Short words that are complete on their own — never ask user to keep speaking.
SHORT_COMPLETE_WORDS = frozenset(
    {
        "hello",
        "hi",
        "hey",
        "howdy",
        "yo",
        "hiya",
        "heya",
        "sup",
        "thanks",
        "thank",
        "yes",
        "yeah",
        "yep",
        "yup",
        "yea",
        "yah",
        "ya",
        "sure",
        "no",
        "nope",
        "nah",
        "ok",
        "okay",
        "good",
        "fine",
        "great",
        "bye",
        "goodbye",
        "morning",
        "evening",
        "stop",
    }
)
def _dedupe_repeated_phrase(text: str) -> str:
    return dedupe_repeated_phrase(text)


def _needs_more_speech(text: str) -> bool:
    if is_complete_command(text):
        return False
    if is_conversational_utterance(text):
        return False
    normalized = _normalize(text)
    if normalized in SHORT_COMPLETE_WORDS:
        return False
    words = normalized.split()
    if is_partial_command(text) or _profile_command_partial(text):
        return True
    if len(words) >= 3:
        return False
    return _looks_incomplete(text)


def _profile_command_partial(text: str) -> bool:
    """True when the user is likely still saying a profile command."""
    if is_complete_command(text):
        return False
    normalized = _normalize(text)
    if not normalized:
        return False
    if normalized in {"pro", "prof", "profile", "profiles", "panel", "panels"}:
        return True
    for starter in ("open", "show", "go to", "launch", "take me to", "silva", "manage"):
        if normalized == starter or normalized.startswith(starter + " "):
            return True
    return False


def _concat_audio(first: sr.AudioData, second: sr.AudioData) -> sr.AudioData:
    raw = first.get_raw_data() + second.get_raw_data()
    return sr.AudioData(raw, first.sample_rate, first.sample_width)


def _normalize(text: str) -> str:
    text = text.strip().lower()
    text = text.replace("'", "")
    return re.sub(r"\s+", " ", text)


def _looks_incomplete(text: str) -> bool:
    if is_complete_command(text):
        return False
    normalized = _normalize(text)
    if not normalized:
        return False
    if normalized in SHORT_COMPLETE_WORDS:
        return False
    if normalized in INCOMPLETE_PHRASES:
        return True
    for phrase in INCOMPLETE_PHRASES:
        if normalized.endswith(" " + phrase) or normalized == phrase:
            return True
    words = normalized.split()
    if len(words) == 1 and words[-1] in TRAILING_FRAGMENT_WORDS:
        return True
    if len(words) == 2 and words[-1] in TRAILING_FRAGMENT_WORDS:
        return True
    if len(words) <= 3 and words[-1] in {"pro", "prof", "panel", "panels"}:
        return True
    return False


def _audio_median_rms(audio: sr.AudioData | None) -> float:
    if audio is None:
        return 0.0
    samples = _audio_samples(audio)
    if len(samples) < 400:
        return 0.0
    frame_size = max(1, int(audio.sample_rate * 0.05))
    rms = _frame_rms(samples, frame_size=frame_size)
    if not rms:
        return 0.0
    import numpy as np

    return float(np.median(rms))


def _boost_quiet_audio(audio: sr.AudioData, gain: float) -> sr.AudioData:
    if audio.sample_width != 2:
        return audio
    samples = _audio_samples(audio)
    if len(samples) == 0:
        return audio
    import numpy as np

    scaled = np.clip(samples * float(gain), -32768, 32767).astype(np.int16).tobytes()
    return sr.AudioData(scaled, audio.sample_rate, audio.sample_width)


def _is_quiet_audio(audio: sr.AudioData | None) -> bool:
    config = load_config()
    if not bool(config.get("stt_quiet_retry_enabled", True)):
        return False
    median = _audio_median_rms(audio)
    return 0 < median < float(config.get("stt_quiet_retry_rms", 700.0))


def _should_retry_quiet_audio(audio: sr.AudioData, text: str | None) -> bool:
    if not _is_quiet_audio(audio):
        return False
    confidence = last_listen_confidence()
    low_confidence = confidence <= float(load_config().get("stt_quiet_retry_confidence", 0.55))
    weak_text = not text or _needs_more_speech(text) or len(text.split()) <= 2
    return low_confidence or weak_text


class SpeechToText:
    def __init__(self):
        config = load_config()
        self._recognizer = sr.Recognizer()
        self._base_energy = int(config.get("stt_energy_threshold", 250))
        # Dynamic energy after TTS/speakers often climbs so high the mic goes deaf.
        self._recognizer.dynamic_energy_threshold = False
        self._recognizer.dynamic_energy_ratio = float(config.get("stt_dynamic_energy_ratio", 1.35))
        self._recognizer.energy_threshold = self._base_energy
        self._recognizer.pause_threshold = float(config.get("stt_pause_threshold", 2.0))
        self._recognizer.phrase_threshold = float(config.get("stt_phrase_threshold", 0.2))
        self._recognizer.non_speaking_duration = float(config.get("stt_non_speaking_duration", 0.75))
        self._default_timeout = float(config.get("stt_listen_timeout", 12.0))
        self._active_listen_timeout = float(
            config.get("stt_active_listen_timeout", config.get("stt_listen_timeout", 12.0))
        )
        self._default_phrase_limit = float(config.get("stt_phrase_limit", 28.0))
        self._continuation_timeout = float(config.get("stt_continuation_timeout", 5.0))
        self._continuation_phrase_limit = float(config.get("stt_continuation_phrase_limit", 16.0))
        self._command_pause_threshold = float(config.get("stt_command_pause_threshold", 2.4))
        self._command_non_speaking_duration = float(config.get("stt_command_non_speaking_duration", 0.9))
        self._reply_pause_threshold = float(config.get("stt_reply_pause_threshold", 2.0))
        self._reply_non_speaking_duration = float(
            config.get("stt_reply_non_speaking_duration", 0.8)
        )
        self._conversational_pause_threshold = float(
            config.get("stt_conversational_pause_threshold", self._reply_pause_threshold)
        )
        self._conversational_non_speaking_duration = float(
            config.get(
                "stt_conversational_non_speaking_duration",
                self._reply_non_speaking_duration,
            )
        )
        self._show_listening_prompt = bool(config.get("stt_show_listening_prompt", True))
        self._show_listening_each_cycle = bool(config.get("stt_show_listening_each_cycle", True))
        self._default_pause_threshold = float(config.get("stt_pause_threshold", 2.6))
        self._default_non_speaking_duration = float(config.get("stt_non_speaking_duration", 1.0))
        self._profile_continuation_timeout = float(config.get("stt_profile_continuation_timeout", 6.0))
        self._warmup_ambient_seconds = float(config.get("stt_warmup_ambient_seconds", 0.2))
        self._quick_ambient_seconds = float(config.get("stt_quick_ambient_seconds", 0.0))
        self._phrase_completion = bool(config.get("stt_phrase_completion", True))
        self._device_index: int | None = None
        self._device_name = ""
        self.last_confidence = 1.0
        self.last_receding_audio = False
        self._movement_recovery_enabled = bool(config.get("stt_movement_recovery_enabled", True))
        self._movement_recovery_factor = min(
            0.95, max(0.5, float(config.get("stt_movement_recovery_factor", 0.75)))
        )
        self._movement_recovery_min_energy = int(config.get("stt_movement_recovery_min_energy", 100))
        self._microphone = sr.Microphone()
        self._mic_lock = threading.Lock()
        self._mic_ready = False
        self._listening_prompt_shown = False
        self._mic_primed = False
        self.last_device_error = False
        self._listen_busy = False
        self._listen_started = 0.0
        global _ACTIVE_STT
        _ACTIVE_STT = self
        self._sync_microphone(force=True)

    def signal_listening(self) -> None:
        if not self._show_listening_prompt:
            return
        from silva.console_view import is_clean_console
        from silva.logger import log_info

        log_info("Listening...")
        if is_clean_console():
            return
        print("Listening...")

    def _sync_microphone(self, *, force: bool = False) -> None:
        """Point SpeechRecognition at the currently detected input. Silent."""
        try:
            from silva.media.devices import current_input_device

            index, name = current_input_device()
        except Exception:
            return
        if not force and index == self._device_index and self._microphone is not None:
            return
        with self._mic_lock:
            try:
                self._microphone = (
                    sr.Microphone(device_index=index) if index is not None else sr.Microphone()
                )
                self._device_index = index
                self._device_name = name
                self._mic_ready = False
                self._mic_primed = False
            except OSError:
                pass

    def release_microphone(self) -> None:
        """Drop the capture device so another Silva window can record voice."""
        from silva.media.devices import set_capture_active

        set_capture_active(False)
        with self._mic_lock:
            self._microphone = None
            self._mic_ready = False
            self._mic_primed = False
            self._device_index = None

    def recover_microphone(self) -> bool:
        """Rebuild the capture device after unplug/replug without leaving voice mode."""
        from silva.logger import log_info
        from silva.media.devices import poll_audio_devices

        self.last_device_error = False
        self._mic_ready = False
        self._mic_primed = False
        try:
            poll_audio_devices(force=True)
        except Exception:
            pass
        self._sync_microphone(force=True)
        try:
            self.prime_microphone()
        except OSError:
            return False
        if not self._mic_primed:
            return False
        log_info(f"Microphone recovered: {self._device_name or 'default'}")
        return True

    def prime_microphone(self) -> None:
        """Open the mic once at startup so the first listen starts immediately."""
        self._sync_microphone()
        if self._mic_primed:
            return
        if self._microphone is None:
            return
        try:
            from silva.media.devices import portaudio_lock, set_capture_active

            with self._mic_lock:
                with portaudio_lock():
                    set_capture_active(True)
                    try:
                        with self._microphone as _source:
                            pass
                    finally:
                        set_capture_active(False)
            self._mic_primed = True
            self._mic_ready = True
        except (OSError, IOError, RuntimeError):
            pass

    def warmup(self) -> None:
        """Calibrate the mic once at startup so listening starts immediately later."""
        if self._mic_ready:
            return
        try:
            with self._microphone as source:
                self._recognizer.adjust_for_ambient_noise(
                    source, duration=self._warmup_ambient_seconds
                )
            self._mic_ready = True
        except OSError:
            pass

    def _recognize_audio(self, audio: sr.AudioData) -> str | None:
        global _LAST_CONFIDENCE
        _LAST_CONFIDENCE = 1.0
        try:
            result = self._recognizer.recognize_google(audio, show_all=True)
        except sr.UnknownValueError:
            _LAST_CONFIDENCE = 0.0
            return None
        except sr.RequestError as exc:
            raise RuntimeError(
                "Could not recognize speech. Check your internet connection "
                "or use --type mode."
            ) from exc
        if not result:
            _LAST_CONFIDENCE = 0.0
            return None
        if isinstance(result, str):
            return result
        alternatives = result.get("alternative") or []
        if not alternatives:
            _LAST_CONFIDENCE = 0.0
            return None
        best = alternatives[0]
        text = str(best.get("transcript") or "").strip()
        try:
            _LAST_CONFIDENCE = float(best.get("confidence") or 0.0)
        except (TypeError, ValueError):
            _LAST_CONFIDENCE = 0.0
        if _LAST_CONFIDENCE <= 0 and len(alternatives) > 1:
            _LAST_CONFIDENCE = 0.52
        self.last_confidence = _LAST_CONFIDENCE
        return text or None

    def _capture_once(
        self,
        source: sr.AudioSource,
        *,
        timeout: float,
        phrase_limit: float,
    ) -> sr.AudioData | None:
        try:
            return self._recognizer.listen(
                source,
                timeout=timeout,
                phrase_time_limit=phrase_limit,
            )
        except sr.WaitTimeoutError:
            return None

    def _use_fast_end_of_speech(self) -> None:
        """End capture soon after the user stops talking (command mode)."""
        self._recognizer.pause_threshold = self._command_pause_threshold
        self._recognizer.non_speaking_duration = self._command_non_speaking_duration

    def _use_reply_end_of_speech(self) -> None:
        """End capture soon after the user stops talking (normal chat)."""
        self._recognizer.pause_threshold = self._conversational_pause_threshold
        self._recognizer.non_speaking_duration = self._conversational_non_speaking_duration

    def _restore_end_of_speech(self) -> None:
        self._recognizer.pause_threshold = self._default_pause_threshold
        self._recognizer.non_speaking_duration = self._default_non_speaking_duration

    def _recover_from_receding_audio(self) -> None:
        if not self._movement_recovery_enabled:
            return
        old = self._base_energy
        new = max(self._movement_recovery_min_energy, int(old * self._movement_recovery_factor))
        if new >= old:
            return
        self._base_energy = new
        self._recognizer.energy_threshold = new
        from silva.logger import log_info

        log_info(f"Lowered mic energy threshold to {new} after moving-away audio")

    def _listen_raw(
        self,
        *,
        timeout: float | None = None,
        phrase_limit: float | None = None,
        ambient_seconds: float | None = None,
        fast_end: bool = True,
        announce: bool | None = None,
        reply_mode: bool = False,
    ) -> sr.AudioData | None:
        self._sync_microphone()
        if self._microphone is None:
            self.last_device_error = True
            return None
        timeout = self._default_timeout if timeout is None else timeout
        phrase_limit = self._default_phrase_limit if phrase_limit is None else phrase_limit
        self._recognizer.energy_threshold = self._base_energy

        if ambient_seconds is None:
            if self._mic_ready:
                ambient_seconds = self._quick_ambient_seconds
            else:
                ambient_seconds = self._warmup_ambient_seconds

        if fast_end:
            if reply_mode:
                self._use_reply_end_of_speech()
            else:
                self._use_fast_end_of_speech()

        if announce is None:
            if self._show_listening_each_cycle:
                announce = True
            elif not self._show_listening_prompt:
                announce = False
            else:
                announce = not self._listening_prompt_shown

        from silva.media.devices import portaudio_lock, set_capture_active

        try:
            with self._mic_lock:
                with portaudio_lock():
                    set_capture_active(True)
                    try:
                        with self._microphone as source:
                            if ambient_seconds > 0:
                                self._recognizer.adjust_for_ambient_noise(
                                    source, duration=ambient_seconds
                                )
                            self._mic_ready = True
                            if announce:
                                self.signal_listening()
                                self._listening_prompt_shown = True
                            return self._capture_once(source, timeout=timeout, phrase_limit=phrase_limit)
                    except (OSError, IOError, RuntimeError):
                        self.last_device_error = True
                        self._mic_ready = False
                        self._mic_primed = False
                        return None
                    finally:
                        set_capture_active(False)
        finally:
            if fast_end:
                self._restore_end_of_speech()

    def _merge_phrase(self, first: str, second: str) -> str:
        a = _normalize(first)
        b = _normalize(second)
        if not a:
            return second.strip()
        if not b:
            return first.strip()
        if b.startswith(a):
            return second.strip()
        if a.startswith(b):
            return first.strip()
        return f"{first.strip()} {second.strip()}"

    def listen(self, timeout: float | None = None, phrase_limit: float | None = None) -> str | None:
        text, _audio = self.listen_with_audio(timeout=timeout, phrase_limit=phrase_limit)
        return text

    def listen_with_audio(
        self,
        timeout: float | None = None,
        phrase_limit: float | None = None,
        *,
        announce: bool | None = None,
        fast_end: bool | None = None,
        skip_continuation: bool = False,
    ) -> tuple[str | None, sr.AudioData | None]:
        if fast_end is None:
            fast_end = bool(load_config().get("stt_fast_listen", True))
        timeout = self._active_listen_timeout if timeout is None else timeout
        phrase_limit = self._default_phrase_limit if phrase_limit is None else phrase_limit
        self.last_device_error = False
        self._listen_busy = True
        self._listen_started = time.time()
        try:
            result = self._listen_with_audio_inner(
                timeout=timeout,
                phrase_limit=phrase_limit,
                announce=announce,
                fast_end=fast_end,
                skip_continuation=skip_continuation,
            )
            self.last_receding_audio = detect_receding_audio(result[1])
            if self.last_receding_audio:
                self._recover_from_receding_audio()
            return result
        finally:
            self._listen_busy = False

    def listen_deadline(self, timeout: float | None = None, phrase_limit: float | None = None) -> float:
        wait = self._active_listen_timeout if timeout is None else timeout
        limit = self._default_phrase_limit if phrase_limit is None else phrase_limit
        return max(8.0, float(wait) + float(limit) + 6.0)

    def _listen_with_audio_inner(
        self,
        *,
        timeout: float,
        phrase_limit: float,
        announce: bool | None,
        fast_end: bool,
        skip_continuation: bool,
    ) -> tuple[str | None, sr.AudioData | None]:
        try:
            audio = self._listen_raw(
                timeout=timeout,
                phrase_limit=phrase_limit,
                ambient_seconds=0.0 if self._mic_ready else None,
                fast_end=fast_end,
                announce=announce,
                reply_mode=True,
            )
            if audio is None:
                return None, None
        except (OSError, IOError, RuntimeError) as exc:
            from silva.logger import log_error

            log_error("Microphone stream dropped", exc=exc)
            self.last_device_error = True
            self._mic_ready = False
            self._mic_primed = False
            return None, None

        try:
            text = self._recognize_audio(audio)
        except RuntimeError:
            return None, None
        confidence = last_listen_confidence()
        if text:
            text = _dedupe_repeated_phrase(text)

        quiet_audio = _is_quiet_audio(audio)
        if quiet_audio:
            gain = float(load_config().get("stt_quiet_retry_gain", 3.2))
            boosted_audio = _boost_quiet_audio(audio, gain)
            try:
                boosted_text = self._recognize_audio(boosted_audio)
            except RuntimeError:
                boosted_text = None
            boosted_confidence = last_listen_confidence()
            if boosted_text:
                boosted_text = _dedupe_repeated_phrase(boosted_text)
            improved = bool(
                boosted_text
                and (
                    not text
                    or boosted_confidence > confidence + 0.02
                    or len(boosted_text.split()) > len(text.split())
                )
            )
            if improved:
                text = boosted_text
                confidence = boosted_confidence
            else:
                confidence = min(confidence, boosted_confidence)

        threshold = float(load_config().get("stt_quiet_retry_confidence", 0.55))
        silent_wait = quiet_audio and confidence <= threshold and (
            not text or _needs_more_speech(text) or len(text.split()) <= 2
        )
        if text and not silent_wait and (
            is_complete_command(text) or is_conversational_utterance(text)
        ):
            return text, audio

        if skip_continuation:
            return (None if silent_wait else text), audio

        if text and self._phrase_completion and (_needs_more_speech(text) or silent_wait):
            merged_audio = audio
            profile_partial = _profile_command_partial(text)
            max_attempts = 2 if profile_partial else 1
            cont_timeout = (
                self._profile_continuation_timeout
                if profile_partial
                else self._continuation_timeout
            )

            for _attempt in range(max_attempts):
                from silva.console_view import is_clean_console

                if not is_clean_console() and not silent_wait:
                    print("(Heard part of your command — keep speaking...)")
                extra = self._listen_raw(
                    timeout=cont_timeout,
                    phrase_limit=self._continuation_phrase_limit,
                    ambient_seconds=0.0,
                    fast_end=fast_end,
                    announce=False,
                    reply_mode=False,
                )
                if extra is None:
                    break
                merged_audio = _concat_audio(merged_audio, extra)
                combined_text = self._recognize_audio(merged_audio)
                if combined_text:
                    text = _dedupe_repeated_phrase(combined_text)
                else:
                    extra_text = self._recognize_audio(extra)
                    if extra_text:
                        text = _dedupe_repeated_phrase(self._merge_phrase(text, extra_text))
                if text and is_complete_command(text):
                    return text, merged_audio
                if text and not _needs_more_speech(text):
                    break

            if silent_wait:
                return None, merged_audio
            return text, merged_audio

        if silent_wait:
            return None, audio

        return text, audio

    def capture_audio(
        self, timeout: float | None = None, phrase_limit: float | None = None
    ) -> sr.AudioData | None:
        timeout = 10.0 if timeout is None else timeout
        phrase_limit = 20.0 if phrase_limit is None else phrase_limit
        try:
            print("Listening for voice enrollment...")
            return self._listen_raw(
                timeout=timeout,
                phrase_limit=phrase_limit,
                ambient_seconds=None,
                fast_end=False,
                announce=True,
            )
        except OSError as exc:
            raise RuntimeError(
                f"Microphone unavailable: {exc}. Check your mic or use --type mode."
            ) from exc
