"""Owner protection verification — 8 random digits (1–10) required before closing."""

from __future__ import annotations

import threading
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass

from silva.config import load_config
from silva.gui.display_manager import register, unregister
from silva.gui.monitors import geometry_on_monitor
from silva.security.protection_protocol import format_verification_code, generate_verification_code


@dataclass
class VerificationResult:
    passed: bool
    digits: list[int]
    reason: str = ""


def _run_dialog(
    *,
    title: str,
    subtitle: str,
    digits: list[int],
    result: dict,
    allow_owner_close: bool,
) -> None:
    root = tk.Tk()
    register(root)
    root.title("Silva - Security Verification")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    width, height = 440, 260
    root.geometry(geometry_on_monitor(width, height, anchor="center"))

    body = tkfont.Font(family="Segoe UI", size=10)
    heading = tkfont.Font(family="Segoe UI", size=11, weight="bold")
    code_font = tkfont.Font(family="Consolas", size=14, weight="bold")

    tk.Label(root, text=title, font=heading, fg="#B71C1C").pack(pady=(14, 4))
    tk.Label(root, text=subtitle, font=body, fg="#455A64", wraplength=400).pack(pady=(0, 8))
    tk.Label(
        root,
        text=f"Enter this code: {format_verification_code(digits)}",
        font=code_font,
        fg="#1A237E",
        wraplength=400,
    ).pack(pady=(0, 10))

    entry_var = tk.StringVar()
    entry = tk.Entry(root, textvariable=entry_var, font=code_font, width=32, justify="center")
    entry.pack(pady=(0, 8))
    entry.focus_set()

    status = tk.Label(root, text="", font=body, fg="#C62828")

    def submit() -> None:
        from silva.security.protection_protocol import parse_verification_entry

        text = entry_var.get()
        if parse_verification_entry(text, digits):
            result["value"] = VerificationResult(passed=True, digits=digits)
            unregister(root)
            root.destroy()
            return
        status.config(text="Incorrect code. Try again.")
        entry_var.set("")
        entry.focus_set()

    def cancel() -> None:
        if not allow_owner_close:
            status.config(text="Verification required. Enter the code to continue.")
            return
        result["value"] = VerificationResult(passed=False, digits=digits, reason="cancelled")
        unregister(root)
        root.destroy()

    row = tk.Frame(root)
    row.pack(pady=(4, 12))
    tk.Button(row, text="Verify", font=body, width=12, command=submit).pack(side="left", padx=6)
    tk.Button(row, text="Cancel", font=body, width=12, command=cancel).pack(side="left", padx=6)
    status.pack()
    root.protocol("WM_DELETE_WINDOW", cancel)
    entry.bind("<Return>", lambda _event: submit())
    root.mainloop()


def run_protection_verification(
    *,
    title: str = "Unauthorized access detected",
    subtitle: str = "Enter the verification code to continue using Silva.",
    allow_owner_close: bool = False,
    digits: list[int] | None = None,
) -> VerificationResult:
    code = digits or generate_verification_code()
    result: dict = {
        "value": VerificationResult(passed=False, digits=code, reason="timeout"),
    }
    thread = threading.Thread(
        target=_run_dialog,
        kwargs={
            "title": title,
            "subtitle": subtitle,
            "digits": code,
            "result": result,
            "allow_owner_close": allow_owner_close,
        },
        daemon=True,
    )
    thread.start()
    timeout = float(load_config().get("protection_verify_timeout_seconds", 300))
    thread.join(timeout=timeout)
    return result.get("value") or VerificationResult(passed=False, digits=code, reason="timeout")
