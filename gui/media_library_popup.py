from __future__ import annotations

import threading
import tkinter as tk
import tkinter.font as tkfont
import tkinter.ttk as ttk
from typing import Callable

from silva.gui.display_manager import register, unregister, watch_shutdown
from silva.gui.monitors import geometry_on_monitor
from silva.logger import log_error

try:
    from PIL import Image, ImageTk
except Exception:
    Image = None
    ImageTk = None

BG = "#121212"
CARD_BG = "#1B1B1B"
TEXT = "#F5F5F5"
MUTED = "#B0BEC5"
ACCENT = "#FFB74D"
WHITE = "#FFFFFF"

_popup: "MediaLibraryPopup | None" = None
_lock = threading.Lock()


def _overlay_parent() -> tk.Misc | None:
    try:
        from silva.gui.display_host import host_root

        return host_root()
    except Exception:
        return None


def _thumbnail(path: str, width: int, height: int, master: tk.Misc):
    if Image is None or ImageTk is None:
        return None
    try:
        with Image.open(path) as source:
            image = source.convert("RGB")
            image.thumbnail((width, height), Image.Resampling.LANCZOS)
            return ImageTk.PhotoImage(image, master=master)
    except Exception:
        return None


def _window_buttons(parent: tk.Misc, on_minimize: Callable[[], None], on_maximize: Callable[[], None], on_close: Callable[[], None]) -> tk.Frame:
    bar = tk.Frame(parent, bg=BG)
    for text, command in (("Min", on_minimize), ("Max", on_maximize), ("X", on_close)):
        tk.Button(
            bar,
            text=text,
            width=4,
            command=command,
            bg=CARD_BG,
            fg=TEXT,
            activebackground=ACCENT,
            activeforeground=BG,
            relief="flat",
            bd=0,
        ).pack(side="right", padx=2)
    return bar


class ImageViewer:
    def __init__(
        self,
        parent: tk.Misc,
        *,
        path: str,
        title: str,
        notes: str = "",
        reference_id: str | None = None,
        save_callback: Callable[[], dict | None] | None = None,
        on_deleted: Callable[[], None] | None = None,
    ) -> None:
        self.path = path
        self.title_text = title
        self.notes = notes
        self.reference_id = reference_id
        self._save_callback = save_callback
        self._on_deleted = on_deleted
        self._photo = None
        self._maximized = False
        self._closed = False

        self.dialog = tk.Toplevel(parent)
        register(self.dialog, persistent=True)
        watch_shutdown(self.dialog)
        self.dialog.title(f"Silva - {title}")
        self.dialog.configure(bg=BG)
        self.dialog.attributes("-topmost", True)
        self.dialog.geometry(geometry_on_monitor(720, 560, anchor="center"))
        self.dialog.protocol("WM_DELETE_WINDOW", self.close)
        self.dialog.bind("<Escape>", lambda _event: self.close())

        _window_buttons(
            self.dialog,
            self._minimize,
            self._toggle_maximize,
            self.close,
        ).pack(anchor="ne", padx=6, pady=(6, 0))

        bold = tkfont.Font(family="Segoe UI", size=12, weight="bold")
        body_font = tkfont.Font(family="Segoe UI", size=10)
        tk.Label(self.dialog, text=title, font=bold, fg=TEXT, bg=BG).pack(
            anchor="w", padx=14, pady=(4, 2)
        )

        self.background = tk.Frame(self.dialog, bg=BG)
        self.background.pack(fill="both", expand=True, padx=12, pady=6)
        self.background.bind("<Button-1>", lambda _event: self.close())

        self.image_label = tk.Label(self.background, bg=BG, cursor="hand2")
        self.image_label.pack(expand=True)

        detail = notes or path
        tk.Label(
            self.dialog,
            text=detail,
            font=body_font,
            fg=MUTED,
            bg=BG,
            wraplength=660,
            justify="left",
        ).pack(anchor="w", padx=14, pady=(0, 6))

        self.actions = tk.Frame(self.dialog, bg=BG)
        self.actions.pack(anchor="e", padx=12, pady=(0, 10))
        self._build_actions()
        self.dialog.after(80, self._fit)

    def _build_actions(self) -> None:
        for child in list(self.actions.winfo_children()):
            child.destroy()
        if self._save_callback is not None and self.reference_id is None:
            tk.Button(
                self.actions,
                text="Save to Library",
                command=self._save,
                bg=ACCENT,
                fg=BG,
                relief="flat",
                bd=0,
            ).pack(side="right", padx=4)
        if self.reference_id is not None:
            tk.Button(
                self.actions,
                text="Delete",
                command=self._delete,
                bg=CARD_BG,
                fg=TEXT,
                relief="flat",
                bd=0,
            ).pack(side="right", padx=4)
        tk.Button(
            self.actions,
            text="Close",
            command=self.close,
            bg=CARD_BG,
            fg=TEXT,
            relief="flat",
            bd=0,
        ).pack(side="right", padx=4)

    def _fit(self) -> None:
        if not self.dialog.winfo_exists():
            return
        width = max(240, self.background.winfo_width() - 20)
        height = max(200, self.background.winfo_height() - 20)
        photo = _thumbnail(self.path, width, height, self.dialog)
        if photo is None:
            self.image_label.configure(text="Image preview unavailable", fg=MUTED)
            return
        self._photo = photo
        self.image_label.configure(image=photo, text="")

    def _minimize(self) -> None:
        self.dialog.iconify()

    def _toggle_maximize(self) -> None:
        self._maximized = not self._maximized
        self.dialog.state("zoomed" if self._maximized else "normal")
        self.dialog.after(80, self._fit)

    def _save(self) -> None:
        if self._save_callback is None:
            return
        try:
            record = self._save_callback()
        except Exception as exc:
            log_error("Saving generated image failed", exc=exc)
            return
        if isinstance(record, dict) and record.get("id"):
            self.reference_id = str(record["id"])
            self._build_actions()

    def _delete(self) -> None:
        if not self.reference_id:
            return
        if not confirm_delete(self.dialog):
            return
        from silva.media.reference_images import delete_reference

        delete_reference(str(self.reference_id))
        callback = self._on_deleted
        self.close()
        if callback:
            callback()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.dialog.winfo_exists():
            unregister(self.dialog)
            self.dialog.destroy()


def show_image_viewer(
    path: str,
    *,
    title: str = "Image",
    notes: str = "",
    reference_id: str | None = None,
    parent: tk.Misc | None = None,
    save_callback: Callable[[], dict | None] | None = None,
    on_deleted: Callable[[], None] | None = None,
) -> ImageViewer | None:
    root = parent or _overlay_parent()
    if root is None:
        return None
    try:
        return ImageViewer(
            root,
            path=path,
            title=title,
            notes=notes,
            reference_id=reference_id,
            save_callback=save_callback,
            on_deleted=on_deleted,
        )
    except Exception as exc:
        log_error("Image viewer failed", exc=exc)
        return None


def confirm_delete(parent: tk.Misc) -> bool:
    from tkinter import messagebox

    return bool(
        messagebox.askyesno(
            "Delete image",
            "Delete this image from Silva and block it from being downloaded again?",
            parent=parent,
        )
    )


class MediaLibraryPopup:
    def __init__(self, parent: tk.Misc, *, owner_id: str = "", on_changed: Callable[[], None] | None = None) -> None:
        self.owner_id = owner_id
        self._on_changed = on_changed
        self._photos = []
        self._expanded = {}
        self._category_frames = {}
        self._category_buttons = {}
        self._closed = False
        self._maximized = False

        self.dialog = tk.Toplevel(parent)
        register(self.dialog, persistent=True)
        watch_shutdown(self.dialog)
        self.dialog.title("Silva - Image Library")
        self.dialog.configure(bg=BG)
        self.dialog.attributes("-topmost", True)
        self.dialog.geometry(geometry_on_monitor(860, 640, anchor="center"))
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
            text="Image Library - owner only",
            font=bold,
            fg=TEXT,
            bg=BG,
        ).pack(anchor="w", padx=14, pady=(4, 2))
        tk.Label(
            self.dialog,
            text="Click a folder to expand it, then single-click an image to view it. Deleting blocks re-download.",
            font=body_font,
            fg=MUTED,
            bg=BG,
        ).pack(anchor="w", padx=14, pady=(0, 4))

        toolbar = tk.Frame(self.dialog, bg=BG)
        toolbar.pack(fill="x", padx=12, pady=(0, 6))
        tk.Button(
            toolbar,
            text="Refresh",
            command=self.refresh,
            bg=CARD_BG,
            fg=TEXT,
            relief="flat",
            bd=0,
        ).pack(side="right", padx=4)
        tk.Button(
            toolbar,
            text="Close",
            command=self.close,
            bg=CARD_BG,
            fg=TEXT,
            relief="flat",
            bd=0,
        ).pack(side="right", padx=4)

        self.status = tk.Label(toolbar, text="", fg=MUTED, bg=BG, font=body_font)
        self.status.pack(side="left")

        self.canvas = tk.Canvas(self.dialog, bg=BG, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(
            self.dialog, orient="vertical", command=self.canvas.yview
        )
        self.body = tk.Frame(self.canvas, bg=BG)
        self.body.bind("<Configure>", lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.body.bind("<MouseWheel>", self._wheel)
        self.canvas.pack(side="left", fill="both", expand=True, padx=(12, 0), pady=(0, 12))
        self.scrollbar.pack(side="right", fill="y", pady=(0, 12))

        self.refresh()

    def _wheel(self, event) -> None:
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _minimize(self) -> None:
        self.dialog.iconify()

    def _toggle_maximize(self) -> None:
        self._maximized = not self._maximized
        self.dialog.state("zoomed" if self._maximized else "normal")

    def refresh(self) -> None:
        from silva.media.reference_images import CATEGORY_LABELS, grouped_references

        for child in list(self.body.winfo_children()):
            child.destroy()
        self._photos.clear()

        groups = grouped_references()
        total = sum(len(items) for items in groups.values())
        self.status.configure(text=f"{total} stored image(s)")

        for category, label in CATEGORY_LABELS.items():
            records = groups.get(category) or []
            section = tk.Frame(self.body, bg=BG)
            section.pack(fill="x", padx=4, pady=(4, 2), anchor="w")

            separator = tk.Frame(section, height=1, bg=WHITE)
            separator.pack(fill="x", pady=(0, 6))

            button = tk.Button(
                section,
                text=f"{'+' if not self._expanded.get(category) else '-'} Folder: {label} ({len(records)})",
                anchor="w",
                command=lambda value=category: self._toggle_category(value),
                bg=CARD_BG,
                fg=TEXT,
                activebackground=ACCENT,
                activeforeground=BG,
                relief="flat",
                bd=0,
            )
            button.pack(fill="x")
            self._category_buttons[category] = button

            children = tk.Frame(section, bg=BG)
            self._category_frames[category] = children
            if self._expanded.get(category):
                children.pack(fill="x", pady=(4, 0))
            for record in records:
                self._add_card(children, record)

    def _toggle_category(self, category: str) -> None:
        frame = self._category_frames.get(category)
        button = self._category_buttons.get(category)
        if frame is None or button is None:
            return
        expanded = not self._expanded.get(category, False)
        self._expanded[category] = expanded
        if expanded:
            frame.pack(fill="x", pady=(4, 0))
        else:
            frame.pack_forget()
        text = str(button.cget("text"))
        button.configure(text=text.replace("+ ", "- ", 1) if expanded else text.replace("- ", "+ ", 1))

    def _add_card(self, parent: tk.Misc, record: dict) -> None:
        path = str(record.get("path") or "")
        reference_id = str(record.get("id") or "")
        label = str(record.get("label") or record.get("name") or "image")
        notes = str(record.get("notes") or "")
        category = str(record.get("category") or "object")

        card = tk.Frame(
            parent,
            bg=CARD_BG,
            highlightthickness=1,
            highlightbackground=WHITE,
            bd=0,
            cursor="hand2",
        )
        card.pack(fill="x", padx=6, pady=4)
        card.bind("<Button-1>", lambda _event: self._open(record))

        top = tk.Frame(card, bg=CARD_BG)
        top.pack(fill="x", padx=8, pady=6)
        photo = _thumbnail(path, 92, 72, self.dialog)
        if photo is not None:
            self._photos.append(photo)
            thumb = tk.Label(top, image=photo, bg=CARD_BG, cursor="hand2")
            thumb.image = photo
            thumb.pack(side="left", padx=(0, 10))
            thumb.bind("<Button-1>", lambda _event: self._open(record))
        else:
            tk.Label(top, text="No preview", bg=CARD_BG, fg=MUTED).pack(side="left")

        text_frame = tk.Frame(top, bg=CARD_BG)
        text_frame.pack(side="left", fill="x", expand=True)
        tk.Label(text_frame, text=label, fg=TEXT, bg=CARD_BG, anchor="w").pack(fill="x")
        tk.Label(
            text_frame,
            text=f"{category} - {notes or 'No notes'}",
            fg=MUTED,
            bg=CARD_BG,
            anchor="w",
            wraplength=520,
        ).pack(fill="x", pady=(2, 4))

        delete = tk.Button(
            top,
            text="Delete",
            command=lambda: self._delete(reference_id),
            bg=CARD_BG,
            fg=TEXT,
            relief="flat",
            bd=0,
        )
        delete.pack(side="right")
        delete.bind("<Button-1>", lambda event: event.widget.bell())

        route = tk.Canvas(card, width=540, height=28, bg=CARD_BG, highlightthickness=0)
        route.pack(fill="x", padx=8, pady=(0, 8))
        route.create_line(8, 18, 532, 18, fill=WHITE, width=1, arrow=tk.LAST)
        route.create_text(
            270,
            10,
            text=f"{record.get('source', 'unknown')} -> {record.get('path', '')}",
            fill=MUTED,
            anchor="s",
            font=tkfont.Font(family="Segoe UI", size=8),
        )

    def _open(self, record: dict) -> None:
        path = str(record.get("path") or "")
        if not path:
            return
        show_image_viewer(
            path,
            title=str(record.get("label") or record.get("name") or "Image"),
            notes=str(record.get("notes") or ""),
            reference_id=str(record.get("id") or "") or None,
            parent=self.dialog,
            on_deleted=self.refresh,
        )

    def _delete(self, reference_id: str) -> None:
        if not confirm_delete(self.dialog):
            return
        from silva.media.reference_images import delete_reference

        if delete_reference(reference_id):
            self.refresh()
            callback = self._on_changed
            if callback:
                callback()

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


def show_media_library_popup(
    *,
    owner_id: str = "",
    on_changed: Callable[[], None] | None = None,
) -> bool:
    from silva.users.manager import get_active_user, is_owner

    user = get_active_user() or {}
    if not is_owner(user):
        return False

    def _build(parent: tk.Misc) -> None:
        global _popup
        try:
            popup = MediaLibraryPopup(
                parent,
                owner_id=str(user.get("id") or owner_id or "owner"),
                on_changed=on_changed,
            )
        except Exception as exc:
            log_error("Media library popup failed", exc=exc)
            return
        with _lock:
            _popup = popup

    parent = _overlay_parent()
    if parent is not None:
        try:
            parent.after(0, lambda: _build(parent))
            return True
        except Exception as exc:
            log_error("Media library popup schedule failed", exc=exc)

    def _run() -> None:
        root = tk.Tk()
        root.withdraw()
        register(root, persistent=True)
        _build(root)
        root.mainloop()

    threading.Thread(target=_run, name="silva-media-library", daemon=True).start()
    return True


def close_media_library_popup() -> None:
    with _lock:
        popup = _popup
    if popup is None:
        return
    try:
        popup.dialog.after(0, popup.close)
    except tk.TclError:
        pass
