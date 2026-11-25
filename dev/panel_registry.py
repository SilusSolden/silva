"""Extensible registry for Silva System Panel tabs and tools."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from silva.gui.dev_panel import DevPanelApp

TabBuilder = Callable[["DevPanelApp", object], None]


@dataclass(frozen=True)
class PanelTabSpec:
    id: str
    title: str
    order: int
    builder: TabBuilder


_BUILTIN_TABS: list[PanelTabSpec] = []


def register_panel_tab(*, tab_id: str, title: str, order: int, builder: TabBuilder) -> None:
    """Register an extra panel tab for future Silva features."""
    global _BUILTIN_TABS
    _BUILTIN_TABS = [item for item in _BUILTIN_TABS if item.id != tab_id]
    _BUILTIN_TABS.append(PanelTabSpec(id=tab_id, title=title, order=order, builder=builder))
    _BUILTIN_TABS.sort(key=lambda item: item.order)


def built_in_panel_tabs() -> list[PanelTabSpec]:
    return list(_BUILTIN_TABS)


def load_extension_tab_specs() -> list[dict]:
    """Optional JSON-defined tabs from ~/.silva/dev/panel_extensions.json."""
    from silva.dev.paths import DEV_DIR, ensure_dev_dir

    ensure_dev_dir()
    path = DEV_DIR / "panel_extensions.json"
    if not path.exists():
        example = DEV_DIR / "panel_extensions.example.json"
        bundled = Path(__file__).resolve().parent / "panel_extensions.example.json"
        if not example.exists() and bundled.exists():
            example.write_text(bundled.read_text(encoding="utf-8"), encoding="utf-8")
        path = example if example.exists() else path
    if not path.exists():
        return []
    try:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    except (OSError, json.JSONDecodeError):
        pass
    return []
