from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, scrolledtext, simpledialog, ttk

from silva.gui.display_manager import register, unregister
from silva.gui.live_chat_instance import (
    LIVE_CHAT_TITLE,
    acquire_live_chat_instance,
    consume_live_chat_notification,
    consume_live_chat_request,
    focus_existing_live_chat,
)
from silva.users.live_chat import (
    can_moderate_live_chat,
    can_reply_live_chat,
    is_live_chat_blocked,
    kick_live_chat_user,
    list_live_chat_messages,
    mark_live_chat_read,
    reply_live_chat_message,
    set_live_chat_blocked,
    submit_live_chat_message,
    unread_live_chat_count,
)
from silva.users.manager import get_active_user


class LiveChatPopupApp:
    def __init__(self) -> None:
        if not acquire_live_chat_instance():
            focus_existing_live_chat()
            raise SystemExit(0)

        self.root = tk.Tk()
        register(self.root)
        self.root.title(LIVE_CHAT_TITLE)
        self.root.geometry("820x620")
        self.root.minsize(680, 500)

        self._title_font = tkfont.Font(family="Segoe UI", size=12, weight="bold")
        self._body_font = tkfont.Font(family="Segoe UI", size=10)
        self._mono_font = tkfont.Font(family="Consolas", size=9)

        self.user = get_active_user() or {}
        self.user_id = str(self.user.get("id") or "guest")
        self.is_staff = can_reply_live_chat(self.user)
        self.can_moderate = can_moderate_live_chat(self.user)
        self.selected_user = self.user_id
        self.messages: list[dict] = []
        self._last_unread = 0
        self._poll_job: str | None = None

        self._build_ui()
        self._apply_request()
        self._refresh()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._poll_job = self.root.after(1500, self._poll)

    def _build_ui(self) -> None:
        header = tk.Label(
            self.root,
            text="Silva Live Chat",
            font=self._title_font,
            fg="#1A237E",
        )
        header.pack(pady=(10, 2))

        self.status_var = tk.StringVar(value="")
        tk.Label(
            self.root,
            textvariable=self.status_var,
            font=self._body_font,
            fg="#546E7A",
        ).pack(pady=(0, 6))

        body = tk.Frame(self.root)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=4)
        body.rowconfigure(0, weight=1)

        if self.is_staff:
            side = ttk.Frame(body)
            side.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
            tk.Label(side, text="User threads", font=self._body_font).pack(anchor="w")
            self.thread_box = tk.Listbox(side, font=self._body_font, height=12)
            self.thread_box.pack(fill="both", expand=True, pady=(4, 8))
            self.thread_box.bind("<<ListboxSelect>>", self._on_thread_select)
            mod_bar = ttk.Frame(side)
            mod_bar.pack(fill="x")
            ttk.Button(mod_bar, text="Block", width=8, command=self._block_selected).pack(side="left", padx=(0, 4))
            ttk.Button(mod_bar, text="Unblock", width=9, command=self._unblock_selected).pack(side="left", padx=(0, 4))
            ttk.Button(mod_bar, text="Kick", width=8, command=self._kick_selected).pack(side="left")
            if not self.can_moderate:
                for child in mod_bar.winfo_children():
                    child.configure(state="disabled")
        else:
            self.thread_box = None

        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(0, weight=1)
        right.rowconfigure(1, weight=0)

        self.history = scrolledtext.ScrolledText(
            right,
            font=self._mono_font,
            wrap="word",
            height=18,
        )
        self.history.grid(row=0, column=0, sticky="nsew")
        self.history.configure(state="disabled")

        entry_bar = ttk.Frame(right)
        entry_bar.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        entry_bar.columnconfigure(0, weight=1)
        self.message_box = tk.Text(entry_bar, height=3, wrap="word", font=self._body_font)
        self.message_box.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.message_box.bind("<Return>", self._on_return)
        self.send_button = ttk.Button(entry_bar, text="Send", width=12, command=self._send)
        self.send_button.grid(row=0, column=1)

        footer = ttk.Frame(self.root)
        footer.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(footer, text="Refresh", width=12, command=self._refresh).pack(side="left", padx=(0, 6))
        ttk.Button(footer, text="Minimize", width=12, command=self._minimize).pack(side="left", padx=(0, 6))
        ttk.Button(footer, text="Close", width=12, command=self._on_close).pack(side="left")

    def _on_return(self, event):
        self._send()
        return "break"

    def _minimize(self) -> None:
        self.root.iconify()

    def _on_close(self) -> None:
        if self._poll_job is not None:
            try:
                self.root.after_cancel(self._poll_job)
            except Exception:
                pass
        unregister(self.root)
        self.root.destroy()

    def _apply_request(self) -> None:
        request = consume_live_chat_request()
        requested_user = str(request.get("user_id") or "")
        if requested_user and self.is_staff:
            self.selected_user = requested_user

    def _thread_users(self) -> list[str]:
        users: list[str] = []
        for item in list_live_chat_messages():
            user_id = str(item.get("user_id") or item.get("thread_id") or "")
            if user_id and user_id not in users:
                users.append(user_id)
        if self.user_id not in users:
            users.insert(0, self.user_id)
        return users

    def _selected_thread(self) -> str:
        if self.is_staff:
            return str(self.selected_user or self.user_id)
        return self.user_id

    def _refresh_threads(self) -> None:
        if self.thread_box is None:
            return
        users = self._thread_users()
        self.thread_box.delete(0, tk.END)
        for user_id in users:
            prefix = "BLOCKED " if is_live_chat_blocked(user_id) else ""
            self.thread_box.insert(tk.END, f"{prefix}{user_id}")
        if self.selected_user in users:
            self.thread_box.selection_set(users.index(self.selected_user))

    def _on_thread_select(self, _event=None) -> None:
        if self.thread_box is None:
            return
        selection = self.thread_box.curselection()
        if not selection:
            return
        users = self._thread_users()
        index = int(selection[0])
        if 0 <= index < len(users):
            self.selected_user = users[index]
            self._refresh_history()

    def _refresh_history(self) -> None:
        self.messages = list_live_chat_messages(user_id=self._selected_thread())
        self.history.configure(state="normal")
        self.history.delete("1.0", tk.END)
        for item in self.messages:
            label = str(item.get("author_label") or "system")
            created = str(item.get("created_at") or "")
            text = str(item.get("text") or "")
            self.history.insert(tk.END, f"[{created}] {label}: {text}\n")
        self.history.configure(state="disabled")
        self.history.see(tk.END)

    def _refresh_status(self) -> None:
        blocked = is_live_chat_blocked(self._selected_thread())
        if self.is_staff:
            label = "Staff view" if self.is_staff else "User view"
            self.status_var.set(f"{label} — thread: {self._selected_thread()}" + (" — BLOCKED" if blocked else ""))
        else:
            self.status_var.set("Chat with the owner, admins, and chat reps." + (" Your typing is blocked." if blocked else ""))
        self.message_box.configure(state="disabled" if blocked else "normal")
        self.send_button.configure(state="disabled" if blocked else "normal")

    def _refresh(self) -> None:
        self._apply_request()
        self._refresh_threads()
        self._refresh_history()
        self._refresh_status()
        mark_live_chat_read(user_id=self.user_id, staff=self.is_staff)
        self._update_notification()

    def _update_notification(self) -> None:
        unread = unread_live_chat_count(user_id=self.user_id, staff=self.is_staff)
        if unread > self._last_unread:
            self.root.title("(new message) " + LIVE_CHAT_TITLE)
            self.root.bell()
            notice = consume_live_chat_notification()
            message = str(notice.get("message") or "New live chat message.")
            self.status_var.set(message)
        elif unread == 0:
            self.root.title(LIVE_CHAT_TITLE)
        self._last_unread = unread

    def _send(self) -> None:
        text = self.message_box.get("1.0", tk.END).strip()
        if not text:
            return
        if self.is_staff:
            target = next(
                (item for item in reversed(self.messages) if item.get("direction") == "user_to_staff"),
                self.messages[-1] if self.messages else None,
            )
            if target is None:
                self.status_var.set("No user message to reply to yet.")
                return
            ok, message = reply_live_chat_message(str(target.get("id") or ""), self.user, text)
        else:
            result = submit_live_chat_message(self.user, text)
            ok = str(result.get("status") or "") not in {"blocked", "empty"}
            message = "" if ok else "You cannot send a message right now."
        if ok:
            self.message_box.delete("1.0", tk.END)
        self.status_var.set(message if message else "Message sent.")
        self._refresh()

    def _block_selected(self) -> None:
        if not self.can_moderate:
            return
        reason = simpledialog.askstring("Block chat", "Reason:", parent=self.root) or ""
        ok, message = set_live_chat_blocked(
            self.user,
            self._selected_thread(),
            blocked=True,
            reason=reason,
        )
        self.status_var.set(message if not ok else message)
        self._refresh()

    def _unblock_selected(self) -> None:
        if not self.can_moderate:
            return
        ok, message = set_live_chat_blocked(self.user, self._selected_thread(), blocked=False)
        self.status_var.set(message)
        self._refresh()

    def _kick_selected(self) -> None:
        if not self.can_moderate:
            return
        reason = simpledialog.askstring("Kick user", "Reason:", parent=self.root) or ""
        ok, message = kick_live_chat_user(self.user, self._selected_thread(), reason=reason)
        if not ok:
            messagebox.showwarning("Not allowed", message, parent=self.root)
        self.status_var.set(message)
        self._refresh()

    def _poll(self) -> None:
        request = consume_live_chat_request()
        if request:
            self._apply_request()
        unread = unread_live_chat_count(user_id=self.user_id, staff=self.is_staff)
        if unread > self._last_unread or request:
            self._refresh()
        else:
            self._update_notification()
        self._poll_job = self.root.after(1500, self._poll)

    def run(self) -> None:
        self.root.mainloop()


def run_live_chat_popup() -> None:
    LiveChatPopupApp().run()
