"""Owner dialog to edit permission grants for each tier."""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont

from silva.users.tier_grants import (
    EDITABLE_PERMISSIONS,
    apply_tier_permissions_to_all_users,
    get_tier_permission_set,
    save_tier_permission_set,
)
from silva.users.tiers import MAX_TIER, tier_description


def open_tier_permissions_dialog(parent: tk.Misc) -> None:
    dialog = tk.Toplevel(parent)
    dialog.title("Silva - Tier Permissions")
    dialog.resizable(False, False)
    dialog.attributes("-topmost", True)
    dialog.transient(parent)

    body = tkfont.Font(family="Segoe UI", size=10)
    title = tkfont.Font(family="Segoe UI", size=11, weight="bold")

    width, height = 440, 420
    px = parent.winfo_rootx() + max(0, (parent.winfo_width() - width) // 2)
    py = parent.winfo_rooty() + max(0, (parent.winfo_height() - height) // 2)
    dialog.geometry(f"{width}x{height}+{px}+{py}")

    tk.Label(dialog, text="Tier Permissions", font=title, fg="#1A237E").pack(pady=(12, 4))

    tier_var = tk.StringVar(value="1")
    desc_var = tk.StringVar(value=tier_description(1))
    status_var = tk.StringVar(value="")

    picker = tk.Frame(dialog)
    picker.pack(fill="x", padx=14, pady=(0, 6))
    tk.Label(picker, text="Tier:", font=body).pack(side="left")
    tier_menu = tk.OptionMenu(picker, tier_var, *[str(t) for t in range(1, MAX_TIER + 1)])
    tier_menu.config(font=body, width=4)
    tier_menu.pack(side="left", padx=(6, 0))
    tk.Label(dialog, textvariable=desc_var, font=body, fg="#607D8B", wraplength=400).pack(
        padx=14, anchor="w"
    )

    checks_frame = tk.LabelFrame(dialog, text="Permissions granted at this tier", font=body, padx=10, pady=8)
    checks_frame.pack(fill="both", expand=True, padx=14, pady=(8, 6))

    check_vars: dict[str, tk.BooleanVar] = {}

    def load_tier(*_args: object) -> None:
        tier = int(tier_var.get())
        desc_var.set(tier_description(tier))
        perms = get_tier_permission_set(tier)
        for key, var in check_vars.items():
            if tier >= MAX_TIER:
                var.set(True)
            else:
                var.set(key in perms)

    for key, label in EDITABLE_PERMISSIONS:
        var = tk.BooleanVar(value=False)
        check_vars[key] = var
        cb = tk.Checkbutton(checks_frame, text=label, variable=var, font=body, anchor="w")
        cb.pack(fill="x", pady=1)

    tier_var.trace_add("write", load_tier)
    load_tier()

    def save() -> None:
        tier = int(tier_var.get())
        if tier >= MAX_TIER:
            status_var.set("Tier 5 (owner) always has full access.")
            return
        selected = {key for key, var in check_vars.items() if var.get()}
        save_tier_permission_set(tier, selected)
        apply_tier_permissions_to_all_users()
        status_var.set(f"Saved permissions for tier {tier}.")

    btn_row = tk.Frame(dialog)
    btn_row.pack(fill="x", padx=14, pady=(4, 8))
    tk.Button(btn_row, text="Save", font=body, width=10, command=save).pack(side="left")
    tk.Button(btn_row, text="Close", font=body, width=10, command=dialog.destroy).pack(side="right")

    tk.Label(dialog, textvariable=status_var, font=body, fg="#1B5E20").pack(padx=14, pady=(0, 10))
