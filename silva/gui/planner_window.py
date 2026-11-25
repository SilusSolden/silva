"""Silva planner: 2D floor-plan sketch and a 3D view of the same project."""

from __future__ import annotations

import math
import threading
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog
from typing import Any

from silva.gui.display_manager import register, unregister, watch_shutdown
from silva.gui.monitors import geometry_on_monitor
from silva.logger import log_error, log_info
from silva.planner.camera import Camera, clamp_camera, project, snap, unproject_floor
from silva.planner.catalog import CATEGORIES, RUN_KINDS, add_custom_item, get_item, items_in, next_upgrade
from silva.planner.icons import icon_path
from silva.planner.import_media import MediaRenderJob
from silva.planner.paint_tools import tool_icon_path
from silva.planner.store import (
    active_floor,
    add_floor,
    add_object,
    add_room,
    add_run,
    add_wall,
    clear_floor,
    current_project,
    delete_item,
    ensure_project,
    find_item,
    move_item,
    rotate_item,
    save_project,
    upgrade_item,
)
from silva.planner.geometry import (
    PlanView,
    distance,
    endpoint_hit,
    format_length,
    format_sq_ft,
    hit_segment,
    parse_length,
    point_in_room,
    room_area_sq_ft,
    room_center,
    room_points,
    screen_to_world,
    snap_to_points,
    total_sq_ft,
    world_to_screen,
    zoom_at,
)
from silva.planner.layout import (
    DEFAULT_SITE,
    GROUND_OPTIONS,
    TERRAIN_OPTIONS,
    apply_instruction,
    rebuild_rooms_from_lines,
    update_wall_geometry,
)

PAPER_2D = "#F4F6F8"
GRID_2D = "#E2E6EA"
GRID_2D_MAJOR = "#CBD2D9"
PAPER_3D = "#EEF2F5"
GRID_3D = "#C5D3DE"
INK = "#243140"
MUTED = "#5B7085"
SIDEBAR = "#FFFFFF"
BAR = "#FAFBFC"
ACCENT = "#1A237E"
SELECT = "#E67E22"
WALL_2D = "#5D6D7E"
WALL_3D = "#5D4037"
WALL_INNER = "#F4F4F4"
WOOD = "#C8A36A"
WOOD_LINE = "#B08D55"
TOOL_ON = "#C5CAE9"
PILL_ON = "#1A237E"
PILL_OFF = "#ECEFF1"

_lock = threading.Lock()
_panel: "PlannerWindow | None" = None


def _parent() -> tk.Misc | None:
    try:
        from silva.gui.display_host import host_root

        return host_root()
    except Exception:
        return None


class PlannerWindow:
    def __init__(self, parent: tk.Misc, *, user_id: str, view_mode: str | None = None) -> None:
        self.user_id = user_id
        self._closed = False
        self.project = ensure_project(current_project())
        cam = self.project.get("camera") or {}
        self.camera = Camera(
            yaw=float(cam.get("yaw", 0.7)),
            pitch=float(cam.get("pitch", 0.58)),
            distance=float(cam.get("distance", 16.0)),
            tx=float(cam.get("tx", 0.0)),
            tz=float(cam.get("tz", 0.0)),
        )
        plan = self.project.get("plan") or {}
        self.plan = PlanView(
            pan_x=float(plan.get("pan_x", 0.0)),
            pan_z=float(plan.get("pan_z", 0.0)),
            ppm=float(plan.get("ppm", 48.0)),
        )
        self.view_mode = "3d" if (view_mode or self.project.get("view_mode") or "2d") == "3d" else "2d"
        self.tool = "line"
        self.catalog_id = "sofa"
        self.selected_id = ""
        self._drag = ""
        self._last = (0, 0)
        self._press = (0, 0)
        self._wall_start: tuple[float, float] | None = None
        self._line_preview: tuple[float, float, float, float] | None = None
        self._endpoint = ""
        self._room_start: tuple[float, float] | None = None
        self._room_preview: tuple[float, float, float, float] | None = None
        self._save_job: str | None = None
        self._photos: list[tk.PhotoImage] = []
        self._icon_cache: dict[str, tk.PhotoImage] = {}
        self._placed_cache: dict[str, tk.PhotoImage] = {}
        self._render_job = MediaRenderJob()
        self._tool_photos: dict[str, tk.PhotoImage] = {}

        self.dialog = tk.Toplevel(parent)
        register(self.dialog, persistent=True)
        watch_shutdown(self.dialog)
        self.dialog.title("Silva - Planner")
        self.dialog.configure(bg=BAR)
        self.dialog.resizable(True, True)
        self.dialog.protocol("WM_DELETE_WINDOW", self.close)
        self.dialog.geometry(geometry_on_monitor(1240, 780, anchor="center"))

        self._title_font = tkfont.Font(family="Segoe UI", size=12, weight="bold")
        self._body = tkfont.Font(family="Segoe UI", size=9)
        self._small = tkfont.Font(family="Segoe UI", size=8)

        self._build()
        self._redraw()
        try:
            self.dialog.deiconify()
            self.dialog.lift()
            self.dialog.focus_force()
        except tk.TclError:
            pass
        log_info(f"Planner window shown ({self.view_mode}).")

    def _build(self) -> None:
        header = tk.Frame(self.dialog, bg=BAR)
        header.pack(fill="x", padx=10, pady=(8, 6))
        tk.Label(header, text=str(self.project.get("name") or "New project"), font=self._title_font, fg=ACCENT, bg=BAR).pack(
            side="left"
        )
        self._floor_label = tk.Label(header, text="", font=self._body, fg=MUTED, bg=BAR)
        self._floor_label.pack(side="left", padx=(10, 0))

        toggle = tk.Frame(header, bg=BAR)
        toggle.pack(side="left", expand=True)
        self._mode_btns: dict[str, tk.Button] = {}
        for key, label in (("2d", "2D"), ("3d", "3D")):
            btn = tk.Button(
                toggle,
                text=label,
                font=self._title_font,
                width=4,
                command=lambda k=key: self.set_view_mode(k),
            )
            btn.pack(side="left", padx=2)
            self._mode_btns[key] = btn

        tk.Button(header, text="Ask Silva to map", font=self._body, command=self._open_map).pack(side="right", padx=4)
        tk.Button(header, text="New floor", font=self._body, command=self._new_floor).pack(side="right", padx=4)
        tk.Button(header, text="Save", font=self._body, command=self._save_now).pack(side="right", padx=4)
        tk.Button(header, text="Close", font=self._body, command=self.close).pack(side="right")

        body = tk.Frame(self.dialog, bg=BAR)
        body.pack(fill="both", expand=True, padx=8, pady=(0, 6))

        side = tk.Frame(body, bg=SIDEBAR, width=248)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)

        tk.Label(side, text="Objects", font=self._body, fg=INK, bg=SIDEBAR).pack(anchor="w", padx=8, pady=(8, 4))
        self._tool_btns: dict[str, tk.Button] = {}
        palette_wrap = tk.Frame(side, bg=SIDEBAR)
        palette_wrap.pack(fill="both", expand=True, padx=6)
        self._palette = tk.Canvas(palette_wrap, bg=SIDEBAR, highlightthickness=0, width=220)
        scroll = tk.Scrollbar(palette_wrap, orient="vertical", command=self._palette.yview)
        self._palette.configure(yscrollcommand=scroll.set)
        self._palette.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self._palette_inner = tk.Frame(self._palette, bg=SIDEBAR)
        self._palette.create_window((0, 0), window=self._palette_inner, anchor="nw")
        self._palette_inner.bind(
            "<Configure>",
            lambda _e: self._palette.configure(scrollregion=self._palette.bbox("all")),
        )
        self._build_object_palette()
        tk.Button(side, text="Add custom object", font=self._small, command=self._add_custom_object).pack(
            fill="x", padx=8, pady=(4, 2)
        )

        action = tk.Frame(side, bg=SIDEBAR)
        action.pack(fill="x", padx=8, pady=6)
        tk.Button(action, text="Upgrade", font=self._small, command=self._upgrade).pack(side="left", padx=2)
        tk.Button(action, text="Rotate", font=self._small, command=self._rotate).pack(side="left", padx=2)
        tk.Button(action, text="Delete", font=self._small, command=self._delete).pack(side="left", padx=2)
        tk.Button(action, text="Delete all", font=self._small, command=self._delete_all).pack(side="left", padx=2)
        render_row = tk.Frame(side, bg=SIDEBAR)
        render_row.pack(fill="x", padx=8, pady=(0, 6))
        tk.Button(render_row, text="Pause", font=self._small, command=self._pause_render).pack(side="left", padx=2)
        tk.Button(render_row, text="Play", font=self._small, command=self._play_render).pack(side="left", padx=2)

        tk.Label(side, text="Selected line", font=self._body, fg=INK, bg=SIDEBAR).pack(anchor="w", padx=8)
        edit = tk.Frame(side, bg=SIDEBAR)
        edit.pack(fill="x", padx=8, pady=(2, 6))
        tk.Label(edit, text="Length", font=self._small, bg=SIDEBAR).grid(row=0, column=0, sticky="w")
        self._length_var = tk.StringVar()
        tk.Entry(edit, textvariable=self._length_var, width=12, font=self._small).grid(row=0, column=1, padx=4)
        tk.Label(edit, text="Angle", font=self._small, bg=SIDEBAR).grid(row=1, column=0, sticky="w")
        self._angle_var = tk.StringVar()
        tk.Entry(edit, textvariable=self._angle_var, width=12, font=self._small).grid(row=1, column=1, padx=4)
        tk.Button(edit, text="Apply", font=self._small, command=self._apply_line_edit).grid(row=0, column=2, rowspan=2, padx=4)

        tk.Label(side, text="Site / land", font=self._body, fg=INK, bg=SIDEBAR).pack(anchor="w", padx=8, pady=(4, 2))
        site_row = tk.Frame(side, bg=SIDEBAR)
        site_row.pack(fill="x", padx=8)
        self._site_on = tk.BooleanVar(value=bool((self.project.get("site") or {}).get("enabled")))
        tk.Checkbutton(
            site_row,
            text="Show lot",
            variable=self._site_on,
            bg=SIDEBAR,
            font=self._small,
            command=self._toggle_site,
        ).pack(side="left")
        self._ground_var = tk.StringVar(value=str((self.project.get("site") or {}).get("ground") or "grass"))
        tk.OptionMenu(site_row, self._ground_var, *GROUND_OPTIONS, command=lambda _v: self._toggle_site()).pack(side="left", padx=4)
        self._terrain_var = tk.StringVar(value=str((self.project.get("site") or {}).get("terrain") or "flat"))
        tk.OptionMenu(side, self._terrain_var, *TERRAIN_OPTIONS, command=lambda _v: self._toggle_site()).pack(anchor="w", padx=8)

        self._hint = tk.Label(side, text="", font=self._small, fg=MUTED, bg=SIDEBAR, wraplength=228, justify="left")
        self._hint.pack(fill="x", padx=8, pady=(4, 8))

        view = tk.Frame(body, bg=PAPER_2D, highlightbackground="#D0D5DA", highlightthickness=1)
        view.pack(side="left", fill="both", expand=True, padx=(8, 0))
        ribbon = tk.Frame(view, bg="#2B2B2B", highlightbackground="#1F1F1F", highlightthickness=1)
        ribbon.pack(fill="x")
        self._draw_strip_btns: dict[str, tk.Button] = {}
        groups = (
            ("Selection", (("select", "Select"),)),
            ("Image", (("import", "Import"),)),
            ("Tools", (("eraser", "Eraser"), ("orbit", "Look"))),
            ("Shapes", (("line", "Line"), ("room", "Rectangle"))),
            ("Lines", (("electrical", "Wire"), ("water", "Water"), ("gas", "Gas"), ("drain", "Drain"))),
            ("Edit", (("delete", "Delete"), ("delete_all", "Delete all"))),
        )
        for title, tools in groups:
            group = tk.Frame(ribbon, bg="#2B2B2B")
            group.pack(side="left", padx=8, pady=4)
            tk.Label(group, text=title, font=self._small, fg="#A6A6A6", bg="#2B2B2B").pack(anchor="w")
            row = tk.Frame(group, bg="#2B2B2B")
            row.pack()
            for key, label in tools:
                photo = self._tool_photo(key)
                if key == "delete":
                    command = self._delete
                elif key == "delete_all":
                    command = self._delete_all
                elif key == "import":
                    command = self._import_media
                else:
                    command = lambda k=key: self._set_tool(k)
                opts = {
                    "text": label,
                    "font": self._small,
                    "compound": "top",
                    "padx": 4,
                    "pady": 2,
                    "bg": "#2B2B2B",
                    "fg": "#F3F3F3",
                    "activebackground": "#3D3D3D",
                    "activeforeground": "#FFFFFF",
                    "relief": "flat",
                    "bd": 0,
                    "highlightthickness": 0,
                    "command": command,
                }
                if photo is not None:
                    opts["image"] = photo
                btn = tk.Button(row, **opts)
                btn.pack(side="left", padx=2)
                self._draw_strip_btns[key] = btn
                if key not in {"delete", "delete_all", "import"}:
                    self._tool_btns[key] = btn
            tk.Frame(ribbon, bg="#3D3D3D", width=1).pack(side="left", fill="y", pady=6)
        self._draw_strip_hint = tk.Label(
            ribbon,
            text="Select a tool, then draw on the plan.",
            font=self._small,
            fg="#A6A6A6",
            bg="#2B2B2B",
        )
        self._draw_strip_hint.pack(side="left", padx=8)
        self.canvas = tk.Canvas(view, bg=PAPER_2D, highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<ButtonPress-3>", self._on_right_press)
        self.canvas.bind("<B3-Motion>", self._on_right_drag)
        self.canvas.bind("<ButtonRelease-3>", self._on_right_release)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Configure>", lambda _e: self._redraw())
        self.dialog.bind("<Delete>", lambda _e: self._delete())
        self.dialog.bind("<r>", lambda _e: self._rotate())
        self.dialog.bind("<R>", lambda _e: self._rotate())
        self.dialog.bind("<Escape>", lambda _e: self._clear_select())
        self.dialog.bind("2", lambda _e: self.set_view_mode("2d"))
        self.dialog.bind("3", lambda _e: self.set_view_mode("3d"))

        self._status = tk.Label(self.dialog, text="", font=self._small, fg=MUTED, bg=BAR, anchor="w")
        self._status.pack(fill="x", padx=12, pady=(0, 8))
        self._refresh_mode_chrome()
        self._set_tool(self.tool)
        self._status.config(text="Line is on.")

    def set_view_mode(self, mode: str) -> None:
        mode = "3d" if str(mode).lower() == "3d" else "2d"
        if mode == self.view_mode:
            self._refresh_mode_chrome()
            return
        self.view_mode = mode
        self.project["view_mode"] = mode
        if mode == "2d" and self.tool == "orbit":
            self._set_tool("line")
        else:
            self._set_tool(self.tool)
        self._refresh_mode_chrome()
        self._redraw()
        self._schedule_save()
        self._status.config(
            text="3D — Draw line still works. Drag on the floor to sketch walls, or pick Look around."
            if mode == "3d"
            else "2D — Draw line is on. Drag on the plan to sketch walls. Close a shape for square footage."
        )

    def _refresh_mode_chrome(self) -> None:
        for key, btn in self._mode_btns.items():
            on = key == self.view_mode
            btn.configure(bg=PILL_ON if on else PILL_OFF, fg="#FFFFFF" if on else INK)
        self.canvas.configure(bg=PAPER_3D if self.view_mode == "3d" else PAPER_2D)
        self._floor_label.config(text=self._floor().get("name") or "First floor")

    def _photo(self, name: str, image_file: str = "") -> tk.PhotoImage | None:
        key = image_file or name
        cached = self._icon_cache.get(key)
        if cached is not None:
            return cached
        path = Path(image_file) if image_file else icon_path(name)
        if not path.exists():
            return None
        try:
            photo = tk.PhotoImage(file=str(path))
        except tk.TclError:
            return None
        if int(photo.width()) > 48:
            factor = max(1, int(photo.width() / 48))
            photo = photo.subsample(factor, factor)
        self._icon_cache[key] = photo
        self._photos.append(photo)
        return photo

    def _tool_photo(self, name: str) -> tk.PhotoImage | None:
        cached = self._tool_photos.get(name)
        if cached is not None:
            return cached
        path = tool_icon_path(name)
        if not path.exists():
            return None
        try:
            photo = tk.PhotoImage(file=str(path))
        except tk.TclError:
            return None
        self._tool_photos[name] = photo
        self._photos.append(photo)
        return photo

    def _placed_photo(self, item: dict[str, Any], yaw: float, pixel_w: int, pixel_h: int) -> tk.PhotoImage | None:
        from io import BytesIO

        from PIL import Image

        key = f"{item.get('id')}:{item.get('image')}:{round(yaw, 2)}:{pixel_w}x{pixel_h}"
        cached = self._placed_cache.get(key)
        if cached is not None:
            return cached
        path = Path(str(item.get("image") or "")) if item.get("image") else icon_path(str(item["id"]))
        if not path.exists():
            return None
        try:
            image = Image.open(path).convert("RGBA")
        except OSError:
            return None
        size = max(16, int(pixel_w), int(pixel_h))
        image = image.resize((max(16, int(pixel_w)), max(16, int(pixel_h))), Image.Resampling.LANCZOS)
        degrees = -math.degrees(yaw)
        if abs(degrees) > 0.5:
            image = image.rotate(degrees, expand=True, resample=Image.Resampling.BICUBIC)
        buf = BytesIO()
        image.save(buf, format="PNG")
        try:
            photo = tk.PhotoImage(data=buf.getvalue())
        except tk.TclError:
            return None
        self._placed_cache[key] = photo
        self._photos.append(photo)
        return photo

    def _build_object_palette(self) -> None:
        for child in self._palette_inner.winfo_children():
            child.destroy()
        for category, label in CATEGORIES:
            items = items_in(category)
            if not items:
                continue
            tk.Label(self._palette_inner, text=label, font=self._body, fg=ACCENT, bg=SIDEBAR).pack(anchor="w", pady=(6, 2))
            for item in items:
                row = tk.Frame(self._palette_inner, bg=SIDEBAR)
                row.pack(fill="x", pady=1)
                photo = self._photo(str(item["id"]), str(item.get("image") or ""))
                if photo is not None:
                    tk.Button(
                        row,
                        image=photo,
                        command=lambda i=item["id"]: self._choose_object(i),
                    ).pack(side="left")
                else:
                    swatch = tk.Frame(row, width=32, height=32, bg=str(item.get("color") or "#90A4AE"))
                    swatch.pack(side="left", padx=2)
                    swatch.pack_propagate(False)
                tk.Button(
                    row,
                    text=str(item["name"]),
                    font=self._small,
                    anchor="w",
                    bg=SIDEBAR,
                    relief="flat",
                    command=lambda i=item["id"]: self._choose_object(i),
                ).pack(side="left", fill="x", expand=True)

    def _choose_object(self, catalog_id: str) -> None:
        item = get_item(catalog_id)
        if item is None:
            return
        self.catalog_id = catalog_id
        tool = str(item.get("tool") or "")
        if tool in RUN_KINDS:
            self._set_tool(tool)
            self._status.config(text=f"{item['name']} — drag to route it.")
            return
        placed = add_object(self.project, catalog_id, *self._drop_point())
        if placed:
            self.selected_id = str(placed.get("id") or "")
            self._set_tool("select")
            self._redraw()
            self._schedule_save()
            self._status.config(text=f"Placed {item['name']}. Drag to move it.")
            return
        self._set_tool("place")
        self._status.config(text=f"Selected {item['name']}. Click the plan to place it.")

    def _drop_point(self) -> tuple[float, float]:
        if self.view_mode == "2d":
            x, z = self.plan.pan_x, self.plan.pan_z
        else:
            x, z = self.camera.tx, self.camera.tz
        count = len(self._floor().get("objects") or []) + len(self._floor().get("marks") or [])
        return x + (count % 5) * 0.6, z + (count // 5) * 0.6

    def _add_custom_object(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.dialog,
            title="Add a custom object image",
            filetypes=[("Images", "*.png *.gif *.jpg *.jpeg *.webp"), ("All files", "*.*")],
        )
        if not path:
            return
        name = Path(path).stem.replace("_", " ").title()
        item = add_custom_item(name=name, image_path=path, width=1.0, depth=1.0, height=1.0)
        self._build_object_palette()
        self._choose_object(str(item["id"]))

    def _set_tool(self, tool: str) -> None:
        if self.view_mode == "2d" and tool == "orbit":
            tool = "select"
        if tool == "wall":
            tool = "line"
        self.tool = tool
        self._room_start = None
        self._room_preview = None
        self._wall_start = None
        self._line_preview = None
        self._endpoint = ""
        strip = getattr(self, "_draw_strip_btns", {})
        for key, btn in self._tool_btns.items():
            if key in strip:
                continue
            btn.configure(bg=TOOL_ON if key == tool else "#F5F5F5")
        for key, btn in strip.items():
            on = key == tool
            btn.configure(
                bg="#505050" if on else "#2B2B2B",
                fg="#FFFFFF",
                activebackground="#3D3D3D",
            )
        hints = {
            "select": "Click an object or line, then drag it.",
            "line": "Drag to draw a wall.",
            "room": "Drag a rectangle to draw a room.",
            "place": "Click the plan to place the selected object.",
            "mark": "Click to drop a mark.",
            "orbit": "Drag to look around in 3D.",
            "eraser": "Click a wall, object, or line to delete it.",
            "electrical": "Drag copper wire where it needs to run.",
            "water": "Drag a water line.",
            "gas": "Drag a gas line.",
            "drain": "Drag a drain line.",
        }
        if hasattr(self, "_hint"):
            self._hint.config(text=hints.get(tool, ""))
        if hasattr(self, "_draw_strip_hint"):
            self._draw_strip_hint.config(text=hints.get(tool, ""))
        if hasattr(self, "canvas"):
            draw_tools = {"line", "room", "wall", "electrical", "water", "gas", "drain"}
            self.canvas.configure(cursor="crosshair" if tool in draw_tools else "arrow")

    def _toggle_site(self) -> None:
        site = self.project.setdefault("site", dict(DEFAULT_SITE))
        site["enabled"] = bool(self._site_on.get())
        site["ground"] = self._ground_var.get()
        site["terrain"] = self._terrain_var.get()
        site["contours"] = True
        self._redraw()
        self._schedule_save()

    def _open_map(self, initial: str = "") -> None:
        from silva.gui.planner_map_dialog import show_planner_map_dialog

        show_planner_map_dialog(initial=initial, on_map=self.apply_speech)

    def apply_speech(self, text: str) -> str:
        try:
            from silva.commands.planner_phrases import is_planner_close_ask, match_planner_draw_tool

            if is_planner_close_ask(text):
                self.close()
                return "I closed the planner."
            tool = match_planner_draw_tool(text)
        except Exception:
            tool = None
        if tool:
            self._set_tool(tool)
            spoken = (
                "Draw line is on. Drag on the plan to sketch walls."
                if tool == "line"
                else "Draw room is on. Drag a rectangle on the plan."
            )
            self._status.config(text=spoken)
            return spoken
        result = apply_instruction(self.project, text, selected_id=self.selected_id)
        if not result:
            return ""
        site = self.project.get("site") or {}
        self._site_on.set(bool(site.get("enabled")))
        if site.get("ground"):
            self._ground_var.set(str(site["ground"]))
        if site.get("terrain"):
            self._terrain_var.set(str(site["terrain"]))
        self._refresh_mode_chrome()
        self._redraw()
        self._schedule_save()
        self._status.config(text=result)
        return result

    def _apply_line_edit(self) -> None:
        found = find_item(self.project, self.selected_id) if self.selected_id else None
        if not found or found[0] != "walls":
            self._status.config(text="Click a line first.")
            return
        length = parse_length(self._length_var.get())
        angle_raw = self._angle_var.get().strip()
        angle = None
        if angle_raw:
            try:
                angle = float(angle_raw.replace("°", "").replace("deg", "").strip())
            except ValueError:
                angle = None
        update_wall_geometry(found[1], length_m=length, angle_deg=angle)
        rebuild_rooms_from_lines(self._floor())
        self._redraw()
        self._schedule_save()
        self._status.config(text="Updated that line.")

    def _fill_line_editor(self) -> None:
        found = find_item(self.project, self.selected_id) if self.selected_id else None
        if not found or found[0] != "walls":
            self._length_var.set("")
            self._angle_var.set("")
            return
        wall = found[1]
        self._length_var.set(format_length(distance(wall["x1"], wall["z1"], wall["x2"], wall["z2"])))
        ang = math.degrees(math.atan2(float(wall["x2"]) - float(wall["x1"]), float(wall["z2"]) - float(wall["z1"])))
        self._angle_var.set(f"{ang:.0f}")

    def _line_points(self) -> list[tuple[float, float]]:
        pts: list[tuple[float, float]] = []
        for wall in list(self._floor().get("walls") or []) + list(self._floor().get("runs") or []):
            pts.append((float(wall["x1"]), float(wall["z1"])))
            pts.append((float(wall["x2"]), float(wall["z2"])))
        return pts

    def _floor(self) -> dict[str, Any]:
        return active_floor(self.project)

    def _sync_views(self) -> None:
        self.project["view_mode"] = self.view_mode
        self.project["camera"] = {
            "yaw": self.camera.yaw,
            "pitch": self.camera.pitch,
            "distance": self.camera.distance,
            "tx": self.camera.tx,
            "tz": self.camera.tz,
        }
        self.project["plan"] = {"pan_x": self.plan.pan_x, "pan_z": self.plan.pan_z, "ppm": self.plan.ppm}

    def _schedule_save(self) -> None:
        if self._save_job is not None:
            try:
                self.dialog.after_cancel(self._save_job)
            except tk.TclError:
                pass
        self._save_job = self.dialog.after(700, self._save_now)

    def _save_now(self) -> None:
        self._save_job = None
        self._sync_views()
        save_project(self.project)
        area = total_sq_ft(self._floor().get("rooms") or [])
        self._status.config(text=f"Saved · {format_sq_ft(area)}")

    def _new_floor(self) -> None:
        floor = add_floor(self.project, f"Floor {len(self.project.get('floors') or []) + 1}")
        self.selected_id = ""
        self._refresh_mode_chrome()
        self._redraw()
        self._schedule_save()
        self._status.config(text=f"Added {floor['name']}.")

    def _upgrade(self) -> None:
        if not self.selected_id:
            self._status.config(text="Select a line or object first, then Upgrade.")
            return
        found = find_item(self.project, self.selected_id)
        if found is None:
            return
        kind, item = found
        if kind == "walls":
            item["thickness"] = min(0.4, float(item.get("thickness") or 0.15) + 0.05)
            item["finish"] = "brick"
            self._redraw()
            self._schedule_save()
            self._status.config(text="Upgraded that wall.")
            return
        nxt = next_upgrade(str(item.get("catalog_id") or ""))
        if nxt is None:
            self._status.config(text="That item has no upgrade yet.")
            return
        upgrade_item(self.project, self.selected_id)
        self._redraw()
        self._schedule_save()
        self._status.config(text=f"Upgraded to {nxt['name']}.")

    def _rotate(self, degrees: float = 90.0) -> None:
        if not self.selected_id:
            self._status.config(text="Click an object first, then rotate.")
            return
        if not rotate_item(self.project, self.selected_id, degrees):
            self._status.config(text="That item does not rotate.")
            return
        self._redraw()
        self._schedule_save()
        self._status.config(text=f"Rotated {int(degrees)}°.")

    def _delete(self) -> None:
        if not self.selected_id:
            self._status.config(text="Click a wall, object, or line first, then Delete.")
            return
        delete_item(self.project, self.selected_id)
        self.selected_id = ""
        self._redraw()
        self._schedule_save()
        self._status.config(text="Deleted.")

    def _delete_all(self) -> None:
        clear_floor(self.project)
        self.selected_id = ""
        self._redraw()
        self._schedule_save()
        self._status.config(text="Cleared this floor.")

    def _import_media(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.dialog,
            title="Import a photo or video",
            filetypes=[
                ("Photos and video", "*.png *.jpg *.jpeg *.webp *.gif *.mp4 *.mov *.avi *.mkv"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        self._save_now()
        self._status.config(text="Rendering… Pause if the PC is busy.")
        self._render_job.start(
            path,
            on_status=lambda text: self.dialog.after(0, lambda t=text: self._status.config(text=t)),
            on_done=lambda text: self.dialog.after(0, lambda t=text: self._finish_render(t)),
        )

    def _finish_render(self, message: str) -> None:
        self.project = ensure_project(current_project())
        self._build_object_palette()
        self._redraw()
        self._status.config(text=message)

    def _pause_render(self) -> None:
        self._render_job.pause()
        self._status.config(text="Render paused.")

    def _play_render(self) -> None:
        self._render_job.play()
        self._status.config(text="Rendering…")

    def _clear_select(self) -> None:
        self.selected_id = ""
        self._wall_start = None
        self._room_start = None
        self._room_preview = None
        self._redraw()

    def _canvas_size(self) -> tuple[int, int]:
        return max(self.canvas.winfo_width(), 40), max(self.canvas.winfo_height(), 40)

    def _world_at(self, event) -> tuple[float, float] | None:
        width, height = self._canvas_size()
        if self.view_mode == "2d":
            x, z = screen_to_world(event.x, event.y, self.plan, width, height)
        else:
            hit = unproject_floor(event.x, event.y, self.camera, width, height)
            if hit is None:
                return None
            x, z = hit
        x, z = snap(x), snap(z)
        return snap_to_points(x, z, self._line_points())

    def _hit_object(self, event) -> str:
        world = self._world_at(event)
        floor = self._floor()
        if self.view_mode == "2d" and world is not None:
            wx, wz = world
            for wall in reversed(list(floor.get("walls") or []) + list(floor.get("runs") or [])):
                if hit_segment(wx, wz, float(wall["x1"]), float(wall["z1"]), float(wall["x2"]), float(wall["z2"])):
                    return str(wall.get("id") or "")
            for obj in reversed(list(floor.get("objects") or []) + list(floor.get("marks") or [])):
                item = get_item(str(obj.get("catalog_id") or ""))
                if item is None:
                    continue
                hw, hd = float(item["w"]) / 2.0, float(item["d"]) / 2.0
                if abs(float(obj["x"]) - wx) <= hw and abs(float(obj["z"]) - wz) <= hd:
                    return str(obj.get("id") or "")
            for room in reversed(list(floor.get("rooms") or [])):
                if point_in_room(wx, wz, room):
                    return str(room.get("id") or "")
            return ""
        width, height = self._canvas_size()
        best_id = ""
        best_z = 1e9
        for obj in list(floor.get("objects") or []) + list(floor.get("marks") or []):
            item = get_item(str(obj.get("catalog_id") or ""))
            if item is None:
                continue
            point = project((float(obj["x"]), item["h"] * 0.5, float(obj["z"])), self.camera, width, height)
            if point is None:
                continue
            px, py, depth = point
            radius = 22 if item["category"] == "marks" else 28
            if (px - event.x) ** 2 + (py - event.y) ** 2 <= radius * radius and depth < best_z:
                best_z = depth
                best_id = str(obj.get("id") or "")
        for wall in list(floor.get("walls") or []) + list(floor.get("runs") or []):
            mid = project(
                ((float(wall["x1"]) + float(wall["x2"])) / 2.0, 1.2, (float(wall["z1"]) + float(wall["z2"])) / 2.0),
                self.camera,
                width,
                height,
            )
            if mid is None:
                continue
            if (mid[0] - event.x) ** 2 + (mid[1] - event.y) ** 2 <= 26 * 26 and mid[2] < best_z:
                best_z = mid[2]
                best_id = str(wall.get("id") or "")
        return best_id

    def _on_press(self, event) -> None:
        self._press = (event.x, event.y)
        self._last = (event.x, event.y)
        self._endpoint = ""
        if self.tool == "eraser":
            hit = self._hit_object(event)
            if hit:
                delete_item(self.project, hit)
                self.selected_id = ""
                self._redraw()
                self._schedule_save()
                self._status.config(text="Deleted.")
            return
        if self.tool in {"line", "wall"} or self.tool in RUN_KINDS:
            start = self._world_at(event)
            if start is None:
                self._status.config(text="Click the floor to start a line.")
                return
            self._wall_start = start
            self._line_preview = None
            self._drag = "line"
            return
        if self.tool == "room":
            start = self._world_at(event)
            if start is None:
                self._status.config(text="Click the floor to start a room.")
                return
            self._room_start = start
            self._drag = "room"
            return
        hit = self._hit_object(event)
        world = self._world_at(event)
        if hit and world:
            found = find_item(self.project, hit)
            if found and found[0] == "walls" and self.tool == "select":
                wall = found[1]
                self._endpoint = endpoint_hit(world[0], world[1], wall["x1"], wall["z1"], wall["x2"], wall["z2"])
                self.selected_id = hit
                self._fill_line_editor()
                self._drag = "endpoint" if self._endpoint else "move"
                self._redraw()
                return
        if hit and self.tool in {"select", "orbit", "place", "mark"}:
            self.selected_id = hit
            self._fill_line_editor()
            self._drag = "move"
            self._redraw()
            return
        if self.tool == "orbit" and self.view_mode == "3d":
            self.selected_id = ""
            self._drag = "orbit"
            self._redraw()
            return
        if self.tool == "select" and self.view_mode == "2d":
            self.selected_id = ""
            self._drag = "pan"
            self._redraw()
            return
        self._drag = "click"

    def _on_drag(self, event) -> None:
        dx = event.x - self._last[0]
        dy = event.y - self._last[1]
        self._last = (event.x, event.y)
        if self._drag == "orbit":
            self.camera.yaw -= dx * 0.008
            self.camera.pitch += dy * 0.008
            clamp_camera(self.camera)
            self._redraw()
            return
        if self._drag == "pan":
            self._pan(dx, dy)
            return
        if self._drag == "line" and self._wall_start is not None:
            now = self._world_at(event)
            if now is None:
                return
            self._line_preview = (self._wall_start[0], self._wall_start[1], now[0], now[1])
            self._redraw()
            return
        if self._drag == "room" and self._room_start is not None:
            now = self._world_at(event)
            if now is None:
                return
            self._room_preview = (self._room_start[0], self._room_start[1], now[0], now[1])
            self._redraw()
            return
        if self._drag == "endpoint" and self.selected_id:
            now = self._world_at(event)
            if now is None:
                return
            found = find_item(self.project, self.selected_id)
            if found and found[0] == "walls":
                if self._endpoint == "a":
                    found[1]["x1"], found[1]["z1"] = now
                else:
                    found[1]["x2"], found[1]["z2"] = now
                self._fill_line_editor()
                self._redraw()
            return
        if self._drag == "move" and self.selected_id:
            hit = self._world_at(event)
            if hit is None:
                return
            move_item(self.project, self.selected_id, hit[0], hit[1])
            self._redraw()

    def _on_release(self, event) -> None:
        moved = abs(event.x - self._press[0]) + abs(event.y - self._press[1])
        drag = self._drag
        self._drag = ""
        if drag == "line":
            preview = self._line_preview
            self._wall_start = None
            self._line_preview = None
            if preview:
                if self.tool in RUN_KINDS:
                    run = add_run(self.project, self.tool, preview[0], preview[1], preview[2], preview[3])
                    if run:
                        self.selected_id = str(run["id"])
                        length = format_length(distance(preview[0], preview[1], preview[2], preview[3]))
                        self._status.config(text=f"{run['label']} {length}")
                        self._schedule_save()
                else:
                    wall = add_wall(self.project, preview[0], preview[1], preview[2], preview[3])
                    if wall:
                        self.selected_id = str(wall["id"])
                        self._fill_line_editor()
                        length = format_length(distance(preview[0], preview[1], preview[2], preview[3]))
                        rooms = self._floor().get("rooms") or []
                        extra = f" · {len(rooms)} room(s), {format_sq_ft(total_sq_ft(rooms))}" if rooms else ""
                        self._status.config(text=f"Line {length}{extra}")
                        self._schedule_save()
            elif moved <= 6:
                hit = self._hit_object(event)
                found = find_item(self.project, hit) if hit else None
                if found and found[0] == "walls":
                    self.selected_id = hit
                    self._fill_line_editor()
            self._redraw()
            return
        if drag == "endpoint":
            rebuild_rooms_from_lines(self._floor())
            self._fill_line_editor()
            self._schedule_save()
            self._redraw()
            return
        if drag == "room":
            preview = self._room_preview
            self._room_start = None
            self._room_preview = None
            if preview:
                room = add_room(self.project, preview[0], preview[1], preview[2], preview[3])
                if room:
                    self.selected_id = str(room["id"])
                    self._status.config(text=f"Drew {room['name']} · {format_sq_ft(room_area_sq_ft(room))}")
                    self._schedule_save()
            self._redraw()
            return
        if drag == "move":
            self._schedule_save()
            return
        if drag in {"orbit", "pan"} and moved > 6:
            self._schedule_save()
            return
        if self.tool in {"place", "mark"}:
            hit = self._world_at(event)
            if hit is None:
                return
            catalog_id = self.catalog_id
            item = get_item(catalog_id)
            if self.tool == "mark" and item and item["category"] != "marks":
                catalog_id = "mark"
            placed = add_object(self.project, catalog_id, hit[0], hit[1])
            if placed:
                self.selected_id = str(placed.get("id") or "")
                self._redraw()
                self._schedule_save()
            return
        if self.tool in {"wall", "line"} and moved <= 6:
            return

    def _pan(self, dx: float, dy: float) -> None:
        if self.view_mode == "2d":
            self.plan.pan_x -= dx / max(self.plan.ppm, 1.0)
            self.plan.pan_z -= dy / max(self.plan.ppm, 1.0)
        else:
            step = self.camera.distance * 0.004
            self.camera.tx -= (dx * math.cos(self.camera.yaw) + dy * math.sin(self.camera.yaw)) * step
            self.camera.tz -= (dy * math.cos(self.camera.yaw) - dx * math.sin(self.camera.yaw)) * step
        self._redraw()

    def _on_right_press(self, event) -> None:
        self._press = (event.x, event.y)
        self._last = (event.x, event.y)
        hit = self._hit_object(event)
        if hit:
            self.selected_id = hit
            self._fill_line_editor()
            self._drag = "menu"
            self._redraw()
            return
        self._drag = "pan"

    def _on_right_drag(self, event) -> None:
        if self._drag != "pan":
            return
        dx = event.x - self._last[0]
        dy = event.y - self._last[1]
        self._last = (event.x, event.y)
        self._pan(dx, dy)

    def _on_right_release(self, event) -> None:
        moved = abs(event.x - self._press[0]) + abs(event.y - self._press[1])
        drag = self._drag
        self._drag = ""
        if drag == "menu" or (moved <= 6 and self._hit_object(event)):
            if not self.selected_id:
                self.selected_id = self._hit_object(event)
            self._show_item_menu(event)
            return
        if drag == "pan" and moved > 6:
            self._schedule_save()

    def _show_item_menu(self, event) -> None:
        if not self.selected_id:
            return
        menu = tk.Menu(self.dialog, tearoff=0, font=self._small)
        menu.add_command(label="Delete", command=self._delete)
        menu.add_command(label="Rotate", command=lambda: self._rotate(15))
        # Extra rows can be added under these later.
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            try:
                menu.grab_release()
            except tk.TclError:
                pass

    def _on_wheel(self, event) -> None:
        width, height = self._canvas_size()
        if self.view_mode == "2d":
            factor = 1.12 if event.delta > 0 else 1 / 1.12
            zoom_at(self.plan, event.x, event.y, width, height, factor)
        else:
            delta = -1 if event.delta > 0 else 1
            self.camera.distance *= 1.0 + (0.08 * delta)
            clamp_camera(self.camera)
        self._redraw()

    def _box_corners(self, x: float, z: float, w: float, d: float, h: float, yaw: float, y0: float = 0.0) -> list[tuple[float, float, float]]:
        hw, hd = w / 2.0, d / 2.0
        c, s = math.cos(yaw), math.sin(yaw)
        pts: list[tuple[float, float, float]] = []
        for dx, dz in ((-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd)):
            rx = dx * c - dz * s
            rz = dx * s + dz * c
            pts.append((x + rx, y0, z + rz))
        for dx, dz in ((-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd)):
            rx = dx * c - dz * s
            rz = dx * s + dz * c
            pts.append((x + rx, y0 + h, z + rz))
        return pts

    def _draw_box(self, corners: list[tuple[float, float, float]], fill: str, outline: str, width: int, height: int) -> None:
        faces = (
            (0, 1, 2, 3),
            (4, 5, 6, 7),
            (0, 1, 5, 4),
            (1, 2, 6, 5),
            (2, 3, 7, 6),
            (3, 0, 4, 7),
        )
        drawn: list[tuple[float, tuple[float, ...], str]] = []
        for face in faces:
            pts3 = [corners[i] for i in face]
            pts2 = [project(p, self.camera, width, height) for p in pts3]
            if any(p is None for p in pts2):
                continue
            depth = sum(p[2] for p in pts2 if p is not None) / 4.0
            flat = tuple(coord for p in pts2 if p is not None for coord in (p[0], p[1]))
            drawn.append((depth, flat, fill))
        drawn.sort(key=lambda item: item[0], reverse=True)
        for _depth, flat, color in drawn:
            if len(flat) < 8:
                continue
            self.canvas.create_polygon(*flat, fill=color, outline=outline, width=1)

    def _redraw(self) -> None:
        if self._closed:
            return
        if self.view_mode == "2d":
            self._redraw_2d()
        else:
            self._redraw_3d()

    def _redraw_2d(self) -> None:
        self.canvas.delete("all")
        width, height = self._canvas_size()
        self.canvas.create_rectangle(0, 0, width, height, fill=PAPER_2D, outline="")
        step = 0.5
        span = max(width, height) / max(self.plan.ppm, 1.0) + 4
        x0 = math.floor((self.plan.pan_x - span) / step) * step
        z0 = math.floor((self.plan.pan_z - span) / step) * step
        x = x0
        while x <= self.plan.pan_x + span:
            a = world_to_screen(x, self.plan.pan_z - span, self.plan, width, height)
            b = world_to_screen(x, self.plan.pan_z + span, self.plan, width, height)
            major = abs(x) < 1e-6 or abs(x / 2.0 - round(x / 2.0)) < 1e-6
            self.canvas.create_line(a[0], a[1], b[0], b[1], fill=GRID_2D_MAJOR if major else GRID_2D)
            x += step
        z = z0
        while z <= self.plan.pan_z + span:
            a = world_to_screen(self.plan.pan_x - span, z, self.plan, width, height)
            b = world_to_screen(self.plan.pan_x + span, z, self.plan, width, height)
            major = abs(z) < 1e-6 or abs(z / 2.0 - round(z / 2.0)) < 1e-6
            self.canvas.create_line(a[0], a[1], b[0], b[1], fill=GRID_2D_MAJOR if major else GRID_2D)
            z += step

        self._draw_site_2d(width, height)
        floor = self._floor()
        for room in floor.get("rooms") or []:
            self._draw_room_2d(room, width, height)
        if self._room_preview:
            x1, z1, x2, z2 = self._room_preview
            a = world_to_screen(x1, z1, self.plan, width, height)
            b = world_to_screen(x2, z2, self.plan, width, height)
            self.canvas.create_rectangle(a[0], a[1], b[0], b[1], outline=SELECT, dash=(4, 3), width=2)

        for wall in floor.get("walls") or []:
            self._draw_line_2d(wall, width, height)
        for run in floor.get("runs") or []:
            self._draw_run_2d(run, width, height)
        if self._line_preview:
            payload = {
                "x1": self._line_preview[0],
                "z1": self._line_preview[1],
                "x2": self._line_preview[2],
                "z2": self._line_preview[3],
                "id": "",
                "kind": self.tool if self.tool in RUN_KINDS else "electrical",
            }
            if self.tool in RUN_KINDS:
                self._draw_run_2d(payload, width, height, preview=True)
            else:
                self._draw_line_2d(payload, width, height, preview=True)

        for obj in floor.get("objects") or []:
            self._draw_item_2d(obj, width, height)
        for mark in floor.get("marks") or []:
            self._draw_item_2d(mark, width, height, mark=True)

        area = total_sq_ft(floor.get("rooms") or [])
        self.canvas.create_text(14, height - 16, text=format_sq_ft(area), fill=MUTED, font=self._small, anchor="w")
        self._draw_empty_prompt(width, height)

    def _draw_site_2d(self, width: int, height: int) -> None:
        site = self.project.get("site") or {}
        if not site.get("enabled"):
            return
        fills = {"grass": "#8FBC8F", "dirt": "#C4A574", "gravel": "#B0B0A8", "rock": "#8A8A86"}
        ox = float(site.get("ox") or -6)
        oz = float(site.get("oz") or -6)
        w = float(site.get("width") or 24)
        d = float(site.get("depth") or 30)
        a = world_to_screen(ox, oz, self.plan, width, height)
        b = world_to_screen(ox + w, oz + d, self.plan, width, height)
        self.canvas.create_rectangle(a[0], a[1], b[0], b[1], fill=fills.get(str(site.get("ground") or "grass"), "#8FBC8F"), outline="#5D6D40", width=2)
        if site.get("contours"):
            spacing = 2.0 if site.get("terrain") == "flat" else 1.2
            x = ox + spacing
            while x < ox + w:
                p1 = world_to_screen(x, oz, self.plan, width, height)
                p2 = world_to_screen(x, oz + d, self.plan, width, height)
                self.canvas.create_line(p1[0], p1[1], p2[0], p2[1], fill="#6B8F6B", dash=(6, 4))
                x += spacing
        label = world_to_screen(ox + 0.4, oz + 0.4, self.plan, width, height)
        self.canvas.create_text(
            label[0],
            label[1],
            text=f"Site · {site.get('ground')} · {site.get('terrain')}",
            fill="#2E4A2E",
            font=self._small,
            anchor="nw",
        )

    def _draw_line_2d(self, wall: dict[str, Any], width: int, height: int, *, preview: bool = False) -> None:
        a = world_to_screen(float(wall["x1"]), float(wall["z1"]), self.plan, width, height)
        b = world_to_screen(float(wall["x2"]), float(wall["z2"]), self.plan, width, height)
        selected = wall.get("id") == self.selected_id
        color = SELECT if selected or preview else WALL_2D
        self.canvas.create_line(a[0], a[1], b[0], b[1], fill=color, width=7 if selected else 5, capstyle="round")
        self.canvas.create_oval(a[0] - 4, a[1] - 4, a[0] + 4, a[1] + 4, fill="#FFFFFF", outline=color)
        self.canvas.create_oval(b[0] - 4, b[1] - 4, b[0] + 4, b[1] + 4, fill="#FFFFFF", outline=color)
        mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
        label = format_length(distance(float(wall["x1"]), float(wall["z1"]), float(wall["x2"]), float(wall["z2"])))
        self.canvas.create_rectangle(mid[0] - 28, mid[1] - 18, mid[0] + 28, mid[1] - 4, fill="#FFFFFF", outline="#D0D5DA")
        self.canvas.create_text(mid[0], mid[1] - 11, text=label, fill=INK, font=self._small)

    def _draw_run_2d(self, run: dict[str, Any], width: int, height: int, *, preview: bool = False) -> None:
        style = RUN_KINDS.get(str(run.get("kind") or ""), {"color": "#B87333", "width": 4, "dash": ()})
        a = world_to_screen(float(run["x1"]), float(run["z1"]), self.plan, width, height)
        b = world_to_screen(float(run["x2"]), float(run["z2"]), self.plan, width, height)
        color = SELECT if run.get("id") == self.selected_id or preview else str(style.get("color") or "#B87333")
        dash = style.get("dash") or ()
        self.canvas.create_line(
            a[0],
            a[1],
            b[0],
            b[1],
            fill=color,
            width=int(style.get("width") or 4),
            dash=dash or None,
            capstyle="round",
        )
        label = str(run.get("label") or style.get("name") or "")
        if label:
            self.canvas.create_text((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 - 10, text=label, fill=INK, font=self._small)

    def _draw_room_2d(self, room: dict[str, Any], width: int, height: int) -> None:
        pts = room_points(room)
        selected = room.get("id") == self.selected_id
        if len(pts) >= 3:
            flat = []
            for px, pz in pts:
                flat.extend(world_to_screen(px, pz, self.plan, width, height))
            self.canvas.create_polygon(*flat, fill=str(room.get("floor_color") or WOOD), outline=SELECT if selected else WALL_2D, width=2)
            cx, cz = room_center(room)
            label_at = world_to_screen(cx, cz, self.plan, width, height)
        else:
            x, z, w, d = float(room.get("x") or 0), float(room.get("z") or 0), float(room.get("w") or 0), float(room.get("d") or 0)
            a = world_to_screen(x, z, self.plan, width, height)
            b = world_to_screen(x + w, z + d, self.plan, width, height)
            self.canvas.create_rectangle(a[0], a[1], b[0], b[1], fill=WOOD, outline=SELECT if selected else WALL_2D, width=2)
            label_at = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
        label = f"{room.get('name') or 'Room'} ({format_sq_ft(room_area_sq_ft(room))})"
        self.canvas.create_rectangle(label_at[0] - 78, label_at[1] - 10, label_at[0] + 78, label_at[1] + 10, fill="#3A3A3A", outline="")
        self.canvas.create_text(label_at[0], label_at[1], text=label, fill="#FFFFFF", font=self._small)

    def _dimension(self, x1: float, y1: float, x2: float, y2: float, text: str) -> None:
        self.canvas.create_line(x1, y1, x2, y2, fill="#7A8A99")
        mx, my = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        self.canvas.create_text(mx, my - 8 if abs(y2 - y1) < 2 else my, text=text, fill="#5D6D7E", font=self._small)

    def _draw_item_2d(self, obj: dict[str, Any], width: int, height: int, *, mark: bool = False) -> None:
        item = get_item(str(obj.get("catalog_id") or ("mark" if mark else "")))
        if item is None:
            return
        yaw = float(obj.get("yaw") or 0.0)
        hw, hd = float(item["w"]) / 2.0, float(item["d"]) / 2.0
        cx, cz = float(obj["x"]), float(obj["z"])
        c, s = math.cos(yaw), math.sin(yaw)
        pts = []
        for dx, dz in ((-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd)):
            rx = dx * c - dz * s
            rz = dx * s + dz * c
            pts.extend(world_to_screen(cx + rx, cz + rz, self.plan, width, height))
        selected = obj.get("id") == self.selected_id
        outline = SELECT if selected else "#1B2838"
        self.canvas.create_polygon(*pts, fill=str(item["color"]), outline=outline, width=3 if selected else 1)
        label_at = world_to_screen(cx, cz, self.plan, width, height)
        pixel_w = max(24, int(abs(item["w"]) * self.plan.ppm))
        pixel_h = max(24, int(abs(item["d"]) * self.plan.ppm))
        photo = self._placed_photo(item, yaw, pixel_w, pixel_h)
        if photo is None:
            photo = self._photo(str(item["id"]), str(item.get("image") or ""))
        if photo is not None:
            self.canvas.create_image(label_at[0], label_at[1], image=photo)
        if selected:
            pad = max(pixel_w, pixel_h) // 2 + 8
            self.canvas.create_rectangle(
                label_at[0] - pad,
                label_at[1] - pad,
                label_at[0] + pad,
                label_at[1] + pad,
                outline=SELECT,
                width=2,
                dash=(4, 2),
            )
        self.canvas.create_text(
            label_at[0],
            label_at[1] + max(18, pixel_h // 2 + 10),
            text=str(obj.get("label") or item["name"]),
            fill=INK,
            font=self._small,
        )

    def _redraw_3d(self) -> None:
        self.canvas.delete("all")
        width, height = self._canvas_size()
        self.canvas.create_rectangle(0, 0, width, height, fill=PAPER_3D, outline="")
        extent = 14
        for i in range(-extent, extent + 1):
            color = "#9BB4C6" if i % 4 == 0 else GRID_3D
            a = project((i, 0, -extent), self.camera, width, height)
            b = project((i, 0, extent), self.camera, width, height)
            if a and b:
                self.canvas.create_line(a[0], a[1], b[0], b[1], fill=color)
            a = project((-extent, 0, i), self.camera, width, height)
            b = project((extent, 0, i), self.camera, width, height)
            if a and b:
                self.canvas.create_line(a[0], a[1], b[0], b[1], fill=color)

        self._draw_site_3d(width, height)
        floor = self._floor()
        for room in floor.get("rooms") or []:
            self._draw_room_3d(room, width, height)
        for wall in floor.get("walls") or []:
            x1, z1, x2, z2 = float(wall["x1"]), float(wall["z1"]), float(wall["x2"]), float(wall["z2"])
            mx, mz = (x1 + x2) / 2.0, (z1 + z2) / 2.0
            length = math.hypot(x2 - x1, z2 - z1) or 0.2
            yaw = math.atan2(x2 - x1, z2 - z1)
            corners = self._box_corners(mx, mz, float(wall.get("thickness") or 0.15), length, float(wall.get("h") or 2.5), yaw)
            outline = SELECT if wall.get("id") == self.selected_id else WALL_3D
            self._draw_box(corners, WALL_3D, outline, width, height)
        self._draw_preview_3d(width, height)
        for run in floor.get("runs") or []:
            style = RUN_KINDS.get(str(run.get("kind") or ""), {"color": "#B87333"})
            a = project((float(run["x1"]), 0.05, float(run["z1"])), self.camera, width, height)
            b = project((float(run["x2"]), 0.05, float(run["z2"])), self.camera, width, height)
            if a and b:
                color = SELECT if run.get("id") == self.selected_id else str(style.get("color") or "#B87333")
                self.canvas.create_line(a[0], a[1], b[0], b[1], fill=color, width=4)
        for obj in floor.get("objects") or []:
            item = get_item(str(obj.get("catalog_id") or ""))
            if item is None:
                continue
            yaw = float(obj.get("yaw") or 0.0)
            corners = self._box_corners(float(obj["x"]), float(obj["z"]), float(item["w"]), float(item["d"]), float(item["h"]), yaw)
            selected = obj.get("id") == self.selected_id
            outline = SELECT if selected else "#1B2838"
            self._draw_box(corners, str(item["color"]), outline, width, height)
            top = project((float(obj["x"]), float(item["h"]), float(obj["z"])), self.camera, width, height)
            if top:
                ppm = max(12.0, 220.0 / max(self.camera.distance, 4.0))
                photo = self._placed_photo(item, yaw, max(28, int(item["w"] * ppm)), max(28, int(item["d"] * ppm)))
                if photo is not None:
                    self.canvas.create_image(top[0], top[1], image=photo)
                if selected:
                    self.canvas.create_oval(top[0] - 22, top[1] - 22, top[0] + 22, top[1] + 22, outline=SELECT, width=2, dash=(3, 2))
            label_pt = project((float(obj["x"]), float(item["h"]) + 0.15, float(obj["z"])), self.camera, width, height)
            if label_pt:
                self.canvas.create_text(label_pt[0], label_pt[1] - 8, text=item["name"], fill=INK, font=self._small)
        for mark in floor.get("marks") or []:
            item = get_item(str(mark.get("catalog_id") or "mark")) or get_item("mark")
            if item is None:
                continue
            corners = self._box_corners(float(mark["x"]), float(mark["z"]), 0.18, 0.18, float(item["h"]), 0.0)
            outline = SELECT if mark.get("id") == self.selected_id else "#7B241C"
            self._draw_box(corners, str(item["color"]), outline, width, height)

        area = total_sq_ft(floor.get("rooms") or [])
        self.canvas.create_text(14, 16, text=floor.get("name") or "First floor", fill=ACCENT, font=self._body, anchor="w")
        self.canvas.create_text(14, height - 16, text=format_sq_ft(area), fill=MUTED, font=self._small, anchor="w")
        self._draw_empty_prompt(width, height)

    def _draw_empty_prompt(self, width: int, height: int) -> None:
        floor = self._floor()
        if floor.get("walls") or floor.get("rooms") or self._line_preview or self._room_preview:
            return
        if self.tool not in {"line", "room", "wall"}:
            return
        message = (
            "Drag on the plan to draw a wall. Length shows in feet and inches."
            if self.tool != "room"
            else "Drag a rectangle to drop a whole room."
        )
        self.canvas.create_text(
            width / 2,
            height / 2,
            text=message,
            fill=MUTED,
            font=self._body,
            justify="center",
            width=max(240, width - 80),
        )

    def _draw_preview_3d(self, width: int, height: int) -> None:
        if self._line_preview:
            x1, z1, x2, z2 = self._line_preview
            a = project((x1, 0.04, z1), self.camera, width, height)
            b = project((x2, 0.04, z2), self.camera, width, height)
            if a and b:
                self.canvas.create_line(a[0], a[1], b[0], b[1], fill=SELECT, width=4)
                label = format_length(distance(x1, z1, x2, z2))
                self.canvas.create_text((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 - 12, text=label, fill=INK, font=self._small)
        if self._room_preview:
            x1, z1, x2, z2 = self._room_preview
            corners = ((x1, z1), (x2, z1), (x2, z2), (x1, z2), (x1, z1))
            pts = [project((x, 0.04, z), self.camera, width, height) for x, z in corners]
            if all(pts):
                flat = []
                for point in pts:
                    flat.extend((point[0], point[1]))
                self.canvas.create_line(*flat, fill=SELECT, dash=(4, 3), width=2)

    def _draw_site_3d(self, width: int, height: int) -> None:
        site = self.project.get("site") or {}
        if not site.get("enabled"):
            return
        fills = {"grass": "#8FBC8F", "dirt": "#C4A574", "gravel": "#B0B0A8", "rock": "#8A8A86"}
        ox = float(site.get("ox") or -6)
        oz = float(site.get("oz") or -6)
        w = float(site.get("width") or 24)
        d = float(site.get("depth") or 30)
        slope = {"flat": 0.0, "gentle": 0.6, "steep": 1.4}.get(str(site.get("terrain") or "flat"), 0.0)
        cx, cz = ox + w / 2.0, oz + d / 2.0
        corners = self._box_corners(cx, cz, w, d, max(0.08, slope * 0.2), 0.0, y0=-0.04)
        self._draw_box(corners, fills.get(str(site.get("ground") or "grass"), "#8FBC8F"), "#5D6D40", width, height)

    def _draw_room_3d(self, room: dict[str, Any], width: int, height: int) -> None:
        pts = room_points(room)
        if len(pts) >= 3:
            xs = [p[0] for p in pts]
            zs = [p[1] for p in pts]
            x, z = min(xs), min(zs)
            w, d = max(xs) - x, max(zs) - z
        else:
            x, z = float(room.get("x") or 0.0), float(room.get("z") or 0.0)
            w, d = float(room.get("w") or 1.0), float(room.get("d") or 1.0)
        cx, cz = x + w / 2.0, z + d / 2.0
        floor = self._box_corners(cx, cz, w, d, 0.04, 0.0)
        self._draw_box(floor, str(room.get("floor_color") or WOOD), WOOD_LINE, width, height)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._sync_views()
        try:
            save_project(self.project)
        except Exception:
            pass
        global _panel
        try:
            if self.dialog.winfo_exists():
                unregister(self.dialog)
                self.dialog.destroy()
        except tk.TclError:
            pass
        with _lock:
            if _panel is self:
                _panel = None


def close_planner_window() -> None:
    with _lock:
        panel = _panel
    if panel is None:
        return
    try:
        panel.close()
    except Exception:
        pass


def planner_is_open() -> bool:
    with _lock:
        panel = _panel
    if panel is None:
        return False
    try:
        return bool(panel.dialog.winfo_exists())
    except tk.TclError:
        return False


def apply_planner_speech(text: str) -> str:
    with _lock:
        panel = _panel
    if panel is None:
        return ""
    try:
        if not panel.dialog.winfo_exists():
            return ""
        return panel.apply_speech(text)
    except tk.TclError:
        return ""


def show_planner_window(
    user_id: str = "guest",
    view_mode: str | None = None,
    *,
    map_text: str | None = None,
    apply_text: str | None = None,
    open_map: bool = False,
) -> None:
    def _build(parent: tk.Misc) -> None:
        global _panel
        with _lock:
            if _panel is not None:
                try:
                    if _panel.dialog.winfo_exists():
                        _panel.user_id = user_id
                        _panel.dialog.deiconify()
                        _panel.dialog.lift()
                        _panel.dialog.focus_force()
                        if view_mode:
                            _panel.set_view_mode(view_mode)
                        if apply_text:
                            _panel.apply_speech(apply_text)
                        if open_map:
                            _panel._open_map(map_text or "")
                        return
                except tk.TclError:
                    pass
        try:
            panel = PlannerWindow(parent, user_id=user_id, view_mode=view_mode)
        except Exception as exc:
            log_error("Planner window failed", exc=exc)
            return
        with _lock:
            _panel = panel
        if apply_text:
            panel.apply_speech(apply_text)
        if open_map:
            panel._open_map(map_text or "")

    parent = _parent()
    if parent is not None:
        try:
            parent.after(0, lambda: _build(parent))
            return
        except Exception as exc:
            log_error("Planner schedule failed", exc=exc)

    def _run() -> None:
        root = tk.Tk()
        root.withdraw()
        register(root, persistent=True)
        _build(root)
        root.mainloop()

    threading.Thread(target=_run, name="silva-planner", daemon=True).start()
