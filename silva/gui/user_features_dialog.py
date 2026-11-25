"""Per-user feature permissions editor (tier 3+)."""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont

from silva.users.features import (
    editable_features_for_target,
    get_user_feature_overrides,
    save_user_feature_overrides,
    universal_features,
)


def open_user_features_dialog(parent: tk.Misc, *, viewer: dict, target: dict) -> None:
    features = editable_features_for_target(viewer, target)
    if not features:
        return

    dialog = tk.Toplevel(parent)
    dialog.title(f"Features — {target.get('name', 'User')}")
    dialog.resizable(False, False)
    dialog.attributes("-topmost", True)
    dialog.transient(parent)

    body = tkfont.Font(family="Segoe UI", size=10)
    title = tkfont.Font(family="Segoe UI", size=11, weight="bold")

    width, height = 380, 300
    px = parent.winfo_rootx() + max(0, (parent.winfo_width() - width) // 2)
    py = parent.winfo_rooty() + max(0, (parent.winfo_height() - height) // 2)
    dialog.geometry(f"{width}x{height}+{px}+{py}")

    tk.Label(
        dialog,
        text=f"Allowed features: {target.get('name', 'User')}",
        font=title,
        fg="#1A237E",
    ).pack(pady=(12, 4))
    tk.Label(
        dialog,
        text="Checked = allowed. Unchecked = blocked for this profile.",
        font=body,
        fg="#607D8B",
        wraplength=340,
    ).pack(pady=(0, 8))

    frame = tk.LabelFrame(dialog, text="Features", font=body, padx=10, pady=8)
    frame.pack(fill="both", expand=True, padx=14, pady=(0, 8))

    overrides = get_user_feature_overrides(target["id"])
    defaults = universal_features()
    vars_map: dict[str, tk.BooleanVar] = {}

    for key, label in features:
        var = tk.BooleanVar(value=overrides.get(key, key in defaults))
        vars_map[key] = var
        tk.Checkbutton(frame, text=label, variable=var, font=body, anchor="w").pack(fill="x", pady=1)

    status = tk.StringVar(value="")

    def save() -> None:
        new_overrides = {key: var.get() for key, var in vars_map.items()}
        save_user_feature_overrides(target["id"], new_overrides)
        status.set("Saved feature permissions.")

    row = tk.Frame(dialog)
    row.pack(fill="x", padx=14, pady=(0, 10))
    tk.Button(row, text="Save", font=body, width=10, command=save).pack(side="left")
    tk.Button(row, text="Close", font=body, width=10, command=dialog.destroy).pack(side="right")
    tk.Label(dialog, textvariable=status, font=body, fg="#1B5E20").pack()
