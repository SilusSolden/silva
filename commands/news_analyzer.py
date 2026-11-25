"""Heuristic ranking and article bullet extraction for news briefings."""

from __future__ import annotations

import re
from html.parser import HTMLParser

import requests

from silva.commands.news_sources import NewsItem, USER_AGENT, REQUEST_TIMEOUT
from silva.logger import log_error

AI_KEYWORDS = (
    "ai",
    "artificial intelligence",
    "machine learning",
    "llm",
    "openai",
    "anthropic",
    "nvidia",
    "chip",
    "model",
    "robot",
    "automation",
    "cyber",
    "hack",
    "breach",
    "ransomware",
    "outage",
    "cloud",
)

FOOD_HEALTH_KEYWORDS = (
    "recall",
    "salmonella",
    "listeria",
    "e. coli",
    "food",
    "fda",
    "outbreak",
    "contamination",
    "allergy",
    "nutrition",
    "health",
)

DISASTER_KEYWORDS = (
    "evacuation",
    "evacuate",
    "tornado",
    "hurricane",
    "flood",
    "wildfire",
    "earthquake",
    "storm",
    "disaster",
    "emergency",
    "state of emergency",
    "power outage",
    "blackout",
)

GOVERNMENT_KEYWORDS = (
    "congress",
    "senate",
    "house",
    "president",
    "white house",
    "supreme court",
    "legislation",
    "bill",
    "regulation",
    "sanctions",
    "tariff",
    "federal",
    "government",
    "policy",
    "election",
    "vote",
)

TECH_GLOBAL_KEYWORDS = (
    "internet",
    "microsoft",
    "google",
    "apple",
    "amazon",
    "meta",
    "security",
    "data center",
    "semiconductor",
    "export ban",
    "critical infrastructure",
)

IMPACT_KEYWORDS = AI_KEYWORDS + GOVERNMENT_KEYWORDS + TECH_GLOBAL_KEYWORDS + DISASTER_KEYWORDS

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip = False
        if tag in {"p", "li", "br", "h1", "h2", "h3"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip and data.strip():
            self._parts.append(data.strip())

    def text(self) -> str:
        return _WS_RE.sub(" ", " ".join(self._parts)).strip()


def _normalize(text: str) -> str:
    return _WS_RE.sub(" ", text.lower()).strip()


def _keyword_score(text: str, keywords: tuple[str, ...]) -> float:
    normalized = _normalize(text)
    score = 0.0
    for word in keywords:
        if word in normalized:
            score += 1.0
    return score


def score_impact(item: NewsItem) -> float:
    blob = f"{item.title} {item.summary}"
    score = _keyword_score(blob, IMPACT_KEYWORDS)
    if item.category == "us_major":
        score += 0.5
    return score


def score_ai(item: NewsItem) -> float:
    blob = f"{item.title} {item.summary}"
    score = _keyword_score(blob, AI_KEYWORDS)
    if item.category == "ai":
        score += 2.0
    return score


def score_food_health_local(item: NewsItem, *, local_terms: tuple[str, ...]) -> float:
    blob = f"{item.title} {item.summary}"
    score = _keyword_score(blob, FOOD_HEALTH_KEYWORDS)
    score += _keyword_score(blob, DISASTER_KEYWORDS) * 1.5
    for term in local_terms:
        if term and term in _normalize(blob):
            score += 3.0
    if item.category == "food_health":
        score += 1.0
    return score


def pick_top(items: list[NewsItem], scorer, count: int, *, used_links: set[str] | None = None) -> list[NewsItem]:
    used = used_links or set()
    ranked = sorted(items, key=lambda item: scorer(item), reverse=True)
    picked: list[NewsItem] = []
    for item in ranked:
        if item.link in used:
            continue
        if scorer(item) <= 0 and item.category not in {"ai", "food_health", "us_major"}:
            continue
        picked.append(item)
        used.add(item.link)
        if len(picked) >= count:
            break
    if len(picked) < count:
        for item in ranked:
            if item.link in used:
                continue
            picked.append(item)
            used.add(item.link)
            if len(picked) >= count:
                break
    return picked


def skim_top_topics(items: list[NewsItem], limit: int = 20) -> list[NewsItem]:
    seen: set[str] = set()
    unique: list[NewsItem] = []
    for item in sorted(items, key=score_impact, reverse=True):
        key = _normalize(item.title)[:120]
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
        if len(unique) >= limit:
            break
    return unique


def select_impact_stories(items: list[NewsItem], count: int = 2) -> list[NewsItem]:
    skimmed = skim_top_topics(items, limit=20)
    relevant = [item for item in skimmed if score_impact(item) >= 1.0]
    pool = relevant or skimmed
    return pick_top(pool, score_impact, count)


def extract_bullets(item: NewsItem, *, max_bullets: int = 5) -> list[str]:
    bullets: list[str] = []
    if item.summary:
        for sentence in _SENTENCE_RE.split(item.summary):
            cleaned = sentence.strip()
            if len(cleaned) >= 40:
                bullets.append(cleaned)
            if len(bullets) >= max_bullets:
                return bullets[:max_bullets]

    page_text = _fetch_article_text(item.link)
    if page_text:
        for sentence in _SENTENCE_RE.split(page_text):
            cleaned = sentence.strip()
            if len(cleaned) < 40 or cleaned.lower() in _normalize(item.title):
                continue
            if any(word in _normalize(cleaned) for word in ("cookie", "subscribe", "newsletter", "sign up")):
                continue
            bullets.append(cleaned)
            if len(bullets) >= max_bullets:
                break

    if not bullets and item.summary:
        bullets.append(item.summary[:280])
    if not bullets:
        bullets.append("Open the source link for full details.")
    return bullets[:max_bullets]


def _fetch_article_text(url: str) -> str:
    try:
        resp = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        parser = _TextExtractor()
        parser.feed(resp.text)
        return parser.text()[:8000]
    except Exception as exc:
        log_error(f"News article fetch failed for {url[:80]}", exc=exc)
        return ""


def choose_best_source(items: list[NewsItem]) -> str:
    if not items:
        return "Unknown"
    counts: dict[str, int] = {}
    for item in items:
        counts[item.source] = counts.get(item.source, 0) + 1
    return max(counts, key=counts.get)
