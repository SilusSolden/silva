"""Web search snippets for visual guides — no browser window."""

from __future__ import annotations

import re

import requests

USER_AGENT = "SilvaAssistant/1.0 (local visual guide)"


def search_snippets(query: str, *, max_results: int = 5) -> list[dict]:
    results: list[dict] = []
    q = query.strip()
    if not q:
        return results

    try:
        resp = requests.get(
            "https://api.duckduckgo.com/",
            params={"q": q, "format": "json", "no_redirect": 1, "no_html": 1},
            timeout=12,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        data = resp.json()
        abstract = str(data.get("AbstractText", "")).strip()
        heading = str(data.get("Heading", "")).strip()
        url = str(data.get("AbstractURL", "")).strip()
        if abstract:
            results.append({"title": heading or q, "snippet": abstract, "url": url, "source": "duckduckgo"})
        for topic in data.get("RelatedTopics", [])[:max_results]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append(
                    {
                        "title": str(topic.get("Text", ""))[:120],
                        "snippet": str(topic.get("Text", "")),
                        "url": str(topic.get("FirstURL", "")),
                        "source": "duckduckgo",
                    }
                )
    except Exception:
        pass

    if len(results) < max_results:
        results.extend(_html_search(q, max_results=max_results - len(results)))
    return results[:max_results]


def _html_search(query: str, *, max_results: int) -> list[dict]:
    try:
        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            timeout=12,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        html = resp.text
    except Exception:
        return []

    items: list[dict] = []
    for match in re.finditer(
        r'class="result__a"[^>]*href="([^"]+)"[^>]*>([^<]+)</a>.*?class="result__snippet"[^>]*>([^<]+)',
        html,
        re.S,
    ):
        items.append(
            {
                "title": re.sub(r"\s+", " ", match.group(2)).strip(),
                "snippet": re.sub(r"\s+", " ", match.group(3)).strip(),
                "url": match.group(1),
                "source": "web",
            }
        )
        if len(items) >= max_results:
            break
    return items


def build_steps_from_results(query: str, results: list[dict]) -> list[str]:
    steps: list[str] = []
    if results:
        steps.append(f"Search focus: {query}")
        for index, item in enumerate(results[:3], start=1):
            title = item.get("title", "Result")
            snippet = item.get("snippet", "")[:280]
            url = item.get("url", "")
            line = f"Review {title}. {snippet}"
            if url:
                line += f" Source: {url}"
            steps.append(line)
    else:
        steps.append(f"Search the web for: {query}")
        steps.append("Check Steam workshop, Reddit, or YouTube for modded game guides if this is from a game mod.")
        steps.append("Pause on the item or menu you need help with and ask Silva again with more detail.")
    steps.append("Say 'I'm done with that step' when ready for the next step.")
    return steps
