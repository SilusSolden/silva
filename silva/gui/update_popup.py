"""Desktop update notifications for Silva."""

from __future__ import annotations

import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from typing import Callable

from silva.dev.update_scanner import UpdateScanResult
from silva.gui.display_manager import register, unregister, watch_shutdown
from silva.gui.monitors import geometry_on_monitor

UpdateChoiceCallback = Callable[[bool], None]
CompleteCallback = Callable[[], None]


def show_update_available_popup(
    scan: UpdateScanResult,
    *,
    on_choice: UpdateChoiceCallback | None = None,
) -> None:
    from silva.dev.auto_update import should_show_desktop_update_popup

    if not should_show_desktop_update_popup():
        return
    threading.Thread(
        target=_build_update_offer_popup,
        args=(scan, on_choice),
        name="silva-update-offer",
        daemon=True,
    ).start()


def show_update_complete_popup(message: str, *, on_close: CompleteCallback | None = None) -> None:
    from silva.dev.auto_update import should_show_desktop_update_popup

    if not should_show_desktop_update_popup():
        return
    threading.Thread(
        target=_build_update_complete_popup,
        args=(message, on_close),
        name="silva-update-complete",
        daemon=True,
    ).start()


def show_message_popup(message: str, *, title: str = "Silva") -> None:
    threading.Thread(
        target=_build_message_popup,
        args=(message, title),
        name="silva-message",
        daemon=True,
    ).start()


def _build_message_popup(message: str, title: str) -> None:
    root = tk.Tk()
    register(root)
    watch_shutdown(root)
    root.title(title)
    root.resizable(False, False)
    root.attributes("-topmost", True)
    root.geometry(geometry_on_monitor(380, 180, anchor="se", margin=24))

    frame = tk.Frame(root, padx=16, pady=14)
    frame.pack(fill="both", expand=True)
    tk.Label(
        frame,
        text=str(message or ""),
        font=tkfont.Font(family="Segoe UI", size=10),
        fg="#37474F",
        wraplength=340,
        justify="left",
    ).pack(anchor="w", pady=(8, 12))

    def _close() -> None:
        unregister(root)
        root.destroy()

    tk.Button(frame, text="OK", width=10, command=_close).pack(anchor="e")
    root.after(12000, _close)
    root.protocol("WM_DELETE_WINDOW", _close)
    root.mainloop()


def _build_update_offer_popup(scan: UpdateScanResult, on_choice: UpdateChoiceCallback | None) -> None:
    root = tk.Tk()
    register(root)
    watch_shutdown(root)
    root.title("Silva Update")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    width, height = 420, 320
    root.geometry(geometry_on_monitor(width, height, anchor="se", margin=24))

    title_font = tkfont.Font(family="Segoe UI", size=12, weight="bold")
    body_font = tkfont.Font(family="Segoe UI", size=10)
    muted_font = tkfont.Font(family="Segoe UI", size=9)

    frame = tk.Frame(root, padx=16, pady=14)
    frame.pack(fill="both", expand=True)

    tk.Label(
        frame,
        text="Silva update available",
        font=title_font,
        fg="#1A237E",
    ).pack(anchor="w")
    tk.Label(
        frame,
        text=f"Version {scan.version} is ready (you have {scan.installed_version}).",
        font=body_font,
        fg="#37474F",
        wraplength=380,
        justify="left",
    ).pack(anchor="w", pady=(6, 8))

    tk.Label(frame, text="What's included:", font=body_font, fg="#455A64").pack(anchor="w")
    list_frame = tk.Frame(frame)
    list_frame.pack(fill="both", expand=True, pady=(4, 8))
    listbox = tk.Listbox(list_frame, font=body_font, height=7, activestyle="none")
    listbox.pack(side="left", fill="both", expand=True)
    scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=listbox.yview)
    scrollbar.pack(side="right", fill="y")
    listbox.config(yscrollcommand=scrollbar.set)
    for item in scan.changes[:10]:
        listbox.insert(tk.END, f"• {item}")

    tk.Label(
        frame,
        text="Install now? Silva keeps running — no restart needed.",
        font=muted_font,
        fg="#607D8B",
        wraplength=380,
        justify="left",
    ).pack(anchor="w", pady=(0, 8))

    def _finish(accepted: bool) -> None:
        unregister(root)
        root.destroy()
        if on_choice is not None:
            on_choice(accepted)

    button_row = tk.Frame(frame)
    button_row.pack(fill="x")
    tk.Button(
        button_row,
        text="Update now",
        width=14,
        command=lambda: _finish(True),
    ).pack(side="left", padx=(0, 8))
    tk.Button(
        button_row,
        text="Later",
        width=10,
        command=lambda: _finish(False),
    ).pack(side="left")

    root.protocol("WM_DELETE_WINDOW", lambda: _finish(False))
    root.mainloop()


def _build_update_complete_popup(message: str, on_close: CompleteCallback | None) -> None:
    root = tk.Tk()
    register(root)
    watch_shutdown(root)
    root.title("Silva Updated")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    width, height = 380, 180
    root.geometry(geometry_on_monitor(width, height, anchor="se", margin=24))

    title_font = tkfont.Font(family="Segoe UI", size=12, weight="bold")
    body_font = tkfont.Font(family="Segoe UI", size=10)

    frame = tk.Frame(root, padx=16, pady=14)
    frame.pack(fill="both", expand=True)

    tk.Label(frame, text="Silva has updated", font=title_font, fg="#2E7D32").pack(anchor="w")
    tk.Label(
        frame,
        text=message,
        font=body_font,
        fg="#37474F",
        wraplength=340,
        justify="left",
    ).pack(anchor="w", pady=(10, 12))

    def _close() -> None:
        unregister(root)
        root.destroy()
        if on_close is not None:
            on_close()

    tk.Button(frame, text="OK", width=10, command=_close).pack(anchor="e")
    root.after(12000, _close)
    root.protocol("WM_DELETE_WINDOW", _close)
    root.mainloop()
