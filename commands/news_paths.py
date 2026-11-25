"""Storage paths for Silva daily news briefings."""

from __future__ import annotations

from pathlib import Path

from silva.config import CONFIG_DIR

NEWS_DIR = CONFIG_DIR / "news"
BRIEFINGS_DIR = NEWS_DIR / "briefings"
STATE_FILE = NEWS_DIR / "state.json"
LATEST_JSON = NEWS_DIR / "latest_briefing.json"


def ensure_news_dir() -> None:
    NEWS_DIR.mkdir(parents=True, exist_ok=True)
    BRIEFINGS_DIR.mkdir(parents=True, exist_ok=True)


def prune_old_briefing_files(keep: Path) -> None:
    """Keep only the current briefing .txt so old days do not pile up."""
    ensure_news_dir()
    try:
        keep_resolved = keep.resolve()
    except OSError:
        keep_resolved = keep
    for path in BRIEFINGS_DIR.glob("*.txt"):
        try:
            if path.resolve() == keep_resolved:
                continue
            path.unlink()
        except OSError:
            continue
