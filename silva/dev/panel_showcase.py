from __future__ import annotations

import json
import os

from silva.dev.paths import DEV_DIR, ensure_dev_dir

SHOWCASE_FILE = DEV_DIR / "panel_showcase.json"

_BUILTIN_FEATURES = (
    ("test", "1. Test"),
    ("train", "2. Train"),
    ("live_update", "3. Live Update"),
)


def _read() -> dict:
    if not SHOWCASE_FILE.exists():
        return {"features": {}}
    try:
        data = json.loads(SHOWCASE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"features": {}}
    features = data.get("features") if isinstance(data, dict) else None
    return {"features": features if isinstance(features, dict) else {}}


def _write(data: dict) -> None:
    ensure_dev_dir()
    temp = SHOWCASE_FILE.with_suffix(".json.tmp")
    temp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temp, SHOWCASE_FILE)


def available_features() -> list[dict]:
    from silva.dev.panel_registry import built_in_panel_tabs, load_extension_tab_specs
    from silva.gui.panel_security_tabs import register_panel_tabs

    register_panel_tabs()
    features = [{"id": key, "title": title} for key, title in _BUILTIN_FEATURES]
    features.extend(
        {"id": spec.id, "title": spec.title}
        for spec in built_in_panel_tabs()
        if spec.id not in {item["id"] for item in features}
    )
    for item in load_extension_tab_specs():
        feature_id = str(item.get("id") or "").strip()
        if not feature_id or feature_id in {entry["id"] for entry in features}:
            continue
        features.append(
            {"id": feature_id, "title": str(item.get("title") or feature_id)}
        )
    return features


def load_showcase() -> dict[str, dict]:
    return _read()["features"]


def feature_state(feature_id: str) -> dict:
    state = load_showcase().get(str(feature_id) or "")
    return state if isinstance(state, dict) else {}


def save_feature_state(feature_id: str, state: dict) -> dict:
    key = str(feature_id or "").strip()
    if not key:
        return {}
    data = _read()
    data["features"][key] = state
    _write(data)
    return state


def mark_feature(feature_id: str, marked: bool = True) -> dict:
    state = feature_state(feature_id)
    state["marked"] = bool(marked)
    return save_feature_state(feature_id, state)


def set_feature_style(
    feature_id: str,
    *,
    accent: str = "",
    layout: str = "",
    notes: str = "",
    reference_id: str = "",
) -> dict:
    state = feature_state(feature_id)
    state.update(
        {
            "accent": str(accent or "").strip(),
            "layout": str(layout or "").strip(),
            "notes": str(notes or "").strip(),
            "reference_id": str(reference_id or "").strip(),
        }
    )
    return save_feature_state(feature_id, state)


def code_agent_request(feature_id: str) -> str:
    features = {item["id"]: item["title"] for item in available_features()}
    title = features.get(feature_id, feature_id)
    state = feature_state(feature_id)
    linked = state.get("reference_id") or "none"
    return (
        f"Update the Silva System Panel feature '{title}' (id: {feature_id}).\n"
        f"Desired accent: {state.get('accent') or 'keep current'}\n"
        f"Desired layout: {state.get('layout') or 'keep current'}\n"
        f"Linked reference image id: {linked}\n"
        f"Notes: {state.get('notes') or 'none'}\n"
        "Keep owner-only permissions unchanged."
    )
