"""Popup to submit a permission access request with a written reason."""

from __future__ import annotations

import threading
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass

from silva.gui.monitors import geometry_on_monitor


@dataclass
class PermissionRequestFormResult:
    submitted: bool
    reason: str
    cancelled: bool = True


def _run_form(action_label: str, prefill: str, result: dict) -> None:
    root = tk.Tk()
    root.title("Silva - Permission Request")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    width, height = 440, 260
    root.geometry(geometry_on_monitor(width, height, anchor="center"))

    body = tkfont.Font(family="Segoe UI", size=10)
    title = tkfont.Font(family="Segoe UI", size=11, weight="bold")

    tk.Label(root, text="Request Permission", font=title, fg="#1A237E").pack(pady=(14, 4))
    tk.Label(
        root,
        text=f"Explain why you need access to: {action_label}",
        font=body,
        fg="#455A64",
        wraplength=400,
    ).pack(pady=(0, 8))

    reason_box = tk.Text(root, font=body, width=48, height=6, wrap="word")
    reason_box.pack(padx=16, pady=(0, 8))
    reason_box.insert("1.0", prefill)
    reason_box.focus_set()

    status = tk.Label(root, text="", font=body, fg="#C62828")
    status.pack()

    def submit() -> None:
        reason = reason_box.get("1.0", "end").strip()
        if len(reason) < 8:
            status.config(text="Please write a little more about why you need this.")
            return
        result["value"] = PermissionRequestFormResult(
            submitted=True,
            reason=reason,
            cancelled=False,
        )
        root.destroy()

    def cancel() -> None:
        result["value"] = PermissionRequestFormResult(submitted=False, reason="", cancelled=True)
        root.destroy()

    row = tk.Frame(root)
    row.pack(pady=(4, 12))
    tk.Button(row, text="Submit Request", font=body, width=14, command=submit).pack(side="left", padx=6)
    tk.Button(row, text="Cancel", font=body, width=10, command=cancel).pack(side="left", padx=6)
    root.protocol("WM_DELETE_WINDOW", cancel)
    root.mainloop()


def run_permission_request_form(
    action_label: str,
    *,
    prefill: str = "",
) -> PermissionRequestFormResult:
    result: dict = {"value": PermissionRequestFormResult(submitted=False, reason="", cancelled=True)}
    thread = threading.Thread(target=_run_form, args=(action_label, prefill, result), daemon=True)
    thread.start()
    thread.join(timeout=300)
    return result.get(
        "value",
        PermissionRequestFormResult(submitted=False, reason="", cancelled=True),
    )
