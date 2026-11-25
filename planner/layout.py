"""Turn drawn lines into rooms, and turn a spoken/typed building request into a plan."""

from __future__ import annotations

import re
import uuid
from typing import Any

from silva.planner.geometry import (
    closed_polygons,
    parse_length,
    polygon_area_sq_ft,
    room_center,
    set_segment_angle,
    set_segment_length,
)

GROUND_OPTIONS = ("grass", "dirt", "gravel", "rock")
TERRAIN_OPTIONS = ("flat", "gentle", "steep")

DEFAULT_SITE = {
    "enabled": False,
    "width": 24.0,
    "depth": 30.0,
    "ox": -6.0,
    "oz": -6.0,
    "terrain": "flat",
    "ground": "grass",
    "contours": True,
}

_ROOM_WORDS = (
    ("bedroom", "Bedroom"),
    ("bath", "Bathroom"),
    ("kitchen", "Kitchen"),
    ("living", "Living room"),
    ("lounge", "Living room"),
    ("garage", "Garage"),
    ("laundry", "Laundry"),
    ("office", "Office"),
    ("dining", "Dining"),
    ("closet", "Closet"),
    ("hallway", "Hall"),
    ("hall", "Hall"),
    ("porch", "Porch"),
    ("utility", "Utility"),
)


def rebuild_rooms_from_lines(floor: dict[str, Any]) -> list[dict[str, Any]]:
    """Replace auto rooms with closed shapes formed by wall lines. Keep named rect rooms."""
    walls = list(floor.get("walls") or [])
    polygons = closed_polygons(walls)
    kept: list[dict[str, Any]] = []
    for room in floor.get("rooms") or []:
        if room.get("locked") or (room.get("w") and not room.get("from_lines")):
            kept.append(room)
    used_names = {str(room.get("name") or "") for room in kept}
    index = 1
    for points in polygons:
        area = polygon_area_sq_ft(points)
        name = f"Room {index}"
        while name in used_names:
            index += 1
            name = f"Room {index}"
        used_names.add(name)
        xs = [p[0] for p in points]
        zs = [p[1] for p in points]
        kept.append(
            {
                "id": uuid.uuid4().hex[:8],
                "name": name,
                "points": [[p[0], p[1]] for p in points],
                "x": min(xs),
                "z": min(zs),
                "w": max(xs) - min(xs),
                "d": max(zs) - min(zs),
                "area_sq_ft": round(area, 3),
                "floor_color": "#C8A36A",
                "from_lines": True,
            }
        )
        index += 1
    floor["rooms"] = kept
    return kept


def update_wall_geometry(
    wall: dict[str, Any],
    *,
    length_m: float | None = None,
    angle_deg: float | None = None,
    x1: float | None = None,
    z1: float | None = None,
    x2: float | None = None,
    z2: float | None = None,
) -> dict[str, Any]:
    ax, az, bx, bz = float(wall["x1"]), float(wall["z1"]), float(wall["x2"]), float(wall["z2"])
    if x1 is not None:
        ax = float(x1)
    if z1 is not None:
        az = float(z1)
    if x2 is not None:
        bx = float(x2)
    if z2 is not None:
        bz = float(z2)
    if angle_deg is not None:
        ax, az, bx, bz = set_segment_angle(ax, az, bx, bz, angle_deg)
    if length_m is not None:
        ax, az, bx, bz = set_segment_length(ax, az, bx, bz, length_m)
    wall["x1"], wall["z1"], wall["x2"], wall["z2"] = ax, az, bx, bz
    return wall


_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}


def _count(text: str, word: str) -> int:
    match = re.search(rf"(?:(\d+)|({'|'.join(_NUMBER_WORDS)}))\s+{word}", text)
    if match:
        if match.group(1):
            return int(match.group(1))
        return _NUMBER_WORDS[match.group(2)]
    if re.search(rf"\b{word}s?\b", text):
        return 1
    return 0


def parse_building_request(text: str) -> dict[str, Any]:
    raw = (text or "").strip().lower()
    floors = 1
    floor_match = re.search(r"(\d+)\s*(story|stories|floor|floors)", raw)
    if floor_match:
        floors = max(1, min(4, int(floor_match.group(1))))
    elif re.search(r"\b(two|2)[ -]?stor(?:y|ies)\b", raw) or "two floor" in raw:
        floors = 2
    rooms: list[str] = []
    bedrooms = _count(raw, "bedroom")
    if bedrooms == 0 and "house" in raw:
        bedrooms = 2
    bathrooms = _count(raw, "bathroom") or _count(raw, "bath")
    if bathrooms == 0 and bedrooms:
        bathrooms = 1
    for _ in range(bedrooms):
        rooms.append("Bedroom")
    for _ in range(bathrooms):
        rooms.append("Bathroom")
    for key, label in _ROOM_WORDS:
        if key in {"bedroom", "bath"}:
            continue
        if re.search(rf"\b{key}", raw):
            rooms.append(label)
    if "kitchen" not in raw and ("house" in raw or "home" in raw or bedrooms):
        rooms.append("Kitchen")
    if "living" not in raw and ("house" in raw or "home" in raw or bedrooms >= 2):
        rooms.append("Living room")
    if not rooms:
        rooms = ["Room 1", "Room 2"]
    width = parse_length(raw) if re.search(r"\bby\b|\bft\b|\bfeet\b", raw) else None
    return {"floors": floors, "rooms": rooms, "width": width, "raw": raw}


def generate_building(project: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    """Lay out connected rooms as lines + closed shapes on one or more floors."""
    names: list[str] = list(spec.get("rooms") or ["Room"])
    floors_n = max(1, int(spec.get("floors") or 1))
    width = float(spec.get("width") or 3.66)  # ~12 ft default room
    depth = 3.05  # ~10 ft
    while len(project.setdefault("floors", [])) < floors_n:
        from silva.planner.store import add_floor

        add_floor(project, f"Floor {len(project['floors']) + 1}")
    per_floor = max(1, (len(names) + floors_n - 1) // floors_n)
    idx = 0
    for floor_i in range(floors_n):
        project["active_floor"] = floor_i
        floor = project["floors"][floor_i]
        floor["walls"] = []
        floor["rooms"] = []
        chunk = names[idx : idx + per_floor] or [f"Room {floor_i + 1}"]
        idx += per_floor
        cols = 2 if len(chunk) > 1 else 1
        expected: list[tuple[str, float, float]] = []
        for i, name in enumerate(chunk):
            col, row = i % cols, i // cols
            x = col * width
            z = row * depth
            _box_walls(floor, x, z, width, depth)
            expected.append((name, x + width / 2.0, z + depth / 2.0))
        rebuild_rooms_from_lines(floor)
        leftover = list(expected)
        for room in floor.get("rooms") or []:
            if not leftover:
                break
            cx, cz = room_center(room)
            best_i = min(range(len(leftover)), key=lambda i: (leftover[i][1] - cx) ** 2 + (leftover[i][2] - cz) ** 2)
            room["name"] = leftover.pop(best_i)[0]
    project["active_floor"] = 0
    project["name"] = "Mapped building"
    return project


def _box_walls(floor: dict[str, Any], x: float, z: float, w: float, d: float) -> None:
    from silva.planner.store import add_wall_raw

    corners = [(x, z), (x + w, z), (x + w, z + d), (x, z + d)]
    for i, (ax, az) in enumerate(corners):
        bx, bz = corners[(i + 1) % 4]
        add_wall_raw(floor, ax, az, bx, bz)


def apply_instruction(project: dict[str, Any], text: str, *, selected_id: str = "") -> str:
    """Change the current plan from voice/typed text. Returns a short spoken result."""
    raw = (text or "").strip().lower()
    from silva.planner.store import active_floor, add_floor, add_room, find_item

    if re.search(r"\b(map|draw|build|layout|lay out|make me)\b", raw) and re.search(
        r"\b(house|home|building|cabin|shop|garage|room|bedroom|floor plan)\b", raw
    ):
        spec = parse_building_request(text)
        generate_building(project, spec)
        return f"I mapped {len(spec['rooms'])} rooms across {spec['floors']} floor{'s' if spec['floors'] != 1 else ''}."

    site = project.setdefault("site", dict(DEFAULT_SITE))
    ground = next((name for name in GROUND_OPTIONS if re.search(rf"\b{name}\b", raw)), None)
    terrain = next((name for name in TERRAIN_OPTIONS if re.search(rf"\b{name}\b", raw)), None)
    site_talk = bool(
        re.search(
            r"\b((the |a )?(lot|land)|geological|topograph\w*|terrain|ground|site layout|add a site|show the lot)\b",
            raw,
        )
    )
    if site_talk:
        site["enabled"] = True
        if ground:
            site["ground"] = ground
        if terrain:
            site["terrain"] = terrain
        if "no contour" in raw or "without contour" in raw:
            site["contours"] = False
        elif "contour" in raw:
            site["contours"] = True
        return "I turned on the site layout around the building."

    floor = active_floor(project)
    if "new floor" in raw or "another floor" in raw or "add a floor" in raw:
        add_floor(project)
        return "I added another floor."

    length = parse_length(text)
    if selected_id and length is not None and re.search(r"\b(wall|line|make|set|length|long|feet|ft|inch)\b", raw):
        found = find_item(project, selected_id)
        if found and found[0] == "walls":
            update_wall_geometry(found[1], length_m=length)
            rebuild_rooms_from_lines(floor)
            from silva.planner.geometry import format_length

            return f"I set that line to {format_length(length)}."

    angle = re.search(r"(\d+)\s*(degree|deg|°)", raw)
    if selected_id and angle and re.search(r"\b(angle|rotate|turn|slant)\b", raw):
        found = find_item(project, selected_id)
        if found and found[0] == "walls":
            update_wall_geometry(found[1], angle_deg=float(angle.group(1)))
            rebuild_rooms_from_lines(floor)
            return f"I set that line to {angle.group(1)} degrees."

    add_match = re.search(
        r"\badd (?:a |an |another )?(bedroom|bathroom|bath|kitchen|garage|office|living room|dining|laundry|closet|room)\b",
        raw,
    )
    if add_match:
        label = add_match.group(1).strip().title()
        if label == "Bath":
            label = "Bathroom"
        rooms = floor.get("rooms") or []
        x = max((float(r.get("x") or 0) + float(r.get("w") or 0) for r in rooms), default=0.0)
        add_room(project, x, 0.0, x + 3.66, 3.05)
        room = (floor.get("rooms") or [])[-1] if (floor.get("rooms") or []) else None
        if room is not None:
            room["name"] = label or room.get("name")
            return f"I added a {room['name']}."
        return f"I added a {label}."

    if selected_id and re.search(r"\b(upgrade|thicker|brick|stronger)\b", raw):
        found = find_item(project, selected_id)
        if found and found[0] == "walls":
            found[1]["thickness"] = min(0.4, float(found[1].get("thickness") or 0.15) + 0.05)
            found[1]["finish"] = "brick"
            return "I upgraded that wall."
        from silva.planner.store import upgrade_item

        if upgrade_item(project, selected_id):
            return "I upgraded that item."
        return "Select a wall or object first, then ask me to upgrade it."

    return ""
