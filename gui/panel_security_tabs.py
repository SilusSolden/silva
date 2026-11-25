"""Owner/admin System Panel tabs with staged, reviewed update controls."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

from PIL import Image, ImageDraw, ImageTk

from silva.dev.admin_review_queue import (
    list_pending_admin_reviews,
    mark_admin_review_applied,
    queue_admin_update,
    review_admin_review,
)
from silva.dev.code_lab import check_python_snippet, format_check_result
from silva.dev.panel_registry import register_panel_tab
from silva.dev.live_update import read_progress
from silva.users.admin_access import (
    CAPABILITIES,
    capability_states,
    reset_user_capabilities,
    set_capability,
)
from silva.users.feature_requests import (
    approve_feature_request,
    block_feature_requests,
    list_pending_feature_requests,
)
from silva.users.manager import get_active_user, is_owner, list_users
from silva.users.profile_access import can_open_control_panel
from silva.users.test_accounts import (
    activate_test_account,
    create_test_account,
    return_to_owner,
)
from silva.users.voice_access import (
    can_request_voice_control,
    list_pending_voice_access_requests,
    reference_image_path,
    requestable_voice_scopes,
    review_voice_access_request,
    submit_voice_access_request,
)


def _user() -> dict:
    return get_active_user() or {}


def _can_view() -> bool:
    return can_open_control_panel(_user())


def _is_owner() -> bool:
    return is_owner(_user())


def _deny(app, action: str) -> bool:
    if not _can_view():
        messagebox.showwarning(
            "Not allowed",
            f"Only the owner and tier 4 admins can {action} from the System Panel.",
            parent=app.root,
        )
        return True
    return False


def _deny_owner(app, action: str) -> bool:
    if not _is_owner():
        messagebox.showwarning("Not allowed", f"Only the owner can {action}.", parent=app.root)
        return True
    return False


def _parse_lines(text: str) -> list[str]:
    result: list[str] = []
    for raw in str(text or "").splitlines():
        item = raw.strip()
        if item and not item.startswith("#") and item not in result:
            result.append(item)
    return result


def _restricted_label(app, frame, action: str) -> None:
    tk.Label(
        frame,
        text=f"Only the owner and tier 4 admins can {action}.",
        font=app._body_font,
        fg="#C62828",
        wraplength=680,
        justify="left",
    ).pack(anchor="w", padx=12, pady=12)


def build_feature_request_tab(app, frame) -> None:
    if not _can_view():
        _restricted_label(app, frame, "review feature requests")
        return

    tk.Label(
        frame,
        text="Pending feature requests — owner can approve or block.",
        font=app._body_font,
        fg="#37474F",
    ).pack(anchor="w", padx=10, pady=(10, 4))

    bar = tk.Frame(frame)
    bar.pack(fill="x", padx=10, pady=6)
    refresh_btn = tk.Button(bar, text="Refresh", width=12)
    refresh_btn.pack(side="left", padx=(0, 8))
    approve_btn = tk.Button(bar, text="Approve", width=12)
    block_btn = tk.Button(bar, text="Block", width=12)
    approve_btn.pack(side="left", padx=(0, 8))
    block_btn.pack(side="left")

    listbox = tk.Listbox(frame, height=10, font=app._body_font)
    listbox.pack(fill="both", padx=10, pady=(0, 8))

    detail = scrolledtext.ScrolledText(frame, font=app._mono_font, height=8, wrap="word")
    detail.pack(fill="both", expand=True, padx=10, pady=(0, 10))
    detail.config(state="disabled")

    items: list[dict] = []

    def show_detail(item: dict | None) -> None:
        detail.config(state="normal")
        detail.delete("1.0", tk.END)
        if item:
            detail.insert(
                "1.0",
                "\n".join(
                    [
                        f"User: {item.get('user_name') or 'Guest'} ({item.get('user_id') or 'guest'})",
                        f"Feature: {item.get('feature') or ''}",
                        f"Reason: {item.get('reason') or 'No extra detail given.'}",
                        f"Submitted: {item.get('submitted_at') or ''}",
                        f"Status: {item.get('status') or 'pending'}",
                    ]
                ),
            )
        detail.config(state="disabled")

    def selected() -> dict | None:
        selection = listbox.curselection()
        if not selection:
            return None
        index = int(selection[0])
        return items[index] if 0 <= index < len(items) else None

    def refresh() -> None:
        nonlocal items
        items = list_pending_feature_requests()
        listbox.delete(0, tk.END)
        for item in items:
            name = item.get("user_name") or item.get("user_id") or "Guest"
            feature = item.get("feature") or "feature"
            reason = str(item.get("reason") or "").strip()
            suffix = f" — {reason}" if reason else ""
            listbox.insert(tk.END, f"{name}: {feature}{suffix}")
        show_detail(items[0] if items else None)

    def approve() -> None:
        if _deny_owner(app, "approve feature requests"):
            return
        item = selected()
        if not item:
            messagebox.showinfo("No selection", "Choose a request first.", parent=app.root)
            return
        approve_feature_request(
            str(item.get("user_id") or ""),
            str(item.get("feature") or ""),
            approver_id=str(_user().get("id") or "owner"),
        )
        refresh()

    def block() -> None:
        if _deny_owner(app, "block feature requests"):
            return
        item = selected()
        if not item:
            messagebox.showinfo("No selection", "Choose a request first.", parent=app.root)
            return
        if not messagebox.askyesno(
            "Block request",
            f"Block this request from {item.get('user_name') or 'Guest'}?",
            parent=app.root,
        ):
            return
        block_feature_requests(
            str(item.get("user_id") or ""),
            str(item.get("feature") or ""),
            by=str(_user().get("id") or "owner"),
        )
        refresh()

    def on_select(_event=None) -> None:
        show_detail(selected())

    refresh_btn.config(command=refresh)
    approve_btn.config(command=approve)
    block_btn.config(command=block)
    listbox.bind("<<ListboxSelect>>", on_select)
    refresh()


def build_update_queue_tab(app, frame) -> None:
    if not _can_view():
        _restricted_label(app, frame, "stage updates")
        return

    top = tk.Frame(frame)
    top.pack(fill="both", expand=True, padx=10, pady=(10, 6))

    left = tk.Frame(top)
    left.pack(side="left", fill="both", expand=True, padx=(0, 6))
    right = tk.Frame(top)
    right.pack(side="left", fill="both", expand=True, padx=(6, 0))

    tk.Label(left, text="Features to add/change (one per line):", font=app._body_font).pack(anchor="w")
    features_box = scrolledtext.ScrolledText(left, font=app._body_font, height=5)
    features_box.pack(fill="x", pady=(0, 8))

    tk.Label(left, text="Changelog / reason (one per line):", font=app._body_font).pack(anchor="w")
    reason_box = scrolledtext.ScrolledText(left, font=app._body_font, height=4)
    reason_box.pack(fill="x", pady=(0, 8))

    tk.Label(left, text="Optional code snippet (checked only, never run):", font=app._body_font).pack(anchor="w")
    code_box = scrolledtext.ScrolledText(left, font=app._mono_font, height=7)
    code_box.pack(fill="both", expand=True)

    tk.Label(right, text="Staged submissions:", font=app._body_font).pack(anchor="w")
    listbox = tk.Listbox(right, height=8, font=app._body_font)
    listbox.pack(fill="both", expand=True, pady=(0, 8))

    detail = scrolledtext.ScrolledText(right, font=app._mono_font, height=9, wrap="word")
    detail.pack(fill="both", expand=True)
    detail.config(state="disabled")

    bar = tk.Frame(frame)
    bar.pack(fill="x", padx=10, pady=6)
    check_btn = tk.Button(bar, text="Check Code", width=14)
    submit_btn = tk.Button(bar, text="Submit to Owner", width=16)
    refresh_btn = tk.Button(bar, text="Refresh Queue", width=14)
    check_btn.pack(side="left", padx=(0, 6))
    submit_btn.pack(side="left", padx=(0, 6))
    refresh_btn.pack(side="left")
    approve_btn = tk.Button(bar, text="Approve & Apply", width=16)
    reject_btn = tk.Button(bar, text="Reject", width=12)
    approve_btn.pack(side="left", padx=(6, 6))
    reject_btn.pack(side="left")

    status_bar = tk.Frame(frame)
    status_bar.pack(fill="x", padx=10, pady=(0, 4))
    progress = ttk.Progressbar(status_bar, orient="horizontal", mode="determinate", maximum=100)
    progress.pack(side="left", fill="x", expand=True, padx=(0, 8))
    status = tk.Label(status_bar, text="Idle", font=app._body_font, fg="#37474F")
    status.pack(side="left")

    output = scrolledtext.ScrolledText(frame, font=app._mono_font, height=7, wrap="word")
    output.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    items: list[dict] = []

    def write_output(text: str) -> None:
        output.delete("1.0", tk.END)
        output.insert("1.0", text)

    def refresh_status() -> None:
        data = read_progress()
        percent = int(data.get("percent") or 0)
        step = str(data.get("step") or "Idle")
        progress["value"] = percent
        status.config(text=f"{step} ({percent}%)")
        return data

    def show_detail(item: dict | None) -> None:
        detail.config(state="normal")
        detail.delete("1.0", tk.END)
        if item:
            lines = [
                f"ID: {item.get('id') or ''}",
                f"From: {item.get('submitted_by_name') or 'Guest'} ({item.get('submitted_by') or 'guest'})",
                f"Submitted: {item.get('submitted_at') or ''}",
                f"Kind: {item.get('kind') or ''}",
                f"Status: {item.get('status') or ''}",
                f"Features: {', '.join(item.get('features') or []) or 'none'}",
                f"Reason: {', '.join(item.get('changelog') or []) or 'none'}",
            ]
            if item.get("code"):
                lines.extend(["", "Code snippet:", str(item.get("code"))])
            checks = item.get("checks") or {}
            if isinstance(checks, dict) and checks:
                lines.extend(["", f"Checks: {checks.get('summary') or ''}"])
            detail.insert("1.0", "\n".join(lines))
        detail.config(state="disabled")

    def selected() -> dict | None:
        selection = listbox.curselection()
        if not selection:
            return None
        index = int(selection[0])
        return items[index] if 0 <= index < len(items) else None

    def refresh() -> None:
        nonlocal items
        items = list_pending_admin_reviews()
        listbox.delete(0, tk.END)
        for item in items:
            who = item.get("submitted_by_name") or item.get("submitted_by") or "Guest"
            kind = item.get("kind") or "update"
            features = ", ".join(item.get("features") or [])
            suffix = features or "code snippet"
            listbox.insert(tk.END, f"{item.get('id')} | {who} | {kind} | {suffix}")
        show_detail(items[0] if items else None)
        refresh_status()

    def check_code() -> None:
        result = check_python_snippet(code_box.get("1.0", tk.END))
        write_output(format_check_result(result))

    def submit() -> None:
        if _deny(app, "stage updates"):
            return
        features = _parse_lines(features_box.get("1.0", tk.END))
        reasons = _parse_lines(reason_box.get("1.0", tk.END))
        source = code_box.get("1.0", tk.END).strip()
        if not features and not source:
            messagebox.showinfo(
                "Nothing to submit",
                "Add features, a changelog reason, or a code snippet first.",
                parent=app.root,
            )
            return
        checks: dict = {}
        if source:
            result = check_python_snippet(source)
            checks = result.to_dict()
            if not result.syntax_ok:
                messagebox.showwarning("Code check failed", result.summary, parent=app.root)
                return
            write_output(format_check_result(result))
        if not reasons:
            reasons = ["Admin-staged update from the System Panel."]
        item = queue_admin_update(
            _user(),
            features=features,
            changelog=reasons,
            code=source,
            checks=checks,
        )
        messagebox.showinfo(
            "Staged for owner",
            f"Submission {item['id']} is waiting for owner review.",
            parent=app.root,
        )
        refresh()

    def approve_apply() -> None:
        if _deny_owner(app, "approve staged updates"):
            return
        item = selected()
        if not item:
            messagebox.showinfo("No selection", "Choose a staged submission first.", parent=app.root)
            return
        ok, reviewed, message = review_admin_review(
            str(item.get("id") or ""),
            reviewer=_user(),
            approve=True,
            note="Approved from System Panel.",
        )
        if not ok:
            messagebox.showwarning("Not approved", message, parent=app.root)
            refresh()
            return

        write_output(f"Approved {reviewed['id']} for {reviewed.get('submitted_by_name') or 'Guest'}.")
        if reviewed.get("code"):
            write_output(
                output.get("1.0", tk.END)
                + "\nCode snippet was checked and approved for owner review. "
                "It was not executed or written to the codebase."
            )

        features = [str(value) for value in (reviewed.get("features") or []) if str(value).strip()]
        if not features:
            refresh()
            return
        summary = "\n".join(f"- {value}" for value in reviewed.get("changelog") or [])
        if not messagebox.askyesno(
            "Apply owner-approved update",
            "Apply this owner-approved update to the running Silva assistant?\n\n" + summary,
            parent=app.root,
        ):
            refresh()
            return

        from silva.dev.panel_update import publish_panel_update
        from silva.dev.live_update import apply_pending_update, queue_live_update
        from silva.notifications.dispatch import notify_owner_async

        changelog = [str(value) for value in (reviewed.get("changelog") or []) if str(value).strip()]
        changelog.append(f"Owner-approved update staged by {reviewed.get('submitted_by_name') or 'admin'}.")
        if reviewed.get("code"):
            changelog.append("Reviewed code proposal was not auto-applied.")
        manifest, scan = publish_panel_update(features=features, changelog=changelog)
        queue_live_update(features=features)
        applied, apply_message = apply_pending_update()
        mark_admin_review_applied(str(reviewed["id"]), owner=_user())
        app._features_box.delete("1.0", tk.END)
        app._features_box.insert("1.0", "\n".join(features))
        app._append_update_log(f"Owner-approved submission {reviewed['id']}.")
        app._append_update_log(apply_message)
        app._update_status.config(
            text=f"Update applied: {manifest.get('version', '')}" if applied else apply_message,
            fg="#2E7D32" if applied else "#C62828",
        )
        notify_owner_async(
            f"Owner-approved System Panel update {manifest.get('version', '')} was applied.",
            reason="silva_update_publish",
            prefer_telegram=True,
        )
        write_output(output.get("1.0", tk.END) + f"\n{scan.changes}\n{apply_message}")
        refresh_status()
        refresh()

    def reject() -> None:
        if _deny_owner(app, "reject staged updates"):
            return
        item = selected()
        if not item:
            messagebox.showinfo("No selection", "Choose a staged submission first.", parent=app.root)
            return
        ok, _reviewed, message = review_admin_review(
            str(item.get("id") or ""),
            reviewer=_user(),
            approve=False,
            note="Rejected from System Panel.",
        )
        if not ok:
            messagebox.showwarning("Not rejected", message, parent=app.root)
        refresh()

    def on_select(_event=None) -> None:
        show_detail(selected())

    check_btn.config(command=check_code)
    submit_btn.config(command=submit)
    refresh_btn.config(command=refresh)
    approve_btn.config(command=approve_apply)
    reject_btn.config(command=reject)
    listbox.bind("<<ListboxSelect>>", on_select)
    refresh()


def build_code_lab_tab(app, frame) -> None:
    if not _can_view():
        _restricted_label(app, frame, "open Code Lab")
        return

    tk.Label(
        frame,
        text="Code Lab — static checks only. Nothing here runs or edits Silva by itself.",
        font=app._body_font,
        fg="#C62828",
        wraplength=680,
        justify="left",
    ).pack(anchor="w", padx=10, pady=(10, 4))

    code_box = scrolledtext.ScrolledText(frame, font=app._mono_font, height=14, wrap="none")
    code_box.pack(fill="both", expand=True, padx=10, pady=(0, 8))

    bar = tk.Frame(frame)
    bar.pack(fill="x", padx=10, pady=6)
    check_btn = tk.Button(bar, text="Check Code", width=14)
    submit_btn = tk.Button(bar, text="Submit to Owner", width=16)
    clear_btn = tk.Button(bar, text="Clear", width=10)
    check_btn.pack(side="left", padx=(0, 6))
    submit_btn.pack(side="left", padx=(0, 6))
    clear_btn.pack(side="left")

    output = scrolledtext.ScrolledText(frame, font=app._mono_font, height=10, wrap="word")
    output.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def write_output(text: str) -> None:
        output.delete("1.0", tk.END)
        output.insert("1.0", text)

    def check() -> None:
        result = check_python_snippet(code_box.get("1.0", tk.END))
        write_output(format_check_result(result))

    def submit() -> None:
        if _deny(app, "submit code for review"):
            return
        source = code_box.get("1.0", tk.END).strip()
        result = check_python_snippet(source)
        write_output(format_check_result(result))
        if not result.syntax_ok:
            messagebox.showwarning("Code check failed", result.summary, parent=app.root)
            return
        item = queue_admin_update(
            _user(),
            features=[],
            changelog=["Code snippet submitted from Code Lab for owner review."],
            code=source,
            checks=result.to_dict(),
        )
        messagebox.showinfo(
            "Staged for owner",
            f"Code snippet {item['id']} is waiting for owner review. Nothing was executed.",
            parent=app.root,
        )

    def clear() -> None:
        code_box.delete("1.0", tk.END)
        output.delete("1.0", tk.END)

    check_btn.config(command=check)
    submit_btn.config(command=submit)
    clear_btn.config(command=clear)


def build_voice_access_requests_tab(app, frame) -> None:
    if not _can_view():
        _restricted_label(app, frame, "review voice-control access")
        return

    top = tk.Frame(frame)
    top.pack(fill="both", expand=True, padx=10, pady=(10, 6))

    left = tk.Frame(top)
    left.pack(side="left", fill="both", expand=True, padx=(0, 6))
    right = tk.Frame(top)
    right.pack(side="left", fill="both", expand=True, padx=(6, 0))

    tk.Label(left, text="Basic voice access", font=app._body_font).pack(anchor="w")
    tk.Label(
        left,
        text=(
            "After voice enrollment, everyone can use voice for normal conversation, images and visual "
            "guides, math, weather/news, notes, appointments, audio, and playback. Major system controls "
            "still need owner approval."
        ),
        font=app._body_font,
        fg="#37474F",
        wraplength=320,
        justify="left",
    ).pack(anchor="w", fill="x", pady=(0, 8))

    requestable = requestable_voice_scopes(_user())
    scope_items = sorted((label, key) for key, label in requestable.items())
    tk.Label(left, text="Request major system control for:", font=app._body_font).pack(anchor="w")
    scope_var = tk.StringVar(value=scope_items[0][0] if scope_items else "")
    scope_box = ttk.Combobox(
        left,
        textvariable=scope_var,
        values=[label for label, _key in scope_items],
        state="readonly" if scope_items else "disabled",
        font=app._body_font,
    )
    scope_box.pack(fill="x", pady=(0, 8))

    tk.Label(left, text="Why do you need this control?", font=app._body_font).pack(anchor="w")
    reason_box = tk.Entry(left, font=app._body_font, state="normal" if scope_items else "disabled")
    reason_box.pack(fill="x", pady=(0, 8))
    submit_btn = tk.Button(
        left,
        text="Submit Request",
        width=18,
        state="normal" if scope_items else "disabled",
    )
    submit_btn.pack(anchor="w", pady=(0, 6))
    form_status = tk.Label(left, text="", font=app._body_font, fg="#37474F", wraplength=320, justify="left")
    form_status.pack(anchor="w", fill="x")

    tk.Label(left, text="Pending voice-control requests:", font=app._body_font).pack(anchor="w", pady=(10, 2))
    listbox = tk.Listbox(left, height=9, font=app._body_font)
    listbox.pack(fill="both", expand=True)

    detail = scrolledtext.ScrolledText(right, font=app._mono_font, height=10, wrap="word")
    detail.pack(fill="both", expand=True)
    detail.config(state="disabled")

    image_label = tk.Label(
        right,
        text="Reference settings image not found.",
        font=app._body_font,
        fg="#455A64",
        justify="left",
    )
    image_label.pack(fill="both", expand=True, pady=(8, 0))

    bar = tk.Frame(frame)
    bar.pack(fill="x", padx=10, pady=6)
    refresh_btn = tk.Button(bar, text="Refresh", width=12)
    approve_btn = tk.Button(bar, text="Approve Scope", width=16)
    deny_btn = tk.Button(bar, text="Deny", width=12)
    refresh_btn.pack(side="left", padx=(0, 8))
    approve_btn.pack(side="left", padx=(0, 8))
    deny_btn.pack(side="left")

    items: list[dict] = []

    def show_detail(item: dict | None) -> None:
        detail.config(state="normal")
        detail.delete("1.0", tk.END)
        if item:
            detail.insert(
                "1.0",
                "\n".join(
                    [
                        f"ID: {item.get('id') or ''}",
                        f"From: {item.get('from_user') or 'Guest'} ({item.get('from_id') or 'guest'})",
                        f"Tier: {item.get('tier') or ''}",
                        f"Scope: {item.get('scope_label') or item.get('scope') or ''}",
                        f"Reason: {item.get('reason') or ''}",
                        f"Submitted: {item.get('submitted_at') or ''}",
                        f"Status: {item.get('status') or 'pending'}",
                        f"Reference: {item.get('reference_image') or ''}",
                    ]
                ),
            )
        detail.config(state="disabled")

    def selected() -> dict | None:
        selection = listbox.curselection()
        if not selection:
            return None
        index = int(selection[0])
        return items[index] if 0 <= index < len(items) else None

    def refresh() -> None:
        nonlocal items
        items = list_pending_voice_access_requests()
        listbox.delete(0, tk.END)
        for item in items:
            who = item.get("from_user") or item.get("from_id") or "Guest"
            scope = item.get("scope_label") or item.get("scope") or "control"
            listbox.insert(tk.END, f"{who}: {scope}")
        show_detail(items[0] if items else None)

    def submit() -> None:
        allowed, message = can_request_voice_control(_user())
        if not allowed:
            form_status.config(text=message, fg="#C62828")
            messagebox.showwarning("Not allowed", message, parent=app.root)
            return
        label = scope_var.get()
        key = next((value for text, value in scope_items if text == label), None)
        if not key:
            form_status.config(text="Choose a voice-control area.", fg="#C62828")
            return
        ok, item, message = submit_voice_access_request(_user(), key, reason_box.get())
        form_status.config(text=message if not ok else f"Submitted {item['id']} for owner approval.", fg="#C62828" if not ok else "#2E7D32")
        if ok:
            reason_box.delete(0, tk.END)
            refresh()

    def review(approve: bool) -> None:
        if _deny_owner(app, "review voice-control access"):
            return
        item = selected()
        if not item:
            messagebox.showinfo("No selection", "Choose a request first.", parent=app.root)
            return
        ok, _reviewed, message = review_voice_access_request(
            str(item.get("id") or ""),
            reviewer=_user(),
            approve=approve,
        )
        if not ok:
            messagebox.showwarning("Not updated", message, parent=app.root)
        refresh()

    def on_select(_event=None) -> None:
        show_detail(selected())

    def show_reference_image() -> None:
        path = Path(str(reference_image_path()))
        if not path.exists():
            return
        try:
            photo = tk.PhotoImage(file=str(path))
            scaled = photo.subsample(2, 2) if photo.width() > 520 else photo
            app._voice_access_reference_photo = photo
            app._voice_access_reference_photo_small = scaled
            image_label.config(image=scaled, text="")
        except tk.TclError as exc:
            image_label.config(text=f"Reference image could not be loaded: {exc}")

    refresh_btn.config(command=refresh)
    approve_btn.config(command=lambda: review(True))
    deny_btn.config(command=lambda: review(False))
    submit_btn.config(command=submit)
    listbox.bind("<<ListboxSelect>>", on_select)
    show_reference_image()
    refresh()


def _smooth_track_photo(width: int, height: int, track_color: str, shadow_color: str, master):
    scale = 4
    image = Image.new("RGBA", (width * scale, height * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (scale, 3 * scale, (width - 1) * scale, height * scale),
        radius=(height - 2) * scale // 2,
        fill=shadow_color,
    )
    draw.rounded_rectangle(
        (0, 0, (width - 1) * scale, (height - 3) * scale),
        radius=(height - 3) * scale // 2,
        fill=track_color,
    )
    draw.arc(
        (5 * scale, scale, (width - 6) * scale, 10 * scale),
        start=200,
        end=340,
        fill=(255, 255, 255, 150),
        width=scale,
    )
    return ImageTk.PhotoImage(image.resize((width, height), Image.Resampling.LANCZOS), master=master)


def _smooth_thumb_photo(thumb_width: int, height: int, enabled: bool, master):
    scale = 4
    width = thumb_width + 4
    image_height = height - 2
    image = Image.new("RGBA", (width * scale, image_height * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    outer_top = scale
    outer_bottom = (image_height - 3) * scale
    draw.rounded_rectangle(
        (3 * scale, 3 * scale, (thumb_width + 2) * scale, (image_height - 1) * scale),
        radius=(image_height - 3) * scale // 2,
        fill=(38, 50, 56, 150),
    )
    draw.rounded_rectangle(
        (outer_top, outer_top, (thumb_width + 1) * scale, outer_bottom),
        radius=min((outer_bottom - outer_top) // 2, thumb_width * scale // 2),
        fill="#ECEFF1",
        outline="#78909C" if enabled else "#B0BEC5",
        width=scale,
    )
    draw.rounded_rectangle(
        (4 * scale, 3 * scale, (thumb_width - 1) * scale, 8 * scale),
        radius=2 * scale,
        fill=(255, 255, 255, 190 if enabled else 120),
    )
    return ImageTk.PhotoImage(image.resize((width, image_height), Image.Resampling.LANCZOS), master=master)


class SlideToggle(tk.Canvas):
    def __init__(self, master, *, command=None, enabled: bool = True, width: int = 64, height: int = 26):
        super().__init__(master, width=width, height=height, bd=0, highlightthickness=0)
        self._command = command
        self._enabled = enabled
        self._value = False
        self._position = 0.0
        self._after_id = None
        self._pad = 3
        self._thumb = height - 10
        self._photo_key = None
        self._track_color = ""
        self._track = self.create_image(0, 0, anchor="nw")
        self._thumb_outer = self.create_image(0, 0, anchor="center")
        self.bind("<ButtonPress-1>", self._on_click)
        self.bind("<Key-space>", self._on_key)
        self.bind("<Key-Return>", self._on_key)
        self.set_enabled(enabled)

    @property
    def value(self) -> bool:
        return self._value

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        self.config(cursor="hand2" if self._enabled else "arrow", takefocus=1 if self._enabled else 0)
        self._draw(self._position)

    def set(self, value: bool, *, animate: bool = True) -> None:
        target = bool(value)
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None
        self._value = target
        if not animate:
            self._position = 1.0 if target else 0.0
            self._draw(self._position)
            return
        start = self._position
        self._animate(start, 1.0 if target else 0.0, 0, 12)

    def _animate(self, start: float, target: float, step: int, steps: int) -> None:
        ratio = step / steps
        eased = ratio * ratio * (3 - 2 * ratio)
        self._position = start + (target - start) * eased
        self._draw(self._position)
        if step < steps:
            self._after_id = self.after(16, lambda: self._animate(start, target, step + 1, steps))
            return
        self._position = target
        self._after_id = None
        self._draw(self._position)

    def _sync_photos(self, track_color: str, shadow_color: str) -> None:
        key = (track_color, shadow_color, self._enabled)
        if self._photo_key == key:
            return
        self._track_photo = _smooth_track_photo(
            self.winfo_reqwidth(),
            self.winfo_reqheight(),
            track_color,
            shadow_color,
            self,
        )
        self._thumb_photo = _smooth_thumb_photo(
            self._thumb,
            self.winfo_reqheight(),
            self._enabled,
            self,
        )
        self.itemconfig(self._track, image=self._track_photo)
        self.itemconfig(self._thumb_outer, image=self._thumb_photo)
        self._photo_key = key

    def _draw(self, position: float) -> None:
        on = position >= 0.5
        if self._enabled:
            track_color = "#2E7D32" if on else "#C62828"
            shadow_color = "#1B5E20" if on else "#8E0000"
        else:
            track_color = "#A5D6A7" if on else "#EF9A9A"
            shadow_color = "#81C784" if on else "#B71C1C"
        self._track_color = track_color
        self._sync_photos(track_color, shadow_color)
        width = self.winfo_reqwidth()
        height = self.winfo_reqheight()
        x = self._pad + position * (width - 2 * self._pad - self._thumb) + self._thumb / 2
        self.coords(self._thumb_outer, x, (height - 3) / 2)

    def _on_click(self, _event=None) -> None:
        if not self._enabled:
            return
        self.set(not self._value)
        if self._command is not None:
            self._command(self._value)

    def _on_key(self, _event=None) -> None:
        self._on_click()


def build_admin_access_tab(app, frame) -> None:
    small_font = ("Segoe UI", 8)
    owner_user = _user()
    users = list_users()
    by_label = {
        f"{user.get('name', user.get('id', 'User'))} ({user.get('id', '?')})": user
        for user in users
    }
    editable = is_owner(owner_user)

    tk.Label(
        frame,
        text="Owner-controlled admin access — click any small switch to allow or block that action.",
        font=app._body_font,
        fg="#37474F",
        wraplength=700,
        justify="left",
    ).pack(fill="x", padx=10, pady=(8, 4))

    picker = tk.Frame(frame)
    picker.pack(fill="x", padx=10, pady=4)
    tk.Label(picker, text="User:", font=small_font).pack(side="left")
    user_var = tk.StringVar()
    choices = sorted(by_label)
    combo = ttk.Combobox(
        picker,
        textvariable=user_var,
        values=choices,
        state="readonly" if choices else "disabled",
        width=34,
        font=small_font,
    )
    combo.pack(side="left", padx=(6, 8))
    if choices:
        current_id = str(_user().get("id") or "")
        user_var.set(next((label for label in choices if by_label[label].get("id") == current_id), choices[0]))

    status = tk.Label(frame, text="", font=small_font, fg="#37474F", wraplength=700, justify="left")
    status.pack(fill="x", padx=10, pady=(0, 4))

    tools = tk.Frame(frame)
    tools.pack(fill="x", padx=10, pady=(0, 6))
    tk.Label(tools, text="Test account:", font=small_font).pack(side="left")
    test_name = tk.StringVar()
    tk.Entry(tools, textvariable=test_name, width=12, font=small_font).pack(side="left", padx=(5, 4))
    test_role = tk.StringVar(value="guest")
    ttk.Combobox(
        tools,
        textvariable=test_role,
        values=("guest", "admin"),
        state="readonly",
        width=7,
        font=small_font,
    ).pack(side="left", padx=(0, 6))
    tk.Button(tools, text="Add Test Account", font=small_font, command=lambda: add_test()).pack(side="left", padx=(0, 6))
    tk.Button(tools, text="Test as Selected", font=small_font, command=lambda: test_selected()).pack(side="left", padx=(0, 6))

    tools_two = tk.Frame(frame)
    tools_two.pack(fill="x", padx=10, pady=(0, 6))
    tk.Button(tools_two, text="Return to Owner", font=small_font, command=lambda: return_owner()).pack(side="left", padx=(0, 6))
    tk.Button(
        tools_two,
        text="Restore Owner Switches",
        font=small_font,
        command=lambda: restore_owner_switches(),
    ).pack(side="left")

    body = tk.Frame(frame)
    body.pack(fill="both", expand=True, padx=10, pady=4)
    grid = tk.Frame(body)
    grid.pack(fill="both", expand=True)

    toggles: dict[str, SlideToggle] = {}
    for index, (key, label, group) in enumerate(CAPABILITIES):
        row, column = divmod(index, 3)
        column *= 2
        tk.Label(grid, text=f"{group}: {label}", font=small_font, anchor="w", width=25).grid(
            row=row, column=column, sticky="w", padx=(0, 6), pady=3
        )
        toggle = SlideToggle(
            grid,
            command=lambda value, item=key: apply_capability(item, value),
            enabled=editable,
        )
        toggle.grid(row=row, column=column + 1, sticky="w", pady=3)
        toggles[key] = toggle

    def selected_user() -> dict:
        return by_label.get(user_var.get(), {})

    def refresh() -> None:
        states = capability_states(selected_user())
        for key, toggle in toggles.items():
            toggle.set(bool(states.get(key)), animate=False)
            toggle.set_enabled(editable)

    def apply_capability(key: str, value: bool) -> None:
        target = selected_user()
        if not target:
            return
        previous = bool(capability_states(target).get(key, False))
        ok, message = set_capability(owner_user, str(target.get("id") or ""), key, value)
        status.config(text=message, fg="#2E7D32" if ok else "#C62828")
        if not ok:
            toggles[key].set(previous)

    def repopulate_users(select_id: str | None = None) -> None:
        nonlocal by_label
        by_label = {
            f"{user.get('name', user.get('id', 'User'))} ({user.get('id', '?')})": user
            for user in list_users()
        }
        values = sorted(by_label)
        combo.config(values=values, state="readonly" if values else "disabled")
        if select_id:
            match = next((label for label in values if by_label[label].get("id") == select_id), None)
            if match:
                user_var.set(match)
        refresh()

    def add_test() -> None:
        ok, user, message = create_test_account(owner_user, test_name.get(), test_role.get())
        status.config(text=message, fg="#2E7D32" if ok else "#C62828")
        if ok:
            test_name.set("")
            repopulate_users(str(user["id"]))

    def test_selected() -> None:
        target = selected_user()
        if not target:
            return
        ok, _user_account, message = activate_test_account(owner_user, str(target.get("id") or ""))
        status.config(text=message, fg="#2E7D32" if ok else "#C62828")
        if ok:
            repopulate_users(str(target.get("id") or ""))

    def return_owner() -> None:
        ok, owner, message = return_to_owner()
        status.config(text=message, fg="#2E7D32" if ok else "#C62828")
        if ok:
            repopulate_users(str(owner["id"]))

    def restore_owner_switches() -> None:
        ok, message = reset_user_capabilities(owner_user, str(owner_user.get("id") or ""))
        status.config(text=message, fg="#2E7D32" if ok else "#C62828")
        repopulate_users(str(owner_user.get("id") or ""))

    combo.bind("<<ComboboxSelected>>", lambda _event: refresh())
    refresh()


def build_panel_showcase_tab(app, frame) -> None:
    if _deny_owner(app, "manage the image studio and panel showcase"):
        return

    from silva.dev.panel_showcase import available_features, feature_state, mark_feature
    from silva.gui.image_generator_popup import show_image_generator_popup
    from silva.gui.media_library_popup import show_media_library_popup
    from silva.gui.panel_showcase_popup import show_panel_showcase_popup

    status_var = tk.StringVar(value="")
    selected: dict[str, str] = {}

    tk.Label(
        frame,
        text=(
            "Panel Showcase tracks every System Panel feature, lets you mark it, and opens its own popup "
            "for appearance notes, code-agent requests, and linked reference images."
        ),
        font=app._body_font,
        fg="#37474F",
        wraplength=720,
        justify="left",
    ).pack(fill="x", padx=10, pady=(8, 4))

    launch = ttk.Frame(frame)
    launch.pack(fill="x", padx=10, pady=(0, 6))
    ttk.Button(
        launch,
        text="Open Image Library",
        command=lambda: show_media_library_popup(),
    ).pack(side="left", padx=(0, 6))
    ttk.Button(
        launch,
        text="Open Image Studio",
        command=lambda: show_image_generator_popup(user_id=str(_user().get("id") or "default")),
    ).pack(side="left", padx=(0, 6))
    ttk.Button(
        launch,
        text="Apply to Panel",
        command=lambda: status_var.set("Saved appearances apply when the panel reloads; ask a code agent for deeper changes."),
    ).pack(side="left")

    columns = ("feature", "marked", "accent", "reference")
    tree = ttk.Treeview(frame, columns=columns, show="headings", height=12)
    for column, title, width in (
        ("feature", "System Panel feature", 300),
        ("marked", "Marked", 80),
        ("accent", "Accent", 90),
        ("reference", "Linked image", 140),
    ):
        tree.heading(column, text=title)
        tree.column(column, width=width)
    tree.pack(fill="both", expand=True, padx=10, pady=(0, 6))

    ttk.Label(frame, textvariable=status_var, foreground="#546E7A").pack(anchor="w", padx=10)

    def _refresh() -> None:
        tree.delete(*tree.get_children())
        selected.clear()
        for feature in available_features():
            feature_id = str(feature.get("id") or "")
            title = str(feature.get("title") or feature_id)
            state = feature_state(feature_id)
            item = tree.insert(
                "",
                "end",
                values=(
                    title,
                    "yes" if state.get("marked") else "no",
                    str(state.get("accent") or "-"),
                    str(state.get("reference_id") or "-"),
                ),
            )
            selected[str(item)] = feature_id

    def _chosen_id() -> str:
        choice = tree.selection()
        return selected.get(str(choice[0]), "") if choice else ""

    def _open_chosen() -> None:
        feature_id = _chosen_id()
        if not feature_id:
            status_var.set("Select a System Panel feature first.")
            return
        opened = show_panel_showcase_popup(feature_id=feature_id, on_changed=_refresh)
        status_var.set("Feature popup opened." if opened else "Feature popup could not be opened.")

    def _mark_chosen() -> None:
        feature_id = _chosen_id()
        if not feature_id:
            status_var.set("Select a System Panel feature first.")
            return
        state = feature_state(feature_id)
        mark_feature(feature_id, not bool(state.get("marked")))
        _refresh()

    actions = ttk.Frame(frame)
    actions.pack(fill="x", padx=10, pady=(0, 10))
    ttk.Button(actions, text="Open Feature Popup", command=_open_chosen).pack(side="left", padx=(0, 6))
    ttk.Button(actions, text="Mark / Unmark", command=_mark_chosen).pack(side="left", padx=(0, 6))
    ttk.Button(actions, text="Refresh", command=_refresh).pack(side="left")

    tree.bind("<Double-1>", lambda _event: _open_chosen())
    _refresh()


def build_future_tasks_tab(app, frame) -> None:
    if _deny_owner(app, "manage future updates"):
        return

    from silva.dev.future_tasks import (
        add_task,
        assign_task,
        complete_task,
        delete_task,
        list_tasks,
        verify_task,
    )
    from silva.users.manager import load_store

    status_var = tk.StringVar(value="")
    selected: dict[str, str] = {}

    tk.Label(
        frame,
        text=(
            "Type future work here, choose a row, then delete, complete, or assign it "
            "to an admin. You can also say add future update ... to Silva."
        ),
        font=app._body_font,
        fg="#37474F",
        wraplength=720,
        justify="left",
    ).pack(fill="x", padx=10, pady=(8, 4))

    entry_row = ttk.Frame(frame)
    entry_row.pack(fill="x", padx=10, pady=(0, 6))
    entry = ttk.Entry(entry_row)
    entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

    columns = ("task", "status", "assigned")
    tree = ttk.Treeview(frame, columns=columns, show="headings", height=12)
    for column, title, width in (
        ("task", "Future update", 520),
        ("status", "Status", 90),
        ("assigned", "Assigned to", 150),
    ):
        tree.heading(column, text=title)
        tree.column(column, width=width)
    tree.pack(fill="both", expand=True, padx=10, pady=(0, 6))

    admins = []
    for user_id, user in (load_store().get("users") or {}).items():
        role = str(user.get("role") or "").lower()
        tier = int(user.get("tier") or 0)
        if role in ("owner", "admin") or tier >= 4:
            admins.append((str(user.get("name") or user_id), str(user_id)))
    admin_combo = ttk.Combobox(
        frame,
        values=[label for label, _user_id in admins],
        state="readonly",
        width=24,
    )
    admin_combo.pack(anchor="w", padx=10, pady=(0, 6))

    ttk.Label(frame, textvariable=status_var, foreground="#546E7A").pack(anchor="w", padx=10)

    def _refresh() -> None:
        tree.delete(*tree.get_children())
        selected.clear()
        for record in list_tasks(30):
            item = tree.insert(
                "",
                "end",
                values=(
                    f"{record.get('id')}: {record.get('text', '')}",
                    str(record.get("status") or "open"),
                    str(record.get("assigned_to") or "-"),
                ),
            )
            selected[str(item)] = str(record.get("id") or "")

    def _chosen_id() -> str:
        choice = tree.selection()
        return selected.get(str(choice[0]), "") if choice else ""

    def _add() -> None:
        value = entry.get().strip()
        if not value:
            status_var.set("Type a future update first.")
            return
        record = add_task(value, created_by=str(_user().get("id") or "owner"))
        status_var.set(f"Added {record['id']}.")
        entry.delete(0, "end")
        _refresh()

    def _delete() -> None:
        ok, message = delete_task(_chosen_id())
        status_var.set(message)
        _refresh()

    def _assign() -> None:
        task_id = _chosen_id()
        label = str(admin_combo.get() or "")
        user_id = next((value for name, value in admins if name == label), "")
        if not task_id or not user_id:
            status_var.set("Select a future update and an admin first.")
            return
        ok, message = assign_task(task_id, user_id)
        status_var.set(message)
        _refresh()

    def _complete() -> None:
        ok, message = complete_task(_chosen_id())
        status_var.set(message)
        _refresh()

    def _verify() -> None:
        ok, message = verify_task(_chosen_id(), verifier_id=str(_user().get("id") or "owner"))
        status_var.set(message)
        _refresh()

    actions = ttk.Frame(frame)
    actions.pack(fill="x", padx=10, pady=(0, 10))
    for label, command in (
        ("Add", _add),
        ("Delete Selected", _delete),
        ("Assign Selected", _assign),
        ("Complete", _complete),
        ("Verify & Delete", _verify),
        ("Refresh", _refresh),
    ):
        ttk.Button(actions, text=label, command=command).pack(side="left", padx=(0, 6))

    entry.bind("<Return>", lambda _event: _add())
    _refresh()


def build_team_updates_tab(app, frame) -> None:
    if _deny(app, "review team updates"):
        return

    from silva.dev.team_updates import (
        approve_update,
        list_updates,
        reject_update,
        submit_update,
    )

    status_var = tk.StringVar(value="")
    email_reply_var = tk.BooleanVar(value=False)
    selected: dict[str, str] = {}

    tk.Label(
        frame,
        text=(
            "Anyone can submit an update by voice or here. Owners and admins approve or reject it. "
            "A rejected update shows a popup and can be emailed back with the reply below."
        ),
        font=app._body_font,
        fg="#37474F",
        wraplength=720,
        justify="left",
    ).pack(fill="x", padx=10, pady=(8, 4))

    entry_row = ttk.Frame(frame)
    entry_row.pack(fill="x", padx=10, pady=(0, 4))
    entry = ttk.Entry(entry_row)
    entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
    email_entry = ttk.Entry(entry_row, width=28)
    email_entry.pack(side="left")

    columns = ("update", "status", "from", "email")
    tree = ttk.Treeview(frame, columns=columns, show="headings", height=9)
    for column, title, width in (
        ("update", "Team update", 420),
        ("status", "Status", 90),
        ("from", "From", 110),
        ("email", "Reply email", 180),
    ):
        tree.heading(column, text=title)
        tree.column(column, width=width)
    tree.pack(fill="both", expand=True, padx=10, pady=(4, 6))

    reply_box = scrolledtext.ScrolledText(frame, height=4, wrap="word")
    reply_box.pack(fill="x", padx=10, pady=(0, 6))

    def _refresh() -> None:
        tree.delete(*tree.get_children())
        selected.clear()
        for item in list_updates(limit=60):
            node = tree.insert(
                "",
                "end",
                values=(
                    str(item.get("text") or ""),
                    str(item.get("status") or "pending"),
                    str(item.get("user_name") or item.get("user_id") or ""),
                    str(item.get("email") or ""),
                ),
            )
            selected[str(node)] = str(item.get("id") or "")

    def _chosen_id() -> str:
        choice = tree.selection()
        return selected.get(str(choice[0]), "") if choice else ""

    def _submit() -> None:
        value = entry.get().strip()
        if not value:
            status_var.set("Type a team update first.")
            return
        record = submit_update(
            value,
            user_id=str(_user().get("id") or "guest"),
            user_name=str(_user().get("name") or "Guest"),
            email=email_entry.get().strip(),
        )
        status_var.set(f"Submitted {record['id']}.")
        entry.delete(0, "end")
        _refresh()

    def _approve() -> None:
        ok, message = approve_update(
            _chosen_id(),
            approver_id=str(_user().get("id") or "owner"),
            reply=reply_box.get("1.0", "end").strip(),
            email_reply=email_reply_var.get(),
        )
        status_var.set(message)
        _refresh()

    def _reject() -> None:
        ok, message = reject_update(
            _chosen_id(),
            approver_id=str(_user().get("id") or "owner"),
            reply=reply_box.get("1.0", "end").strip(),
            email_reply=email_reply_var.get(),
        )
        status_var.set(message)
        _refresh()

    actions = ttk.Frame(frame)
    actions.pack(fill="x", padx=10, pady=(0, 4))
    for label, command in (
        ("Submit", _submit),
        ("Approve Selected", _approve),
        ("Reject Selected", _reject),
        ("Refresh", _refresh),
    ):
        ttk.Button(actions, text=label, command=command).pack(side="left", padx=(0, 6))
    ttk.Checkbutton(
        actions,
        text="Email reply",
        variable=email_reply_var,
    ).pack(side="left", padx=(8, 0))
    ttk.Label(frame, textvariable=status_var, foreground="#546E7A").pack(anchor="w", padx=10)
    _refresh()


def build_live_chat_tab(app, frame) -> None:
    if not _can_view():
        _restricted_label(app, frame, "view live admin chat")
        return

    from silva.users.live_chat import list_live_chat_messages, reply_live_chat_message

    tk.Label(
        frame,
        text="Live chat with users — owner and tier 4 admins can reply.",
        font=app._body_font,
        fg="#37474F",
    ).pack(anchor="w", padx=10, pady=(10, 4))

    bar = ttk.Frame(frame)
    bar.pack(fill="x", padx=10, pady=6)
    ttk.Button(bar, text="Refresh", command=lambda: refresh()).pack(side="left", padx=(0, 6))
    ttk.Button(bar, text="Resolve Selected", command=lambda: resolve()).pack(side="left")

    listbox = tk.Listbox(frame, height=9, font=app._body_font)
    listbox.pack(fill="both", padx=10, pady=(0, 6))

    detail = scrolledtext.ScrolledText(frame, height=8, wrap="word", font=app._body_font)
    detail.pack(fill="both", padx=10, pady=(0, 6))
    detail.configure(state="disabled")

    reply_box = tk.Text(frame, height=3, wrap="word", font=app._body_font)
    reply_box.pack(fill="x", padx=10, pady=(0, 6))

    status_var = tk.StringVar(value="")
    ttk.Label(frame, textvariable=status_var, foreground="#546E7A").pack(anchor="w", padx=10)
    ttk.Button(frame, text="Send Reply", command=lambda: send_reply()).pack(anchor="w", padx=10, pady=(4, 10))

    items: list[dict] = []

    def selected() -> dict | None:
        selection = listbox.curselection()
        if not selection:
            return None
        index = int(selection[0])
        return items[index] if 0 <= index < len(items) else None

    def show_detail(item: dict | None) -> None:
        detail.configure(state="normal")
        detail.delete("1.0", tk.END)
        if item:
            detail.insert(
                "1.0",
                f"From: {item.get('user_name') or item.get('user_id') or 'Guest'}\n"
                f"Kind: {item.get('kind') or 'help'}\n"
                f"Status: {item.get('status') or 'open'}\n"
                f"Created: {item.get('created_at') or ''}\n\n"
                f"Message: {item.get('text') or ''}\n\n"
                f"Reply: {item.get('reply') or ''}",
            )
        detail.configure(state="disabled")

    def refresh() -> None:
        nonlocal items
        items = list_live_chat_messages()
        listbox.delete(0, tk.END)
        for item in items:
            preview = str(item.get("text") or "").replace("\n", " ")[:70]
            listbox.insert(
                tk.END,
                f"{item.get('id')} | {item.get('user_name') or item.get('user_id') or 'Guest'} "
                f"| {item.get('status') or 'open'} | {preview}",
            )
        show_detail(items[0] if items else None)
        status_var.set("")

    def send_reply() -> None:
        if _deny(app, "reply in live chat"):
            return
        item = selected()
        if not item:
            messagebox.showinfo("No selection", "Choose a chat message first.", parent=app.root)
            return
        ok, message = reply_live_chat_message(str(item.get("id") or ""), _user(), reply_box.get("1.0", tk.END))
        status_var.set(message if not ok else "Reply sent.")
        if ok:
            reply_box.delete("1.0", tk.END)
        refresh()
        status_var.set(message if not ok else "Reply sent.")

    def resolve() -> None:
        if _deny(app, "resolve live chat"):
            return
        item = selected()
        if not item:
            messagebox.showinfo("No selection", "Choose a chat message first.", parent=app.root)
            return
        ok, message = reply_live_chat_message(
            str(item.get("id") or ""),
            _user(),
            "Marked resolved by an admin.",
        )
        status_var.set(message if not ok else "Marked resolved.")
        refresh()
        status_var.set(message if not ok else "Marked resolved.")

    listbox.bind("<<ListboxSelect>>", lambda _event: show_detail(selected()))
    refresh()


def build_dev_branch_tab(app, frame) -> None:
    if not _can_view():
        _restricted_label(app, frame, "review dev branch voting")
        return

    from silva.dev.dev_branch import prepare_dev_branch, run_dev_branch_checks
    from silva.dev.feature_votes import (
        STATUS_LIVE,
        cast_dev_vote,
        list_dev_features,
        mark_dev_feature_live,
        owner_finalize,
        propose_dev_feature,
        start_dev_testing,
        vote_totals,
    )
    from silva.users.update_channels import get_update_channel, set_update_channel

    tk.Label(
        frame,
        text="Dev branch and feature votes — voting is circle yes/no, owner has final approval.",
        font=app._body_font,
        fg="#37474F",
    ).pack(anchor="w", padx=10, pady=(10, 4))

    setup = ttk.Frame(frame)
    setup.pack(fill="x", padx=10, pady=6)
    ttk.Button(setup, text="Prepare Dev Branch", command=lambda: prepare()).pack(side="left", padx=(0, 6))
    ttk.Button(setup, text="Run Dev Checks", command=lambda: run_checks()).pack(side="left", padx=(0, 6))
    ttk.Button(setup, text="Stable Channel", command=lambda: set_channel("stable")).pack(side="left", padx=(0, 6))
    ttk.Button(setup, text="Dev Channel", command=lambda: set_channel("dev")).pack(side="left")

    output = scrolledtext.ScrolledText(frame, height=6, wrap="word", font=app._body_font)
    output.pack(fill="both", padx=10, pady=(0, 6))

    proposal = ttk.Frame(frame)
    proposal.pack(fill="x", padx=10, pady=6)
    title_var = tk.StringVar(value="")
    ttk.Label(proposal, text="Feature:").pack(side="left")
    ttk.Entry(proposal, textvariable=title_var, width=36).pack(side="left", padx=(4, 8))
    ttk.Button(proposal, text="Propose", command=lambda: propose()).pack(side="left")
    details_box = tk.Text(frame, height=2, wrap="word", font=app._body_font)
    details_box.pack(fill="x", padx=10, pady=(0, 6))

    listbox = tk.Listbox(frame, height=8, font=app._body_font)
    listbox.pack(fill="both", padx=10, pady=(0, 6))

    detail = scrolledtext.ScrolledText(frame, height=5, wrap="word", font=app._body_font)
    detail.pack(fill="both", padx=10, pady=(0, 6))
    detail.configure(state="disabled")

    actions = ttk.Frame(frame)
    actions.pack(fill="x", padx=10, pady=(0, 4))
    vote_var = tk.IntVar(value=1)
    ttk.Radiobutton(actions, text="Yes", variable=vote_var, value=1).pack(side="left", padx=(0, 4))
    ttk.Radiobutton(actions, text="No", variable=vote_var, value=0).pack(side="left", padx=(0, 8))
    ttk.Button(actions, text="Cast Vote", command=lambda: vote()).pack(side="left", padx=(0, 6))
    ttk.Button(actions, text="Start Dev Testing", command=lambda: start_testing()).pack(side="left", padx=(0, 6))
    ttk.Button(actions, text="Final Approve", command=lambda: finalize(True)).pack(side="left", padx=(0, 6))
    ttk.Button(actions, text="Reject", command=lambda: finalize(False)).pack(side="left", padx=(0, 6))
    ttk.Button(actions, text="Mark Live", command=lambda: go_live(False)).pack(side="left", padx=(0, 6))
    ttk.Button(actions, text="Emergency Push", command=lambda: go_live(True)).pack(side="left")

    status_var = tk.StringVar(value="")
    ttk.Label(frame, textvariable=status_var, foreground="#546E7A").pack(anchor="w", padx=10, pady=(0, 10))

    items: list[dict] = []

    def selected() -> dict | None:
        selection = listbox.curselection()
        if not selection:
            return None
        index = int(selection[0])
        return items[index] if 0 <= index < len(items) else None

    def show_detail(item: dict | None) -> None:
        detail.configure(state="normal")
        detail.delete("1.0", tk.END)
        if item:
            totals = vote_totals(item)
            detail.insert(
                "1.0",
                f"Title: {item.get('title') or ''}\n"
                f"Status: {item.get('status') or ''}\n"
                f"Proposed by: {item.get('proposed_by_name') or item.get('proposed_by') or ''}\n"
                f"Votes: yes {totals['yes']}, no {totals['no']}\n"
                f"Dev branch: {item.get('dev_branch_path') or ''}\n\n"
                f"Details: {item.get('details') or ''}",
            )
        detail.configure(state="disabled")

    def refresh() -> None:
        nonlocal items
        items = list_dev_features()
        listbox.delete(0, tk.END)
        for item in items:
            totals = vote_totals(item)
            listbox.insert(
                tk.END,
                f"{item.get('id')} | {item.get('status') or ''} | {item.get('title') or ''} "
                f"| yes {totals['yes']} no {totals['no']}",
            )
        show_detail(items[0] if items else None)

    def log(text: str) -> None:
        output.insert("end", text + "\n")
        output.see("end")

    def prepare() -> None:
        if _deny(app, "prepare the dev branch"):
            return
        path = prepare_dev_branch()
        status_var.set(f"Dev branch ready: {path}")
        log(f"Dev branch ready: {path}")

    def run_checks() -> None:
        if _deny(app, "run dev checks"):
            return
        ok, text = run_dev_branch_checks()
        status_var.set("Dev checks passed." if ok else "Dev checks failed.")
        log("Dev checks passed." if ok else "Dev checks failed.")
        log(text)

    def propose() -> None:
        if _deny(app, "propose dev features"):
            return
        title = title_var.get().strip()
        if not title:
            messagebox.showinfo("Missing title", "Enter a feature title first.", parent=app.root)
            return
        item = propose_dev_feature(_user(), title, details_box.get("1.0", tk.END))
        title_var.set("")
        details_box.delete("1.0", tk.END)
        status_var.set(f"Proposed {item['id']} for dev testing.")
        refresh()

    def vote() -> None:
        if _deny(app, "vote on dev features"):
            return
        item = selected()
        if not item:
            messagebox.showinfo("No selection", "Choose a dev feature first.", parent=app.root)
            return
        ok, message = cast_dev_vote(str(item.get("id") or ""), _user(), bool(vote_var.get()))
        status_var.set(message)
        refresh()
        status_var.set(message)

    def start_testing() -> None:
        if _deny(app, "prepare dev testing"):
            return
        item = selected()
        if not item:
            messagebox.showinfo("No selection", "Choose a dev feature first.", parent=app.root)
            return
        ok, message = start_dev_testing(str(item.get("id") or ""), _user())
        status_var.set(message)
        refresh()
        status_var.set(message)

    def finalize(approve: bool) -> None:
        if approve and _deny_owner(app, "approve dev features"):
            return
        if not approve and _deny_owner(app, "reject dev features"):
            return
        item = selected()
        if not item:
            messagebox.showinfo("No selection", "Choose a dev feature first.", parent=app.root)
            return
        ok, message = owner_finalize(str(item.get("id") or ""), _user(), approve)
        status_var.set(message)
        refresh()
        status_var.set(message)

    def go_live(emergency: bool) -> None:
        if _deny(app, "push a dev feature live"):
            return
        item = selected()
        if not item or item.get("status") == STATUS_LIVE:
            messagebox.showinfo("No selection", "Choose an unfinished dev feature first.", parent=app.root)
            return
        ok, message = mark_dev_feature_live(str(item.get("id") or ""), _user(), emergency=emergency)
        status_var.set(message)
        refresh()
        status_var.set(message)

    def set_channel(channel: str) -> None:
        ok, message = set_update_channel(str(_user().get("id") or "guest"), channel)
        if ok:
            message = f"{message} Current channel: {get_update_channel(str(_user().get('id') or 'guest'))}."
        status_var.set(message)

    listbox.bind("<<ListboxSelect>>", lambda _event: show_detail(selected()))
    refresh()


def register_panel_tabs() -> None:
    from silva.gui.panel_crosschat_deck_tab import build_crosschat_deck_tab

    register_panel_tab(
        tab_id="feature_request_review",
        title="4. Requests",
        order=4,
        builder=build_feature_request_tab,
    )
    register_panel_tab(
        tab_id="admin_update_queue",
        title="5. Update Queue",
        order=5,
        builder=build_update_queue_tab,
    )
    register_panel_tab(
        tab_id="code_lab",
        title="6. Code Lab",
        order=6,
        builder=build_code_lab_tab,
    )
    register_panel_tab(
        tab_id="voice_access_requests",
        title="7. Voice Access",
        order=7,
        builder=build_voice_access_requests_tab,
    )
    register_panel_tab(
        tab_id="admin_access",
        title="8. Admin Access",
        order=8,
        builder=build_admin_access_tab,
    )
    register_panel_tab(
        tab_id="future_tasks",
        title="9. Future Tasks",
        order=9,
        builder=build_future_tasks_tab,
    )
    register_panel_tab(
        tab_id="team_updates",
        title="10. Team Updates",
        order=10,
        builder=build_team_updates_tab,
    )
    register_panel_tab(
        tab_id="crosschat_stream_deck",
        title="11. CrossChat & Deck",
        order=11,
        builder=build_crosschat_deck_tab,
    )
    register_panel_tab(
        tab_id="dev_branch_votes",
        title="13. Dev Branch & Votes",
        order=13,
        builder=build_dev_branch_tab,
    )
