"""Voice and name enrollment popup for Silva."""

from __future__ import annotations

import threading
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass

from silva.gui.monitors import geometry_on_monitor


@dataclass
class EnrollmentResult:
    name: str
    confirmed: bool
    voice_enabled: bool = True
    face_recognition_future: bool = False
    cancelled: bool = False


def _run_name_prompt(default_name: str, result: dict) -> None:
    root = tk.Tk()
    root.title("Silva Voice Enrollment")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    width, height = 460, 220
    root.geometry(geometry_on_monitor(width, height, anchor="center"))

    title_font = tkfont.Font(family="Segoe UI", size=12, weight="bold")
    body_font = tkfont.Font(family="Segoe UI", size=10)

    tk.Label(root, text="Enroll Your Voice", font=title_font, fg="#1A237E").pack(pady=(14, 4))
    tk.Label(
        root,
        text="Enter your name, then Silva will record your voice.",
        font=body_font,
        fg="#455A64",
    ).pack(pady=(0, 8))

    tk.Label(root, text="Your name", font=body_font).pack()
    name_entry = tk.Entry(root, font=body_font, width=36)
    name_entry.pack(pady=(2, 10))
    name_entry.insert(0, default_name)
    name_entry.focus_set()

    tk.Label(root, text="Future extras (optional)", font=body_font, fg="#607D8B").pack()
    voice_var = tk.BooleanVar(value=True)
    face_var = tk.BooleanVar(value=False)

    voice_row = tk.Frame(root)
    voice_row.pack(anchor="w", padx=40, pady=(4, 0))
    tk.Checkbutton(
        voice_row,
        text="Voice recognition (active)",
        variable=voice_var,
        state="disabled",
        font=body_font,
    ).pack(anchor="w")

    face_row = tk.Frame(root)
    face_row.pack(anchor="w", padx=40, pady=(2, 8))
    tk.Checkbutton(
        face_row,
        text="Face recognition (coming soon - saved for later)",
        variable=face_var,
        font=body_font,
    ).pack(anchor="w")

    def start() -> None:
        name = name_entry.get().strip()
        if not name:
            return
        result["value"] = EnrollmentResult(
            name=name.title(),
            confirmed=False,
            voice_enabled=True,
            face_recognition_future=face_var.get(),
            cancelled=False,
        )
        root.destroy()

    def cancel() -> None:
        result["value"] = EnrollmentResult(
            name="",
            confirmed=False,
            cancelled=True,
        )
        root.destroy()

    btn_row = tk.Frame(root)
    btn_row.pack(pady=(4, 10))
    tk.Button(btn_row, text="Start Recording", font=body_font, command=start, width=16).pack(side="left", padx=6)
    tk.Button(btn_row, text="Cancel", font=body_font, command=cancel, width=10).pack(side="left", padx=6)

    root.mainloop()


def _run_success_prompt(name: str, result: dict) -> None:
    root = tk.Tk()
    root.title("Silva Enrollment Complete")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    width, height = 420, 180
    root.geometry(geometry_on_monitor(width, height, anchor="center"))

    title_font = tkfont.Font(family="Segoe UI", size=12, weight="bold")
    body_font = tkfont.Font(family="Segoe UI", size=10)

    tk.Label(root, text="Voice Saved", font=title_font, fg="#1B5E20").pack(pady=(16, 4))
    tk.Label(
        root,
        text=f"{name}'s voice and name were saved to Silva.",
        font=body_font,
        fg="#455A64",
    ).pack(pady=(0, 10))

    confirm_var = tk.BooleanVar(value=False)

    def toggle() -> None:
        done_btn.config(state="normal" if confirm_var.get() else "disabled")

    tk.Checkbutton(
        root,
        text="I confirm enrollment was successful",
        variable=confirm_var,
        command=toggle,
        font=body_font,
    ).pack(pady=(0, 8))

    done_btn = tk.Button(root, text="Done", font=body_font, state="disabled", width=12)
    done_btn.pack()

    def finish() -> None:
        if not confirm_var.get():
            return
        result["value"] = True
        root.destroy()

    done_btn.config(command=finish)
    root.mainloop()


def prompt_enrollment_start(default_name: str = "Kevin") -> EnrollmentResult:
    result: dict = {"value": EnrollmentResult(name="", confirmed=False, cancelled=True)}
    thread = threading.Thread(target=_run_name_prompt, args=(default_name, result), daemon=True)
    thread.start()
    thread.join(timeout=120)
    return result.get("value", EnrollmentResult(name="", confirmed=False, cancelled=True))


def prompt_enrollment_success(name: str) -> bool:
    result: dict = {"value": False}
    thread = threading.Thread(target=_run_success_prompt, args=(name, result), daemon=True)
    thread.start()
    thread.join(timeout=120)
    return bool(result.get("value", False))
