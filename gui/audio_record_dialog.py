"""Record a user's voice into their WAV profile — one recorder, not stacked windows."""

from __future__ import annotations

import math
import struct
import threading
import tkinter as tk
from dataclasses import dataclass
from typing import Callable

from silva.audio_recorder import VoiceRecorder, default_input_device, pause_live_listen
from silva.gui.display_manager import register, unregister
from silva.logger import log_error, log_info
from silva.users.voice_id import save_voice_profile, wav_path


@dataclass
class AudioRecordResult:
    saved: bool
    user_id: str
    name: str
    wav_file: str
    cancelled: bool = True


class _MicCanvas(tk.Canvas):
    def __init__(self, master, **kwargs) -> None:
        super().__init__(master, width=220, height=88, bg="#ECEFF1", highlightthickness=0, **kwargs)
        self._bars: list[int] = []
        self._draw_base()

    def _draw_base(self) -> None:
        self.delete("all")
        self._bars = []
        for i in range(8):
            bar = self.create_rectangle(16 + i * 26, 70, 32 + i * 26, 70, fill="#1E88E5", outline="")
            self._bars.append(bar)

    def set_level(self, level: float) -> None:
        level = max(0.0, min(1.0, level))
        for index, bar_id in enumerate(self._bars):
            height = 8 + int(54 * level * (0.55 + 0.45 * math.sin(index + level * 8)))
            self.coords(bar_id, 16 + index * 26, 80 - height, 32 + index * 26, 80)


class VoiceRecordStrip(tk.Frame):
    """In-window recorder so Record Voice does not stack a second recording popup."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        user_id: str,
        user_name: str,
        on_closed: Callable[[AudioRecordResult], None] | None = None,
    ) -> None:
        super().__init__(master, bg="#E8EAF6", padx=10, pady=8)
        self.user_id = user_id
        self.user_name = user_name
        self._on_closed = on_closed
        self._closed = False
        self._saved_path = ""
        self._after_id = None
        self.dialog = self

        pause_live_listen()
        self.recorder = VoiceRecorder()
        _, mic_name = default_input_device()

        import tkinter.font as tkfont

        body = tkfont.Font(family="Segoe UI", size=10)
        title = tkfont.Font(family="Segoe UI", size=10, weight="bold")

        tk.Label(
            self,
            text=f"Recording {user_name} — speak, then Save Voice",
            font=title,
            bg="#E8EAF6",
            fg="#1A237E",
        ).pack(anchor="w")
        tk.Label(
            self,
            text=f"Saves to {wav_path(user_id).name}  |  Mic: {mic_name}",
            font=body,
            bg="#E8EAF6",
            fg="#607D8B",
        ).pack(anchor="w")
        self._status = tk.Label(
            self,
            text="Starting microphone...",
            font=body,
            bg="#E8EAF6",
            fg="#455A64",
            wraplength=640,
            justify="left",
        )
        self._status.pack(anchor="w", pady=(4, 2))

        self._mic = _MicCanvas(self)
        self._mic.pack(pady=4)

        row = tk.Frame(self, bg="#E8EAF6")
        row.pack(anchor="w", pady=(2, 0))
        tk.Button(
            row,
            text="Save Voice",
            font=body,
            bg="#1B5E20",
            fg="white",
            activebackground="#2E7D32",
            activeforeground="white",
            width=14,
            command=self._save_voice,
        ).pack(side="left", padx=(0, 6))
        tk.Button(row, text="Cancel", font=body, width=10, command=self.cancel).pack(side="left")

        self.recorder.start()
        self._schedule(250, self._check_started)

    def _schedule(self, ms: int, callback) -> None:
        self._cancel_after()
        if self._closed:
            return
        try:
            self._after_id = self.after(ms, callback)
        except tk.TclError:
            self._after_id = None

    def _cancel_after(self) -> None:
        after_id = self._after_id
        self._after_id = None
        if after_id is None:
            return
        try:
            self.after_cancel(after_id)
        except tk.TclError:
            pass

    def _peak_level(self) -> float:
        frames = self.recorder.snapshot_frames()
        if not frames:
            return 0.0
        chunk = frames[-1]
        if len(chunk) < 2:
            return 0.0
        count = len(chunk) // 2
        samples = struct.unpack(f"{count}h", chunk[: count * 2])
        if not samples:
            return 0.0
        return min(1.0, max(abs(value) for value in samples) / 32768.0)

    def _alive(self) -> bool:
        if self._closed:
            return False
        try:
            return bool(self.winfo_exists())
        except tk.TclError:
            return False

    def _animate(self) -> None:
        if not self._alive():
            return
        try:
            if self.recorder.is_recording:
                level = self._peak_level()
                self._mic.set_level(level)
                seconds = self.recorder.seconds()
                if level >= 0.04:
                    self._status.config(
                        text=f"Hearing you ({seconds:.1f}s). Click Save Voice when you're done.",
                        fg="#1B5E20",
                    )
                else:
                    self._status.config(
                        text=f"Listening... speak now ({seconds:.1f}s).",
                        fg="#455A64",
                    )
                self._schedule(80, self._animate)
        except tk.TclError:
            self._closed = True

    def _check_started(self) -> None:
        if not self._alive():
            return
        try:
            if self.recorder.last_error:
                self._status.config(
                    text=self.recorder.last_error + " Click Cancel, then Record Voice again.",
                    fg="#C62828",
                )
                return
            if self.recorder.is_recording:
                self._animate()
                return
        except tk.TclError:
            self._closed = True
            return
        self._schedule(200, self._check_started)

    def stop_and_save(self) -> AudioRecordResult:
        self.recorder.stop()
        reason = self.recorder.reject_reason()
        if reason:
            raise RuntimeError(reason)
        audio = self.recorder.to_audio_data()
        if audio is None:
            raise RuntimeError("No audio to save.")
        path = save_voice_profile(
            self.user_id,
            audio,
            name=self.user_name,
            wav_file=wav_path(self.user_id),
        )
        from silva.gui.voice_panel import SetVoiceResult
        from silva.users.enrollment import apply_voice_enrollment

        enrolled = apply_voice_enrollment(
            SetVoiceResult(
                saved=True,
                name=self.user_name,
                user_id=self.user_id,
                wav_file=str(path),
                cancelled=False,
            )
        )
        if enrolled is None:
            raise RuntimeError("Voice file saved but the profile could not be updated.")
        self._saved_path = str(path)
        log_info(
            f"Voice WAV enrolled for {self.user_name}: {path} "
            f"({self.recorder.seconds():.1f}s, rms {self.recorder.rms():.3f})"
        )
        return AudioRecordResult(
            saved=True,
            user_id=self.user_id,
            name=self.user_name,
            wav_file=str(path),
            cancelled=False,
        )

    def _save_voice(self) -> None:
        if self._closed:
            return
        try:
            result = self.stop_and_save()
        except Exception as exc:
            if "barely heard" in str(exc).lower() or "too short" in str(exc).lower():
                log_info(str(exc))
            else:
                log_error("Voice recording did not save", exc=exc)
            try:
                self._status.config(text=str(exc), fg="#C62828")
            except tk.TclError:
                return
            if not self.recorder.is_recording:
                pause_live_listen()
                self.recorder.start()
                self._schedule(250, self._check_started)
            return
        self._status.config(text=f"Voice saved to {wav_path(self.user_id).name}.", fg="#1B5E20")
        self._close(result)

    def cancel(self) -> None:
        self.recorder.stop()
        self._close(
            AudioRecordResult(
                saved=bool(self._saved_path),
                user_id=self.user_id,
                name=self.user_name,
                wav_file=self._saved_path,
                cancelled=not bool(self._saved_path),
            )
        )

    def _close(self, result: AudioRecordResult) -> None:
        if self._closed:
            return
        self._closed = True
        self._cancel_after()
        self.recorder.stop()
        if self._on_closed:
            self._on_closed(result)
        try:
            self.destroy()
        except tk.TclError:
            pass


class VoiceExampleBar(tk.Frame):
    """Saved WAV shown under Record Voice as the profile's voice example."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        user_id: str,
        user_name: str,
        wav_file,
    ) -> None:
        super().__init__(master, bg="#ECEFF1", padx=10, pady=8)
        from silva.audio_recorder import play_wav_file, wav_preview_levels

        preview = wav_preview_levels(wav_file)
        self._wav_file = wav_file

        import tkinter.font as tkfont

        title = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        body = tkfont.Font(family="Segoe UI", size=9)

        tk.Label(
            self,
            text=f"{user_name}'s saved voice example",
            font=title,
            bg="#ECEFF1",
            fg="#1A237E",
        ).pack(anchor="w")
        tk.Label(
            self,
            text=f"{preview['name']}  •  {preview['seconds']:.1f}s  •  used to auto-switch this profile",
            font=body,
            bg="#ECEFF1",
            fg="#546E7A",
        ).pack(anchor="w")

        canvas = tk.Canvas(self, width=520, height=46, bg="#FFFFFF", highlightthickness=0)
        canvas.pack(fill="x", pady=(6, 4))
        levels = preview["levels"]
        bar_w = max(2, int(500 / max(1, len(levels))))
        for index, level in enumerate(levels):
            height = 4 + int(34 * level)
            x = 8 + index * bar_w
            canvas.create_rectangle(x, 42 - height, x + bar_w - 1, 42, fill="#1565C0", outline="")

        def _play() -> None:
            try:
                play_wav_file(self._wav_file)
            except Exception as exc:
                log_info(f"Could not play saved voice: {exc}")

        tk.Button(self, text="Play example", font=body, width=14, command=_play).pack(anchor="w")


class AudioRecordDialog:
    """Standalone Record Voice popup. Saves only when the user clicks Save Voice."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        user_id: str,
        user_name: str,
        on_closed: Callable[[AudioRecordResult], None] | None = None,
    ) -> None:
        self.user_id = user_id
        self.user_name = user_name
        self._on_closed = on_closed
        self._closed = False
        pause_live_listen()

        self.window = tk.Toplevel(parent)
        register(self.window)
        self.window.title("Silva - Record Voice")
        self.window.resizable(False, False)
        try:
            self.window.attributes("-topmost", True)
        except tk.TclError:
            pass
        self.window.geometry("420x340")
        self.window.transient(parent)

        import tkinter.font as tkfont

        body = tkfont.Font(family="Segoe UI", size=9)
        tk.Label(
            self.window,
            text="Only what you say in this popup is saved. Click Save Voice to confirm.",
            font=body,
            fg="#546E7A",
            wraplength=380,
            justify="left",
        ).pack(anchor="w", padx=12, pady=(10, 0))

        self.strip = VoiceRecordStrip(
            self.window,
            user_id=user_id,
            user_name=user_name,
            on_closed=self._on_strip_closed,
        )
        self.strip.pack(fill="both", expand=True, padx=8, pady=8)
        self.window.protocol("WM_DELETE_WINDOW", self.cancel)
        try:
            self.window.focus_force()
            self.window.lift()
        except tk.TclError:
            pass

    def cancel(self) -> None:
        self.strip.cancel()

    def _save_voice(self) -> None:
        self.strip._save_voice()

    def _on_strip_closed(self, result: AudioRecordResult) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            unregister(self.window)
            if self.window.winfo_exists():
                self.window.destroy()
        except tk.TclError:
            pass
        if self._on_closed:
            self._on_closed(result)


def get_record_dialog_class():
    """Latest Record Voice popup. Loaded on the Tk thread when the window opens."""
    try:
        from silva.dev.live_update import load_gui_module_from_disk

        fresh = load_gui_module_from_disk("silva.gui.audio_record_dialog")
        cls = getattr(fresh, "AudioRecordDialog", None)
        if cls is not None:
            return cls
    except Exception:
        pass
    return AudioRecordDialog


def run_audio_record_blocking(user: dict) -> AudioRecordResult:
    holder: dict = {
        "value": AudioRecordResult(
            saved=False,
            user_id=user.get("id", ""),
            name=user.get("name", ""),
            wav_file="",
            cancelled=True,
        )
    }
    done = threading.Event()

    def on_closed(result: AudioRecordResult) -> None:
        holder["value"] = result
        done.set()

    def _open(parent: tk.Misc) -> None:
        AudioRecordDialog(
            parent,
            user_id=user["id"],
            user_name=user.get("name", "User"),
            on_closed=on_closed,
        )

    try:
        from silva.gui.display_host import host_root

        parent = host_root()
    except Exception:
        parent = None

    if parent is not None:
        try:
            parent.after(0, lambda: _open(parent))
            done.wait(timeout=300)
            return holder["value"]
        except tk.TclError as exc:
            log_error("Voice recorder could not use the display host", exc=exc)

    def _run() -> None:
        root = tk.Tk()
        root.title("Silva - Record Voice")
        root.resizable(False, False)
        register(root)

        def _closed(result: AudioRecordResult) -> None:
            holder["value"] = result
            try:
                root.quit()
            except tk.TclError:
                pass
            done.set()

        strip = VoiceRecordStrip(
            root,
            user_id=user["id"],
            user_name=user.get("name", "User"),
            on_closed=_closed,
        )
        strip.pack(fill="both", expand=True, padx=8, pady=8)
        root.protocol("WM_DELETE_WINDOW", strip.cancel)
        root.mainloop()
        unregister(root)
        try:
            root.destroy()
        except tk.TclError:
            pass

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=300)
    return holder["value"]
