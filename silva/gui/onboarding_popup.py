"""One-time first-run guide popup for new Silva accounts."""

from __future__ import annotations

import threading
import tkinter as tk
import tkinter.font as tkfont
from collections.abc import Callable
from tkinter.scrolledtext import ScrolledText

from silva.gui.display_manager import register, unregister, watch_shutdown
from silva.gui.monitors import geometry_on_monitor
from silva.logger import log_error, log_info
from silva.users.manager import is_owner

BG = "#FAFAFA"
ACCENT = "#1A237E"
MUTED = "#546E7A"


def _overlay_parent() -> tk.Misc | None:
    try:
        from silva.gui.display_host import host_root

        return host_root()
    except Exception:
        return None


def onboarding_text(user: dict) -> tuple[str, tuple[str, ...]]:
    from silva.users.onboarding import examples_for_user, summary_for_user

    return summary_for_user(user), examples_for_user(user)


class OnboardingPopup:
    def __init__(
        self,
        parent: tk.Misc,
        user: dict,
        on_complete: Callable[[dict], None] | None = None,
    ) -> None:
        from silva.users.onboarding import first_run_details

        summary, _examples = onboarding_text(user)
        self._closed = False
        self._on_complete = on_complete
        self._dialog = tk.Toplevel(parent)
        register(self._dialog, persistent=True)
        watch_shutdown(self._dialog)
        self._dialog.title("Silva - First-time setup")
        self._dialog.configure(bg=BG)
        self._dialog.resizable(True, True)
        self._dialog.attributes("-topmost", True)
        self._dialog.protocol("WM_DELETE_WINDOW", self._close_as_guest)
        self._dialog.geometry(geometry_on_monitor(620, 640, anchor="center"))

        title_font = tkfont.Font(family="Segoe UI", size=14, weight="bold")
        body_font = tkfont.Font(family="Segoe UI", size=10)

        header = tk.Frame(self._dialog, bg=BG)
        header.pack(fill="x", padx=18, pady=(14, 6))
        tk.Label(header, text=summary, font=body_font, fg="#263238", bg=BG, wraplength=560, justify="left").pack(
            anchor="w"
        )

        tk.Label(self._dialog, text="What's new and how to report issues", font=title_font, fg=ACCENT, bg=BG).pack(
            anchor="w", padx=18, pady=(8, 4)
        )
        self._details = ScrolledText(
            self._dialog,
            wrap="word",
            height=14,
            font=body_font,
            bg="#FFFFFF",
            fg="#263238",
            padx=8,
            pady=8,
        )
        self._details.insert("1.0", first_run_details(user))
        self._details.configure(state="disabled")
        self._details.pack(fill="both", expand=True, padx=18, pady=(0, 10))
        self._details.focus_set()
        self._bind_scrolling(self._details)

        setup = tk.LabelFrame(self._dialog, text="Profile and update choice", font=body_font, bg=BG, fg=ACCENT)
        setup.pack(fill="x", padx=18, pady=(0, 8))

        self._name_var = tk.StringVar(value="" if str(user.get("id") or "") == "guest" else str(user.get("name") or ""))
        name_row = tk.Frame(setup, bg=BG)
        name_row.pack(fill="x", padx=10, pady=(8, 4))
        tk.Label(name_row, text="Profile name:", font=body_font, bg=BG).pack(side="left")
        tk.Entry(name_row, textvariable=self._name_var, width=26, font=body_font).pack(side="left", padx=(8, 0))

        current_tier = int(user.get("tier") or 1)
        if is_owner(user):
            self._role_var = tk.StringVar(value="owner")
            tk.Label(setup, text="Profile level: Owner", font=body_font, fg=ACCENT, bg=BG).pack(
                anchor="w", padx=10, pady=2
            )
        elif current_tier >= 4:
            self._role_var = tk.StringVar(value="admin")
            tk.Label(setup, text="Profile level: Admin", font=body_font, fg=ACCENT, bg=BG).pack(
                anchor="w", padx=10, pady=2
            )
        else:
            self._role_var = tk.StringVar(value="basic" if self._name_var.get().strip() else "guest")
            roles = tk.Frame(setup, bg=BG)
            roles.pack(fill="x", padx=10, pady=2)
            tk.Label(roles, text="Profile level:", font=body_font, bg=BG).pack(side="left")
            for label, value in (("Guest", "guest"), ("Basic", "basic"), ("Request admin", "admin")):
                tk.Radiobutton(
                    roles,
                    text=label,
                    value=value,
                    variable=self._role_var,
                    font=body_font,
                    bg=BG,
                    selectcolor="#FFFFFF",
                ).pack(side="left", padx=(8, 0))

        self._notify_var = tk.IntVar(value=1 if user.get("update_notifications", True) else 0)
        tk.Checkbutton(
            setup,
            text="Notify me when a newer build is available",
            variable=self._notify_var,
            font=body_font,
            bg=BG,
            anchor="w",
        ).pack(fill="x", padx=10, pady=(2, 8))

        buttons = tk.Frame(self._dialog, bg=BG)
        buttons.pack(pady=(4, 14))
        tk.Button(buttons, text="Continue as guest", font=body_font, width=18, command=self._close_as_guest).pack(
            side="left", padx=6
        )
        tk.Button(buttons, text="Save choice", font=body_font, width=16, command=self._save_choice).pack(
            side="left", padx=6
        )
        log_info("Onboarding popup shown.")

    def _bind_scrolling(self, widget: tk.Text) -> None:
        widget.bind("<MouseWheel>", lambda event: widget.yview_scroll(int(-event.delta / 120), "units"))
        widget.bind("<Up>", lambda event: widget.yview_scroll(-1, "units"))
        widget.bind("<Down>", lambda event: widget.yview_scroll(1, "units"))
        widget.bind("<Prior>", lambda event: widget.yview_scroll(-1, "pages"))
        widget.bind("<Next>", lambda event: widget.yview_scroll(1, "pages"))
        widget.bind("<Home>", lambda event: widget.yview_moveto(0.0))
        widget.bind("<End>", lambda event: widget.yview_moveto(1.0))
        widget.bind("<space>", lambda event: widget.yview_scroll(1, "pages"))
        widget.bind("<Shift-space>", lambda event: widget.yview_scroll(-1, "pages"))
        widget.bind("<ButtonPress-2>", lambda event: widget.scan_mark(event.x, event.y))
        widget.bind("<B2-Motion>", lambda event: widget.scan_dragto(event.x, event.y, gain=1))

    def _finish(self, payload: dict) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._on_complete is not None:
                self._on_complete(payload)
        finally:
            if self._dialog.winfo_exists():
                unregister(self._dialog)
                self._dialog.destroy()

    def _save_choice(self) -> None:
        self._finish(
            {
                "profile_name": str(self._name_var.get() or "").strip(),
                "requested_role": str(self._role_var.get() or "guest"),
                "update_notifications": bool(self._notify_var.get()),
            }
        )

    def _close_as_guest(self) -> None:
        self._finish(
            {
                "profile_name": "",
                "requested_role": "guest",
                "update_notifications": bool(self._notify_var.get()),
            }
        )


def show_onboarding_popup(user: dict, on_complete: Callable[[dict], None] | None = None) -> None:
    def _build(parent: tk.Misc) -> None:
        try:
            OnboardingPopup(parent, user, on_complete)
        except Exception as exc:
            log_error("Onboarding popup failed", exc=exc)

    parent = _overlay_parent()
    if parent is not None:
        try:
            parent.after(0, lambda: _build(parent))
            return
        except Exception as exc:
            log_error("Onboarding popup schedule failed", exc=exc)

    def _run() -> None:
        root = tk.Tk()
        root.withdraw()
        register(root, persistent=True)
        _build(root)
        root.mainloop()

    threading.Thread(target=_run, name="silva-onboarding", daemon=True).start()
