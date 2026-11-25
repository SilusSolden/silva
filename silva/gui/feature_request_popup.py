"""Text popup for feature requests when speech is not available."""

from __future__ import annotations

import threading
import tkinter as tk
import tkinter.font as tkfont
from typing import Callable

from silva.gui.display_manager import register, unregister, watch_shutdown
from silva.gui.monitors import geometry_on_monitor
from silva.logger import log_error, log_info

BG = "#FAFAFA"
ACCENT = "#1A237E"
MUTED = "#78909C"


def _overlay_parent() -> tk.Misc | None:
    try:
        from silva.gui.display_host import host_root

        return host_root()
    except Exception:
        return None


class FeatureRequestPopup:
    def __init__(
        self,
        parent: tk.Misc,
        user: dict,
        feature: str,
        label: str,
        on_submitted: Callable[[str], None] | None = None,
    ) -> None:
        self._user = user
        self._feature = feature
        self._on_submitted = on_submitted
        self._closed = False

        self.dialog = tk.Toplevel(parent)
        register(self.dialog, persistent=True)
        watch_shutdown(self.dialog)
        self.dialog.title("Silva - Feature request")
        self.dialog.configure(bg=BG)
        self.dialog.resizable(True, True)
        self.dialog.attributes("-topmost", True)
        self.dialog.protocol("WM_DELETE_WINDOW", self._close)
        self.dialog.geometry(geometry_on_monitor(540, 400, anchor="center"))

        title_font = tkfont.Font(family="Segoe UI", size=13, weight="bold")
        body_font = tkfont.Font(family="Segoe UI", size=10)

        tk.Label(
            self.dialog,
            text=f"Request: {label}",
            font=title_font,
            fg=ACCENT,
            bg=BG,
            wraplength=500,
            justify="left",
        ).pack(anchor="w", padx=16, pady=(14, 4))
        tk.Label(
            self.dialog,
            text="Type what you need. The owner and admins will see it in the terminal.",
            font=body_font,
            fg=MUTED,
            bg=BG,
            wraplength=500,
            justify="left",
        ).pack(anchor="w", padx=16)

        self._text = tk.Text(self.dialog, font=body_font, wrap="word", undo=True)
        self._text.pack(fill="both", expand=True, padx=16, pady=10)
        self._text.bind("<Return>", self._on_return)
        self._text.bind("<KP_Enter>", self._on_return)
        self._text.focus_set()

        self._status = tk.StringVar(value="")
        tk.Label(self.dialog, textvariable=self._status, font=body_font, fg="#1B5E20", bg=BG).pack(
            anchor="w", padx=16
        )

        row = tk.Frame(self.dialog, bg=BG)
        row.pack(fill="x", padx=16, pady=(4, 14))
        tk.Button(row, text="Send", font=body_font, width=12, command=self._save).pack(side="left")
        tk.Button(row, text="Cancel", font=body_font, width=10, command=self._close).pack(side="right")
        log_info("Feature request popup shown.")

    def _on_return(self, event) -> str | None:
        if int(getattr(event, "state", 0)) & 0x0001:
            return None
        self._save()
        return "break"

    def _save(self) -> None:
        reason = self._text.get("1.0", "end-1c").strip()
        if len(reason) < 5:
            self._status.set("Please type a little more detail.")
            return
        from silva.users.feature_requests import submit_feature_request

        submit_feature_request(self._user, self._feature, reason=reason)
        if self._on_submitted:
            self._on_submitted(reason)
        self._close()

    def _close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.dialog.winfo_exists():
            unregister(self.dialog)
            self.dialog.destroy()


def show_feature_request_popup(
    user: dict,
    feature: str,
    label: str,
    *,
    on_submitted: Callable[[str], None] | None = None,
) -> None:
    def _build(parent: tk.Misc) -> None:
        try:
            FeatureRequestPopup(parent, user, feature, label, on_submitted)
        except Exception as exc:
            log_error("Feature request popup failed", exc=exc)

    parent = _overlay_parent()
    if parent is not None:
        try:
            parent.after(0, lambda: _build(parent))
            return
        except Exception as exc:
            log_error("Feature request popup schedule failed", exc=exc)

    def _run() -> None:
        root = tk.Tk()
        root.withdraw()
        register(root, persistent=True)
        _build(root)
        root.mainloop()

    threading.Thread(target=_run, name="silva-feature-request", daemon=True).start()
