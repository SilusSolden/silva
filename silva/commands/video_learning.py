"""Local video-watch learning: categorize notes without downloading media."""

from __future__ import annotations

import re
import time
from pathlib import Path

from silva.commands.knowledge_store import (
    format_saved_list,
    list_saved,
    remember_result,
    save_knowledge,
)

VIDEO_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("manhwa", "manhwa"),
    ("manga", "manga"),
    ("grid", "grid-systems-electrical"),
    ("electrical", "grid-systems-electrical"),
    ("survival", "survival"),
    ("emergency", "survival"),
    ("invention", "inventions"),
    ("inventor", "inventions"),
    ("core video", "core-video"),
    ("essential video", "core-video"),
    ("basic stuff", "informative-basic-stuff"),
    ("informative", "informative-basic-stuff"),
    ("education", "informative-basic-stuff"),
    ("random video", "random-videos"),
)

CATEGORY_LABELS = {
    "informative-basic-stuff": "informative and basic stuff",
    "survival": "survival",
    "grid-systems-electrical": "grid systems and electrical",
    "inventions": "inventions",
    "random-videos": "random videos",
    "core-video": "core video",
    "manhwa": "manhwa",
    "manga": "manga",
}

_VIDEO_QUERY_RE = re.compile(
    r"\b(?:what did (?:you|silva) (?:learn|say|think)|what was (?:that|the) video about|"
    r"tell me about (?:that|the) video|what (?:videos|manhwa|manga) do you know|"
    r"what do you know about (?:manhwa|manga)|video (?:notes|learning|memory))\b",
    re.I,
)

_EXPLICIT_DOWNLOAD_RE = re.compile(
    r"\b(?:please\s+)?(?:download|save\s+(?:a\s+)?copy\s+of|save\s+the\s+video\s+file|grab\s+the\s+video\s+file)\b"
    r".{0,60}\b(?:video|clip|episode|anime|manga|manhwa|it|this|that)\b|"
    r"\b(?:download|save|grab)\b.{0,40}\b(?:this|that|the)\b.{0,20}\b(?:video|clip|episode)\b",
    re.I,
)

_DOWNLOAD_NEGATION_RE = re.compile(
    r"\b(?:do\s?n['’]?t|do\s+not|never|no|not|did\s+you|didn['’]?t|already)\b.{0,32}\bdownload\b|"
    r"\bdownload\b.{0,32}\b(?:later|tomorrow|maybe|sometime)\b",
    re.I,
)

_CONFIRM_DOWNLOAD_RE = re.compile(
    r"^\s*(?:yes|yeah|yep|yup)\s*,?\s+(?:please\s+)?download\s+(?:this|the|it)\b"
    r"|^\s*yes\s*,?\s+download\s+this\s+video\b",
    re.I,
)


def categorize_video(title: str, notes: str = "") -> str:
    blob = f"{title} {notes}".lower()
    for needle, category in VIDEO_CATEGORIES:
        if needle in blob:
            return category
    return "random-videos"


def is_video_query(text: str) -> bool:
    return bool(_VIDEO_QUERY_RE.search(str(text or "")))


def is_explicit_download_request(text: str) -> bool:
    value = str(text or "").strip()
    if not value or _DOWNLOAD_NEGATION_RE.search(value):
        return False
    return bool(_EXPLICIT_DOWNLOAD_RE.search(value))


def is_confirmed_download_request(text: str) -> bool:
    return bool(_CONFIRM_DOWNLOAD_RE.match(str(text or "")))


def download_confirmation_reply() -> str:
    return "I heard a download request. Say yes download this video to confirm."


def download_declined_reply() -> str:
    return "I heard the confirmation clearly. No downloader is configured, so nothing was downloaded."


def remember_video(
    user_id: str,
    title: str,
    notes: str,
    reply: str = "",
    source: str = "",
) -> dict[str, str]:
    cleaned_title = " ".join(str(title or "").split()) or "watched video"
    cleaned_notes = " ".join(str(notes or "").split())
    cleaned_reply = " ".join(str(reply or "").split())
    category = categorize_video(cleaned_title, cleaned_notes)
    body = (
        f"Title: {cleaned_title}\n"
        f"Source: {source or 'screen while you watched'}\n"
        f"Category: {CATEGORY_LABELS.get(category, category)}\n\n"
        f"What I learned:\n{cleaned_notes or 'No spoken notes were captured.'}\n\n"
        f"What I told you:\n{cleaned_reply or 'I did not describe this video while watching.'}\n"
    )
    topic = f"video {cleaned_title} {time.strftime('%Y%m%d-%H%M%S')}"
    path = save_knowledge(topic, body, category=category)
    remember_result(user_id, topic, body, category=category)
    return {"category": category, "topic": topic, "path": str(path)}


def _read_row(row: dict) -> tuple[str, Path] | None:
    path = Path(str(row.get("path") or ""))
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8"), path
    except OSError:
        return None


def answer_video_query(query: str) -> str:
    value = str(query or "").strip()
    lowered = value.lower()
    if "what videos do you know" in lowered or "video notes" in lowered or "video memory" in lowered:
        listing = format_saved_list("video")
        return listing
    needle = "video"
    for word in re.findall(r"[a-z0-9]+", lowered):
        if word in {"what", "did", "you", "silva", "learn", "say", "think", "was", "that", "the", "about", "tell", "me", "do", "know", "video", "from", "for", "of", "into"}:
            continue
        needle = word
        break
    rows = list_saved(query=needle)
    if not rows:
        return "I don't have a saved video in that category yet."
    for row in rows:
        if any(token in lowered for token in row.get("category", "").split("-")):
            found = _read_row(row)
            if found:
                return " ".join(found[0].split())[:900]
    found = _read_row(rows[-1])
    if not found:
        return "I don't have a saved video in that category yet."
    return " ".join(found[0].split())[:900]
