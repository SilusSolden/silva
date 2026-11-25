"""Record any word several ways, then speak the learned sounds in Silva's own voice."""

from __future__ import annotations

import math
import struct
import threading
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass
from typing import Callable

from silva.audio_recorder import VoiceRecorder, default_input_device, pause_live_listen, play_wav_file
from silva.gui.display_manager import register, unregister, watch_shutdown
from silva.gui.monitors import geometry_on_monitor
from silva.logger import log_error, log_info
from silva.users.word_pronunciations import (
    assign_word,
    get_clip,
    list_clips,
    list_word_maps,
    new_clip_path,
    pick_single_word,
    register_clip,
    remember_word_from_clip,
    remove_variant,
    set_active_variant,
    transcribe_clip,
    unassign_word,
)

BG = "#FAFAFA"
ACCENT = "#1A237E"
MUTED = "#607D8B"
MIN_WORD_SECONDS = 0.28
MIN_WORD_RMS = 0.008
SPEECH_LEVEL = 0.04
SILENCE_AFTER_WORD = 0.55
MAX_WORD_SECONDS = 2.2


@dataclass
class PronunciationRecordResult:
    saved: bool = False
    clip_id: str = ""
    wav_file: str = ""
    cancelled: bool = True


@dataclass
class PronunciationAssignResult:
    saved: bool = False
    word: str = ""
    clip_id: str = ""
    spoken_as: str = ""
    cancelled: bool = True


def _parent() -> tk.Misc | None:
    try:
        from silva.gui.display_host import host_root

        return host_root()
    except Exception:
        return None


def _fresh_class(name: str):
    try:
        from silva.dev.live_update import load_gui_module_from_disk

        fresh = load_gui_module_from_disk("silva.gui.word_pronunciation_dialog")
        cls = getattr(fresh, name, None)
        if cls is not None:
            return cls
    except Exception:
        pass
    return globals().get(name)


class _LevelCanvas(tk.Canvas):
    def __init__(self, master, **kwargs) -> None:
        super().__init__(master, width=360, height=42, bg="#ECEFF1", highlightthickness=0, **kwargs)
        self._bars = [
            self.create_rectangle(10 + i * 14, 36, 20 + i * 14, 36, fill="#90A4AE", outline="")
            for i in range(24)
        ]

    def set_level(self, level: float) -> None:
        level = max(0.0, min(1.0, level))
        for index, bar_id in enumerate(self._bars):
            height = 6 + int(28 * level * (0.55 + 0.45 * math.sin(index + level * 8)))
            self.coords(bar_id, 10 + index * 14, 38 - height, 20 + index * 14, 38)


class WordPronunciationRecordDialog:
    def __init__(
        self,
        parent: tk.Misc,
        *,
        user_id: str,
        word: str | None = None,
        on_closed: Callable[[PronunciationRecordResult], None] | None = None,
    ) -> None:
        self.user_id = user_id
        self.word = (word or "").strip()
        self._on_closed = on_closed
        self._closed = False
        self._after_id = None
        self._heard_speech = False
        self._speech_started = 0.0
        self._last_loud = 0.0
        self._saving = False
        pause_live_listen()
        self.recorder = VoiceRecorder()
        _, mic_name = default_input_device()

        self.dialog = tk.Toplevel(parent)
        register(self.dialog)
        watch_shutdown(self.dialog)
        self.dialog.title("Silva - Record pronunciation")
        self.dialog.configure(bg=BG)
        self.dialog.resizable(False, False)
        self.dialog.attributes("-topmost", True)
        self.dialog.protocol("WM_DELETE_WINDOW", self.cancel)
        self.dialog.geometry(geometry_on_monitor(420, 280, anchor="center"))

        body = tkfont.Font(family="Segoe UI", size=10)
        title = tkfont.Font(family="Segoe UI", size=12, weight="bold")
        heading = f'Say only "{self.word}"' if self.word else "Say only the word"
        tk.Label(self.dialog, text=heading, font=title, fg=ACCENT, bg=BG).pack(anchor="w", padx=16, pady=(14, 4))
        tk.Label(
            self.dialog,
            text=(
                "Say the word or phrase once. I will listen, remember how it sounded, and speak it in my voice. "
                "The recording is only a preview and is not played when I talk. "
                f"Mic: {mic_name}"
            ),
            font=body,
            fg=MUTED,
            bg=BG,
            wraplength=380,
            justify="left",
        ).pack(anchor="w", padx=16)

        self._status = tk.Label(self.dialog, text="Starting microphone...", font=body, fg="#455A64", bg=BG)
        self._status.pack(anchor="w", padx=16, pady=(8, 4))
        self._level = _LevelCanvas(self.dialog)
        self._level.pack(padx=16, pady=4)

        row = tk.Frame(self.dialog, bg=BG)
        row.pack(fill="x", padx=16, pady=(10, 16))
        tk.Button(
            row,
            text="Save recording",
            font=body,
            bg="#1B5E20",
            fg="white",
            activebackground="#2E7D32",
            activeforeground="white",
            width=16,
            command=self._save,
        ).pack(side="left")
        tk.Button(row, text="Cancel", font=body, width=10, command=self.cancel).pack(side="right")

        self.recorder.start()
        self._schedule(200, self._tick)
        try:
            self.dialog.lift()
            self.dialog.focus_force()
        except tk.TclError:
            pass

    def _schedule(self, ms: int, callback) -> None:
        self._cancel_after()
        if self._closed:
            return
        try:
            self._after_id = self.dialog.after(ms, callback)
        except tk.TclError:
            self._after_id = None

    def _cancel_after(self) -> None:
        after_id = self._after_id
        self._after_id = None
        if after_id is None:
            return
        try:
            self.dialog.after_cancel(after_id)
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

    def _tick(self) -> None:
        if self._closed:
            return
        try:
            if self.recorder.last_error:
                self._status.config(text=self.recorder.last_error, fg="#C62828")
                return
            if self.recorder.is_recording:
                level = self._peak_level()
                self._level.set_level(level)
                seconds = self.recorder.seconds()
                if level >= SPEECH_LEVEL:
                    if not self._heard_speech:
                        self._heard_speech = True
                        self._speech_started = seconds
                    self._last_loud = seconds
                if (
                    self._heard_speech
                    and (seconds - self._speech_started) >= MIN_WORD_SECONDS
                    and (seconds - self._last_loud) >= SILENCE_AFTER_WORD
                ):
                    self._status.config(text="Heard the word. Saving.", fg="#1B5E20")
                    self._save()
                    return
                if seconds >= MAX_WORD_SECONDS:
                    self._save()
                    return
                self._status.config(
                    text=f"Say only the word ({seconds:.1f}s).",
                    fg="#1B5E20" if level >= SPEECH_LEVEL else "#455A64",
                )
                self._schedule(80, self._tick)
        except tk.TclError:
            self._closed = True

    def _save(self) -> None:
        if self._saving or self._closed:
            return
        self._saving = True
        self.recorder.stop()
        seconds = self.recorder.seconds()
        rms = self.recorder.rms()
        if seconds < MIN_WORD_SECONDS:
            self._status.config(text="That was too short. Say only the word.", fg="#C62828")
            self._restart_record()
            return
        if rms < MIN_WORD_RMS:
            self._status.config(text="I barely heard you. Say the word closer.", fg="#C62828")
            self._restart_record()
            return
        try:
            clip_id, path = new_clip_path(self.user_id)
            self.recorder.save_wav(path)
            clip = register_clip(self.user_id, clip_id, path, label=self.word)
        except Exception as exc:
            log_error("Pronunciation WAV did not save", exc=exc)
            self._status.config(text=str(exc), fg="#C62828")
            self._restart_record()
            return
        log_info(f"Pronunciation WAV saved: {clip.wav_file} ({seconds:.1f}s)")
        self._close(
            PronunciationRecordResult(
                saved=True,
                clip_id=clip.id,
                wav_file=clip.wav_file,
                cancelled=False,
            )
        )

    def _restart_record(self) -> None:
        self._saving = False
        self._heard_speech = False
        self._speech_started = 0.0
        self._last_loud = 0.0
        pause_live_listen()
        self.recorder.start()
        self._schedule(200, self._tick)

    def cancel(self) -> None:
        self.recorder.stop()
        self._close(PronunciationRecordResult())

    def _close(self, result: PronunciationRecordResult) -> None:
        if self._closed:
            return
        self._closed = True
        self._cancel_after()
        if self.recorder.is_recording:
            self.recorder.stop()
        callback = self._on_closed
        try:
            if self.dialog.winfo_exists():
                unregister(self.dialog)
                self.dialog.destroy()
        except tk.TclError:
            pass
        if callback:
            callback(result)


class WordPronunciationAssignDialog:
    def __init__(
        self,
        parent: tk.Misc,
        *,
        user_id: str,
        clip_id: str | None = None,
        word: str | None = None,
        on_closed: Callable[[PronunciationAssignResult], None] | None = None,
    ) -> None:
        self.user_id = user_id
        self._on_closed = on_closed
        self._closed = False
        self._clips = list_clips(user_id)
        self._selected_id = clip_id or (self._clips[0].id if self._clips else "")

        self.dialog = tk.Toplevel(parent)
        register(self.dialog)
        watch_shutdown(self.dialog)
        self.dialog.title("Silva - Assign pronunciation")
        self.dialog.configure(bg=BG)
        self.dialog.resizable(False, False)
        self.dialog.attributes("-topmost", True)
        self.dialog.protocol("WM_DELETE_WINDOW", self.cancel)
        self.dialog.geometry(geometry_on_monitor(460, 420, anchor="center"))

        body = tkfont.Font(family="Segoe UI", size=10)
        title = tkfont.Font(family="Segoe UI", size=12, weight="bold")
        tk.Label(self.dialog, text="Which word is this recording?", font=title, fg=ACCENT, bg=BG).pack(
            anchor="w", padx=16, pady=(14, 4)
        )
        tk.Label(
            self.dialog,
            text="I listen to the recording and keep the word or phrase. Type it if I did not hear it.",
            font=body,
            fg=MUTED,
            bg=BG,
            wraplength=420,
            justify="left",
        ).pack(anchor="w", padx=16)

        word_row = tk.Frame(self.dialog, bg=BG)
        word_row.pack(fill="x", padx=16, pady=(10, 4))
        tk.Label(word_row, text="Word", font=body, bg=BG).pack(side="left")
        self._word_var = tk.StringVar(value=word or "")
        self._entry = tk.Entry(word_row, textvariable=self._word_var, font=body)
        self._entry.pack(side="left", fill="x", expand=True, padx=8)
        tk.Button(word_row, text="Speak word", font=body, command=self._listen_word).pack(side="left")

        tk.Label(self.dialog, text="Saved WAV files", font=body, bg=BG).pack(anchor="w", padx=16, pady=(8, 2))
        list_frame = tk.Frame(self.dialog, bg=BG)
        list_frame.pack(fill="both", expand=True, padx=16)
        self._listbox = tk.Listbox(list_frame, font=body, height=8, activestyle="none")
        self._listbox.pack(side="left", fill="both", expand=True)
        scroll = tk.Scrollbar(list_frame, command=self._listbox.yview)
        scroll.pack(side="right", fill="y")
        self._listbox.config(yscrollcommand=scroll.set)
        self._listbox.bind("<<ListboxSelect>>", self._on_select)
        self._fill_clips()
        self._fill_word_from_clip()

        self._status = tk.Label(self.dialog, text="", font=body, fg="#1B5E20", bg=BG, wraplength=420, justify="left")
        self._status.pack(anchor="w", padx=16, pady=(6, 0))

        row = tk.Frame(self.dialog, bg=BG)
        row.pack(fill="x", padx=16, pady=(8, 16))
        tk.Button(row, text="Play WAV", font=body, width=12, command=self._play).pack(side="left")
        tk.Button(
            row,
            text="Save override",
            font=body,
            bg="#1B5E20",
            fg="white",
            activebackground="#2E7D32",
            activeforeground="white",
            width=14,
            command=self._save,
        ).pack(side="left", padx=8)
        tk.Button(row, text="Cancel", font=body, width=10, command=self.cancel).pack(side="right")
        self._entry.focus_set()

    def _fill_clips(self) -> None:
        self._listbox.delete(0, tk.END)
        selected = 0
        for index, clip in enumerate(self._clips):
            name = PathName(clip.wav_file)
            label = f"{name}    {clip.created_at}"
            if clip.label:
                label = f"{name}    ({clip.label})    {clip.created_at}"
            self._listbox.insert(tk.END, label)
            if clip.id == self._selected_id:
                selected = index
        if self._clips:
            self._listbox.selection_set(selected)
            self._listbox.see(selected)

    def _selected_clip(self):
        selection = self._listbox.curselection()
        if selection:
            return self._clips[selection[0]]
        if self._selected_id:
            return get_clip(self.user_id, self._selected_id)
        return self._clips[0] if self._clips else None

    def _on_select(self, _event=None) -> None:
        clip = self._selected_clip()
        if clip is not None:
            self._selected_id = clip.id
            self._fill_word_from_clip()

    def _fill_word_from_clip(self) -> None:
        clip = self._selected_clip()
        if clip is None:
            return
        if self._word_var.get().strip():
            return

        def worker() -> None:
            heard = pick_single_word(transcribe_clip(clip.wav_file))
            try:
                self.dialog.after(0, lambda: self._apply_transcribed(heard))
            except tk.TclError:
                pass

        threading.Thread(target=worker, daemon=True, name="silva-pronounce-transcribe").start()

    def _apply_transcribed(self, heard: str) -> None:
        if self._closed or self._word_var.get().strip():
            return
        if heard:
            self._word_var.set(heard)
            self._status.config(text=f'Heard "{heard}". That word will be saved.', fg="#1B5E20")
            return
        self._status.config(text="Type the word or phrase this recording is for.", fg="#455A64")

    def _play(self) -> None:
        clip = self._selected_clip()
        if clip is None:
            self._status.config(text="Save a recording first.", fg="#C62828")
            return
        try:
            play_wav_file(clip.wav_file)
        except Exception as exc:
            self._status.config(text=str(exc), fg="#C62828")

    def _listen_word(self) -> None:
        self._status.config(text="Listening for the word...", fg="#455A64")
        pause_live_listen()

        def worker() -> None:
            text = ""
            error = ""
            try:
                import speech_recognition as sr

                recognizer = sr.Recognizer()
                with sr.Microphone() as source:
                    recognizer.adjust_for_ambient_noise(source, duration=0.25)
                    audio = recognizer.listen(source, timeout=6, phrase_time_limit=4)
                text = recognizer.recognize_google(audio)
            except Exception as exc:
                error = str(exc) or "I did not catch a word."
            try:
                self.dialog.after(0, lambda: self._apply_spoken(text, error))
            except tk.TclError:
                pass

        threading.Thread(target=worker, daemon=True, name="silva-pronounce-word").start()

    def _apply_spoken(self, text: str, error: str) -> None:
        if self._closed:
            return
        word = pick_single_word(text)
        if word:
            self._word_var.set(word)
            self._status.config(text=f'Heard "{word}".', fg="#1B5E20")
            return
        self._status.config(text=error or "I did not catch a word. Type it instead.", fg="#C62828")

    def _save(self) -> None:
        clip = self._selected_clip()
        if clip is None:
            self._status.config(text="Pick a saved WAV file.", fg="#C62828")
            return
        try:
            mapped = remember_word_from_clip(self.user_id, clip.id, expected_word=self._word_var.get())
        except RuntimeError:
            try:
                mapped = assign_word(self.user_id, self._word_var.get(), clip.id)
            except RuntimeError as exc:
                self._status.config(text=str(exc), fg="#C62828")
                return
        log_info(f"Pronunciation memory saved: {mapped.word!r} -> {mapped.wav_file}")
        self._close(
            PronunciationAssignResult(
                saved=True,
                word=mapped.word,
                clip_id=mapped.clip_id,
                spoken_as=mapped.spoken_as,
                cancelled=False,
            )
        )

    def cancel(self) -> None:
        self._close(PronunciationAssignResult())

    def _close(self, result: PronunciationAssignResult) -> None:
        if self._closed:
            return
        self._closed = True
        callback = self._on_closed
        try:
            if self.dialog.winfo_exists():
                unregister(self.dialog)
                self.dialog.destroy()
        except tk.TclError:
            pass
        if callback:
            callback(result)


def PathName(path: str) -> str:
    return str(path).replace("\\", "/").rsplit("/", 1)[-1]


class WordPronunciationEditorDialog:
    def __init__(
        self,
        parent: tk.Misc,
        *,
        user_id: str,
        word: str | None = None,
        on_closed: Callable[[], None] | None = None,
    ) -> None:
        self.user_id = user_id
        self._focus_word = (word or "").strip().lower()
        self._on_closed = on_closed
        self._closed = False
        self._maps = []
        self._clips = []

        self.dialog = tk.Toplevel(parent)
        register(self.dialog)
        watch_shutdown(self.dialog)
        self.dialog.title("Silva - Edit pronunciations")
        self.dialog.configure(bg=BG)
        self.dialog.resizable(True, True)
        self.dialog.attributes("-topmost", True)
        self.dialog.protocol("WM_DELETE_WINDOW", self._close)
        self.dialog.geometry(geometry_on_monitor(520, 480, anchor="center"))

        body = tkfont.Font(family="Segoe UI", size=10)
        title = tkfont.Font(family="Segoe UI", size=12, weight="bold")
        tk.Label(self.dialog, text="Custom word pronunciations", font=title, fg=ACCENT, bg=BG).pack(
            anchor="w", padx=16, pady=(14, 4)
        )
        tk.Label(
            self.dialog,
            text="Any word or phrase can have many recordings. I learn how each one sounded and speak it in my own voice; the WAV is only a preview. 'Sounds like' is optional when I mishear you.",
            font=body,
            fg=MUTED,
            bg=BG,
            wraplength=480,
            justify="left",
        ).pack(anchor="w", padx=16)

        list_frame = tk.Frame(self.dialog, bg=BG)
        list_frame.pack(fill="both", expand=True, padx=16, pady=(8, 4))
        self._listbox = tk.Listbox(list_frame, font=body, height=10, activestyle="none")
        self._listbox.pack(side="left", fill="both", expand=True)
        scroll = tk.Scrollbar(list_frame, command=self._listbox.yview)
        scroll.pack(side="right", fill="y")
        self._listbox.config(yscrollcommand=scroll.set)
        self._listbox.bind("<<ListboxSelect>>", self._on_select)

        form = tk.Frame(self.dialog, bg=BG)
        form.pack(fill="x", padx=16, pady=4)
        tk.Label(form, text="Word", font=body, bg=BG).grid(row=0, column=0, sticky="w")
        self._word_var = tk.StringVar()
        tk.Entry(form, textvariable=self._word_var, font=body, width=28).grid(row=0, column=1, sticky="ew", padx=8)
        tk.Label(form, text="Recording", font=body, bg=BG).grid(row=1, column=0, sticky="w", pady=(8, 0))
        self._clip_var = tk.StringVar()
        self._clip_menu = tk.OptionMenu(form, self._clip_var, "")
        self._clip_menu.config(font=body, width=36)
        self._clip_menu.grid(row=1, column=1, sticky="ew", padx=8, pady=(8, 0))
        tk.Label(form, text="Sounds like", font=body, bg=BG).grid(row=2, column=0, sticky="w", pady=(8, 0))
        self._sound_var = tk.StringVar()
        tk.Entry(form, textvariable=self._sound_var, font=body, width=28).grid(row=2, column=1, sticky="ew", padx=8, pady=(8, 0))
        form.columnconfigure(1, weight=1)

        self._status = tk.Label(self.dialog, text="", font=body, fg="#1B5E20", bg=BG, wraplength=480, justify="left")
        self._status.pack(anchor="w", padx=16, pady=(4, 0))

        row = tk.Frame(self.dialog, bg=BG)
        row.pack(fill="x", padx=16, pady=(8, 16))
        tk.Button(row, text="Preview", font=body, width=8, command=self._play).pack(side="left")
        tk.Button(row, text="Add pronunciation", font=body, width=16, command=self._save_match).pack(side="left", padx=4)
        tk.Button(row, text="Use", font=body, width=6, command=self._activate_selected).pack(side="left")
        tk.Button(row, text="Remove one", font=body, width=11, command=self._remove_selected_variant).pack(side="left", padx=4)
        tk.Button(row, text="Remove word", font=body, width=12, command=self._remove_word).pack(side="left")
        tk.Button(row, text="Close", font=body, width=8, command=self._close).pack(side="right")

        self._refresh()
        self._select_focus_word()

    def _clip_label(self, clip) -> str:
        name = PathName(clip.wav_file)
        if clip.label:
            return f"{name}  ({clip.label})"
        return name

    def _refresh_clip_menu(self) -> None:
        menu = self._clip_menu["menu"]
        menu.delete(0, "end")
        labels = [self._clip_label(clip) for clip in self._clips]
        if not labels:
            labels = [""]
        for label, clip in zip(labels, self._clips or [None]):
            menu.add_command(
                label=label,
                command=lambda value=label, clip_id=getattr(clip, "id", ""): self._pick_clip(value, clip_id),
            )
        current = self._selected_map()
        if current:
            clip = get_clip(self.user_id, current.clip_id)
            if clip is not None:
                self._clip_var.set(self._clip_label(clip))
                return
        if self._clips:
            self._clip_var.set(self._clip_label(self._clips[0]))
        else:
            self._clip_var.set("")

    def _pick_clip(self, label: str, clip_id: str) -> None:
        self._clip_var.set(label)
        self._picked_clip_id = clip_id

    def _refresh(self) -> None:
        self._maps = list_word_maps(self.user_id)
        self._clips = list_clips(self.user_id)
        self._picked_clip_id = ""
        self._listbox.delete(0, tk.END)
        for item in self._maps:
            shown = PathName(item.wav_file) or item.word
            sound = f"  ({item.spoken_as})" if item.spoken_as and item.spoken_as != item.word else ""
            star = "  *" if item.active else ""
            self._listbox.insert(tk.END, f"{item.word}{star}  →  {shown}{sound}")
        self._refresh_clip_menu()
        if not self._maps:
            self._status.config(text="No word overrides yet. Record one, then assign it.", fg="#455A64")

    def _select_focus_word(self) -> None:
        if not self._focus_word:
            if self._maps:
                self._listbox.selection_set(0)
                self._on_select()
            return
        for index, item in enumerate(self._maps):
            if item.word == self._focus_word:
                self._listbox.selection_set(index)
                self._listbox.see(index)
                self._on_select()
                return
        self._word_var.set(self._focus_word)
        if self._maps:
            self._listbox.selection_set(0)
            self._on_select()

    def _selected_map(self):
        selection = self._listbox.curselection()
        if not selection:
            return None
        return self._maps[selection[0]]

    def _on_select(self, _event=None) -> None:
        item = self._selected_map()
        if item is None:
            return
        self._word_var.set(item.word)
        self._sound_var.set("" if item.spoken_as == item.word else item.spoken_as)
        clip = get_clip(self.user_id, item.clip_id)
        if clip is not None:
            self._clip_var.set(self._clip_label(clip))
            self._picked_clip_id = clip.id

    def _chosen_clip_id(self) -> str:
        if getattr(self, "_picked_clip_id", ""):
            return self._picked_clip_id
        wanted = self._clip_var.get()
        for clip in self._clips:
            if self._clip_label(clip) == wanted:
                return clip.id
        item = self._selected_map()
        return item.clip_id if item else ""

    def _play(self) -> None:
        clip = get_clip(self.user_id, self._chosen_clip_id())
        if clip is None:
            self._status.config(text="Pick a WAV file first.", fg="#C62828")
            return
        try:
            play_wav_file(clip.wav_file)
        except Exception as exc:
            self._status.config(text=str(exc), fg="#C62828")

    def _save_match(self) -> None:
        sound = self._sound_var.get().strip()
        try:
            mapped = assign_word(
                self.user_id,
                self._word_var.get(),
                self._chosen_clip_id(),
                spoken_as=sound or None,
                context=sound,
            )
        except RuntimeError as exc:
            self._status.config(text=str(exc), fg="#C62828")
            return
        self._focus_word = mapped.word
        self._refresh()
        self._select_focus_word()
        self._sound_var.set("" if mapped.spoken_as == mapped.word else mapped.spoken_as)
        self._status.config(
            text=f'Added a pronunciation for "{mapped.word}". I will speak it in my voice; the newest one is active.',
            fg="#1B5E20",
        )

    def _activate_selected(self) -> None:
        item = self._selected_map()
        if item is None:
            self._status.config(text="Select a pronunciation to use.", fg="#C62828")
            return
        variant_id = item.variant_id or item.clip_id
        if not set_active_variant(self.user_id, item.word, variant_id):
            self._status.config(text="I could not activate that pronunciation.", fg="#C62828")
            return
        self._focus_word = item.word
        self._refresh()
        self._select_focus_word()
        self._status.config(text=f'Using "{item.spoken_as}" for "{item.word}".', fg="#1B5E20")

    def _remove_selected_variant(self) -> None:
        item = self._selected_map()
        if item is None:
            self._status.config(text="Select a pronunciation to remove.", fg="#C62828")
            return
        variant_id = item.variant_id or item.clip_id
        if not remove_variant(self.user_id, item.word, variant_id):
            self._status.config(text="I could not remove that pronunciation.", fg="#C62828")
            return
        removed = item.spoken_as
        self._focus_word = item.word
        self._refresh()
        self._select_focus_word()
        self._status.config(text=f'Removed the "{removed}" pronunciation for "{item.word}".', fg="#455A64")

    def _remove_word(self) -> None:
        word = self._word_var.get().strip() or (self._selected_map().word if self._selected_map() else "")
        if not word:
            self._status.config(text="Select a word to remove.", fg="#C62828")
            return
        unassign_word(self.user_id, word)
        self._focus_word = ""
        self._word_var.set("")
        self._refresh()
        self._status.config(text=f'Removed the override for "{word}".', fg="#455A64")

    def _rerecord(self) -> None:
        word = self._word_var.get().strip()
        if not word:
            self._status.config(text="Type the word to re-record first.", fg="#C62828")
            return
        context = self._sound_var.get().strip()
        self.dialog.withdraw()

        def after_record(result: PronunciationRecordResult) -> None:
            if result.saved and result.clip_id:
                try:
                    remember_word_from_clip(self.user_id, result.clip_id, expected_word=word, context=context)
                except RuntimeError:
                    try:
                        assign_word(self.user_id, word, result.clip_id)
                    except RuntimeError as exc:
                        self._status.config(text=str(exc), fg="#C62828")
            try:
                self.dialog.deiconify()
                self.dialog.lift()
            except tk.TclError:
                return
            self._focus_word = word.lower()
            self._refresh()
            self._select_focus_word()
            if result.saved:
                self._status.config(text=f'Updated the recording for "{word}".', fg="#1B5E20")
            else:
                self._status.config(text="Re-record cancelled.", fg="#455A64")

        WordPronunciationRecordDialog(
            self.dialog.master,
            user_id=self.user_id,
            word=word,
            on_closed=after_record,
        )

    def _close(self) -> None:
        if self._closed:
            return
        self._closed = True
        callback = self._on_closed
        try:
            if self.dialog.winfo_exists():
                unregister(self.dialog)
                self.dialog.destroy()
        except tk.TclError:
            pass
        if callback:
            callback()


def _run_on_host(opener) -> None:
    parent = _parent()
    if parent is None:
        raise RuntimeError("Silva display is not ready.")
    parent.after(0, lambda: opener(parent))


def run_pronunciation_record_blocking(user_id: str, word: str | None = None) -> PronunciationRecordResult:
    holder: dict = {"value": PronunciationRecordResult()}
    done = threading.Event()

    def on_closed(result: PronunciationRecordResult) -> None:
        holder["value"] = result
        done.set()

    def opener(parent: tk.Misc) -> None:
        cls = _fresh_class("WordPronunciationRecordDialog") or WordPronunciationRecordDialog
        cls(parent, user_id=user_id, word=word, on_closed=on_closed)

    try:
        _run_on_host(opener)
        done.wait(timeout=300)
    except Exception as exc:
        log_error("Pronunciation recorder could not open", exc=exc)
        done.set()
    return holder["value"]


def run_pronunciation_assign_blocking(
    user_id: str,
    *,
    clip_id: str | None = None,
    word: str | None = None,
) -> PronunciationAssignResult:
    holder: dict = {"value": PronunciationAssignResult()}
    done = threading.Event()

    def on_closed(result: PronunciationAssignResult) -> None:
        holder["value"] = result
        done.set()

    def opener(parent: tk.Misc) -> None:
        cls = _fresh_class("WordPronunciationAssignDialog") or WordPronunciationAssignDialog
        cls(parent, user_id=user_id, clip_id=clip_id, word=word, on_closed=on_closed)

    try:
        _run_on_host(opener)
        done.wait(timeout=300)
    except Exception as exc:
        log_error("Pronunciation assign window could not open", exc=exc)
        done.set()
    return holder["value"]


def run_pronunciation_editor_blocking(user_id: str, word: str | None = None) -> None:
    done = threading.Event()

    def opener(parent: tk.Misc) -> None:
        cls = _fresh_class("WordPronunciationEditorDialog") or WordPronunciationEditorDialog
        cls(parent, user_id=user_id, word=word, on_closed=done.set)

    try:
        _run_on_host(opener)
        done.wait(timeout=600)
    except Exception as exc:
        log_error("Pronunciation editor could not open", exc=exc)
        done.set()
