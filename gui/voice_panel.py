"""Set Voice panel - record, save, and enroll user voice for Silva."""

from __future__ import annotations

import threading
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass

from silva.audio_recorder import VoiceRecorder, default_input_device, list_input_devices
from silva.gui.display_manager import register, unregister
from silva.gui.monitors import geometry_on_monitor
from silva.users.manager import _slug
from silva.users.voice_id import save_voice_profile, wav_path


@dataclass
class SetVoiceResult:
    saved: bool
    name: str
    user_id: str
    wav_file: str
    face_recognition_future: bool = False
    cancelled: bool = True


def _run_panel(
    default_name: str,
    fixed_user_id: str | None,
    auto_record: bool,
    result: dict,
) -> None:
    root = tk.Tk()
    register(root)
    root.title("Silva - Record Voice")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    width, height = 500, 380
    root.geometry(geometry_on_monitor(width, height, anchor="center"))

    title_font = tkfont.Font(family="Segoe UI", size=12, weight="bold")
    body_font = tkfont.Font(family="Segoe UI", size=10)
    mic_font = tkfont.Font(family="Segoe UI", size=9)

    _, default_mic_name = default_input_device()
    recorder = VoiceRecorder()
    recorded = {"has_audio": False, "wav_path": ""}

    tk.Label(root, text="Record Your Voice", font=title_font, fg="#1A237E").pack(pady=(14, 4))
    tk.Label(
        root,
        text="Speak clearly into your microphone or headset. Press Stop when finished.",
        font=body_font,
        fg="#455A64",
        wraplength=440,
        justify="center",
    ).pack(pady=(0, 8))

    mic_frame = tk.Frame(root, bg="#ECEFF1", padx=10, pady=6)
    mic_frame.pack(fill="x", padx=24, pady=(0, 8))
    mic_label = tk.Label(
        mic_frame,
        text=f"Microphone: {default_mic_name}",
        font=mic_font,
        bg="#ECEFF1",
        fg="#37474F",
        wraplength=420,
        justify="left",
    )
    mic_label.pack(anchor="w")

    devices = list_input_devices()
    if len(devices) > 1:
        device_names = [("Default", None)]
        device_names.extend(
            (f"{item['name']}{' (default)' if item['is_default'] else ''}", item["index"])
            for item in devices
        )
        device_map = {label: index for label, index in device_names}

        tk.Label(mic_frame, text="Input device:", font=mic_font, bg="#ECEFF1").pack(anchor="w", pady=(4, 0))
        device_var = tk.StringVar(value=device_names[0][0])
        device_menu = tk.OptionMenu(
            mic_frame,
            device_var,
            *[label for label, _index in device_names],
        )
        device_menu.config(font=mic_font, width=42)
        device_menu.pack(anchor="w", pady=(2, 0))

        def on_device_change(*_args) -> None:
            selected = device_var.get()
            index = device_map.get(selected)
            if index is None:
                _, name = default_input_device()
                mic_label.config(text=f"Microphone: {name}")
            else:
                match = next((item for item in devices if item["index"] == index), None)
                if match:
                    mic_label.config(text=f"Microphone: {match['name']}")

        device_var.trace_add("write", on_device_change)

        def get_selected_device_index() -> int | None:
            return device_map.get(device_var.get())

    else:

        def get_selected_device_index() -> int | None:
            return None

    tk.Label(root, text="Your name", font=body_font).pack()
    name_entry = tk.Entry(root, font=body_font, width=36)
    name_entry.pack(pady=(2, 8))
    name_entry.insert(0, default_name)
    if fixed_user_id:
        name_entry.config(state="readonly")

    status = tk.Label(root, text="Opening microphone...", font=body_font, fg="#607D8B")
    status.pack(pady=(0, 8))

    btn_row = tk.Frame(root)
    btn_row.pack(pady=(0, 8))

    record_btn = tk.Button(btn_row, text="Record Again", font=body_font, width=12, state="disabled")
    stop_btn = tk.Button(
        btn_row,
        text="Stop & Save Voice",
        font=body_font,
        width=16,
        state="disabled",
        bg="#C62828",
        fg="white",
        activebackground="#B71C1C",
        activeforeground="white",
    )
    record_btn.pack(side="left", padx=6)
    stop_btn.pack(side="left", padx=6)

    tk.Label(root, text="Future extras", font=body_font, fg="#607D8B").pack()
    face_var = tk.BooleanVar(value=False)
    tk.Checkbutton(
        root,
        text="Face recognition (save for later - not active yet)",
        variable=face_var,
        font=body_font,
    ).pack(anchor="w", padx=40, pady=(2, 8))

    done_btn = tk.Button(root, text="Done", font=body_font, width=12, state="disabled")
    done_btn.pack(pady=(8, 10))

    def start_record() -> None:
        nonlocal recorder
        recorder = VoiceRecorder(device_index=get_selected_device_index())
        recorder.start()
        root.after(400, _check_recording_started)

    def _check_recording_started() -> None:
        if recorder.last_error:
            status.config(text=recorder.last_error, fg="#C62828")
            record_btn.config(state="normal")
            stop_btn.config(state="disabled")
            return
        if recorder.is_recording or recorder.has_audio():
            mic_name = recorder.device_name or default_mic_name
            mic_label.config(text=f"Listening on: {mic_name}")
            record_btn.config(state="disabled")
            stop_btn.config(state="normal")
            status.config(text="Recording... speak now, then press Stop & Save Voice.", fg="#C62828")
        elif auto_record:
            status.config(text="Starting microphone...", fg="#607D8B")
            root.after(200, _check_recording_started)

    def save_voice() -> bool:
        name = name_entry.get().strip().title()
        if not name:
            status.config(text="Enter your name first.", fg="#C62828")
            return False
        if not recorder.has_audio():
            status.config(text="No audio captured. Try recording again.", fg="#C62828")
            return False
        try:
            audio = recorder.to_audio_data()
            if audio is None:
                raise RuntimeError("No audio to save.")
            user_id = fixed_user_id or _slug(name)
            path = save_voice_profile(user_id, audio, name=name, wav_file=wav_path(user_id))
            recorded["wav_path"] = str(path)
            recorded["has_audio"] = True
            done_btn.config(state="normal")
            stop_btn.config(state="disabled")
            record_btn.config(state="normal")
            status.config(
                text=f"Voice saved for {name}. Silva will recognize you automatically.",
                fg="#1B5E20",
            )
            result["pending"] = SetVoiceResult(
                saved=True,
                name=name,
                user_id=user_id,
                wav_file=str(path),
                face_recognition_future=face_var.get(),
                cancelled=False,
            )
            return True
        except RuntimeError as exc:
            status.config(text=str(exc), fg="#C62828")
            return False

    def stop_record() -> None:
        recorder.stop()
        if not recorder.has_audio():
            status.config(text="No audio captured. Press Record Again and speak.", fg="#C62828")
            record_btn.config(state="normal")
            stop_btn.config(state="disabled")
            return
        status.config(text="Saving your voice...", fg="#607D8B")
        root.update_idletasks()
        save_voice()

    def finish() -> None:
        pending = result.get("pending")
        if pending is None:
            status.config(text="Record and save your voice first.", fg="#C62828")
            return
        result["value"] = pending
        unregister(root)
        root.destroy()

    def cancel() -> None:
        recorder.stop()
        result["value"] = SetVoiceResult(
            saved=False,
            name="",
            user_id="",
            wav_file="",
            cancelled=True,
        )
        unregister(root)
        root.destroy()

    record_btn.config(command=start_record)
    stop_btn.config(command=stop_record)
    done_btn.config(command=finish)
    root.protocol("WM_DELETE_WINDOW", cancel)

    if auto_record:
        root.after(350, start_record)
    else:
        status.config(text="Press Record Again to start, then Stop & Save Voice.", fg="#607D8B")
        record_btn.config(state="normal")

    root.mainloop()


def run_set_voice_panel(
    default_name: str = "Kevin",
    *,
    user_id: str | None = None,
    auto_record: bool = True,
) -> SetVoiceResult:
    result: dict = {
        "value": SetVoiceResult(saved=False, name="", user_id="", wav_file="", cancelled=True),
        "pending": None,
    }
    thread = threading.Thread(
        target=_run_panel,
        args=(default_name, user_id, auto_record, result),
        daemon=True,
    )
    thread.start()
    thread.join(timeout=300)
    return result.get(
        "value",
        SetVoiceResult(saved=False, name="", user_id="", wav_file="", cancelled=True),
    )
