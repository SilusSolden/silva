"""Typing prompt shown when Silva needs wake confirmation."""

from __future__ import annotations

import threading
import time
import tkinter as tk
import tkinter.font as tkfont

from silva.gui.monitors import geometry_on_monitor
from silva.wake import (
    get_wake_confirm_timeout,
    get_wake_phrases,
    is_wake_command,
    is_wake_confirm_no,
    is_wake_confirm_yes,
)


def _run_confirm_dialog(result: dict, timeout_seconds: int) -> None:
    root = tk.Tk()
    root.title("Silva")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    width, height = 460, 170
    root.geometry(geometry_on_monitor(width, height, anchor="center"))

    title_font = tkfont.Font(family="Segoe UI", size=12, weight="bold")
    body_font = tkfont.Font(family="Segoe UI", size=10)
    wake_examples = ", ".join(f'"{p}"' for p in list(get_wake_phrases())[:3])

    tk.Label(
        root,
        text="Silva is asleep",
        font=title_font,
        fg="#1A237E",
    ).pack(pady=(12, 4))

    tk.Label(
        root,
        text="Are you trying to wake me up?",
        font=body_font,
        fg="#455A64",
    ).pack()

    tk.Label(
        root,
        text=f"Type a wake phrase, yes, or no. Examples: {wake_examples}",
        font=body_font,
        fg="#78909C",
        wraplength=420,
    ).pack(pady=(0, 8))

    entry = tk.Entry(root, font=body_font, width=46)
    entry.pack(padx=16, pady=(0, 4))
    entry.focus_set()

    status = tk.Label(root, text="", font=body_font, fg="#C62828")
    status.pack()

    timer = tk.Label(root, text="", font=body_font, fg="#78909C")
    timer.pack()

    closed = {"done": False}

    def finish(value: str) -> None:
        if closed["done"]:
            return
        closed["done"] = True
        result["value"] = value
        root.destroy()

    def submit() -> None:
        text = entry.get().strip()
        if is_wake_command(text) or is_wake_confirm_yes(text):
            finish("wake")
            return
        if is_wake_confirm_no(text):
            finish("no")
            return
        status.config(text="Type a wake phrase, yes, or no.")

    def on_timeout() -> None:
        finish("timeout")

    entry.bind("<Return>", lambda _event: submit())
    tk.Button(root, text="Submit", font=body_font, command=submit).pack(pady=(4, 8))

    remaining = {"seconds": timeout_seconds}

    def tick() -> None:
        if closed["done"]:
            return
        timer.config(text=f"Closing in {remaining['seconds']}s if no response")
        remaining["seconds"] -= 1
        if remaining["seconds"] < 0:
            on_timeout()
            return
        root.after(1000, tick)

    root.after(1000, tick)
    root.protocol("WM_DELETE_WINDOW", on_timeout)
    root.mainloop()


def prompt_wake_confirmation() -> str:
    """
    Ask if the user is trying to wake Silva.
    Returns: 'wake', 'no', or 'timeout'.
    """
    result: dict[str, str] = {"value": "timeout"}
    timeout_seconds = get_wake_confirm_timeout()
    thread = threading.Thread(
        target=_run_confirm_dialog,
        args=(result, timeout_seconds),
        daemon=True,
    )
    thread.start()
    thread.join(timeout=timeout_seconds + 2)
    return result["value"]


def prompt_wake_command() -> bool:
    """Direct wake typing box (manual use only)."""
    result: dict[str, str] = {"value": "timeout"}

    def run() -> None:
        root = tk.Tk()
        root.title("Wake Silva")
        root.resizable(False, False)
        root.attributes("-topmost", True)

        width, height = 420, 150
        root.geometry(geometry_on_monitor(width, height, anchor="center"))

        title_font = tkfont.Font(family="Segoe UI", size=12, weight="bold")
        body_font = tkfont.Font(family="Segoe UI", size=10)
        wake_examples = ", ".join(f'"{p}"' for p in list(get_wake_phrases())[:3])

        tk.Label(root, text="Silva is asleep", font=title_font, fg="#1A237E").pack(pady=(14, 4))
        tk.Label(root, text="Type a wake phrase to continue", font=body_font, fg="#455A64").pack()
        tk.Label(root, text=f"Examples: {wake_examples}", font=body_font, fg="#78909C").pack(pady=(0, 8))

        entry = tk.Entry(root, font=body_font, width=42)
        entry.pack(padx=16, pady=(0, 6))
        entry.focus_set()

        status = tk.Label(root, text="", font=body_font, fg="#C62828")
        status.pack()

        def submit() -> None:
            if is_wake_command(entry.get().strip()):
                result["value"] = "wake"
                root.destroy()
                return
            status.config(text="That was not a wake phrase. Try again.")

        entry.bind("<Return>", lambda _event: submit())
        tk.Button(root, text="Wake Silva", font=body_font, command=submit).pack(pady=(4, 10))
        root.mainloop()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout=get_wake_confirm_timeout() + 2)
    return result["value"] == "wake"
