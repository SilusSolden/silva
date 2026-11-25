"""Turn a photo or video into planner walls and objects, with pause/play."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

from silva.logger import log_error, log_info
from silva.planner.catalog import add_custom_item
from silva.planner.store import add_object, add_wall, current_project

IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
VIDEO_TYPES = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".gif"}


class MediaRenderJob:
    def __init__(self) -> None:
        self._pause = threading.Event()
        self._stop = threading.Event()
        self.busy = False
        self.status = "Idle"

    def pause(self) -> None:
        self._pause.set()
        self.status = "Paused"

    def play(self) -> None:
        self._pause.clear()
        self.status = "Rendering"

    def cancel(self) -> None:
        self._stop.set()
        self._pause.clear()

    def is_paused(self) -> bool:
        return self._pause.is_set()

    def _wait_if_paused(self) -> bool:
        while self._pause.is_set() and not self._stop.is_set():
            time.sleep(0.08)
        return not self._stop.is_set()

    def start(
        self,
        path: str,
        *,
        on_status: Callable[[str], None] | None = None,
        on_done: Callable[[str], None] | None = None,
    ) -> None:
        if self.busy:
            if on_status:
                on_status("Already rendering. Pause or wait.")
            return
        self.busy = True
        self._stop.clear()
        self._pause.clear()
        self.status = "Rendering"

        def worker() -> None:
            try:
                message = self._render(Path(path), on_status)
            except Exception as exc:
                log_error("Planner media render failed", exc=exc)
                message = "I could not render that file."
            self.busy = False
            self.status = "Idle"
            if on_done:
                on_done(message)

        threading.Thread(target=worker, name="silva-planner-render", daemon=True).start()

    def _render(self, path: Path, on_status: Callable[[str], None] | None) -> str:
        if not path.is_file():
            return "That file is gone."
        suffix = path.suffix.lower()
        if suffix in IMAGE_TYPES and suffix != ".gif":
            return self._render_image(path, on_status)
        if suffix in VIDEO_TYPES:
            return self._render_video(path, on_status)
        return "Use a photo (png, jpg) or a video (mp4, gif)."

    def _render_image(self, path: Path, on_status: Callable[[str], None] | None) -> str:
        if on_status:
            on_status("Reading photo…")
        if not self._wait_if_paused():
            return "Stopped rendering."
        item = add_custom_item(name=path.stem.replace("_", " ").title(), image_path=str(path), width=1.6, depth=1.2, height=0.9)
        project = current_project()
        add_object(project, item["id"], 0.0, 0.0)
        walls = _trace_walls(path)
        if on_status:
            on_status("Tracing walls…")
        for x1, z1, x2, z2 in walls:
            if not self._wait_if_paused():
                return "Stopped rendering."
            add_wall(project, x1, z1, x2, z2)
        from silva.planner.store import save_project

        save_project(project)
        extra = f" and {len(walls)} wall(s)" if walls else ""
        log_info(f"Planner imported photo {path.name}{extra}")
        return f"Rendered {item['name']} as a 3D object{extra}."

    def _render_video(self, path: Path, on_status: Callable[[str], None] | None) -> str:
        frames = list(_video_frames(path, limit=24))
        if not frames:
            return "I could not read frames from that video."
        placed = 0
        for index, frame_path in enumerate(frames):
            if not self._wait_if_paused():
                return f"Paused after {placed} frame(s). Press Play to continue later, or import again."
            if on_status:
                on_status(f"Rendering frame {index + 1} of {len(frames)}…")
            item = add_custom_item(
                name=f"{path.stem} frame {index + 1}",
                image_path=str(frame_path),
                width=1.4,
                depth=1.0,
                height=0.8,
            )
            project = current_project()
            add_object(project, item["id"], (index % 5) * 1.5, (index // 5) * 1.5)
            placed += 1
            time.sleep(0.05)
        from silva.planner.store import save_project

        save_project(current_project())
        return f"Rendered {placed} 3D object(s) from the video."


def _trace_walls(path: Path) -> list[tuple[float, float, float, float]]:
    try:
        import cv2
    except Exception:
        return []
    image = cv2.imread(str(path))
    if image is None:
        return []
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, 80, 160)
    lines = cv2.HoughLinesP(edges, 1, 3.14159 / 180.0, threshold=80, minLineLength=40, maxLineGap=12)
    if lines is None:
        return []
    h, w = gray.shape[:2]
    scale = 8.0 / max(w, h)
    walls: list[tuple[float, float, float, float]] = []
    for row in lines[:18]:
        x1, y1, x2, y2 = (int(v) for v in row[0])
        walls.append((x1 * scale - 4.0, y1 * scale - 4.0, x2 * scale - 4.0, y2 * scale - 4.0))
    return walls


def _video_frames(path: Path, *, limit: int = 24) -> list[Path]:
    suffix = path.suffix.lower()
    out_dir = path.parent / f".silva_frames_{path.stem}"
    out_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    if suffix == ".gif":
        from PIL import Image

        image = Image.open(path)
        n = getattr(image, "n_frames", 1)
        step = max(1, n // limit)
        for index in range(0, n, step):
            image.seek(index)
            dest = out_dir / f"frame_{len(saved):03d}.png"
            image.convert("RGBA").save(dest)
            saved.append(dest)
            if len(saved) >= limit:
                break
        return saved
    try:
        import cv2
    except Exception:
        return saved
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        return saved
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    step = max(1, total // limit) if total else 8
    index = 0
    kept = 0
    while kept < limit:
        ok, frame = capture.read()
        if not ok:
            break
        if index % step == 0:
            dest = out_dir / f"frame_{kept:03d}.png"
            cv2.imwrite(str(dest), frame)
            saved.append(dest)
            kept += 1
        index += 1
    capture.release()
    return saved
