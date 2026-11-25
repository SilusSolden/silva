"""Save 3D planner projects next to Silva's other files on the main drive."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from silva.config import CONFIG_DIR
from silva.planner.catalog import get_item, next_upgrade

PLANNER_DIR = CONFIG_DIR / "planner"
PROJECTS_DIR = PLANNER_DIR / "projects"
CURRENT_FILE = PLANNER_DIR / "current.txt"


def configure_paths(root: Path) -> None:
    global PLANNER_DIR, PROJECTS_DIR, CURRENT_FILE
    PLANNER_DIR = Path(root)
    PROJECTS_DIR = PLANNER_DIR / "projects"
    CURRENT_FILE = PLANNER_DIR / "current.txt"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _ensure() -> None:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)


def new_project(name: str = "Building project") -> dict[str, Any]:
    return {
        "id": uuid.uuid4().hex[:10],
        "name": (name or "Building project").strip() or "Building project",
        "updated_at": _now(),
        "view_mode": "2d",
        "camera": {"yaw": 0.7, "pitch": 0.58, "distance": 16.0, "tx": 0.0, "tz": 0.0},
        "plan": {"pan_x": 0.0, "pan_z": 0.0, "ppm": 48.0},
        "site": {
            "enabled": False,
            "width": 24.0,
            "depth": 30.0,
            "ox": -6.0,
            "oz": -6.0,
            "terrain": "flat",
            "ground": "grass",
            "contours": True,
        },
        "floors": [_empty_floor("First floor")],
        "active_floor": 0,
    }


def _empty_floor(name: str) -> dict[str, Any]:
    return {
        "id": uuid.uuid4().hex[:8],
        "name": name,
        "rooms": [],
        "walls": [],
        "objects": [],
        "marks": [],
        "runs": [],
    }


def ensure_project(project: dict[str, Any]) -> dict[str, Any]:
    project.setdefault("view_mode", "2d")
    project.setdefault("camera", {"yaw": 0.7, "pitch": 0.58, "distance": 16.0, "tx": 0.0, "tz": 0.0})
    project.setdefault("plan", {"pan_x": 0.0, "pan_z": 0.0, "ppm": 48.0})
    project.setdefault(
        "site",
        {
            "enabled": False,
            "width": 24.0,
            "depth": 30.0,
            "ox": -6.0,
            "oz": -6.0,
            "terrain": "flat",
            "ground": "grass",
            "contours": True,
        },
    )
    floors = project.setdefault("floors", [_empty_floor("First floor")])
    for floor in floors:
        floor.setdefault("rooms", [])
        floor.setdefault("walls", [])
        floor.setdefault("objects", [])
        floor.setdefault("marks", [])
        floor.setdefault("runs", [])
        floor.setdefault("name", "Floor")
    return project


def current_project() -> dict[str, Any]:
    _ensure()
    path = current_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("floors"):
                return ensure_project(data)
        except (OSError, json.JSONDecodeError):
            pass
    project = new_project()
    save_project(project)
    return project


def current_path() -> Path:
    _ensure()
    if CURRENT_FILE.exists():
        try:
            name = CURRENT_FILE.read_text(encoding="utf-8").strip()
            if name:
                candidate = PROJECTS_DIR / name
                if candidate.exists():
                    return candidate
        except OSError:
            pass
    return PROJECTS_DIR / "current.json"


def save_project(project: dict[str, Any]) -> Path:
    _ensure()
    project = dict(project)
    project["updated_at"] = _now()
    pid = str(project.get("id") or uuid.uuid4().hex[:10])
    project["id"] = pid
    path = PROJECTS_DIR / f"{pid}.json"
    path.write_text(json.dumps(project, indent=2), encoding="utf-8")
    CURRENT_FILE.write_text(path.name, encoding="utf-8")
    latest = PROJECTS_DIR / "current.json"
    if latest != path:
        latest.write_text(json.dumps(project, indent=2), encoding="utf-8")
    return path


def list_projects() -> list[dict[str, str]]:
    _ensure()
    found: list[dict[str, str]] = []
    for path in sorted(PROJECTS_DIR.glob("*.json")):
        if path.name == "current.json":
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        found.append(
            {
                "id": str(data.get("id") or path.stem),
                "name": str(data.get("name") or "Project"),
                "updated_at": str(data.get("updated_at") or ""),
                "file": path.name,
            }
        )
    return found


def active_floor(project: dict[str, Any]) -> dict[str, Any]:
    ensure_project(project)
    floors = project.setdefault("floors", [_empty_floor("First floor")])
    index = int(project.get("active_floor") or 0)
    index = max(0, min(index, len(floors) - 1))
    project["active_floor"] = index
    return floors[index]


def add_floor(project: dict[str, Any], name: str = "") -> dict[str, Any]:
    floors = project.setdefault("floors", [])
    label = name.strip() or f"Floor {len(floors) + 1}"
    floor = _empty_floor(label)
    floors.append(floor)
    project["active_floor"] = len(floors) - 1
    return floor


def add_room(project: dict[str, Any], x1: float, z1: float, x2: float, z2: float) -> dict[str, Any] | None:
    from silva.planner.geometry import normalize_rect

    x, z, width, depth = normalize_rect(x1, z1, x2, z2)
    if width < 0.75 or depth < 0.75:
        return None
    floor = active_floor(project)
    add_wall_raw(floor, x, z, x + width, z)
    add_wall_raw(floor, x + width, z, x + width, z + depth)
    add_wall_raw(floor, x + width, z + depth, x, z + depth)
    add_wall_raw(floor, x, z + depth, x, z)
    from silva.planner.layout import rebuild_rooms_from_lines

    rebuild_rooms_from_lines(floor)
    rooms = floor.get("rooms") or []
    return rooms[-1] if rooms else None


def add_object(project: dict[str, Any], catalog_id: str, x: float, z: float) -> dict[str, Any] | None:
    item = get_item(catalog_id)
    if item is None:
        return None
    floor = active_floor(project)
    obj = {
        "id": uuid.uuid4().hex[:8],
        "catalog_id": item["id"],
        "x": float(x),
        "z": float(z),
        "yaw": 0.0,
    }
    if item["category"] == "marks":
        mark = {
            "id": obj["id"],
            "catalog_id": item["id"],
            "x": float(x),
            "z": float(z),
            "label": item["name"],
        }
        floor.setdefault("marks", []).append(mark)
        return mark
    floor.setdefault("objects", []).append(obj)
    return obj


def add_wall_raw(floor: dict[str, Any], x1: float, z1: float, x2: float, z2: float) -> dict[str, Any]:
    def _ends(ax: float, az: float, bx: float, bz: float) -> tuple:
        return tuple(sorted(((round(ax, 3), round(az, 3)), (round(bx, 3), round(bz, 3)))))

    ends = _ends(x1, z1, x2, z2)
    for existing in floor.get("walls") or []:
        if _ends(float(existing["x1"]), float(existing["z1"]), float(existing["x2"]), float(existing["z2"])) == ends:
            return existing
    wall = {
        "id": uuid.uuid4().hex[:8],
        "x1": float(x1),
        "z1": float(z1),
        "x2": float(x2),
        "z2": float(z2),
        "h": 2.5,
        "thickness": 0.15,
    }
    floor.setdefault("walls", []).append(wall)
    return wall


def add_run(project: dict[str, Any], kind: str, x1: float, z1: float, x2: float, z2: float) -> dict[str, Any] | None:
    from silva.planner.catalog import RUN_KINDS
    from silva.planner.geometry import distance

    style = RUN_KINDS.get(str(kind or "").strip())
    if style is None or distance(x1, z1, x2, z2) < 0.12:
        return None
    floor = active_floor(project)
    run = {
        "id": uuid.uuid4().hex[:8],
        "kind": str(kind),
        "x1": float(x1),
        "z1": float(z1),
        "x2": float(x2),
        "z2": float(z2),
        "label": style["name"],
    }
    floor.setdefault("runs", []).append(run)
    return run


def add_wall(project: dict[str, Any], x1: float, z1: float, x2: float, z2: float) -> dict[str, Any] | None:
    from silva.planner.geometry import distance
    from silva.planner.layout import rebuild_rooms_from_lines

    if distance(x1, z1, x2, z2) < 0.2:
        return None
    floor = active_floor(project)
    wall = add_wall_raw(floor, x1, z1, x2, z2)
    rebuild_rooms_from_lines(floor)
    return wall


def find_item(project: dict[str, Any], item_id: str) -> tuple[str, dict[str, Any]] | None:
    floor = active_floor(project)
    for kind in ("objects", "marks", "walls", "rooms", "runs"):
        for item in floor.get(kind, []):
            if item.get("id") == item_id:
                return kind, item
    return None


def move_item(project: dict[str, Any], item_id: str, x: float, z: float) -> bool:
    found = find_item(project, item_id)
    if found is None:
        return False
    kind, item = found
    if kind in {"walls", "runs"}:
        dx = x - (item["x1"] + item["x2"]) / 2.0
        dz = z - (item["z1"] + item["z2"]) / 2.0
        item["x1"] += dx
        item["x2"] += dx
        item["z1"] += dz
        item["z2"] += dz
        return True
    if kind == "rooms":
        item["x"] = float(x) - float(item.get("w") or 0.0) / 2.0
        item["z"] = float(z) - float(item.get("d") or 0.0) / 2.0
        return True
    item["x"] = float(x)
    item["z"] = float(z)
    return True


def rotate_item(project: dict[str, Any], item_id: str, degrees: float = 90.0) -> bool:
    found = find_item(project, item_id)
    if found is None:
        return False
    kind, item = found
    if kind not in {"objects", "marks"}:
        return False
    item["yaw"] = float(item.get("yaw") or 0.0) + math_radians(degrees)
    return True


def math_radians(degrees: float) -> float:
    import math

    return math.radians(degrees)


def clear_floor(project: dict[str, Any]) -> None:
    floor = active_floor(project)
    floor["walls"] = []
    floor["rooms"] = []
    floor["objects"] = []
    floor["marks"] = []
    floor["runs"] = []


def delete_item(project: dict[str, Any], item_id: str) -> bool:
    floor = active_floor(project)
    for kind in ("objects", "marks", "walls", "rooms", "runs"):
        items = floor.get(kind, [])
        kept = [item for item in items if item.get("id") != item_id]
        if len(kept) != len(items):
            floor[kind] = kept
            if kind == "walls":
                from silva.planner.layout import rebuild_rooms_from_lines

                rebuild_rooms_from_lines(floor)
            return True
    return False


def upgrade_item(project: dict[str, Any], item_id: str) -> dict[str, Any] | None:
    found = find_item(project, item_id)
    if found is None:
        return None
    kind, item = found
    if kind not in {"objects", "marks"}:
        return None
    nxt = next_upgrade(str(item.get("catalog_id") or ""))
    if nxt is None:
        return None
    item["catalog_id"] = nxt["id"]
    if kind == "marks":
        item["label"] = nxt["name"]
    return item
