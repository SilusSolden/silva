"""Persistent Stream Deck XL bindings and plugin-ready weather tile snapshots."""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime

from silva.config import CONFIG_DIR, load_config

STORE_FILE = CONFIG_DIR / "stream_deck_bindings.json"
TILE_DIR = CONFIG_DIR / "stream_deck"
MAX_SLOTS = 32
MAX_PAGES = 32
_LOCK = threading.Lock()

_STREAM_RE = re.compile(r"\bstream deck|deck button|deck tile", re.I)
_SLOT_RE = re.compile(
    r"(?:page\s*(\d+).*?(?:slot|button|key)\s*(\d+)|(?:slot|button|key)\s*(\d+).*?page\s*(\d+))",
    re.I,
)
_LIST_RE = re.compile(r"\b(?:list|show|what(?:'s| is)? on|whats on)\b.*\bstream deck\b|\bstream deck list\b", re.I)
_WEATHER_RE = re.compile(r"\bweather\b", re.I)
_RUN_RE = re.compile(r"\b(?:run|press|activate|trigger)\b", re.I)


def _key(user_id: str) -> str:
    return str(user_id or "guest")


def _load() -> dict:
    if not STORE_FILE.exists():
        return {"users": {}}
    try:
        data = json.loads(STORE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"users": {}}
    if not isinstance(data, dict) or not isinstance(data.get("users"), dict):
        return {"users": {}}
    return data


def _save(state: dict) -> None:
    try:
        STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp = STORE_FILE.with_suffix(".json.tmp")
        temp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        temp.replace(STORE_FILE)
    except OSError:
        pass


def enabled() -> bool:
    return bool(load_config().get("stream_deck_enabled", True))


def can_setup(user_id: str = "") -> bool:
    if not enabled():
        return False
    if bool(load_config().get("stream_deck_user_setup_enabled", True)):
        return True
    from silva.conversation.speech_policy import is_privileged

    return is_privileged(_key(user_id))


def _slot_key(page: int, slot: int) -> str:
    return f"{page}:{slot}"


def _valid_slot(page: int, slot: int) -> bool:
    return 1 <= page <= MAX_PAGES and 1 <= slot <= MAX_SLOTS


def set_binding(
    *,
    user_id: str,
    page: int,
    slot: int,
    label: str,
    command: str = "",
    weather: bool = False,
    scope: str = "user",
) -> bool:
    if not enabled() or not _valid_slot(page, slot):
        return False
    command = " ".join(str(command or "").split())
    label = " ".join(str(label or command or weather_tile_text()).split())[:80]
    if not command and not weather:
        return False
    with _LOCK:
        state = _load()
        owners = state.setdefault("users", {})
        key = "global" if scope == "global" else _key(user_id)
        binding = owners.setdefault(key, {})
        binding[_slot_key(page, slot)] = {
            "page": page,
            "slot": slot,
            "label": label[:80],
            "command": command[:400],
            "weather": bool(weather),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        _save(state)
    return True


def get_binding(*, user_id: str, page: int, slot: int) -> dict | None:
    if not _valid_slot(page, slot):
        return None
    key = _slot_key(page, slot)
    with _LOCK:
        state = _load()
        users = state.get("users") or {}
        binding = (users.get(_key(user_id)) or {}).get(key) or (users.get("global") or {}).get(key)
    return dict(binding) if isinstance(binding, dict) else None


def list_bindings(*, user_id: str) -> list[dict]:
    with _LOCK:
        state = _load()
        users = state.get("users") or {}
        items = list((users.get(_key(user_id)) or {}).values())
        items.extend((users.get("global") or {}).values())
    return [dict(item) for item in items if isinstance(item, dict)]


def remove_binding(*, user_id: str, page: int, slot: int) -> bool:
    key = _slot_key(page, slot)
    with _LOCK:
        state = _load()
        users = state.get("users") or {}
        binding = users.get(_key(user_id))
        if not isinstance(binding, dict) or key not in binding:
            return False
        del binding[key]
        _save(state)
    return True


def resolve_slot_action(*, user_id: str, page: int, slot: int) -> dict:
    binding = get_binding(user_id=user_id, page=page, slot=slot)
    if binding is None:
        return {"page": page, "slot": slot, "command": "", "found": False}
    command = binding.get("command") or ""
    if binding.get("weather"):
        command = f"what's my local weather"
    return {
        "page": page,
        "slot": slot,
        "label": binding.get("label") or "",
        "command": command,
        "weather": bool(binding.get("weather")),
        "found": True,
    }


def weather_tile_text() -> str:
    snapshot = load_config().get("last_weather") or {}
    if not isinstance(snapshot, dict) or not snapshot.get("temp_f"):
        return "Weather unavailable"
    return f"{snapshot.get('temp_f')}F {str(snapshot.get('conditions') or '').strip()}".strip()


def publish_weather_tile() -> Path:
    TILE_DIR.mkdir(parents=True, exist_ok=True)
    snapshot = load_config().get("last_weather") or {}
    payload = {
        "enabled": bool(load_config().get("stream_deck_weather_tile_enabled", False)),
        "text": weather_tile_text(),
        "city": str((snapshot or {}).get("city") or ""),
        "temp_f": (snapshot or {}).get("temp_f"),
        "conditions": str((snapshot or {}).get("conditions") or ""),
        "humidity": (snapshot or {}).get("humidity"),
        "wind_mph": (snapshot or {}).get("wind_mph"),
        "updated_at": str((snapshot or {}).get("updated_at") or ""),
    }
    json_path = TILE_DIR / "weather_tile.json"
    text_path = TILE_DIR / "weather_tile.txt"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    text_path.write_text(payload["text"], encoding="utf-8")
    return json_path


def _parse_slot(text: str) -> tuple[int, int] | None:
    match = _SLOT_RE.search(text)
    if match is None:
        return None
    if match.group(1) and match.group(2):
        return int(match.group(1)), int(match.group(2))
    if match.group(3) and match.group(4):
        return int(match.group(4)), int(match.group(3))
    return None


def parse_stream_deck_speech(text: str, *, user_id: str = "") -> dict | None:
    value = str(text or "").strip()
    if not value or not enabled() or _STREAM_RE.search(value) is None:
        return None
    slot = _parse_slot(value)
    if _LIST_RE.search(value):
        return {"action": "list"}
    if re.search(r"\b(?:add me|set me up|connect me|bind me)\b", value, re.I):
        return {"action": "setup", "slot": slot}
    if _WEATHER_RE.search(value) and re.search(r"\b(?:bind|set|put|assign|tie|make)\b", value, re.I):
        return {"action": "bind_weather", "slot": slot}
    if _RUN_RE.search(value):
        return {"action": "run", "slot": slot}
    return {"action": "help", "slot": slot}


def _ask_for_command(assistant, page: int, slot: int, user_id: str) -> None:
    from silva.gui.text_input_popup import show_text_input_popup

    assistant.say(f"Type the command for Stream Deck page {page}, slot {slot}.", interruptible=False)

    def save(value: str) -> None:
        ok = set_binding(user_id=user_id, page=page, slot=slot, label=value, command=value)
        assistant.say("Stream Deck button saved." if ok else "I couldn't save that button.", interruptible=False)

    show_text_input_popup(
        "Silva Stream Deck",
        f"Command for page {page}, slot {slot}:",
        save,
        width=560,
    )


def handle_stream_deck_speech(assistant, text: str) -> bool:
    getter = getattr(assistant, "_user_id", None)
    user_id = getter() if callable(getter) else "guest"
    action = parse_stream_deck_speech(text, user_id=user_id)
    if action is None:
        return False
    kind = str(action.get("action") or "")
    slot = action.get("slot")

    if kind == "list":
        bindings = list_bindings(user_id=user_id)
        if bindings:
            summary = "; ".join(
                f"page {item.get('page')} slot {item.get('slot')}: {item.get('label')}"
                for item in bindings[:12]
            )
            assistant.say(f"Stream Deck bindings: {summary}.", interruptible=False)
        else:
            assistant.say("No Stream Deck bindings are saved.", interruptible=False)
        return True

    if kind == "run" and isinstance(slot, tuple):
        binding = resolve_slot_action(user_id=user_id, page=slot[0], slot=slot[1])
        if not binding.get("found") or not binding.get("command"):
            assistant.say("That Stream Deck button is not bound.", interruptible=False)
            return True
        assistant._handle_input(binding["command"])
        return True

    if not can_setup(user_id):
        assistant.say("Stream Deck setup is locked to approved users.", interruptible=False)
        return True

    if kind == "bind_weather":
        if not isinstance(slot, tuple):
            assistant.say("Say the page and slot, for example page 1 slot 5.", interruptible=False)
            return True
        ok = set_binding(
            user_id=user_id,
            page=slot[0],
            slot=slot[1],
            label="Weather",
            weather=True,
        )
        publish_weather_tile()
        assistant.say(
            f"Weather tile bound to page {slot[0]} slot {slot[1]}." if ok else "I couldn't bind that tile.",
            interruptible=False,
        )
        return True

    if isinstance(slot, tuple):
        command_match = re.search(r"\b(?:run|say|command|to)\s+(.+)$", text, re.I)
        command = command_match.group(1).strip() if command_match else ""
        if command:
            ok = set_binding(
                user_id=user_id,
                page=slot[0],
                slot=slot[1],
                label=command,
                command=command,
            )
            assistant.say(
                f"Stream Deck page {slot[0]} slot {slot[1]} saved." if ok else "I couldn't save that button.",
                interruptible=False,
            )
            return True
        _ask_for_command(assistant, slot[0], slot[1], user_id)
        return True

    assistant.say(
        "Say a page and slot, then the command. For example: stream deck page 1 slot 5 run weather.",
        interruptible=False,
    )
    return True


def is_stream_deck_command(text: str, *, user_id: str = "") -> bool:
    return parse_stream_deck_speech(text, user_id=user_id) is not None
