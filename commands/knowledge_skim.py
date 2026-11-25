"""Skim Wikipedia and public web results without opening a browser."""

from __future__ import annotations

import re
from dataclasses import dataclass

from silva.commands.knowledge_phrases import KnowledgeSpeech, match_knowledge_speech
from silva.commands.knowledge_store import (
    STORAGE_REFUSAL,
    category_for,
    format_saved_list,
    last_result,
    read_saved,
    remember_result,
    save_knowledge,
)
from silva.commands.visual_guide_search import search_snippets
from silva.commands.wikipedia import _fetch_article, _search_title
from silva.history_store import record_search
from silva.logger import log_error, log_info
from silva.storage.drives import StorageRefused

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_MAX_SPEECH = 720
_MAX_LIST = 250
_LIST_HINTS = {
    "medicine names": "list of drugs",
    "medicain names": "list of drugs",
    "medication names": "list of drugs",
    "medications": "list of drugs",
    "meds names": "list of drugs",
    "drug names": "list of drugs",
    "drugs": "list of drugs",
    "prescription names": "list of drugs",
}

_IMPOSSIBLE_REPLY = (
    "I can't copy all of Wikipedia or the whole internet. "
    "Ask for one topic, or a list I can actually skim, like medicine names, "
    "and I can save that to a file."
)


@dataclass
class SkimResult:
    title: str
    spoken: str
    full: str
    items: list[str]


def _web_lines(query: str, *, limit: int = 3) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    try:
        results = search_snippets(query, max_results=6)
    except Exception as exc:
        log_error("Knowledge web skim failed", exc=exc)
        return lines
    for item in results:
        snippet = re.sub(r"\s+", " ", str(item.get("snippet") or "")).strip()
        title = re.sub(r"\s+", " ", str(item.get("title") or "")).strip()
        if len(snippet) < 24:
            continue
        key = snippet[:80].lower()
        if key in seen:
            continue
        seen.add(key)
        if title and title.lower() not in snippet.lower()[:48]:
            lines.append(f"{title}: {snippet}")
        else:
            lines.append(snippet)
        if len(lines) >= limit:
            break
    return lines


def web_addendum(query: str) -> str:
    lines = _web_lines(query, limit=2)
    if not lines:
        return ""
    return "Also from a web skim: " + " ".join(lines)


def _wiki_article(query: str) -> tuple[str, str]:
    try:
        title = _search_title(query)
        if not title:
            return "", ""
        article = _fetch_article(title)
        return title, article
    except Exception as exc:
        log_error("Knowledge Wikipedia skim failed", exc=exc)
        return "", ""


def _clip_speech(text: str, limit: int = _MAX_SPEECH) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rsplit(" ", 1)[0] + "."


def skim_topic(query: str) -> SkimResult:
    query = query.strip()
    title, article = _wiki_article(query)
    web_lines = _web_lines(query, limit=3)
    if not title:
        fallback_title, fallback_article = _wiki_article(f"{query} overview")
        title, article = fallback_title, fallback_article

    parts: list[str] = []
    if article:
        sentences = [s.strip() for s in _SENTENCE_RE.split(article) if s.strip()]
        parts.append(" ".join(sentences[:4]) if sentences else article[:800])
    if web_lines:
        parts.append("Web skim: " + " ".join(web_lines[:2]))
    spoken = _clip_speech(" ".join(parts) if parts else "")
    full_bits = []
    if title:
        full_bits.append(f"Wikipedia: {title}")
    if article:
        full_bits.append(article)
    if web_lines:
        full_bits.append("Web skim:\n- " + "\n- ".join(web_lines))
    full = "\n\n".join(full_bits).strip()
    return SkimResult(title=title or query, spoken=spoken, full=full, items=[])


def _list_items(text: str) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for raw in (text or "").splitlines():
        line = re.sub(r"^[\s\-*•]+\s*", "", raw).strip()
        line = re.sub(r"^\d+[\.)]\s*", "", line).strip()
        if not line or line.endswith(":") or len(line) < 2 or len(line) > 72:
            continue
        if line.endswith(".") and line.count(" ") > 4:
            continue
        if line.count(" ") > 6:
            continue
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(line)
        if len(items) >= _MAX_LIST:
            break
    return items


def skim_catalog(topic: str) -> SkimResult:
    topic = topic.strip()
    search_q = _LIST_HINTS.get(topic.lower(), f"list of {topic}")
    title, article = _wiki_article(search_q)
    if not article:
        title, article = _wiki_article(topic)
    items = _list_items(article)
    web_lines = _web_lines(search_q, limit=3)
    if len(items) < 8:
        for line in web_lines:
            for chunk in re.split(r"[;•|]", line):
                piece = chunk.strip(" .")
                if 2 <= len(piece) <= 60 and piece.count(" ") <= 5:
                    if piece.lower() not in {x.lower() for x in items}:
                        items.append(piece)
                if len(items) >= _MAX_LIST:
                    break
    full_bits = [f"List: {title or topic}"]
    if items:
        full_bits.append("\n".join(f"- {name}" for name in items))
    elif article:
        full_bits.append(article)
    if web_lines:
        full_bits.append("Web skim:\n- " + "\n- ".join(web_lines))
    full = "\n\n".join(full_bits).strip()
    if items:
        sample = ", ".join(items[:8])
        extra = f" and {len(items) - 8} more" if len(items) > 8 else ""
        spoken = f"I found {len(items)} names, including {sample}{extra}."
    else:
        spoken = _clip_speech(article or " ".join(web_lines))
    return SkimResult(title=title or topic, spoken=spoken, full=full, items=items)


def _related_queries(topic: str) -> list[str]:
    base = re.sub(r"\s+", " ", topic.strip())
    if not base:
        return []
    extras = [f"{base} types", f"{base} uses"]
    return [item for item in extras if item.lower() != base.lower()][:2]


def _save_and_say(
    user_id: str,
    topic: str,
    result: SkimResult,
    *,
    empty_msg: str,
    related: bool = True,
) -> str:
    if not result.full:
        return empty_msg
    cat = category_for(topic)
    remember_result(user_id, result.title or topic, result.full, category=cat)
    record_search(user_id, kind="knowledge", query=topic, title=result.title, summary=result.spoken[:300])
    try:
        path = save_knowledge(result.title or topic, result.full, category=cat)
    except StorageRefused:
        return STORAGE_REFUSAL
    extra = 0
    if related:
        for query in _related_queries(topic):
            related_result = skim_topic(query)
            if not related_result.full:
                continue
            try:
                save_knowledge(related_result.title or query, related_result.full, category=cat)
                extra += 1
            except StorageRefused:
                break
    log_info(f"Knowledge saved to {path} related={extra}")
    spoken = result.spoken or "Saved."
    extra_bit = f" I also saved {extra} related file{'s' if extra != 1 else ''} in {cat}." if extra else f" Category {cat}."
    return f"I saved what I found to {path}.{extra_bit} {spoken}"


def handle_knowledge_speech(user_id: str, text: str) -> str | None:
    speech = match_knowledge_speech(text)
    if speech is None:
        return None
    return _run_knowledge(user_id, speech)


def _run_knowledge(user_id: str, speech: KnowledgeSpeech) -> str:
    if speech.action == "impossible":
        return _IMPOSSIBLE_REPLY

    if speech.action == "set_drive":
        from silva.storage.drives import set_data_drive

        return set_data_drive(speech.query)

    if speech.action == "drive_status":
        from silva.storage.drives import describe_data_drive

        return describe_data_drive()

    if speech.action == "retrieve":
        if not speech.query:
            return format_saved_list()
        found = read_saved(speech.query)
        if found is None:
            return format_saved_list(speech.query)
        text, path = found
        spoken = _clip_speech(text, limit=500)
        return f"From {path.drive or path} in {path.parent.name}: {spoken}"

    if speech.action == "save_last":
        last = last_result(user_id)
        if last is None:
            return "I don't have a lookup to save yet. Ask me to look something up first."
        try:
            path = save_knowledge(last["topic"], last["body"], category=last.get("category") or None)
        except StorageRefused:
            return STORAGE_REFUSAL
        log_info(f"Last knowledge saved to {path}")
        return f"I saved the last lookup to {path}."

    query = speech.query.strip()
    if not query or query in {"this", "that", "it", "them"}:
        return "Tell me what you want me to look up."

    try:
        if speech.action == "catalog":
            result = skim_catalog(query)
            empty = f"I could not skim a usable list of {query}. Try a narrower topic."
            if speech.store:
                return _save_and_say(user_id, query, result, empty_msg=empty, related=False)
            if not result.full:
                return empty
            remember_result(user_id, result.title or query, result.full)
            record_search(user_id, kind="knowledge", query=query, title=result.title, summary=result.spoken[:300])
            return result.spoken or empty
        result = skim_topic(query)
        if speech.action == "store" or speech.store:
            return _save_and_say(
                user_id,
                query,
                result,
                empty_msg=f"I skimmed for {query} but could not pull enough to save.",
            )
        if not result.full:
            return f"I skimmed for {query} but could not pull a clear answer."
        remember_result(user_id, result.title or query, result.full)
        record_search(user_id, kind="knowledge", query=query, title=result.title, summary=result.spoken[:300])
        label = result.title if result.title else query
        return f"Here's what I found about {label}. {result.spoken}"
    except Exception as exc:
        log_error("Knowledge skim failed", exc=exc)
        return "I could not skim that right now."
