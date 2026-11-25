"""2D floor-plan mapping and US length labels for the Silva planner."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

SNAP_M = 0.12


@dataclass
class PlanView:
    pan_x: float = 0.0
    pan_z: float = 0.0
    ppm: float = 48.0


def clamp_plan(view: PlanView) -> None:
    view.ppm = max(14.0, min(140.0, float(view.ppm)))


def world_to_screen(x: float, z: float, view: PlanView, width: int, height: int) -> tuple[float, float]:
    sx = width / 2.0 + (x - view.pan_x) * view.ppm
    sy = height / 2.0 + (z - view.pan_z) * view.ppm
    return sx, sy


def screen_to_world(sx: float, sy: float, view: PlanView, width: int, height: int) -> tuple[float, float]:
    x = view.pan_x + (sx - width / 2.0) / max(view.ppm, 1.0)
    z = view.pan_z + (sy - height / 2.0) / max(view.ppm, 1.0)
    return x, z


def format_length(meters: float) -> str:
    inches = abs(float(meters)) * 39.37007874
    feet = int(inches // 12)
    inch = int(round(inches - feet * 12))
    if inch == 12:
        feet += 1
        inch = 0
    if inch == 0:
        return f"{feet}'"
    return f"{feet}' {inch}\""


def meters_to_sq_ft(area_m2: float) -> float:
    return abs(float(area_m2)) * 10.7639104167


def sq_ft(width_m: float, depth_m: float) -> float:
    return meters_to_sq_ft(float(width_m) * float(depth_m))


def parse_length(text: str) -> float | None:
    """Parse '12 feet', '12 ft 6 in', 12'6\", or meters into meters."""
    raw = (text or "").strip().lower().replace("foot", "ft").replace("feet", "ft")
    raw = raw.replace("inches", "in").replace("inch", "in")
    raw = raw.replace("″", '"').replace("′", "'")
    if not raw:
        return None
    feet_inch = re.search(r"(\d+)\s*'\s*(\d+)?\s*\"?", raw)
    if feet_inch and "'" in raw:
        feet = int(feet_inch.group(1))
        inch = int(feet_inch.group(2) or 0)
        return (feet * 12 + inch) * 0.0254
    ft = re.search(r"(\d+(?:\.\d+)?)\s*ft", raw)
    inch = re.search(r"(\d+(?:\.\d+)?)\s*in", raw)
    if ft or inch:
        total_in = 0.0
        if ft:
            total_in += float(ft.group(1)) * 12.0
        if inch:
            total_in += float(inch.group(1))
        return total_in * 0.0254
    meters = re.search(r"(\d+(?:\.\d+)?)\s*m\b", raw)
    if meters:
        return float(meters.group(1))
    try:
        value = float(re.sub(r"[^\d.]+", "", raw))
    except ValueError:
        return None
    if value <= 0:
        return None
    # Bare numbers in this planner are feet.
    return value * 0.3048


def distance(x1: float, z1: float, x2: float, z2: float) -> float:
    return math.hypot(x2 - x1, z2 - z1)


def snap_point(x: float, z: float, step: float = 0.25) -> tuple[float, float]:
    if step <= 0:
        return x, z
    return round(x / step) * step, round(z / step) * step


def snap_to_points(x: float, z: float, points: list[tuple[float, float]], radius: float = SNAP_M) -> tuple[float, float]:
    best = None
    best_d = radius
    for px, pz in points:
        d = distance(x, z, px, pz)
        if d <= best_d:
            best_d = d
            best = (px, pz)
    return best if best is not None else (x, z)


def polygon_area_m2(points: list[tuple[float, float]]) -> float:
    if len(points) < 3:
        return 0.0
    total = 0.0
    for i, (x1, z1) in enumerate(points):
        x2, z2 = points[(i + 1) % len(points)]
        total += x1 * z2 - x2 * z1
    return abs(total) * 0.5


def polygon_area_sq_ft(points: list[tuple[float, float]]) -> float:
    return meters_to_sq_ft(polygon_area_m2(points))


def polygon_centroid(points: list[tuple[float, float]]) -> tuple[float, float]:
    if not points:
        return 0.0, 0.0
    return (
        sum(p[0] for p in points) / len(points),
        sum(p[1] for p in points) / len(points),
    )


def point_in_polygon(x: float, z: float, points: list[tuple[float, float]]) -> bool:
    inside = False
    j = len(points) - 1
    for i, (xi, zi) in enumerate(points):
        xj, zj = points[j]
        if (zi > z) != (zj > z) and x < (xj - xi) * (z - zi) / ((zj - zi) or 1e-9) + xi:
            inside = not inside
        j = i
    return inside


def hit_segment(x: float, z: float, x1: float, z1: float, x2: float, z2: float, slop: float = 0.18) -> bool:
    length = distance(x1, z1, x2, z2) or 1e-9
    t = max(0.0, min(1.0, ((x - x1) * (x2 - x1) + (z - z1) * (z2 - z1)) / (length * length)))
    px = x1 + t * (x2 - x1)
    pz = z1 + t * (z2 - z1)
    return distance(x, z, px, pz) <= slop


def endpoint_hit(x: float, z: float, x1: float, z1: float, x2: float, z2: float, slop: float = 0.2) -> str:
    if distance(x, z, x1, z1) <= slop:
        return "a"
    if distance(x, z, x2, z2) <= slop:
        return "b"
    return ""


def set_segment_length(x1: float, z1: float, x2: float, z2: float, meters: float, *, from_start: bool = True) -> tuple[float, float, float, float]:
    meters = max(0.2, float(meters))
    dx, dz = x2 - x1, z2 - z1
    length = math.hypot(dx, dz) or 1e-9
    scale = meters / length
    if from_start:
        return x1, z1, x1 + dx * scale, z1 + dz * scale
    return x2 - dx * scale, z2 - dz * scale, x2, z2


def set_segment_angle(x1: float, z1: float, x2: float, z2: float, degrees: float) -> tuple[float, float, float, float]:
    length = distance(x1, z1, x2, z2) or 1.0
    rad = math.radians(float(degrees))
    return x1, z1, x1 + math.sin(rad) * length, z1 + math.cos(rad) * length


def _point_on_segment(
    px: float, pz: float, x1: float, z1: float, x2: float, z2: float, slop: float = SNAP_M
) -> bool:
    if distance(px, pz, x1, z1) <= slop or distance(px, pz, x2, z2) <= slop:
        return False
    return hit_segment(px, pz, x1, z1, x2, z2, slop=slop)


def split_walls_at_junctions(walls: list[dict], *, snap: float = SNAP_M) -> list[dict]:
    """Break walls where another line T-junctions into the middle of them."""
    points: list[tuple[float, float]] = []
    for wall in walls:
        points.append((float(wall["x1"]), float(wall["z1"])))
        points.append((float(wall["x2"]), float(wall["z2"])))
    unique: list[tuple[float, float]] = []
    for px, pz in points:
        if not any(distance(px, pz, ux, uz) <= snap for ux, uz in unique):
            unique.append((px, pz))
    split: list[dict] = []
    for wall in walls:
        a = (float(wall["x1"]), float(wall["z1"]))
        b = (float(wall["x2"]), float(wall["z2"]))
        hits = [a, b]
        for point in unique:
            if _point_on_segment(point[0], point[1], a[0], a[1], b[0], b[1], slop=snap):
                hits.append(point)
        hits.sort(key=lambda p: distance(a[0], a[1], p[0], p[1]))
        for i in range(len(hits) - 1):
            if distance(hits[i][0], hits[i][1], hits[i + 1][0], hits[i + 1][1]) < snap * 0.4:
                continue
            piece = dict(wall)
            piece["x1"], piece["z1"] = hits[i]
            piece["x2"], piece["z2"] = hits[i + 1]
            split.append(piece)
    return split or list(walls)


def closed_polygons(walls: list[dict], *, snap: float = SNAP_M) -> list[list[tuple[float, float]]]:
    """Find interior rooms from line segments that meet end to end."""
    def key(x: float, z: float) -> tuple[float, float]:
        return (round(float(x) / snap) * snap, round(float(z) / snap) * snap)

    node_pos: dict[tuple[float, float], tuple[float, float]] = {}
    nodes: dict[tuple[float, float], set[tuple[float, float]]] = {}
    for wall in split_walls_at_junctions(walls, snap=snap):
        a_raw = (float(wall["x1"]), float(wall["z1"]))
        b_raw = (float(wall["x2"]), float(wall["z2"]))
        a, b = key(*a_raw), key(*b_raw)
        if a == b:
            continue
        node_pos.setdefault(a, a_raw)
        node_pos.setdefault(b, b_raw)
        nodes.setdefault(a, set()).add(b)
        nodes.setdefault(b, set()).add(a)

    seen: set[tuple[tuple[float, float], tuple[float, float]]] = set()
    faces: list[list[tuple[float, float]]] = []

    def next_ccw(curr: tuple[float, float], prev: tuple[float, float]) -> tuple[float, float] | None:
        incoming = math.atan2(prev[1] - curr[1], prev[0] - curr[0])
        options: list[tuple[float, tuple[float, float]]] = []
        for nxt in nodes.get(curr, ()):
            if nxt == prev:
                continue
            rel = (math.atan2(nxt[1] - curr[1], nxt[0] - curr[0]) - incoming) % (math.pi * 2.0)
            if rel < 1e-6:
                continue
            options.append((rel, nxt))
        if not options:
            return None
        options.sort()
        return options[0][1]

    for start, neighbors in list(nodes.items()):
        for first in neighbors:
            edge = (start, first)
            if edge in seen:
                continue
            path = [start]
            prev, curr = start, first
            guard = 0
            while guard < 80:
                guard += 1
                seen.add((prev, curr))
                path.append(curr)
                nxt = next_ccw(curr, prev)
                if nxt is None:
                    break
                prev, curr = curr, nxt
                if curr == start:
                    if len(path) >= 4:
                        faces.append(path[:-1] if path[-1] == path[0] else path)
                    break

    scored: list[tuple[float, list[tuple[float, float]]]] = []
    seen_keys: set[tuple] = set()
    for face in faces:
        if len(face) < 3:
            continue
        pts = [node_pos.get(p, p) for p in face]
        area = polygon_area_m2(pts)
        if area < 0.4:
            continue
        key_pts = tuple(sorted((round(p[0], 3), round(p[1], 3)) for p in pts))
        if key_pts in seen_keys:
            continue
        seen_keys.add(key_pts)
        scored.append((area, pts))
    scored.sort(key=lambda item: item[0], reverse=True)
    if len(scored) <= 1:
        return [face for _, face in scored]
    # Drop the largest loop (the outer boundary) when inner rooms exist.
    return [face for _, face in scored[1:]]


def format_sq_ft(area: float) -> str:
    return f"{area:,.3f} sq ft"


def normalize_rect(x1: float, z1: float, x2: float, z2: float) -> tuple[float, float, float, float]:
    xa, xb = (x1, x2) if x1 <= x2 else (x2, x1)
    za, zb = (z1, z2) if z1 <= z2 else (z2, z1)
    return xa, za, xb - xa, zb - za


def room_center(room: dict) -> tuple[float, float]:
    pts = room_points(room)
    if pts:
        return polygon_centroid(pts)
    return (
        float(room.get("x") or 0.0) + float(room.get("w") or 0.0) / 2.0,
        float(room.get("z") or 0.0) + float(room.get("d") or 0.0) / 2.0,
    )


def room_points(room: dict) -> list[tuple[float, float]]:
    raw = room.get("points")
    if isinstance(raw, list) and len(raw) >= 3:
        pts = []
        for item in raw:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                pts.append((float(item[0]), float(item[1])))
        return pts
    x = float(room.get("x") or 0.0)
    z = float(room.get("z") or 0.0)
    w = float(room.get("w") or 0.0)
    d = float(room.get("d") or 0.0)
    if w <= 0 or d <= 0:
        return []
    return [(x, z), (x + w, z), (x + w, z + d), (x, z + d)]


def room_area_sq_ft(room: dict) -> float:
    pts = room_points(room)
    if pts:
        return polygon_area_sq_ft(pts)
    return sq_ft(float(room.get("w") or 0.0), float(room.get("d") or 0.0))


def total_sq_ft(rooms: list[dict]) -> float:
    return sum(room_area_sq_ft(room) for room in rooms)


def point_in_room(x: float, z: float, room: dict) -> bool:
    pts = room_points(room)
    if len(pts) >= 3:
        return point_in_polygon(x, z, pts)
    rx = float(room.get("x") or 0.0)
    rz = float(room.get("z") or 0.0)
    rw = float(room.get("w") or 0.0)
    rd = float(room.get("d") or 0.0)
    return rx <= x <= rx + rw and rz <= z <= rz + rd


def zoom_at(view: PlanView, sx: float, sy: float, width: int, height: int, factor: float) -> None:
    world_x, world_z = screen_to_world(sx, sy, view, width, height)
    view.ppm *= factor
    clamp_plan(view)
    new_x, new_z = screen_to_world(sx, sy, view, width, height)
    view.pan_x += world_x - new_x
    view.pan_z += world_z - new_z
