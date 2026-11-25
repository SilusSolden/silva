"""System Panel tab for CrossChat memory and Stream Deck XL bindings."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from silva.config import CONFIG_DIR
from silva.users.manager import get_active_user


def build_crosschat_deck_tab(app, frame) -> None:
    from silva.dev.stream_deck import (
        MAX_PAGES,
        MAX_SLOTS,
        list_bindings,
        publish_weather_tile,
        remove_binding,
        set_binding,
    )

    user = get_active_user() or {}
    user_id = str(user.get("id") or "guest")
    status = tk.StringVar(value="")
    page_var = tk.StringVar(value="1")
    slot_var = tk.StringVar(value="1")
    label_var = tk.StringVar(value="")
    command_var = tk.StringVar(value="")
    instruction_var = tk.StringVar(value="")

    header = tk.Label(
        frame,
        text=(
            "CrossChat saves tone and custom instructions across voice and text. "
            "Stream Deck bindings use pages 1-32 and slots 1-32."
        ),
        font=app._body_font,
        fg="#37474F",
    )
    header.pack(anchor="w", padx=10, pady=(10, 6))

    tree = ttk.Treeview(frame, columns=("page", "slot", "label", "command"), show="headings", height=8)
    for column, width in (("page", 70), ("slot", 70), ("label", 190), ("command", 380)):
        tree.heading(column, text=column.title())
        tree.column(column, width=width, anchor="w")
    tree.pack(fill="both", padx=10, pady=(0, 8))

    controls = ttk.Frame(frame)
    controls.pack(fill="x", padx=10, pady=(0, 8))
    ttk.Label(controls, text="Page").pack(side="left")
    ttk.Entry(controls, textvariable=page_var, width=5).pack(side="left", padx=(4, 8))
    ttk.Label(controls, text="Slot").pack(side="left")
    ttk.Entry(controls, textvariable=slot_var, width=5).pack(side="left", padx=(4, 8))
    ttk.Entry(controls, textvariable=label_var, width=18).pack(side="left", padx=(0, 6))
    ttk.Entry(controls, textvariable=command_var, width=40).pack(side="left", fill="x", expand=True)

    def values() -> tuple[int, int]:
        try:
            return int(page_var.get()), int(slot_var.get())
        except (TypeError, ValueError):
            return 0, 0

    def refresh() -> None:
        for item in tree.get_children():
            tree.delete(item)
        for binding in list_bindings(user_id=user_id):
            tree.insert(
                "",
                "end",
                values=(
                    binding.get("page"),
                    binding.get("slot"),
                    binding.get("label"),
                    binding.get("command") or ("WEATHER TILE" if binding.get("weather") else ""),
                ),
            )

    def bind_command() -> None:
        page, slot = values()
        command = command_var.get().strip()
        if not 1 <= page <= MAX_PAGES or not 1 <= slot <= MAX_SLOTS or not command:
            status.set("Enter a valid page, slot, and command.")
            return
        ok = set_binding(
            user_id=user_id,
            page=page,
            slot=slot,
            label=label_var.get().strip() or command,
            command=command,
        )
        status.set("Command bound." if ok else "Could not bind command.")
        refresh()

    def bind_weather() -> None:
        page, slot = values()
        if not 1 <= page <= MAX_PAGES or not 1 <= slot <= MAX_SLOTS:
            status.set("Enter a valid page and slot.")
            return
        ok = set_binding(user_id=user_id, page=page, slot=slot, label="Weather", weather=True)
        path = publish_weather_tile()
        status.set(f"Weather tile bound. Snapshot: {path}" if ok else "Could not bind weather tile.")
        refresh()

    def remove() -> None:
        selected = tree.selection()
        if not selected:
            status.set("Select a binding first.")
            return
        values_row = tree.item(selected[0], "values")
        if len(values_row) < 2:
            return
        try:
            page, slot = int(values_row[0]), int(values_row[1])
        except (TypeError, ValueError):
            return
        remove_binding(user_id=user_id, page=page, slot=slot)
        refresh()

    actions = ttk.Frame(frame)
    actions.pack(fill="x", padx=10, pady=(0, 8))
    for text, command in (
        ("Bind Command", bind_command),
        ("Bind Weather Tile", bind_weather),
        ("Remove", remove),
        ("Refresh", refresh),
    ):
        ttk.Button(actions, text=text, command=command).pack(side="left", padx=(0, 6))

    ttk.Label(frame, text="CrossChat custom instruction", font=app._body_font).pack(anchor="w", padx=10, pady=(6, 4))
    instruction_row = ttk.Frame(frame)
    instruction_row.pack(fill="x", padx=10, pady=(0, 8))
    ttk.Entry(instruction_row, textvariable=instruction_var, width=70).pack(side="left", fill="x", expand=True)

    def save_instruction() -> None:
        from silva.conversation.crosschat_memory import add_instruction, list_instructions

        value = instruction_var.get().strip()
        ok = add_instruction(value, user_id=user_id)
        status.set("Instruction saved." if ok else "Could not save instruction.")
        if ok:
            instruction_var.set("")
            items = list_instructions(user_id=user_id)
            status.set("Saved: " + "; ".join(items[-4:]))

    ttk.Button(instruction_row, text="Save Instruction", command=save_instruction).pack(side="left", padx=(6, 0))
    ttk.Label(frame, textvariable=status, foreground="#546E7A").pack(anchor="w", padx=10)
    ttk.Label(
        frame,
        text=f"Tiles are written to {CONFIG_DIR / 'stream_deck' / 'weather_tile.json'}",
        foreground="#78909C",
    ).pack(anchor="w", padx=10, pady=(0, 10))
    refresh()
