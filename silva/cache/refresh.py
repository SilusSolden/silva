"""Rebuild Silva disk caches after updates or new features."""

from __future__ import annotations

from silva.logger import log_info


def refresh_all_caches(*, force: bool = False) -> None:
    from silva.cache.router_cache import preload_router_cache
    from silva.conversation.vocabulary import preload_vocabulary

    preload_router_cache(force_rebuild=force)
    preload_vocabulary()
    try:
        from silva.dev.runtime_hooks import safe_install_runtime_hooks

        safe_install_runtime_hooks()
    except Exception:
        pass
    log_info("Silva caches refreshed.")
