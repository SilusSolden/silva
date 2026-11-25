from __future__ import annotations

import threading
import tkinter as tk
import tkinter.font as tkfont
import tkinter.ttk as ttk
from typing import Callable

from silva.gui.display_manager import register, unregister, watch_shutdown
from silva.gui.media_library_popup import (
    _thumbnail,
    _window_buttons,
    show_image_viewer,
    show_media_library_popup,
)
from silva.gui.monitors import geometry_on_monitor
from silva.logger import log_error

BG = "#121212"
CARD_BG = "#1B1B1B"
TEXT = "#F5F5F5"
MUTED = "#B0BEC5"
ACCENT = "#FFB74D"

_popup: "PanelShowcasePopup | None" = None
_lock = threading.Lock()


def _overlay_parent() -> tk.Misc | None:
    try:
        from silva.gui.display_host import host_root

        return host_root()
    except Exception:
        return None


class PanelShowcasePopup:
    def __init__(
        self,
        parent: tk.Misc,
        *,
        feature_id: str = "",
        on_changed: Callable[[], None] | None = None,
    ) -> None:
        self._on_changed = on_changed
        self._closed = False
        self._maximized = False
        self._photos = []
        self._reference_ids: list[str] = []

        self.dialog = tk.Toplevel(parent)
        register(self.dialog, persistent=True)
        watch_shutdown(self.dialog)
        self.dialog.title("Silva - Panel Showcase")
        self.dialog.configure(bg=BG)
        self.dialog.attributes("-topmost", True)
        self.dialog.geometry(geometry_on_monitor(720, 620, anchor="center"))
        self.dialog.protocol("WM_DELETE_WINDOW", self.close)
        self.dialog.bind("<Escape>", lambda _event: self.close())

        _window_buttons(
            self.dialog,
            self._minimize,
            self._toggle_maximize,
            self.close,
        ).pack(anchor="ne", padx=6, pady=(6, 0))

        bold = tkfont.Font(family="Segoe UI", size=13, weight="bold")
        body_font = tkfont.Font(family="Segoe UI", size=10)
        tk.Label(
            self.dialog,
            text="Panel Showcase - owner only",
            font=bold,
            fg=TEXT,
            bg=BG,
        ).pack(anchor="w", padx=14, pady=(4, 2))
        tk.Label(
            self.dialog,
            text="Select any System Panel feature, mark it, and describe how it should look.",
            font=body_font,
            fg=MUTED,
            bg=BG,
        ).pack(anchor="w", padx=14, pady=(0, 6))

        top = tk.Frame(self.dialog, bg=BG)
        top.pack(fill="x", padx=12)
        ttk.Label(top, text="Feature", font=body_font).pack(side="left")
        self.features = ttk.Combobox(top, state="readonly", width=48)
        self.features.pack(side="left", padx=(6, 8), fill="x", expand=True)
        self.mark_button = tk.Button(
            top,
            text="Mark",
            command=self._toggle_mark,
            bg=CARD_BG,
            fg=TEXT,
            relief="flat",
            bd=0,
        )
        self.mark_button.pack(side="right")

        form = tk.Frame(self.dialog, bg=BG)
        form.pack(fill="both", expand=True, padx=12, pady=10)

        ttk.Label(form, text="Accent color", font=body_font).grid(row=0, column=0, sticky="w")
        self.accent = ttk.Entry(form, width=22)
        self.accent.grid(row=1, column=0, sticky="w", pady=(0, 8))
        self.accent.insert(0, ACCENT)

        ttk.Label(form, text="Layout", font=body_font).grid(row=0, column=1, sticky="w")
        self.layout = ttk.Combobox(
            form,
            values=("chat", "cards", "compact", "wide"),
            state="readonly",
            width=20,
        )
        self.layout.grid(row=1, column=1, sticky="w", pady=(0, 8))
        self.layout.set("cards")

        ttk.Label(form, text="Reference image", font=body_font).grid(row=2, column=0, sticky="w")
        self.reference = ttk.Combobox(form, state="readonly", width=48)
        self.reference.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self.reference.bind("<<ComboboxSelected>>", lambda _event: self._preview_reference())

        self.preview = tk.Label(
            form,
            text="No linked reference image",
            bg=CARD_BG,
            fg=MUTED,
            width=64,
            height=10,
        )
        self.preview.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        ttk.Label(form, text="Appearance notes", font=body_font).grid(row=5, column=0, sticky="w")
        self.notes = tk.Text(form, height=7, wrap="word", font=body_font)
        self.notes.grid(row=6, column=0, columnspan=2, sticky="nsew")
        form.rowconfigure(6, weight=1)
        form.columnconfigure(1, weight=1)

        actions = tk.Frame(self.dialog, bg=BG)
        actions.pack(fill="x", padx=12, pady=(0, 12))
        for text, command in (
            ("Save", self._save),
            ("Copy Request", self._copy_request),
            ("Open Image", self._open_reference),
            ("Image Library", self._open_library),
            ("Close", self.close),
        ):
            tk.Button(
                actions,
                text=text,
                command=command,
                bg=CARD_BG,
                fg=TEXT,
                relief="flat",
                bd=0,
            ).pack(side="right", padx=3)

        self._load_feature_options(feature_id)

    def _load_feature_options(self, preferred: str = "") -> None:
        from silva.dev.panel_showcase import available_features, feature_state

        features = available_features()
        self._feature_map = {item["title"]: item["id"] for item in features}
        self.features.configure(values=list(self._feature_map))
        chosen = next(
            (title for title, key in self._feature_map.items() if key == preferred),
            features[0]["title"] if features else "",
        )
        self.features.set(chosen)
        self.features.bind("<<ComboboxSelected>>", lambda _event: self._load_state())
        self._load_reference_options()
        self._load_state()

    def _current_id(self) -> str:
        return str(self._feature_map.get(str(self.features.get() or ""), ""))

    def _load_reference_options(self) -> None:
        from silva.media.reference_images import find_references

        records = find_references(limit=500)
        self._reference_ids = [str(record.get("id") or "") for record in records]
        labels = [
            f"{record.get('label') or record.get('name') or 'image'} ({record.get('category', 'object')})"
            for record in records
        ]
        self.reference.configure(values=labels)
        if labels:
            self.reference.set(labels[0])
        else:
            self.reference.set("")

    def _load_state(self) -> None:
        from silva.dev.panel_showcase import feature_state

        state = feature_state(self._current_id())
        self.accent.delete(0, "end")
        self.accent.insert(0, str(state.get("accent") or ACCENT))
        self.layout.set(str(state.get("layout") or "cards"))
        self.notes.delete("1.0", "end")
        self.notes.insert("1.0", str(state.get("notes") or ""))
        self.mark_button.configure(text="Marked" if state.get("marked") else "Mark")

        reference_id = str(state.get("reference_id") or "")
        if reference_id in self._reference_ids:
            index = self._reference_ids.index(reference_id)
            labels = list(self.reference.cget("values"))
            if index < len(labels):
                self.reference.set(labels[index])
        self._preview_reference()

    def _selected_reference_id(self) -> str:
        labels = list(self.reference.cget("values"))
        index = labels.index(str(self.reference.get() or "")) if self.reference.get() in labels else -1
        return self._reference_ids[index] if 0 <= index < len(self._reference_ids) else ""

    def _preview_reference(self) -> None:
        from silva.media.reference_images import reference_path

        path = reference_path(self._selected_reference_id())
        if path is None:
            self.preview.configure(image="", text="No linked reference image")
            return
        photo = _thumbnail(str(path), 360, 180, self.dialog)
        if photo is None:
            self.preview.configure(image="", text="Preview unavailable")
            return
        self._photos.append(photo)
        self.preview.configure(image=photo, text="")
        self.preview.image = photo

    def _toggle_mark(self) -> None:
        from silva.dev.panel_showcase import mark_feature

        feature_id = self._current_id()
        if not feature_id:
            return
        state = mark_feature(feature_id, str(self.mark_button.cget("text")) != "Marked")
        self.mark_button.configure(text="Marked" if state.get("marked") else "Mark")
        self._changed()

    def _save(self) -> None:
        from silva.dev.panel_showcase import set_feature_style

        feature_id = self._current_id()
        if not feature_id:
            return
        set_feature_style(
            feature_id,
            accent=str(self.accent.get() or ""),
            layout=str(self.layout.get() or ""),
            notes=self.notes.get("1.0", "end"),
            reference_id=self._selected_reference_id(),
        )
        self._changed()

    def _copy_request(self) -> None:
        from silva.dev.panel_showcase import code_agent_request

        text = code_agent_request(self._current_id())
        self.dialog.clipboard_clear()
        self.dialog.clipboard_append(text)
        self.notes.delete("1.0", "end")
        self.notes.insert("1.0", text)

    def _open_reference(self) -> None:
        from silva.media.reference_images import get_reference, reference_path

        reference_id = self._selected_reference_id()
        path = reference_path(reference_id)
        if path is None:
            return
        record = get_reference(reference_id) or {}
        show_image_viewer(
            str(path),
            title=str(record.get("label") or "Reference image"),
            notes=str(record.get("notes") or ""),
            reference_id=reference_id,
            parent=self.dialog,
        )

    def _open_library(self) -> None:
        show_media_library_popup(on_changed=self._load_reference_options)

    def _changed(self) -> None:
        if self._on_changed:
            self._on_changed()

    def _minimize(self) -> None:
        self.dialog.iconify()

    def _toggle_maximize(self) -> None:
        self._maximized = not self._maximized
        self.dialog.state("zoomed" if self._maximized else "normal")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.dialog.winfo_exists():
            unregister(self.dialog)
            self.dialog.destroy()
        with _lock:
            if _popup is self:
                _popup = None


def show_panel_showcase_popup(
    *,
    feature_id: str = "",
    on_changed: Callable[[], None] | None = None,
) -> bool:
    from silva.users.manager import get_active_user, is_owner

    if not is_owner(get_active_user() or {}):
        return False

    def _build(parent: tk.Misc) -> None:
        global _popup
        try:
            popup = PanelShowcasePopup(parent, feature_id=feature_id, on_changed=on_changed)
        except Exception as exc:
            log_error("Panel showcase popup failed", exc=exc)
            return
        with _lock:
            _popup = popup

    parent = _overlay_parent()
    if parent is not None:
        try:
            parent.after(0, lambda: _build(parent))
            return True
        except Exception as exc:
            log_error("Panel showcase popup schedule failed", exc=exc)

    def _run() -> None:
        root = tk.Tk()
        root.withdraw()
        register(root, persistent=True)
        _build(root)
        root.mainloop()

    threading.Thread(target=_run, name="silva-panel-showcase", daemon=True).start()
    return True
