"""Voice profile switch confirmation dialog."""

from __future__ import annotations

import threading
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass

from typing import Callable

from silva.gui.display_manager import register, unregister
from silva.gui.monitors import geometry_on_monitor


@dataclass
class ProfileConfirmResult:
    confirmed: bool
    user_id: str
    name: str


def _run_dialog(
    user_id: str,
    name: str,
    score: float,
    result: dict,
    on_result: Callable[[ProfileConfirmResult], None] | None,
) -> None:
    root = tk.Tk()
    register(root)
    root.title("Silva - Profile Switch")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    width, height = 400, 180
    root.geometry(geometry_on_monitor(width, height, anchor="center"))

    body = tkfont.Font(family="Segoe UI", size=10)
    title = tkfont.Font(family="Segoe UI", size=11, weight="bold")

    tk.Label(
        root,
        text=f"Switch to {name}?",
        font=title,
        fg="#1A237E",
    ).pack(pady=(16, 4))
    tk.Label(
        root,
        text=f"Voice match detected ({score:.0%}). Confirm this profile?",
        font=body,
        fg="#455A64",
        wraplength=360,
    ).pack(pady=(0, 10))
    tk.Label(
        root,
        text="Face verification may be required for protected profiles.",
        font=body,
        fg="#607D8B",
        wraplength=360,
    ).pack(pady=(0, 6))
    tk.Label(
        root,
        text="You can also say yes or no.",
        font=body,
        fg="#607D8B",
    ).pack(pady=(0, 10))

    row = tk.Frame(root)
    row.pack(pady=(0, 12))

    def yes() -> None:
        value = ProfileConfirmResult(confirmed=True, user_id=user_id, name=name)
        result["value"] = value
        if on_result:
            on_result(value)
        unregister(root)
        root.destroy()

    def no() -> None:
        value = ProfileConfirmResult(confirmed=False, user_id=user_id, name=name)
        result["value"] = value
        if on_result:
            on_result(value)
        unregister(root)
        root.destroy()

    tk.Button(row, text="Yes", font=body, width=10, command=yes).pack(side="left", padx=8)
    tk.Button(row, text="No", font=body, width=10, command=no).pack(side="left", padx=8)
    root.protocol("WM_DELETE_WINDOW", no)
    root.mainloop()


def confirm_profile_switch(
    user_id: str,
    name: str,
    score: float,
    *,
    on_result: Callable[[ProfileConfirmResult], None] | None = None,
) -> None:
    result: dict = {
        "value": ProfileConfirmResult(confirmed=False, user_id=user_id, name=name),
    }
    thread = threading.Thread(
        target=_run_dialog,
        args=(user_id, name, score, result, on_result),
        daemon=True,
    )
    thread.start()
