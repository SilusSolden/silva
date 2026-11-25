"""Owner security panel — review access attempts, allow, kick, block."""

from __future__ import annotations

import threading
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass

from silva.gui.display_manager import register, unregister
from silva.users.access_security import (
    block_actor,
    grant_temporary_access,
    list_pending_attempts,
    list_unread_alerts,
    mark_alerts_read,
    update_attempt_status,
)
from silva.users.manager import get_active_user, get_owner, is_owner


@dataclass
class SecurityPanelResult:
    closed: bool = True


def _run_panel(result: dict) -> None:
    root = tk.Tk()
    register(root)
    root.title("Silva - Security")
    root.resizable(True, True)
    root.attributes("-topmost", True)
    root.geometry("640x520")

    title_font = tkfont.Font(family="Segoe UI", size=12, weight="bold")
    body = tkfont.Font(family="Segoe UI", size=10)
    small = tkfont.Font(family="Segoe UI", size=9)

    if not is_owner(get_active_user()):
        tk.Label(root, text="Owner access only.", font=title_font, fg="#C62828").pack(pady=20)
        tk.Button(root, text="Close", command=root.destroy).pack()
        root.mainloop()
        return

    tk.Label(root, text="Security Center", font=title_font, fg="#1A237E").pack(pady=(12, 4))
    tk.Label(
        root,
        text="Review who is trying to access protected profiles. Allow with a time limit, or block instantly.",
        font=small,
        fg="#455A64",
        wraplength=580,
    ).pack(pady=(0, 8))

    alerts_frame = tk.LabelFrame(root, text="Recent alerts", font=body, padx=8, pady=6)
    alerts_frame.pack(fill="x", padx=12, pady=(0, 6))
    alerts_box = tk.Listbox(alerts_frame, font=small, height=4)
    alerts_box.pack(fill="x")

    pending_frame = tk.LabelFrame(root, text="Pending access attempts", font=body, padx=8, pady=6)
    pending_frame.pack(fill="both", expand=True, padx=12, pady=(0, 6))
    pending_box = tk.Listbox(pending_frame, font=small, height=10)
    pending_box.pack(fill="both", expand=True)

    status = tk.Label(root, text="", font=small, fg="#37474F")
    status.pack(fill="x", padx=12, pady=(0, 4))

    controls = tk.Frame(root)
    controls.pack(fill="x", padx=12, pady=(0, 12))

    attempt_map: dict[int, dict] = {}

    def refresh() -> None:
        alerts_box.delete(0, tk.END)
        for alert in list_unread_alerts()[-8:]:
            alerts_box.insert(tk.END, alert.get("message", ""))

        pending_box.delete(0, tk.END)
        attempt_map.clear()
        for index, item in enumerate(list_pending_attempts()[-20:]):
            label = (
                f"{item['actor_name']} → {item['target_name']} (tier {item['target_tier']}) "
                f"[{item['reason']}] score {item.get('voice_score', 0):.2f}"
            )
            pending_box.insert(tk.END, label)
            attempt_map[index] = item

    def selected() -> dict | None:
        sel = pending_box.curselection()
        if not sel:
            return None
        return attempt_map.get(int(sel[0]))

    def allow_access() -> None:
        item = selected()
        if item is None:
            status.config(text="Select an attempt first.", fg="#C62828")
            return
        minutes = int(minutes_var.get())
        owner = get_owner()
        grant_temporary_access(
            item["id"],
            actor_id=item["actor_id"],
            target_user_id=item["target_user_id"],
            minutes=minutes,
            approver_id=owner["id"],
        )
        status.config(
            text=f"Allowed {item['actor_name']} for {minutes} minutes.",
            fg="#1B5E20",
        )
        refresh()

    def kick_block() -> None:
        item = selected()
        if item is None:
            status.config(text="Select an attempt first.", fg="#C62828")
            return
        block_actor(
            item["actor_id"],
            item["target_user_id"],
            reason="blocked_by_owner_from_security_panel",
        )
        update_attempt_status(item["id"], "denied")
        status.config(text=f"Blocked {item['actor_name']} from {item['target_name']}.", fg="#C62828")
        refresh()

    def deny_only() -> None:
        item = selected()
        if item is None:
            return
        update_attempt_status(item["id"], "denied")
        status.config(text="Attempt denied.", fg="#37474F")
        refresh()

    def close_panel() -> None:
        mark_alerts_read()
        result["value"] = SecurityPanelResult(closed=True)
        unregister(root)
        root.destroy()

    tk.Label(controls, text="Allow for:", font=small).pack(side="left")
    minutes_var = tk.StringVar(value="15")
    tk.OptionMenu(controls, minutes_var, "5", "15", "30", "60", "120").pack(side="left", padx=6)
    tk.Button(controls, text="Allow", font=body, width=10, command=allow_access).pack(side="left", padx=4)
    tk.Button(controls, text="Deny", font=body, width=8, command=deny_only).pack(side="left", padx=4)
    tk.Button(controls, text="Kick & Block", font=body, width=12, command=kick_block).pack(side="left", padx=4)
    tk.Button(controls, text="Close", font=body, width=10, command=close_panel).pack(side="right")

    refresh()
    root.protocol("WM_DELETE_WINDOW", close_panel)
    root.mainloop()


def run_security_panel() -> SecurityPanelResult:
    result: dict = {"value": SecurityPanelResult(closed=True)}
    thread = threading.Thread(target=_run_panel, args=(result,), daemon=True)
    thread.start()
    thread.join(timeout=600)
    return result.get("value", SecurityPanelResult(closed=True))
