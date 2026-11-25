"""Build, persist, and format Silva daily news briefings."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from silva.commands.news_analyzer import (
    choose_best_source,
    extract_bullets,
    pick_top,
    score_ai,
    score_food_health_local,
    score_impact,
    select_impact_stories,
    skim_top_topics,
)
from silva.commands.news_paths import (
    BRIEFINGS_DIR,
    LATEST_JSON,
    STATE_FILE,
    ensure_news_dir,
    prune_old_briefing_files,
)
from silva.commands.news_sources import NewsItem, fetch_all_headline_pools
from silva.config import load_config
from silva.location import resolve_location
from silva.logger import log_error, log_info


def _local_terms() -> tuple[str, ...]:
    try:
        location = resolve_location()
        city = location.city.split(",")[0].strip().lower()
        parts = [part.strip().lower() for part in location.city.split(",") if part.strip()]
        return tuple(dict.fromkeys([city, *parts]))
    except Exception:
        return ()


def _story_payload(item: NewsItem, *, slot: str) -> dict[str, Any]:
    return {
        "slot": slot,
        "title": item.title,
        "link": item.link,
        "source": item.source,
        "category": item.category,
        "summary": item.summary,
        "bullets": extract_bullets(item),
        "impact_score": score_impact(item),
    }


def build_daily_briefing(*, user_id: str, user_name: str) -> dict[str, Any]:
    ensure_news_dir()
    pools = fetch_all_headline_pools()
    all_items = pools["ai"] + pools["food_health"] + pools["us_major"]
    local = _local_terms()

    used_links: set[str] = set()
    ai_stories = pick_top(pools["ai"], score_ai, 2, used_links=used_links)
    food_story = pick_top(
        pools["food_health"] + pools["us_major"],
        lambda item: score_food_health_local(item, local_terms=local),
        1,
        used_links=used_links,
    )

    skimmed = skim_top_topics(all_items, limit=20)
    impact_candidates = [item for item in skimmed if score_impact(item) >= 1.0] or skimmed
    us_picks = pick_top(impact_candidates, score_impact, 2, used_links=used_links)

    if len(us_picks) < 2:
        us_picks = pick_top(pools["us_major"], score_impact, 2, used_links=used_links)

    top_five = ai_stories + food_story + us_picks
    impact_highlights = select_impact_stories(all_items, count=2)

    try:
        location = resolve_location()
        location_label = location.city
    except Exception:
        location_label = "Unknown"

    today = date.today().isoformat()
    briefing = {
        "date": today,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "user_id": user_id,
        "user_name": user_name,
        "location": location_label,
        "primary_source": choose_best_source(us_picks),
        "skimmed_topic_count": len(skimmed),
        "impact_highlights": [_story_payload(item, slot="impact") for item in impact_highlights],
        "top_five": [_story_payload(item, slot=f"slot_{index + 1}") for index, item in enumerate(top_five)],
        "sections": {
            "ai": [_story_payload(item, slot="ai") for item in ai_stories],
            "food_health_local": [_story_payload(item, slot="food_health_local") for item in food_story],
            "us_major": [_story_payload(item, slot="us_major") for item in us_picks],
        },
    }
    return briefing


def save_briefing(briefing: dict[str, Any]) -> tuple[Path, Path]:
    ensure_news_dir()
    day = briefing.get("date", date.today().isoformat())
    txt_path = BRIEFINGS_DIR / f"{day}.txt"
    txt_path.write_text(format_briefing_text(briefing), encoding="utf-8")
    prune_old_briefing_files(txt_path)
    LATEST_JSON.write_text(json.dumps(briefing, indent=2), encoding="utf-8")

    state = load_news_state()
    state["last_briefing_date"] = day
    state["last_txt_path"] = str(txt_path)
    state["pending_prompt"] = not bool(load_config().get("news_briefing_manual_only", True))
    state["prompted_user_id"] = None
    save_news_state(state)
    log_info(f"Daily news briefing saved for {day} at {txt_path}")
    return txt_path, LATEST_JSON


def load_latest_briefing() -> dict[str, Any] | None:
    if not LATEST_JSON.exists():
        return None
    try:
        return json.loads(LATEST_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_news_state() -> dict[str, Any]:
    ensure_news_dir()
    if not STATE_FILE.exists():
        return {}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_news_state(state: dict[str, Any]) -> None:
    ensure_news_dir()
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def format_briefing_text(briefing: dict[str, Any]) -> str:
    lines = [
        "SILVA DAILY NEWS BRIEFING",
        f"Date: {briefing.get('date', '')}",
        f"Prepared for: {briefing.get('user_name', 'Admin')}",
        f"Location context: {briefing.get('location', 'Unknown')}",
        f"Primary US source selected: {briefing.get('primary_source', 'Unknown')}",
        f"Topics skimmed: {briefing.get('skimmed_topic_count', 0)}",
        "",
        "=== HIGH-IMPACT PICKS (tech, computers, government) ===",
    ]
    for index, story in enumerate(briefing.get("impact_highlights", []), start=1):
        lines.extend(_format_story_block(index, story))

    lines.extend(["", "=== TODAY'S TOP 5 ==="])
    section_labels = [
        ("AI & technology", briefing.get("sections", {}).get("ai", [])),
        ("Food, health & local alerts", briefing.get("sections", {}).get("food_health_local", [])),
        ("Major US headlines", briefing.get("sections", {}).get("us_major", [])),
    ]
    counter = 1
    for label, stories in section_labels:
        lines.append("")
        lines.append(f"--- {label} ---")
        for story in stories:
            lines.extend(_format_story_block(counter, story))
            counter += 1

    lines.extend(
        [
            "",
            "Notes:",
            "- Silva skimmed major feeds, ranked about 20 topics, and picked stories that may affect technology or government policy.",
            "- Ask Silva to show the news briefing anytime to reopen this file.",
            "",
        ]
    )
    return "\n".join(lines)


def _format_story_block(index: int, story: dict[str, Any]) -> list[str]:
    lines = [
        f"{index}. {story.get('title', 'Untitled')}",
        f"   Source: {story.get('source', 'Unknown')} | {story.get('link', '')}",
    ]
    for bullet in story.get("bullets", []):
        lines.append(f"   • {bullet}")
    lines.append("")
    return lines


def briefing_summary_speech(briefing: dict[str, Any]) -> str:
    highlights = briefing.get("impact_highlights") or []
    top_five = briefing.get("top_five") or []
    titles = [item.get("title", "") for item in highlights[:2] if item.get("title")]
    if not titles:
        titles = [item.get("title", "") for item in top_five[:2] if item.get("title")]
    if not titles:
        return "Your daily news briefing is ready."
    joined = "; ".join(titles[:2])
    return f"Your daily news briefing is ready. Top stories include: {joined}."


def generate_and_store_briefing(*, user_id: str, user_name: str) -> dict[str, Any]:
    try:
        briefing = build_daily_briefing(user_id=user_id, user_name=user_name)
        save_briefing(briefing)
        return briefing
    except Exception as exc:
        log_error("Failed to build daily news briefing", exc=exc)
        raise
