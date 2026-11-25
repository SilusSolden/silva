"""Wikipedia lookup command for Silva."""

from __future__ import annotations

import re

import requests

from silva.commands.knowledge_store import remember_result
from silva.commands.visual_guide_search import search_snippets
from silva.config import load_config
from silva.history_store import record_search
from silva.logger import log_info

API_URL = "https://en.wikipedia.org/w/api.php"
REQUEST_TIMEOUT = 15
USER_AGENT = {"User-Agent": "Silva/0.1 (local assistant)"}


def _wiki_get(params: dict) -> requests.Response:
    try:
        resp = requests.get(
            API_URL,
            params=params,
            timeout=REQUEST_TIMEOUT,
            headers=USER_AGENT,
        )
        resp.raise_for_status()
        return resp
    except requests.exceptions.SSLError:
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        resp = requests.get(
            API_URL,
            params=params,
            timeout=REQUEST_TIMEOUT,
            headers=USER_AGENT,
            verify=False,
        )
        resp.raise_for_status()
        return resp


def _clean_wikipedia_text(text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    return text


def _search_title(query: str) -> str | None:
    resp = _wiki_get(
        {
            "action": "query",
            "format": "json",
            "list": "search",
            "srsearch": query,
            "srlimit": 1,
            "utf8": 1,
        }
    )
    results = resp.json().get("query", {}).get("search", [])
    if not results:
        return None
    return results[0]["title"]


def _fetch_article(title: str) -> str:
    resp = _wiki_get(
        {
            "action": "query",
            "format": "json",
            "prop": "extracts",
            "explaintext": 1,
            "exsectionformat": "plain",
            "titles": title,
            "redirects": 1,
            "utf8": 1,
        }
    )
    pages = resp.json().get("query", {}).get("pages", {})
    if not pages:
        raise RuntimeError(f"No Wikipedia article found for '{title}'.")

    page = next(iter(pages.values()))
    if page.get("missing"):
        raise RuntimeError(f"No Wikipedia article found for '{title}'.")

    extract = page.get("extract", "").strip()
    if not extract:
        raise RuntimeError(f"Wikipedia article '{title}' has no readable text.")

    return _clean_wikipedia_text(extract)


def _web_notes(query: str) -> str:
    lines: list[str] = []
    try:
        results = search_snippets(query, max_results=3)
    except Exception:
        return ""
    for item in results:
        snippet = re.sub(r"\s+", " ", str(item.get("snippet") or "")).strip()
        if len(snippet) < 24:
            continue
        lines.append(snippet)
        if len(lines) >= 2:
            break
    if not lines:
        return ""
    return "Also from a web skim: " + " ".join(lines)


def search_wikipedia(query: str, *, user_id: str = "guest") -> str:
    query = query.strip()
    if not query:
        raise RuntimeError("Tell me what you want to search on Wikipedia.")

    title = _search_title(query)
    article = ""
    if title:
        try:
            article = _fetch_article(title)
        except RuntimeError:
            article = ""
    web = _web_notes(query)
    body = article.strip()
    if web:
        body = f"{body}\n\n{web}".strip() if body else web
    if not body:
        raise RuntimeError(f"I could not find a Wikipedia article or a web skim for '{query}'.")

    remember_result(user_id, title or query, body)
    config = load_config()
    raw_cap = int(config.get("wikipedia_speech_chars", 720))
    # Older default (6000) read whole articles aloud for minutes.
    if raw_cap >= 4000:
        raw_cap = 720
    max_speech = max(240, min(raw_cap, 1200))
    label = title or query
    log_info(f"Wikipedia article: {label} ({len(body)} chars, speaking up to {max_speech})")
    record_search(user_id, kind="wikipedia", query=query, title=label, summary=body[:300])

    if not article:
        spoken = web if len(web) <= max_speech else web[:max_speech].rsplit(" ", 1)[0]
        return (
            f"I didn't find a Wikipedia page for {query}, but I skimmed the web.\n\n{spoken}"
        )

    intro = f"Here is what Wikipedia says about {title}."
    spoken_body = article
    if web and len(article) < max_speech - 80:
        spoken_body = f"{article}\n\n{web}"
    if len(spoken_body) <= max_speech:
        return f"{intro}\n\n{spoken_body}"

    spoken = spoken_body[:max_speech].rsplit(" ", 1)[0]
    return f"{intro}\n\n{spoken}"
