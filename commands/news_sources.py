"""RSS news source definitions and fetching."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from html import unescape

import requests

from silva.logger import log_error

REQUEST_TIMEOUT = 12
USER_AGENT = "SilvaAssistant/1.0 (+local news briefing)"

# Category pools for the daily top-5 layout.
AI_FEEDS = (
    {"name": "MIT Technology Review", "url": "https://www.technologyreview.com/feed/"},
    {"name": "Ars Technica", "url": "https://feeds.arstechnica.com/arstechnica/index"},
    {"name": "The Verge", "url": "https://www.theverge.com/rss/index.xml"},
)

FOOD_HEALTH_FEEDS = (
    {"name": "FDA Food Safety", "url": "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/food-safety/rss.xml"},
    {"name": "NPR Health", "url": "https://feeds.npr.org/1128/rss.xml"},
)

US_MAJOR_FEEDS = (
    {"name": "Reuters Top News", "url": "https://feeds.reuters.com/reuters/topNews"},
    {"name": "NPR News", "url": "https://feeds.npr.org/1001/rss.xml"},
    {"name": "AP Top News", "url": "https://feeds.apnews.com/apnews/topnews"},
    {"name": "BBC US & Canada", "url": "https://feeds.bbci.co.uk/news/world/us_and_canada/rss.xml"},
)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


@dataclass
class NewsItem:
    title: str
    link: str
    summary: str
    source: str
    category: str
    published: str = ""
    tags: list[str] = field(default_factory=list)


def _strip_html(text: str) -> str:
    if not text:
        return ""
    text = unescape(_TAG_RE.sub(" ", text))
    return _WS_RE.sub(" ", text).strip()


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _find_text(node: ET.Element, names: tuple[str, ...]) -> str:
    for child in node:
        if _local_name(child.tag) in names and child.text:
            return child.text.strip()
    return ""


def _parse_rss(xml_text: str, *, source: str, category: str, limit: int) -> list[NewsItem]:
    items: list[NewsItem] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return items

    channel = root.find("channel")
    if channel is None:
        channel = root

    for entry in channel.findall("item")[:limit]:
        title = _find_text(entry, ("title",))
        link = _find_text(entry, ("link",))
        summary = _find_text(entry, ("description", "summary", "content"))
        published = _find_text(entry, ("pubDate", "published", "updated"))
        if title and link:
            items.append(
                NewsItem(
                    title=_strip_html(title),
                    link=link.strip(),
                    summary=_strip_html(summary),
                    source=source,
                    category=category,
                    published=published,
                )
            )

    if items:
        return items

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for entry in root.findall(".//atom:entry", ns)[:limit]:
        title = _find_text(entry, ("title",))
        link = ""
        for link_node in entry:
            if _local_name(link_node.tag) == "link":
                link = link_node.attrib.get("href", link_node.text or "")
                if link:
                    break
        summary = _find_text(entry, ("summary", "content"))
        published = _find_text(entry, ("published", "updated"))
        if title and link:
            items.append(
                NewsItem(
                    title=_strip_html(title),
                    link=link.strip(),
                    summary=_strip_html(summary),
                    source=source,
                    category=category,
                    published=published,
                )
            )
    return items


def fetch_feed(url: str, *, source: str, category: str, limit: int = 10) -> list[NewsItem]:
    try:
        resp = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        return _parse_rss(resp.text, source=source, category=category, limit=limit)
    except Exception as exc:
        log_error(f"News feed fetch failed for {source}", exc=exc)
        return []


def fetch_category_pool(feeds: tuple[dict[str, str], ...], category: str, limit_per_feed: int = 8) -> list[NewsItem]:
    collected: list[NewsItem] = []
    for feed in feeds:
        collected.extend(
            fetch_feed(
                feed["url"],
                source=feed["name"],
                category=category,
                limit=limit_per_feed,
            )
        )
    return collected


def fetch_all_headline_pools() -> dict[str, list[NewsItem]]:
    return {
        "ai": fetch_category_pool(AI_FEEDS, "ai"),
        "food_health": fetch_category_pool(FOOD_HEALTH_FEEDS, "food_health"),
        "us_major": fetch_category_pool(US_MAJOR_FEEDS, "us_major"),
    }
