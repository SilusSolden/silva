"""Phrase recorder popup — camera-style record button (white off, red recording)."""

from __future__ import annotations

import math
import struct
import threading
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass
from typing import Callable

from silva.audio_recorder import VoiceRecorder, default_input_device
from silva.gui.display_manager import register, unregister
from silva.gui.monitors import geometry_on_monitor
from silva.logger import log_error, log_info
from silva.users.phrase_recordings import (
    DEFAULT_INTENDED_PHRASES,
    delete_phrase_sample,
    list_phrase_samples,
    save_phrase_sample,
)


@dataclass
class PhraseRecordResult:
    saved_count: int = 0
    cancelled: bool = True


_popup_lock = threading.Lock()
_popup: PhraseRecordDialog | None = None


class _RecordButton(tk.Canvas):
    def __init__(self, master, *, command: Callable[[], None], **kwargs) -> None:
        super().__init__(master, width=88, height=88, bg="#FAFAFA", highlightthickness=0, **kwargs)
        self._command = command
        self._recording = False
        self._outer = self.create_oval(8, 8, 80, 80, fill="#FFFFFF", outline="#CFD8DC", width=3)
        self._inner = self.create_oval(26, 26, 62, 62, fill="#FFFFFF", outline="")
        self.bind("<Button-1>", self._click)

    def set_recording(self, active: bool) -> None:
        self._recording = active
        if active:
            self.itemconfig(self._outer, fill="#FFEBEE", outline="#E53935")
            self.itemconfig(self._inner, fill="#E53935", outline="")
        else:
            self.itemconfig(self._outer, fill="#FFFFFF", outline="#CFD8DC")
            self.itemconfig(self._inner, fill="#FFFFFF", outline="")

    def _click(self, _event) -> None:
        self._command()


class PhraseRecordDialog:
    def __init__(
        self,
        parent: tk.Misc,
        *,
        user_id: str,
        user_name: str,
        on_closed: Callable[[PhraseRecordResult], None] | None = None,
    ) -> None:
        self.user_id = user_id
        self.user_name = user_name
        self._on_closed = on_closed
        self._closed = False
        self._saved_count = 0
        self.recorder = VoiceRecorder()
        _, mic_name = default_input_device()

        self.dialog = tk.Toplevel(parent)
        register(self.dialog)
        self.dialog.title("Silva - Phrase Recorder")
        self.dialog.resizable(False, False)
        self.dialog.attributes("-topmost", True)
        self.dialog.transient(parent)
        self.dialog.protocol("WM_DELETE_WINDOW", self._close)

        width, height = 440, 560
        self.dialog.geometry(geometry_on_monitor(width, height, anchor="center"))

        body = tkfont.Font(family="Segoe UI", size=10)
        title = tkfont.Font(family="Segoe UI", size=11, weight="bold")

        tk.Label(
            self.dialog,
            text=f"Phrase recorder — {user_name}",
            font=title,
            fg="#1A237E",
        ).pack(pady=(14, 4))
        tk.Label(self.dialog, text=f"Microphone: {mic_name}", font=body, fg="#607D8B").pack()

        tk.Label(
            self.dialog,
            text="Record how YOU say a phrase. Silva uses these silently when speech recognition mishears you.",
            font=body,
            fg="#455A64",
            wraplength=400,
            justify="left",
        ).pack(pady=(8, 6), padx=16)

        form = tk.Frame(self.dialog)
        form.pack(fill="x", padx=16, pady=4)
        tk.Label(
            form,
            text="Command Silva should run (pick a preset or type any command):",
            font=body,
            anchor="w",
        ).pack(fill="x")
        self._phrase_var = tk.StringVar(value=DEFAULT_INTENDED_PHRASES[0])
        self._phrase_menu = tk.OptionMenu(form, self._phrase_var, *DEFAULT_INTENDED_PHRASES)
        self._phrase_menu.config(font=body, width=42)
        self._phrase_menu.pack(fill="x", pady=(4, 0))
        tk.Label(form, text="Or type your own command:", font=body, anchor="w").pack(fill="x", pady=(8, 0))
        self._custom_entry = tk.Entry(form, font=body)
        self._custom_entry.pack(fill="x", pady=(4, 0))

        kind_row = tk.Frame(form)
        kind_row.pack(fill="x", pady=(8, 0))
        tk.Label(kind_row, text="Type:", font=body).pack(side="left")
        self._kind_var = tk.StringVar(value="command")
        tk.Radiobutton(kind_row, text="Wake / sleep", variable=self._kind_var, value="wake", font=body).pack(
            side="left", padx=(8, 0)
        )
        tk.Radiobutton(kind_row, text="Command", variable=self._kind_var, value="command", font=body).pack(
            side="left", padx=(8, 0)
        )
        tk.Label(
            form,
            text="Use Wake / sleep only for wake-up and sleep phrases.",
            font=body,
            fg="#78909C",
        ).pack(anchor="w", pady=(2, 0))

        self._status = tk.Label(self.dialog, text="Tap the white button to record.", font=body, fg="#455A64")
        self._status.pack(pady=(10, 4))

        self._level = tk.Canvas(self.dialog, width=360, height=36, bg="#ECEFF1", highlightthickness=0)
        self._level.pack(pady=4)
        self._bars = [self._level.create_rectangle(12 + i * 14, 30, 22 + i * 14, 30, fill="#90A4AE") for i in range(22)]

        btn_row = tk.Frame(self.dialog)
        btn_row.pack(pady=8)
        self._record_btn = _RecordButton(btn_row, command=self._toggle_record)
        self._record_btn.pack()

        tk.Label(
            self.dialog,
            text="White = ready   Red = recording   Tap again to stop and save",
            font=body,
            fg="#607D8B",
        ).pack()

        list_frame = tk.LabelFrame(self.dialog, text="Saved recordings", font=body, padx=8, pady=6)
        list_frame.pack(fill="both", expand=True, padx=16, pady=(8, 10))
        self._listbox = tk.Listbox(list_frame, font=body, height=7, activestyle="none")
        self._listbox.pack(side="left", fill="both", expand=True)
        scroll = tk.Scrollbar(list_frame, command=self._listbox.yview)
        scroll.pack(side="right", fill="y")
        self._listbox.config(yscrollcommand=scroll.set)

        actions = tk.Frame(self.dialog)
        actions.pack(pady=(0, 12))
        tk.Button(actions, text="Delete Selected", font=body, command=self._delete_selected).pack(side="left", padx=4)
        tk.Button(actions, text="Close", font=body, command=self._close, width=10).pack(side="left", padx=4)

        self._refresh_list()

    def _intended_text(self) -> str:
        custom = self._custom_entry.get().strip()
        if custom:
            return custom
        return self._phrase_var.get().strip()

    def _phrase_kind(self, intended: str) -> str:
        selected = self._kind_var.get().strip() or "command"
        if selected == "wake":
            return "wake"
        lowered = intended.lower()
        wake_markers = ("wake up", "hey silva", "silva sleep", "go to sleep")
        if any(marker in lowered for marker in wake_markers) or lowered in {"silva", "stop"}:
            return "wake"
        return "command"

    def _refresh_list(self) -> None:
        self._listbox.delete(0, tk.END)
        self._samples = list_phrase_samples(self.user_id)
        for sample in self._samples:
            self._listbox.insert(
                tk.END,
                f"[{sample.phrase_kind}] {sample.intended_text} — {sample.created_at}",
            )

    def _delete_selected(self) -> None:
        selection = self._listbox.curselection()
        if not selection:
            self._status.config(text="Select a recording to delete.", fg="#C62828")
            return
        sample = self._samples[selection[0]]
        delete_phrase_sample(self.user_id, sample.id)
        self._refresh_list()
        self._status.config(text="Recording deleted.", fg="#455A64")

    def _peak_level(self) -> float:
        if not self.recorder._frames:
            return 0.0
        chunk = self.recorder._frames[-1]
        if len(chunk) < 2:
            return 0.0
        count = len(chunk) // 2
        samples = struct.unpack(f"{count}h", chunk[: count * 2])
        if not samples:
            return 0.0
        return min(1.0, max(abs(value) for value in samples) / 32768.0)

    def _animate_level(self) -> None:
        if self._closed or not self.dialog.winfo_exists():
            return
        if self.recorder.is_recording:
            level = self._peak_level()
            for index, bar_id in enumerate(self._bars):
                height = 6 + int(22 * level * (0.55 + 0.45 * math.sin(index + level * 8)))
                self._level.coords(bar_id, 12 + index * 14, 34 - height, 22 + index * 14, 34)
            self.dialog.after(80, self._animate_level)

    def _toggle_record(self) -> None:
        if self.recorder.is_recording:
            self.recorder.stop()
            self._record_btn.set_recording(False)
            if not self.recorder.has_audio():
                self._status.config(text="No audio captured. Tap record and speak again.", fg="#C62828")
                return
            audio = self.recorder.to_audio_data()
            if audio is None:
                self._status.config(text="Could not read audio.", fg="#C62828")
                return
            try:
                intended = self._intended_text()
                kind = self._phrase_kind(intended)
                save_phrase_sample(
                    self.user_id,
                    audio,
                    intended_text=intended,
                    phrase_kind=kind,
                )
            except RuntimeError as exc:
                self._status.config(text=str(exc), fg="#C62828")
                return
            self._saved_count += 1
            self._refresh_list()
            self._status.config(text=f"Saved recording for {intended!r}. Record another or close.", fg="#1B5E20")
            return

        intended = self._intended_text()
        if not intended:
            self._status.config(text="Choose or type a phrase first.", fg="#C62828")
            return
        self.recorder.start()
        if self.recorder.last_error:
            self._status.config(text=self.recorder.last_error, fg="#C62828")
            return
        self._record_btn.set_recording(True)
        self._status.config(text=f"Recording... say {intended!r}", fg="#C62828")
        self._animate_level()

    def _close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.recorder.is_recording:
            self.recorder.stop()
        result = PhraseRecordResult(saved_count=self._saved_count, cancelled=self._saved_count == 0)
        if self._on_closed:
            self._on_closed(result)
        if self.dialog.winfo_exists():
            unregister(self.dialog)
            self.dialog.destroy()


def show_phrase_record_popup(
    user: dict,
    *,
    on_closed: Callable[[PhraseRecordResult], None] | None = None,
) -> bool:
    global _popup

    def _finished(result: PhraseRecordResult) -> None:
        global _popup
        with _popup_lock:
            _popup = None
        log_info(f"Phrase recorder closed with {result.saved_count} saved recording(s).")
        if on_closed is not None:
            on_closed(result)

    def _build(parent: tk.Misc) -> None:
        global _popup
        try:
            dialog = PhraseRecordDialog(
                parent,
                user_id=user["id"],
                user_name=user.get("name", "User"),
                on_closed=_finished,
            )
        except Exception as exc:
            log_error("Phrase recorder popup failed", exc=exc)
            return
        with _popup_lock:
            _popup = dialog
        log_info("Phrase recorder popup opened.")

    try:
        from silva.gui.display_host import host_root

        parent = host_root()
    except Exception:
        parent = None

    if parent is not None:
        try:
            parent.after(0, lambda: _build(parent))
            log_info("Phrase recorder popup scheduled on display host.")
            return True
        except tk.TclError as exc:
            log_error("Phrase recorder could not use the display host", exc=exc)

    def _run() -> None:
        root = tk.Tk()
        root.withdraw()
        register(root)
        try:
            _build(root)
            root.mainloop()
        finally:
            unregister(root)
            try:
                root.destroy()
            except tk.TclError:
                pass

    threading.Thread(target=_run, name="silva-phrase-recorder", daemon=True).start()
    log_info("Phrase recorder popup started on its own display thread.")
    return True


def run_phrase_record_blocking(user: dict) -> PhraseRecordResult:
    holder: dict = {"value": PhraseRecordResult()}
    done = threading.Event()

    def _closed(result: PhraseRecordResult) -> None:
        holder["value"] = result
        done.set()

    if not show_phrase_record_popup(user, on_closed=_closed):
        return holder["value"]
    done.wait(timeout=600)
    return holder["value"]
