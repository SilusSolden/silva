"""Spoken ways to open Silva's 3D building planner."""

from __future__ import annotations

import re

from silva.commands.help_phrases import should_yield_to_feature_help

_PUNCT_RE = re.compile(r"[^\w\s]")
_SPACE_RE = re.compile(r"\s+")

_WAKE_PREFIXES = (
    "hey silva ",
    "ok silva ",
    "okay silva ",
    "yo silva ",
    "silva ",
    "please ",
    "can you ",
    "could you ",
    "would you ",
)

_EXACT = frozenset(
    {
        "open the planner",
        "open planner",
        "open the 3d planner",
        "open 3d planner",
        "open the 3d graph",
        "open 3d graph",
        "open the floor plan",
        "open floor plan",
        "open the blueprint",
        "open blueprint",
        "open the building planner",
        "open building planner",
        "show the planner",
        "show the 3d planner",
        "show the floor plan",
        "show the 3d graph",
        "start the planner",
        "launch the planner",
        "open my floor plan",
        "open my planner",
        "switch to 3d",
        "switch to 2d",
        "show 3d",
        "show 2d",
        "3d view",
        "2d view",
        "open 2d planner",
        "open the 2d planner",
        "open 2d floor plan",
        "map me a building",
        "map a building",
        "map the building",
        "draw me a house",
        "draw a floor plan",
        "layout a house",
        "lay out a house",
        "add a site",
        "show the lot",
        "add the geological layout",
        "add topographic layout",
        "draw a line",
        "draw line",
        "draw walls",
        "draw a wall",
        "start drawing",
        "let me draw",
        "draw on the plan",
        "draw a room",
        "draw room",
        "close the planner",
        "close planner",
        "close the 3d planner",
        "close the 2d planner",
        "close the floor plan",
        "close the blueprint",
        "exit the planner",
        "hide the planner",
        "close that planner",
    }
)

_MAP_RE = re.compile(
    r"\b("
    r"map (me )?(a |an |the |this )?.{0,40}?\b(building|house|home|cabin|shop|floor plan)|"
    r"draw (me )?(a |an |the )?.{0,40}?\b(house|building|floor plan)|"
    r"lay(?:out| out) (a |an |the )?.{0,40}?\b(house|building)|"
    r"make me (a |an )?.{0,40}?\b(house|building|floor plan)"
    r")\b",
    re.I,
)

_OPEN_RE = re.compile(
    r"\b(open|show|start|launch)\b.{0,28}\b("
    r"3d planner|3d graph|floor plan|building planner|building project|"
    r"blueprint(?: planner)?|planner"
    r")\b",
    re.I,
)


def _fold(text: str) -> str:
    normalized = (text or "").strip().lower().replace("'", "")
    normalized = _PUNCT_RE.sub(" ", normalized)
    normalized = _SPACE_RE.sub(" ", normalized).strip()
    changed = True
    while changed and normalized:
        changed = False
        for prefix in _WAKE_PREFIXES:
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix) :].strip()
                changed = True
                break
    return normalized


def match_planner_draw_tool(text: str) -> str | None:
    normalized = _fold(text)
    if normalized in {
        "draw a line",
        "draw line",
        "draw walls",
        "draw a wall",
        "start drawing",
        "let me draw",
        "draw on the plan",
    }:
        return "line"
    if normalized in {"draw a room", "draw room"}:
        return "room"
    return None


def is_planner_close_ask(text: str) -> bool:
    normalized = _fold(text)
    return normalized in {
        "close the planner",
        "close planner",
        "close the 3d planner",
        "close the 2d planner",
        "close the floor plan",
        "close the blueprint",
        "exit the planner",
        "hide the planner",
        "close that planner",
    }


def is_planner_command(text: str) -> bool:
    if should_yield_to_feature_help(text):
        return False
    normalized = _fold(text)
    if not normalized:
        return False
    if is_planner_close_ask(text):
        return True
    if normalized in _EXACT:
        return True
    if match_planner_draw_tool(text):
        return True
    if match_planner_view(text):
        return True
    if is_planner_map_ask(text):
        return True
    return bool(_OPEN_RE.search(normalized))


def is_planner_map_ask(text: str) -> bool:
    normalized = _fold(text)
    if not normalized:
        return False
    if normalized in {"map me a building", "map a building", "draw me a house", "draw a floor plan"}:
        return True
    return bool(_MAP_RE.search(normalized))


def is_planner_site_ask(text: str) -> bool:
    normalized = _fold(text)
    if not normalized:
        return False
    if normalized in {
        "add a site",
        "show the lot",
        "add the geological layout",
        "add topographic layout",
    }:
        return True
    return bool(re.search(r"\b(geological|topograph\w*|site layout|show the lot)\b", normalized))


def match_planner_view(text: str) -> str | None:
    normalized = _fold(text)
    if not normalized:
        return None
    has_2d = bool(re.search(r"\b2d\b", normalized))
    has_3d = bool(re.search(r"\b3d\b", normalized))
    if has_2d == has_3d:
        return None
    contextual = any(
        token in normalized
        for token in (
            "planner",
            "floor plan",
            "graph",
            "view",
            "switch",
            "show",
            "open",
            "mode",
            "blueprint",
        )
    )
    if not contextual:
        return None
    return "2d" if has_2d else "3d"
