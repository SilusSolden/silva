"""Disk-backed index of commands, features, and conversation openers."""

from __future__ import annotations

import pickle
import re
from dataclasses import dataclass
from pathlib import Path

from silva.config import CONFIG_DIR, load_config

CACHE_DIR = CONFIG_DIR / "cache"
CACHE_FILE = CACHE_DIR / "router_cache_v1.pkl"
CACHE_VERSION = 1


@dataclass(frozen=True)
class RouteHint:
    route_type: str
    name: str | None = None


def _normalize(text: str) -> str:
    text = text.strip().lower()
    text = text.replace("'", "")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _cache_enabled() -> bool:
    return bool(load_config().get("router_cache_enabled", True))


def _collect_routes() -> tuple[dict[str, RouteHint], list[tuple[str, RouteHint]]]:
    from silva.commands.registry import WEATHER_PHRASES, WIKIPEDIA_PREFIXES
    from silva.conversation import small_talk as st
    from silva.stt_quick_commands import _QUICK_EXACT

    exact: dict[str, RouteHint] = {}
    contains: list[tuple[str, RouteHint]] = []

    def add_exact(phrases: tuple[str, ...], route_type: str, name: str | None = None) -> None:
        for phrase in phrases:
            key = _normalize(phrase)
            if key:
                exact[key] = RouteHint(route_type, name)

    def add_contains(phrases: tuple[str, ...], route_type: str, name: str | None = None) -> None:
        for phrase in phrases:
            key = _normalize(phrase)
            if key:
                contains.append((key, RouteHint(route_type, name)))

    add_exact(WEATHER_PHRASES, "command", "weather")
    add_contains(WIKIPEDIA_PREFIXES, "command", "wikipedia")
    add_exact(st.GREETING_TRIGGERS, "conversation", "greeting")
    add_exact(st.HOW_ARE_YOU_TRIGGERS, "conversation", "how_are_you")
    add_contains(st.HOW_ARE_YOU_TRIGGERS, "conversation", "how_are_you")
    add_exact(st.WHATS_UP_TRIGGERS, "conversation", "whats_up")
    add_exact(st.THANKS_TRIGGERS, "conversation", "thanks")
    add_exact(st.CASUAL_CHECKINS, "conversation", "how_are_you")
    add_exact(_QUICK_EXACT, "quick", None)

    contains.sort(key=lambda item: len(item[0]), reverse=True)
    return exact, contains


def build_router_cache() -> dict:
    exact, contains = _collect_routes()
    return {
        "version": CACHE_VERSION,
        "exact": exact,
        "contains": contains,
    }


def save_router_cache(payload: dict) -> None:
    if not _cache_enabled():
        return
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with CACHE_FILE.open("wb") as handle:
            pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        pass


def load_router_cache() -> dict | None:
    if not _cache_enabled() or not CACHE_FILE.exists():
        return None
    try:
        with CACHE_FILE.open("rb") as handle:
            payload = pickle.load(handle)
        if payload.get("version") != CACHE_VERSION:
            return None
        return payload
    except Exception:
        return None


_exact_index: dict[str, RouteHint] = {}
_contains_index: list[tuple[str, RouteHint]] = []
_ready = False


def preload_router_cache(*, force_rebuild: bool = False) -> None:
    global _exact_index, _contains_index, _ready
    if _ready and not force_rebuild:
        return

    payload = None if force_rebuild else load_router_cache()
    if payload is None:
        payload = build_router_cache()
        save_router_cache(payload)

    _exact_index = dict(payload["exact"])
    _contains_index = list(payload["contains"])
    _ready = True


def lookup_route(text: str) -> RouteHint | None:
    preload_router_cache()
    normalized = _normalize(text)
    if not normalized:
        return None

    from silva.commands.help_phrases import is_capability_ask, is_feature_detail_ask, is_help_request
    from silva.conversation.correction_repair import is_correction_repair_command

    if (
        is_help_request(text)
        or is_feature_detail_ask(text)
        or is_capability_ask(text)
        or is_correction_repair_command(text)
    ):
        return None

    if normalized in _exact_index:
        return _exact_index[normalized]

    for phrase, hint in _contains_index:
        if phrase in normalized:
            return hint
    return None
