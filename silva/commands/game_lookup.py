"""Skim public web results for in-game how-tos, then speak a short answer."""

from __future__ import annotations

import re

from silva.commands.game_lookup_phrases import extract_game_query, is_game_lookup
from silva.commands.visual_guide_search import search_snippets
from silva.commands.wikipedia import _fetch_article, _search_title
from silva.history_store import record_search
from silva.logger import log_error, log_info

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_MAX_SPEECH = 900


def _wiki_blurb(query: str) -> str:
    try:
        title = _search_title(query)
        if not title:
            return ""
        article = _fetch_article(title)
    except Exception as exc:
        log_error("Game lookup Wikipedia skim failed", exc=exc)
        return ""
    sentences = [s.strip() for s in _SENTENCE_RE.split(article) if s.strip()]
    if not sentences:
        return ""
    blurb = " ".join(sentences[:2])
    if len(blurb) > 420:
        blurb = blurb[:417].rsplit(" ", 1)[0] + "."
    return f"Wikipedia on {title}: {blurb}"


def _snippet_lines(results: list[dict]) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for item in results:
        snippet = re.sub(r"\s+", " ", str(item.get("snippet") or "")).strip()
        title = re.sub(r"\s+", " ", str(item.get("title") or "")).strip()
        if len(snippet) < 24:
            continue
        key = snippet[:80].lower()
        if key in seen:
            continue
        seen.add(key)
        if title and title.lower() not in snippet.lower()[:40]:
            lines.append(f"{title}: {snippet}")
        else:
            lines.append(snippet)
        if len(lines) >= 3:
            break
    return lines


def lookup_game_info(query: str) -> str:
    query = query.strip()
    if not query:
        return "Tell me the game and what you want to know how to do."

    search_q = f"{query} game guide walkthrough"
    results = search_snippets(search_q, max_results=6)
    if not results:
        results = search_snippets(query, max_results=6)

    wiki = _wiki_blurb(query)
    snippets = _snippet_lines(results)

    if not wiki and not snippets:
        return (
            f"I skimmed the web for {query} but could not pull a clear guide. "
            "Name the game and the exact thing you want to do, then ask again."
        )

    parts = [f"Here is what I found for {query}."]
    if wiki:
        parts.append(wiki)
    if snippets:
        parts.append("Guides online also say: " + " ".join(snippets))
    spoken = " ".join(parts)
    if len(spoken) > _MAX_SPEECH:
        spoken = spoken[: _MAX_SPEECH - 1].rsplit(" ", 1)[0] + "."
    return spoken


def handle_game_lookup_speech(text: str, *, user_id: str = "guest") -> str | None:
    if not is_game_lookup(text):
        return None
    query = extract_game_query(text)
    log_info(f"Game lookup: {query[:160]}")
    try:
        answer = lookup_game_info(query)
    except Exception as exc:
        log_error("Game lookup failed", exc=exc)
        return "Sorry, I could not look that game information up right now."
    record_search(user_id, kind="game", query=query, title="web skim", summary=answer[:300])
    return answer
