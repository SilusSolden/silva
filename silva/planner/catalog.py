"""Furniture, fixtures, utilities, and custom objects for the planner."""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from silva.config import CONFIG_DIR

# Sizes are meters. tool=draw a run; upgrades_to swaps a placed item.
ITEMS: tuple[dict[str, Any], ...] = (
    {"id": "sofa", "name": "Sofa", "category": "furniture", "w": 2.2, "d": 0.9, "h": 0.8, "color": "#5D6D7E", "upgrades_to": "sectional"},
    {"id": "sectional", "name": "Sectional sofa", "category": "furniture", "w": 2.8, "d": 1.6, "h": 0.85, "color": "#4A6274"},
    {"id": "chair", "name": "Chair", "category": "furniture", "w": 0.55, "d": 0.55, "h": 0.9, "color": "#7B5E57", "upgrades_to": "armchair"},
    {"id": "armchair", "name": "Armchair", "category": "furniture", "w": 0.85, "d": 0.85, "h": 0.9, "color": "#6D4C41"},
    {"id": "table", "name": "Table", "category": "furniture", "w": 1.4, "d": 0.8, "h": 0.75, "color": "#A1887F", "upgrades_to": "dining_table"},
    {"id": "dining_table", "name": "Dining table", "category": "furniture", "w": 1.8, "d": 0.95, "h": 0.75, "color": "#8D6E63"},
    {"id": "coffee_table", "name": "Coffee table", "category": "furniture", "w": 1.1, "d": 0.6, "h": 0.45, "color": "#A1887F"},
    {"id": "ottoman", "name": "Ottoman", "category": "furniture", "w": 0.7, "d": 0.7, "h": 0.45, "color": "#8D6E63"},
    {"id": "bed", "name": "Bed", "category": "furniture", "w": 1.6, "d": 2.1, "h": 0.7, "color": "#5C6BC0", "upgrades_to": "king_bed"},
    {"id": "king_bed", "name": "King bed", "category": "furniture", "w": 2.0, "d": 2.2, "h": 0.75, "color": "#3F51B5"},
    {"id": "crib", "name": "Crib", "category": "furniture", "w": 1.4, "d": 0.75, "h": 0.9, "color": "#9FA8DA"},
    {"id": "desk", "name": "Desk", "category": "furniture", "w": 1.4, "d": 0.7, "h": 0.75, "color": "#795548"},
    {"id": "office_chair", "name": "Office chair", "category": "furniture", "w": 0.65, "d": 0.65, "h": 1.1, "color": "#6D4C41"},
    {"id": "nightstand", "name": "Nightstand", "category": "furniture", "w": 0.5, "d": 0.4, "h": 0.55, "color": "#8D6E63"},
    {"id": "dresser", "name": "Dresser", "category": "furniture", "w": 1.4, "d": 0.5, "h": 1.1, "color": "#6D4C41"},
    {"id": "wardrobe", "name": "Wardrobe", "category": "furniture", "w": 1.2, "d": 0.6, "h": 2.1, "color": "#5D4037"},
    {"id": "bookshelf", "name": "Bookshelf", "category": "furniture", "w": 0.9, "d": 0.35, "h": 1.8, "color": "#6D4C41"},
    {"id": "tv_stand", "name": "TV stand", "category": "furniture", "w": 1.6, "d": 0.4, "h": 0.5, "color": "#455A64"},
    {"id": "bench", "name": "Bench", "category": "furniture", "w": 1.2, "d": 0.4, "h": 0.45, "color": "#8D6E63"},
    {"id": "rug", "name": "Rug", "category": "furniture", "w": 2.0, "d": 1.4, "h": 0.04, "color": "#BCAAA4"},
    {"id": "lamp", "name": "Lamp", "category": "furniture", "w": 0.35, "d": 0.35, "h": 1.5, "color": "#FFE082"},
    {"id": "fridge", "name": "Fridge", "category": "appliances", "w": 0.7, "d": 0.7, "h": 1.8, "color": "#90A4AE", "upgrades_to": "french_fridge"},
    {"id": "french_fridge", "name": "French-door fridge", "category": "appliances", "w": 0.9, "d": 0.75, "h": 1.8, "color": "#78909C"},
    {"id": "stove", "name": "Stove", "category": "appliances", "w": 0.76, "d": 0.7, "h": 0.95, "color": "#546E7A", "upgrades_to": "range"},
    {"id": "range", "name": "Range", "category": "appliances", "w": 0.9, "d": 0.75, "h": 0.95, "color": "#37474F"},
    {"id": "range_hood", "name": "Range hood", "category": "appliances", "w": 0.9, "d": 0.5, "h": 0.4, "color": "#90A4AE"},
    {"id": "dishwasher", "name": "Dishwasher", "category": "appliances", "w": 0.6, "d": 0.65, "h": 0.85, "color": "#607D8B"},
    {"id": "washer", "name": "Washer", "category": "appliances", "w": 0.7, "d": 0.7, "h": 0.95, "color": "#78909C"},
    {"id": "dryer", "name": "Dryer", "category": "appliances", "w": 0.7, "d": 0.7, "h": 0.95, "color": "#90A4AE"},
    {"id": "microwave", "name": "Microwave", "category": "appliances", "w": 0.55, "d": 0.4, "h": 0.35, "color": "#455A64"},
    {"id": "sink", "name": "Sink", "category": "appliances", "w": 0.8, "d": 0.55, "h": 0.9, "color": "#B0BEC5"},
    {"id": "cabinet", "name": "Cabinet", "category": "appliances", "w": 1.2, "d": 0.6, "h": 0.9, "color": "#B0BEC5"},
    {"id": "toilet", "name": "Toilet", "category": "fixtures", "w": 0.4, "d": 0.7, "h": 0.8, "color": "#ECEFF1"},
    {"id": "shower", "name": "Shower", "category": "fixtures", "w": 0.9, "d": 0.9, "h": 2.0, "color": "#B3E5FC"},
    {"id": "bathtub", "name": "Bathtub", "category": "fixtures", "w": 1.7, "d": 0.8, "h": 0.55, "color": "#E1F5FE"},
    {"id": "vanity", "name": "Vanity", "category": "fixtures", "w": 1.2, "d": 0.55, "h": 0.85, "color": "#D7CCC8"},
    {"id": "counter", "name": "Counter", "category": "fixtures", "w": 2.0, "d": 0.6, "h": 0.9, "color": "#D7CCC8"},
    {"id": "island", "name": "Kitchen island", "category": "fixtures", "w": 1.8, "d": 0.9, "h": 0.9, "color": "#BCAAA4"},
    {"id": "door", "name": "Door", "category": "fixtures", "w": 0.9, "d": 0.12, "h": 2.1, "color": "#A1887F"},
    {"id": "window", "name": "Window", "category": "fixtures", "w": 1.2, "d": 0.12, "h": 1.2, "color": "#81D4FA"},
    {"id": "stairs", "name": "Stairs", "category": "fixtures", "w": 1.0, "d": 2.4, "h": 2.5, "color": "#8D6E63"},
    {"id": "fireplace", "name": "Fireplace", "category": "fixtures", "w": 1.6, "d": 0.6, "h": 1.4, "color": "#5D4037"},
    {"id": "outlet", "name": "Outlet", "category": "electrical", "w": 0.18, "d": 0.12, "h": 0.18, "color": "#F1C40F"},
    {"id": "switch", "name": "Switch", "category": "electrical", "w": 0.12, "d": 0.08, "h": 0.12, "color": "#F9A825"},
    {"id": "light", "name": "Ceiling light", "category": "electrical", "w": 0.4, "d": 0.4, "h": 0.12, "color": "#FFF59D"},
    {"id": "ceiling_fan", "name": "Ceiling fan", "category": "electrical", "w": 1.2, "d": 1.2, "h": 0.35, "color": "#90A4AE"},
    {"id": "panel", "name": "Breaker panel", "category": "electrical", "w": 0.4, "d": 0.15, "h": 0.7, "color": "#455A64"},
    {"id": "copper_wire", "name": "Copper wire", "category": "electrical", "w": 0.2, "d": 0.2, "h": 0.05, "color": "#B87333", "tool": "electrical"},
    {"id": "water_heater", "name": "Water heater", "category": "plumbing", "w": 0.55, "d": 0.55, "h": 1.5, "color": "#90A4AE"},
    {"id": "hose_bib", "name": "Hose bib", "category": "plumbing", "w": 0.15, "d": 0.12, "h": 0.2, "color": "#1976D2"},
    {"id": "water_line", "name": "Water line", "category": "plumbing", "w": 0.2, "d": 0.2, "h": 0.05, "color": "#1976D2", "tool": "water"},
    {"id": "drain_line", "name": "Drain line", "category": "plumbing", "w": 0.2, "d": 0.2, "h": 0.05, "color": "#5D4037", "tool": "drain"},
    {"id": "gas_line", "name": "Gas line", "category": "plumbing", "w": 0.2, "d": 0.2, "h": 0.05, "color": "#F9A825", "tool": "gas"},
    {"id": "vent", "name": "Air vent", "category": "hvac", "w": 0.5, "d": 0.3, "h": 0.08, "color": "#BCAAA4"},
    {"id": "thermostat", "name": "Thermostat", "category": "hvac", "w": 0.12, "d": 0.08, "h": 0.12, "color": "#FFCC80"},
    {"id": "car", "name": "Car", "category": "outdoor", "w": 4.4, "d": 1.8, "h": 1.5, "color": "#546E7A"},
    {"id": "tree", "name": "Tree", "category": "outdoor", "w": 1.5, "d": 1.5, "h": 3.0, "color": "#2E7D32"},
    {"id": "fence", "name": "Fence", "category": "outdoor", "w": 2.0, "d": 0.12, "h": 1.2, "color": "#6D4C41"},
    {"id": "deck", "name": "Deck", "category": "outdoor", "w": 3.0, "d": 3.0, "h": 0.3, "color": "#A1887F"},
    {"id": "mark", "name": "Mark", "category": "marks", "w": 0.25, "d": 0.25, "h": 1.2, "color": "#C0392B"},
    {"id": "electrical", "name": "Electrical mark", "category": "marks", "w": 0.25, "d": 0.25, "h": 0.9, "color": "#F1C40F"},
    {"id": "plumbing", "name": "Plumbing mark", "category": "marks", "w": 0.25, "d": 0.25, "h": 0.9, "color": "#2980B9"},
    {"id": "note_pin", "name": "Note pin", "category": "marks", "w": 0.25, "d": 0.25, "h": 1.1, "color": "#8E44AD"},
)

CATEGORIES: tuple[tuple[str, str], ...] = (
    ("furniture", "Furniture"),
    ("appliances", "Appliances"),
    ("fixtures", "Fixtures"),
    ("electrical", "Electrical"),
    ("plumbing", "Plumbing"),
    ("hvac", "HVAC"),
    ("outdoor", "Outdoor"),
    ("marks", "Marks"),
    ("custom", "Custom"),
)

RUN_KINDS: dict[str, dict[str, Any]] = {
    "electrical": {"name": "Copper wire", "color": "#B87333", "width": 4, "dash": ()},
    "water": {"name": "Water line", "color": "#1976D2", "width": 4, "dash": ()},
    "gas": {"name": "Gas line", "color": "#F9A825", "width": 4, "dash": (6, 3)},
    "drain": {"name": "Drain line", "color": "#5D4037", "width": 4, "dash": (4, 2)},
}

CUSTOM_DIR = CONFIG_DIR / "planner" / "custom"
CUSTOM_FILE = CUSTOM_DIR / "items.json"


def _builtin() -> dict[str, dict[str, Any]]:
    return {item["id"]: dict(item) for item in ITEMS}


def _read_custom() -> list[dict[str, Any]]:
    if not CUSTOM_FILE.exists():
        return []
    try:
        data = json.loads(CUSTOM_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    items: list[dict[str, Any]] = []
    for raw in data:
        if isinstance(raw, dict) and raw.get("id") and raw.get("name"):
            item = dict(raw)
            item.setdefault("category", "custom")
            item.setdefault("w", 1.0)
            item.setdefault("d", 1.0)
            item.setdefault("h", 1.0)
            item.setdefault("color", "#FFB74D")
            items.append(item)
    return items


def all_items() -> list[dict[str, Any]]:
    merged = _builtin()
    for item in _read_custom():
        merged[str(item["id"])] = item
    return list(merged.values())


def get_item(catalog_id: str) -> dict[str, Any] | None:
    key = str(catalog_id or "").strip()
    found = _builtin().get(key)
    if found:
        return found
    for item in _read_custom():
        if item["id"] == key:
            return item
    return None


def items_in(category: str) -> list[dict[str, Any]]:
    return [item for item in all_items() if item.get("category") == category]


def next_upgrade(catalog_id: str) -> dict[str, Any] | None:
    item = get_item(catalog_id)
    if not item:
        return None
    nxt = item.get("upgrades_to")
    if not nxt:
        return None
    return get_item(str(nxt))


def add_custom_item(
    *,
    name: str,
    image_path: str = "",
    width: float = 1.0,
    depth: float = 1.0,
    height: float = 1.0,
) -> dict[str, Any]:
    CUSTOM_DIR.mkdir(parents=True, exist_ok=True)
    item_id = f"custom_{uuid.uuid4().hex[:8]}"
    stored = ""
    source = Path(image_path) if image_path else None
    if source is not None and source.is_file():
        dest = CUSTOM_DIR / f"{item_id}.png"
        try:
            if source.suffix.lower() in {".png", ".gif"}:
                shutil.copyfile(source, dest)
            else:
                from PIL import Image

                Image.open(source).convert("RGBA").save(dest)
            stored = str(dest)
        except OSError:
            stored = str(source)
    item = {
        "id": item_id,
        "name": (name or "Custom object").strip() or "Custom object",
        "category": "custom",
        "w": max(0.1, float(width)),
        "d": max(0.1, float(depth)),
        "h": max(0.05, float(height)),
        "color": "#FFB74D",
        "image": stored,
    }
    items = _read_custom()
    items.append(item)
    CUSTOM_FILE.write_text(json.dumps(items, indent=2), encoding="utf-8")
    return item
