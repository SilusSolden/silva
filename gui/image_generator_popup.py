from __future__ import annotations

import random
import threading
import tkinter as tk
import tkinter.font as tkfont
import tkinter.ttk as ttk

from silva.gui.display_manager import register, unregister, watch_shutdown
from silva.gui.media_library_popup import (
    _thumbnail,
    _window_buttons,
    show_image_viewer,
    show_media_library_popup,
)
from silva.gui.monitors import geometry_on_monitor
from silva.logger import log_error, log_info

BG = "#121212"
CARD_BG = "#1B1B1B"
TEXT = "#F5F5F5"
MUTED = "#B0BEC5"
ACCENT = "#FFB74D"
DANGER = "#EF5350"

STYLES = ("Auto", "Ocean", "Forest", "Sunset", "Neon", "Paper", "Error")
ASPECTS = {
    "Square 1:1": "square",
    "Wide 4:3": "wide",
    "Tall 3:4": "tall",
    "Portrait 4:5": "portrait",
}

_popup: "ImageGeneratorPopup | None" = None
_lock = threading.Lock()


def _overlay_parent() -> tk.Misc | None:
    try:
        from silva.gui.display_host import host_root

        return host_root()
    except Exception:
        return None


class ImageGeneratorPopup:
    def __init__(self, parent: tk.Misc, *, user_id: str = "") -> None:
        self.user_id = str(user_id or "default")
        self._photos = []
        self._closed = False
        self._maximized = False
        self.current: dict | None = None

        self.dialog = tk.Toplevel(parent)
        register(self.dialog, persistent=True)
        watch_shutdown(self.dialog)
        self.dialog.title("Silva - Image Studio")
        self.dialog.configure(bg=BG)
        self.dialog.attributes("-topmost", True)
        self.dialog.geometry(geometry_on_monitor(860, 760, anchor="center"))
        self.dialog.minsize(720, 640)
        self.dialog.protocol("WM_DELETE_WINDOW", self.close)
        self.dialog.bind("<Escape>", lambda _event: self.close())

        self.bold = tkfont.Font(family="Segoe UI", size=13, weight="bold")
        self.body_font = tkfont.Font(family="Segoe UI", size=10)
        self.small_font = tkfont.Font(family="Segoe UI", size=9)

        _window_buttons(
            self.dialog,
            self._minimize,
            self._toggle_maximize,
            self.close,
        ).pack(anchor="ne", padx=6, pady=(6, 0))

        tk.Label(
            self.dialog,
            text="Image Studio",
            font=tkfont.Font(family="Segoe UI", size=18, weight="bold"),
            fg=TEXT,
            bg=BG,
        ).pack(anchor="w", padx=16, pady=(4, 0))
        tk.Label(
            self.dialog,
            text="Local lightweight generator - prompt, style, refine, describe, save",
            font=self.body_font,
            fg=MUTED,
            bg=BG,
        ).pack(anchor="w", padx=16, pady=(0, 8))

        self._build_prompt_section()
        self._build_style_section()
        self._build_result_section()
        self._build_recent_section()
        self._build_toolbar()

        self._load_recent()

    def _section(self, number: int, title: str, subtitle: str) -> tk.Frame:
        outer = tk.Frame(self.dialog, bg=CARD_BG, highlightbackground="#37474F", highlightthickness=1)
        outer.pack(fill="x", padx=14, pady=(0, 8))
        badge = tk.Label(
            outer,
            text=str(number),
            width=2,
            font=self.bold,
            fg=BG,
            bg=ACCENT,
        )
        badge.grid(row=0, column=0, sticky="nw", padx=(10, 8), pady=10)
        heading = tk.Frame(outer, bg=CARD_BG)
        heading.grid(row=0, column=1, sticky="w", pady=(8, 0))
        tk.Label(heading, text=title, font=self.bold, fg=TEXT, bg=CARD_BG).pack(anchor="w")
        tk.Label(heading, text=subtitle, font=self.small_font, fg=MUTED, bg=CARD_BG).pack(anchor="w")
        body = tk.Frame(outer, bg=CARD_BG)
        body.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=(2, 10))
        outer.columnconfigure(1, weight=1)
        return body

    def _build_prompt_section(self) -> None:
        body = self._section(1, "Prompt", "Type or dictate what you want to see.")
        self.prompt = tk.Text(body, height=3, wrap="word", font=self.body_font, bg="#222222", fg=TEXT, insertbackground=TEXT, relief="flat")
        self.prompt.pack(fill="x")
        hint = tk.Label(
            body,
            text="Example: a blue chart with a friendly robot on a dark background",
            font=self.small_font,
            fg=MUTED,
            bg=CARD_BG,
        )
        hint.pack(anchor="w", pady=(4, 0))

    def _build_style_section(self) -> None:
        body = self._section(2, "Look and frame", "Pick a palette, frame shape, and placement seed.")
        controls = tk.Frame(body, bg=CARD_BG)
        controls.pack(fill="x")
        for column, label, values, variable in (
            (0, "Style", STYLES, "style"),
            (1, "Frame", tuple(ASPECTS), "aspect"),
        ):
            tk.Label(controls, text=label, font=self.small_font, fg=MUTED, bg=CARD_BG).grid(
                row=0, column=column, sticky="w"
            )
            combo = ttk.Combobox(controls, values=values, state="readonly", width=16)
            combo.set(values[0])
            combo.grid(row=1, column=column, sticky="w", padx=(0, 14), pady=(2, 0))
            setattr(self, f"_{variable}", combo)

        tk.Label(controls, text="Seed", font=self.small_font, fg=MUTED, bg=CARD_BG).grid(
            row=0, column=2, sticky="w"
        )
        self._seed = tk.Entry(controls, width=14, bg="#222222", fg=TEXT, insertbackground=TEXT, relief="flat")
        self._seed.grid(row=1, column=2, sticky="w", pady=(2, 0))
        tk.Button(
            controls,
            text="Randomize",
            command=self._randomize,
            bg="#283593",
            fg=TEXT,
            relief="flat",
            bd=0,
        ).grid(row=1, column=3, sticky="w", padx=(8, 0), pady=(2, 0))

    def _build_result_section(self) -> None:
        body = self._section(3, "Result and description", "The generated image stays open in the image viewer.")
        split = tk.Frame(body, bg=CARD_BG)
        split.pack(fill="x")

        left = tk.Frame(split, bg=CARD_BG)
        left.pack(side="left", padx=(0, 10))
        self.preview = tk.Label(
            left,
            text="No image yet",
            bg="#0D0D0D",
            fg=MUTED,
            width=52,
            height=16,
            relief="solid",
            bd=1,
        )
        self.preview.pack()

        right = tk.Frame(split, bg=CARD_BG)
        right.pack(side="left", fill="both", expand=True)
        tk.Label(right, text="Description", font=self.small_font, fg=MUTED, bg=CARD_BG).pack(anchor="w")
        self.description = tk.Text(
            right,
            height=8,
            wrap="word",
            font=self.body_font,
            bg="#222222",
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
        )
        self.description.pack(fill="both", expand=True)
        self.status = tk.Label(right, text="Ready.", fg=MUTED, bg=CARD_BG, font=self.small_font, anchor="w")
        self.status.pack(fill="x", pady=(4, 0))

    def _build_recent_section(self) -> None:
        body = self._section(4, "Recent generations", "Click a card to keep working on that image.")
        self.recent = tk.Frame(body, bg=CARD_BG)
        self.recent.pack(fill="x")

    def _build_toolbar(self) -> None:
        toolbar = tk.Frame(self.dialog, bg=BG)
        toolbar.pack(fill="x", padx=14, pady=(2, 12))
        buttons = (
            ("Generate", self._generate, ACCENT, BG, 11),
            ("GPU Status", self._gpu_status, "#37474F", TEXT, 10),
            ("GPU Test", self._gpu_test, "#1E88E5", TEXT, 9),
            ("Add Detail", self._edit, "#37474F", TEXT, 10),
            ("Describe", self._describe, "#37474F", TEXT, 10),
            ("Copy", self._copy, "#37474F", TEXT, 9),
            ("Save", self._save, "#2E7D32", TEXT, 9),
            ("Open", self._open, "#37474F", TEXT, 9),
            ("Library", self._library, "#4527A0", TEXT, 9),
            ("Clear", self._clear, "#37474F", TEXT, 9),
            ("Close", self.close, DANGER, TEXT, 9),
        )
        for text, command, bg, fg, width in buttons:
            tk.Button(
                toolbar,
                text=text,
                command=command,
                width=width,
                bg=bg,
                fg=fg,
                activebackground=bg,
                activeforeground=fg,
                relief="flat",
                bd=0,
                padx=8,
                pady=6,
            ).pack(side="left", padx=(0, 5))

    def _current_prompt(self) -> str:
        return self.prompt.get("1.0", "end").strip()

    def _style_value(self) -> str:
        value = str(self._style.get() or "Auto")
        return "auto" if value == "Auto" else value.lower()

    def _aspect_value(self) -> str:
        return ASPECTS.get(str(self._aspect.get() or "Square 1:1"), "square")

    def _seed_value(self) -> int | None:
        value = str(self._seed.get() or "").strip()
        if not value:
            return None
        try:
            return int(value)
        except ValueError:
            return abs(hash(value)) % 1_000_000

    def _randomize(self) -> None:
        self._seed.delete(0, "end")
        self._seed.insert(0, str(random.randint(1, 999999)))

    def _set_status(self, text: str, *, error: bool = False) -> None:
        self.status.configure(text=text, fg=DANGER if error else MUTED)

    def _load_recent(self) -> None:
        from silva.media.image_generator import recent_images

        for child in self.recent.winfo_children():
            child.destroy()
        for record in recent_images(6):
            photo = _thumbnail(str(record.get("path") or ""), 92, 64, self.dialog)
            if photo is None:
                continue
            self._photos.append(photo)
            card = tk.Button(
                self.recent,
                image=photo,
                text=str(record.get("prompt") or "Image")[:18],
                compound="top",
                bg=CARD_BG,
                fg=TEXT,
                relief="flat",
                bd=1,
                command=lambda item=record: self._select_recent(item),
            )
            card.pack(side="left", padx=(0, 8), pady=(4, 0))

    def _select_recent(self, record: dict) -> None:
        from silva.media.image_generator import set_active_image

        set_active_image(str(record.get("id") or ""), self.user_id)
        self._show_record(record)
        self._set_status(f"Selected: {record.get('prompt', '')[:80]}")

    def _show_record(self, record: dict) -> None:
        from silva.media.image_generator import describe_generated_image

        self.current = record
        path = str(record.get("path") or "")
        photo = _thumbnail(path, 480, 320, self.dialog)
        if photo is not None:
            self._photos.append(photo)
            self.preview.configure(image=photo, text="")
            self.preview.image = photo
        self.description.delete("1.0", "end")
        self.description.insert("1.0", describe_generated_image(str(record.get("id") or "")))
        if record.get("seed") is not None:
            self._seed.delete(0, "end")
            self._seed.insert(0, str(record["seed"]))

    def _job(self, work) -> None:
        def runner() -> None:
            try:
                record = work()
            except Exception as exc:
                log_error("Image Studio job failed", exc=exc)
                record = {"refusal": f"Image Studio failed: {exc}"}
            try:
                self.dialog.after(0, lambda: self._job_done(record))
            except tk.TclError:
                pass

        self._set_status("Working...")
        threading.Thread(target=runner, name="silva-image-studio", daemon=True).start()

    def _job_done(self, record: dict | None) -> None:
        if isinstance(record, dict) and record.get("refusal"):
            self._set_status(str(record["refusal"]), error=True)
            return
        if not isinstance(record, dict):
            self._set_status("No image was produced.", error=True)
            return
        self._set_status(f"Ready: {record.get('prompt', '')[:80]}")
        self._show_record(record)
        self._load_recent()
        self._open_viewer(record)

    def _open_viewer(self, record: dict) -> None:
        from silva.media.image_generator import save_generated_to_library

        image_id = str(record.get("id") or "")
        show_image_viewer(
            str(record.get("path") or ""),
            title=str(record.get("prompt") or "Generated image")[:70],
            notes=str(record.get("description") or ""),
            save_callback=lambda: save_generated_to_library(image_id, user_id=self.user_id),
        )

    def _generate(self) -> None:
        from silva.media.image_generator import generate_image

        prompt = self._current_prompt()
        if not prompt:
            self._set_status("Type a prompt first.", error=True)
            return
        log_info(f"Image Studio typed generation: {prompt[:120]}")
        self._job(
            lambda: generate_image(
                prompt,
                user_id=self.user_id,
                style=self._style_value(),
                aspect=self._aspect_value(),
                seed=self._seed_value(),
            )
        )

    def _gpu_status(self) -> None:
        from silva.media.image_generator_gpu import startup_check

        result = startup_check()
        self._set_status(str(result.get("message") or "GPU status is unavailable."), error=not result.get("ready"))

    def _gpu_test(self) -> None:
        from silva.media.image_generator import generate_gpu_test_image

        self._set_status("Running a small CUDA image test...")
        self._job(lambda: generate_gpu_test_image(user_id=self.user_id))

    def _edit(self) -> None:
        from silva.media.image_generator import active_image_for, edit_image

        active = active_image_for(self.user_id)
        if active is None:
            self._set_status("Generate an image first.", error=True)
            return
        detail = self._current_prompt()
        if not detail:
            self._set_status("Type the detail to add.", error=True)
            return
        log_info(f"Image Studio typed edit: {detail[:120]}")
        self._job(
            lambda: edit_image(
                str(active["id"]),
                detail,
                user_id=self.user_id,
                style=self._style_value(),
                aspect=self._aspect_value(),
                seed=self._seed_value(),
            )
        )

    def _describe(self) -> None:
        from silva.media.image_generator import active_image_for, describe_generated_image

        active = active_image_for(self.user_id)
        if active is None:
            self._set_status("Generate an image first.", error=True)
            return
        text = describe_generated_image(str(active["id"]))
        self.description.delete("1.0", "end")
        self.description.insert("1.0", text)
        self._set_status("Description ready. Copy to send it to a code agent.")

    def _copy(self) -> None:
        text = self.description.get("1.0", "end").strip()
        if not text:
            self._set_status("Describe the image first.", error=True)
            return
        self.dialog.clipboard_clear()
        self.dialog.clipboard_append(text)
        self._set_status("Description copied to clipboard.")

    def _save(self) -> None:
        from silva.media.image_generator import active_image_for, save_generated_to_library

        active = active_image_for(self.user_id)
        if active is None:
            self._set_status("Generate an image first.", error=True)
            return
        record = save_generated_to_library(str(active["id"]), user_id=self.user_id)
        self._set_status(
            "Saved to the owner-only image library." if record else "Already saved or unavailable.",
            error=record is None,
        )

    def _open(self) -> None:
        from silva.media.image_generator import active_image_for

        active = active_image_for(self.user_id)
        if active is not None:
            self._open_viewer(active)
        else:
            self._set_status("Generate an image first.", error=True)

    def _library(self) -> None:
        show_media_library_popup(owner_id=self.user_id)

    def _clear(self) -> None:
        self.prompt.delete("1.0", "end")
        self._set_status("Prompt cleared.")

    def _minimize(self) -> None:
        self.dialog.iconify()

    def _toggle_maximize(self) -> None:
        self._maximized = not self._maximized
        self.dialog.state("zoomed" if self._maximized else "normal")

    def close(self) -> None:
        global _popup
        if self._closed:
            return
        self._closed = True
        if self.dialog.winfo_exists():
            unregister(self.dialog)
            self.dialog.destroy()
        with _lock:
            if _popup is self:
                _popup = None


def show_image_generator_popup(*, user_id: str = "") -> bool:
    def _build(parent: tk.Misc) -> None:
        global _popup
        try:
            popup = ImageGeneratorPopup(parent, user_id=user_id)
        except Exception as exc:
            log_error("Image Studio popup failed", exc=exc)
            return
        with _lock:
            _popup = popup

    parent = _overlay_parent()
    if parent is not None:
        try:
            parent.after(0, lambda: _build(parent))
            return True
        except Exception as exc:
            log_error("Image Studio popup schedule failed", exc=exc)

    def _run() -> None:
        root = tk.Tk()
        root.withdraw()
        register(root, persistent=True)
        _build(root)
        root.mainloop()

    threading.Thread(target=_run, name="silva-image-studio", daemon=True).start()
    return True


def close_image_generator_popup() -> None:
    with _lock:
        popup = _popup
    if popup is None:
        return
    try:
        popup.dialog.after(0, popup.close)
    except tk.TclError:
        pass
