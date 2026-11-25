"""Bug report popup — type or review before sending."""

from __future__ import annotations

import threading
import tkinter as tk
import tkinter.font as tkfont
from typing import Callable

from silva.gui.display_manager import register, unregister
from silva.users.bug_reports import create_report, forward_report, list_reports_for_reviewer, resolve_report


class BugReportDialog:
    def __init__(
        self,
        parent: tk.Misc,
        *,
        user: dict,
        initial_text: str = "",
        on_sent: Callable[[str], None] | None = None,
    ) -> None:
        self.user = user
        self._on_sent = on_sent
        self._closed = False

        self.dialog = tk.Toplevel(parent)
        register(self.dialog)
        self.dialog.title("Silva - Bug Report")
        self.dialog.resizable(True, True)
        self.dialog.attributes("-topmost", True)
        self.dialog.transient(parent)
        self.dialog.protocol("WM_DELETE_WINDOW", self._close)

        body = tkfont.Font(family="Segoe UI", size=10)
        title = tkfont.Font(family="Segoe UI", size=11, weight="bold")

        self.dialog.geometry("520x420")
        tk.Label(self.dialog, text="Report a Silva bug", font=title, fg="#1A237E").pack(
            anchor="w", padx=14, pady=(12, 4)
        )
        tk.Label(
            self.dialog,
            text="Describe the issue. Review below, then send to the next tier for help.",
            font=body,
            fg="#607D8B",
            wraplength=480,
        ).pack(anchor="w", padx=14)

        self._text = tk.Text(self.dialog, font=body, height=10, wrap="word")
        self._text.pack(fill="both", expand=True, padx=14, pady=8)
        if initial_text:
            self._text.insert("1.0", initial_text)

        self._status = tk.StringVar(value="")
        tk.Label(self.dialog, textvariable=self._status, font=body, fg="#1B5E20").pack(anchor="w", padx=14)

        row = tk.Frame(self.dialog)
        row.pack(fill="x", padx=14, pady=(0, 12))
        tk.Button(row, text="Send Report", font=body, width=12, command=self._send).pack(side="left", padx=(0, 6))
        tk.Button(row, text="Close", font=body, width=10, command=self._close).pack(side="right")

        reviewer_items = list_reports_for_reviewer(user)
        if reviewer_items:
            admin = tk.LabelFrame(self.dialog, text="Reports waiting for you", font=body, padx=8, pady=6)
            admin.pack(fill="x", padx=14, pady=(0, 10))
            for item in reviewer_items[-3:]:
                line = f"{item.get('id')}: {item.get('reporter_name')} — {item.get('message', '')[:80]}"
                tk.Label(admin, text=line, font=body, anchor="w", wraplength=470).pack(anchor="w")
                btns = tk.Frame(admin)
                btns.pack(anchor="w", pady=(2, 6))
                rid = item["id"]
                tk.Button(
                    btns,
                    text="Forward up",
                    font=body,
                    command=lambda report_id=rid: self._forward(report_id),
                ).pack(side="left", padx=(0, 4))
                tk.Button(
                    btns,
                    text="Mark resolved",
                    font=body,
                    command=lambda report_id=rid: self._resolve(report_id),
                ).pack(side="left")

    def _send(self) -> None:
        message = self._text.get("1.0", "end").strip()
        if len(message) < 8:
            self._status.set("Please add a little more detail before sending.")
            return
        report = create_report(user=self.user, message=message, source="typed")
        self._status.set(f"Report {report['id']} sent to tier {report['assigned_tier']} for review.")
        if self._on_sent:
            self._on_sent(message)

    def _forward(self, report_id: str) -> None:
        if forward_report(report_id, actor=self.user):
            self._status.set(f"Forwarded report {report_id} to a higher tier.")

    def _resolve(self, report_id: str) -> None:
        if resolve_report(report_id, actor=self.user):
            self._status.set(f"Resolved report {report_id}.")

    def _close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.dialog.winfo_exists():
            unregister(self.dialog)
            self.dialog.destroy()


def run_bug_report_dialog(user: dict, *, initial_text: str = "") -> None:
    def _run() -> None:
        root = tk.Tk()
        root.withdraw()
        BugReportDialog(root, user=user, initial_text=initial_text)
        root.mainloop()
        try:
            root.destroy()
        except tk.TclError:
            pass

    threading.Thread(target=_run, daemon=True).start()
