"""Orbit camera and floor picking for the 3D planner canvas."""

from __future__ import annotations

import math
from dataclasses import dataclass

FOV = math.radians(50.0)
NEAR = 0.2


@dataclass
class Camera:
    yaw: float = 0.7
    pitch: float = 0.58
    distance: float = 16.0
    tx: float = 0.0
    tz: float = 0.0


def clamp_camera(cam: Camera) -> None:
    cam.pitch = max(0.14, min(1.32, float(cam.pitch)))
    cam.distance = max(4.0, min(90.0, float(cam.distance)))


def _sub(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _scale(a: tuple[float, float, float], s: float) -> tuple[float, float, float]:
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _norm(a: tuple[float, float, float]) -> tuple[float, float, float]:
    length = math.sqrt(_dot(a, a)) or 1.0
    return _scale(a, 1.0 / length)


def eye_point(cam: Camera) -> tuple[float, float, float]:
    cp = math.cos(cam.pitch)
    return (
        cam.tx + math.sin(cam.yaw) * cp * cam.distance,
        math.sin(cam.pitch) * cam.distance,
        cam.tz + math.cos(cam.yaw) * cp * cam.distance,
    )


def camera_basis(cam: Camera) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
    eye = eye_point(cam)
    target = (cam.tx, 0.0, cam.tz)
    forward = _norm(_sub(target, eye))
    world_up = (0.0, 1.0, 0.0)
    right = _norm(_cross(forward, world_up))
    if abs(right[0]) + abs(right[1]) + abs(right[2]) < 1e-6:
        right = (1.0, 0.0, 0.0)
    up = _norm(_cross(right, forward))
    return eye, forward, right, up


def project(
    point: tuple[float, float, float],
    cam: Camera,
    width: int,
    height: int,
) -> tuple[float, float, float] | None:
    eye, forward, right, up = camera_basis(cam)
    rel = _sub(point, eye)
    x = _dot(rel, right)
    y = _dot(rel, up)
    z = _dot(rel, forward)
    if z < NEAR:
        return None
    aspect = max(width, 1) / max(height, 1)
    tan_fov = math.tan(FOV / 2.0)
    px = (x / (z * tan_fov * aspect) + 1.0) * 0.5 * width
    py = (1.0 - y / (z * tan_fov)) * 0.5 * height
    return (px, py, z)


def unproject_floor(
    mx: float,
    my: float,
    cam: Camera,
    width: int,
    height: int,
) -> tuple[float, float] | None:
    eye, forward, right, up = camera_basis(cam)
    aspect = max(width, 1) / max(height, 1)
    tan_fov = math.tan(FOV / 2.0)
    ndc_x = (mx / max(width, 1)) * 2.0 - 1.0
    ndc_y = 1.0 - (my / max(height, 1)) * 2.0
    direction = _norm(
        _add(
            _add(forward, _scale(right, ndc_x * tan_fov * aspect)),
            _scale(up, ndc_y * tan_fov),
        )
    )
    if abs(direction[1]) < 1e-6:
        return None
    t = -eye[1] / direction[1]
    if t < 0:
        return None
    hit = _add(eye, _scale(direction, t))
    return (hit[0], hit[2])


def snap(value: float, step: float = 0.25) -> float:
    if step <= 0:
        return value
    return round(value / step) * step
