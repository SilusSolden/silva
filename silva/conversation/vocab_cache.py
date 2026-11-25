"""Disk-backed conversation vocabulary cache (fast NVMe/SSD load on startup)."""

from __future__ import annotations

import pickle
from pathlib import Path

from silva.config import CONFIG_DIR, load_config

CACHE_DIR = CONFIG_DIR / "cache"
CACHE_FILE = CACHE_DIR / "conversation_vocab_v2.pkl"
CACHE_VERSION = 2


def cache_enabled() -> bool:
    return bool(load_config().get("conversation_cache_enabled", True))


def load_cached_vocabulary() -> dict | None:
    if not cache_enabled() or not CACHE_FILE.exists():
        return None
    try:
        with CACHE_FILE.open("rb") as handle:
            payload = pickle.load(handle)
        if payload.get("version") != CACHE_VERSION:
            return None
        return payload
    except Exception:
        return None


def save_vocabulary_cache(payload: dict) -> None:
    if not cache_enabled():
        return
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {**payload, "version": CACHE_VERSION}
        with CACHE_FILE.open("wb") as handle:
            pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        pass
