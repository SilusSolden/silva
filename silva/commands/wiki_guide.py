"""Step-by-step Wikipedia crafting guides with resume and recall."""

from __future__ import annotations

import re

from silva.commands.wikipedia import _fetch_article, _search_title
from silva.history_store import (
    clear_active_guide,
    find_guide,
    get_recent_conversations,
    get_recent_guides,
    get_recent_searches,
    load_active_guide,
    record_guide,
    record_search,
    save_active_guide,
)
from silva.logger import log_info

_MATERIALS_RE = re.compile(
    r"(?:(?:materials|ingredients|tools|supplies|equipment|you will need)[:\s]*\n)(.+?)(?:\n\n|\n(?:\d+\.|step|instructions|method|directions|procedure)\b)",
    re.I | re.S,
)
_STEP_LINE_RE = re.compile(
    r"^\s*(?:step\s*)?(\d+)[\.\):\-]\s*(.+?)\s*$",
    re.I | re.M,
)
_BULLET_RE = re.compile(r"^\s*[\-*•]\s*(.+?)\s*$", re.M)


def _normalize(text: str) -> str:
    text = text.strip().lower()
    text = text.replace("'", "")
    return re.sub(r"\s+", " ", text)


def _extract_materials(article: str) -> list[str]:
    match = _MATERIALS_RE.search(article)
    if match:
        block = match.group(1)
        items = _BULLET_RE.findall(block)
        if items:
            return [item.strip() for item in items[:20] if item.strip()]
        return [line.strip() for line in block.split("\n") if line.strip()][:20]

    intro = article[:1200]
    bullets = _BULLET_RE.findall(intro)
    if len(bullets) >= 2:
        return [b.strip() for b in bullets[:15]]
    return []


def _extract_steps(article: str) -> list[str]:
    steps: list[tuple[int, str]] = []
    for match in _STEP_LINE_RE.finditer(article):
        num = int(match.group(1))
        text = match.group(2).strip()
        if len(text) > 8:
            steps.append((num, text))

    if steps:
        steps.sort(key=lambda item: item[0])
        return [text for _, text in steps]

    for section in re.split(r"\n(?:instructions|directions|method|procedure|steps)\s*[:\n]", article, flags=re.I):
        bullets = _BULLET_RE.findall(section)
        if len(bullets) >= 3:
            return [b.strip() for b in bullets[:30]]

    sentences = re.split(r"(?<=[.!?])\s+", article)
    long_sentences = [s.strip() for s in sentences if len(s.split()) >= 6]
    if len(long_sentences) >= 4:
        return long_sentences[:20]

    return []


def _format_materials(materials: list[str]) -> str:
    if not materials:
        return ""
    lines = "\n".join(f"- {item}" for item in materials)
    return f"Here is what you will need:\n{lines}"


def _format_step(index: int, total: int, text: str) -> str:
    return f"Step {index} of {total}: {text}"


def _guide_payload(
    user_id: str,
    *,
    query: str,
    title: str,
    materials: list[str],
    steps: list[str],
    current_step: int = 0,
) -> dict:
    return {
        "user_id": user_id,
        "query": query,
        "title": title,
        "materials": materials,
        "steps": steps,
        "current_step": current_step,
        "total_steps": len(steps),
    }


def is_crafting_query(text: str) -> bool:
    normalized = _normalize(text)
    triggers = (
        "how do i make",
        "how do you make",
        "how to make",
        "how do i build",
        "how to build",
        "how do i form",
        "how to form",
        "how do i craft",
        "how to craft",
        "recipe for",
        "steps to make",
        "guide for making",
        "construction steps for",
        "how do i construct",
        "how to construct",
    )
    return any(normalized.startswith(t + " ") or normalized == t for t in triggers)


def is_guide_control(text: str) -> str | None:
    normalized = _normalize(text)
    if normalized in {"where am i", "where am i at", "where am i now", "where am i right now"}:
        return None
    controls = {
        "next step": "next",
        "next": "next",
        "continue guide": "next",
        "continue": "next",
        "keep going": "next",
        "previous step": "prev",
        "go back": "prev",
        "back a step": "prev",
        "repeat step": "repeat",
        "repeat that step": "repeat",
        "say that again": "repeat",
        "where was i": "status",
        "what step am i on": "status",
        "what step am i at": "status",
        "resume guide": "status",
        "cancel guide": "cancel",
        "stop guide": "cancel",
        "end guide": "cancel",
    }
    if normalized in controls:
        return controls[normalized]
    if normalized.startswith("help me from step "):
        return "jump"
    if normalized.startswith("continue from step "):
        return "jump"
    if normalized.startswith("start from step "):
        return "jump"
    if normalized.startswith("resume from step "):
        return "jump"
    return None


def _parse_step_number(text: str) -> int | None:
    match = re.search(r"step\s*(\d+)", text, re.I)
    if match:
        return int(match.group(1))
    match = re.search(r"(\d+)\s*$", text.strip())
    if match:
        return int(match.group(1))
    return None


def start_guide(user_id: str, query: str) -> str:
    query = query.strip()
    if not query:
        raise RuntimeError("Tell me what you want to make or look up.")

    title = _search_title(query)
    if title is None:
        raise RuntimeError(f"I could not find a Wikipedia article for '{query}'.")

    article = _fetch_article(title)
    materials = _extract_materials(article)
    steps = _extract_steps(article)

    record_search(user_id, kind="wikipedia_guide", query=query, title=title, summary=article[:300])
    log_info(f"Wikipedia guide started: {title}\n{article}")

    if not steps:
        intro = f"I found Wikipedia information about {title}, but it is not in clear numbered steps."
        if materials:
            intro += f"\n\n{_format_materials(materials)}"
        intro += f"\n\nHere is the overview:\n{article[:2500]}"
        return intro

    guide = _guide_payload(user_id, query=query, title=title, materials=materials, steps=steps, current_step=0)
    save_active_guide(user_id, guide)
    record_guide(user_id, guide)

    parts = [f"I found a guide for {title} with {len(steps)} steps."]
    if materials:
        parts.append(_format_materials(materials))
    parts.append(_format_step(1, len(steps), steps[0]))
    parts.append("Say next step when you are ready, or tell me a step number to jump to.")
    return "\n\n".join(parts)


def handle_guide_control(user_id: str, text: str) -> str | None:
    action = is_guide_control(text)
    if action is None:
        return None

    guide = load_active_guide(user_id)
    if guide is None and action in {"next", "prev", "repeat", "status", "jump"}:
        if action == "status":
            return recall_status(user_id)
        return "You do not have an active guide. Say how to make something to start one."

    if action == "cancel":
        clear_active_guide(user_id)
        return "Guide cancelled. Your progress is still saved in your Silva history."

    steps: list[str] = guide.get("steps", [])
    total = len(steps)
    if not steps:
        clear_active_guide(user_id)
        return "That guide has no steps left."

    index = int(guide.get("current_step", 0))

    if action == "jump":
        step_num = _parse_step_number(text)
        if step_num is None or step_num < 1 or step_num > total:
            return f"Tell me a step number between 1 and {total}."
        index = step_num - 1

    elif action == "next":
        index = min(index + 1, total - 1)

    elif action == "prev":
        index = max(index - 1, 0)

    elif action == "repeat":
        pass

    elif action == "status":
        title = guide.get("title", "your project")
        return (
            f"You are on step {index + 1} of {total} for {title}. "
            f"Say next step to continue, or help me from step {index + 1}."
        )

    guide["current_step"] = index
    save_active_guide(user_id, guide)
    record_guide(user_id, guide)

    if index >= total - 1 and action == "next":
        clear_active_guide(user_id)
        return (
            f"Step {total} of {total}: {steps[index]}\n\n"
            f"That was the last step for {guide.get('title', 'this project')}. "
            "Nice work. The full guide stays in your Silva history."
        )

    return _format_step(index + 1, total, steps[index])


def resume_guide(user_id: str, query_hint: str = "") -> str:
    active = load_active_guide(user_id)
    if active and (not query_hint or query_hint.lower() in str(active.get("title", "")).lower()):
        index = int(active.get("current_step", 0))
        steps = active.get("steps", [])
        title = active.get("title", "your project")
        if not steps:
            return f"I still have {title} saved, but there are no steps to continue."
        return (
            f"Continuing {title}. You were on step {index + 1} of {len(steps)}.\n\n"
            f"{_format_step(index + 1, len(steps), steps[index])}\n\n"
            "Say next step when you are ready."
        )

    past = find_guide(user_id, query_hint) if query_hint else None
    if past is None:
        guides = get_recent_guides(user_id, limit=1)
        past = guides[0] if guides else None

    if past is None:
        return "I do not have a saved guide to resume. Say how to make something to start one."

    save_active_guide(user_id, past)
    index = int(past.get("current_step", 0))
    steps = past.get("steps", [])
    title = past.get("title", "your project")
    if not steps:
        return f"I found {title} in your history but it has no step list."
    return (
        f"Resuming {title} from step {index + 1} of {len(steps)}.\n\n"
        f"{_format_step(index + 1, len(steps), steps[index])}"
    )


def recall_history(user_id: str, *, kind: str = "all", limit: int = 5) -> str:
    parts: list[str] = []
    if kind in {"all", "searches"}:
        searches = get_recent_searches(user_id, limit=limit)
        if searches:
            lines = [f"- {s.get('title', s.get('query', '?'))} ({s.get('time', '')})" for s in searches]
            parts.append("Recent searches:\n" + "\n".join(lines))
    if kind in {"all", "guides"}:
        guides = get_recent_guides(user_id, limit=limit)
        if guides:
            lines = []
            for g in guides:
                step = int(g.get("current_step", 0)) + 1
                total = g.get("total_steps", len(g.get("steps", [])))
                lines.append(f"- {g.get('title', '?')} step {step}/{total} ({g.get('time', '')})")
            parts.append("Recent crafting guides:\n" + "\n".join(lines))
    if kind in {"all", "conversations"}:
        chats = get_recent_conversations(user_id, limit=limit)
        if chats:
            lines = [f"- You: {c.get('user', '')[:60]} | Silva: {c.get('ai', '')[:60]}" for c in chats]
            parts.append("Recent conversations:\n" + "\n".join(lines))

    if not parts:
        return "Your Silva history is empty so far."
    return "\n\n".join(parts)


def recall_status(user_id: str) -> str:
    active = load_active_guide(user_id)
    if active:
        index = int(active.get("current_step", 0))
        total = active.get("total_steps", len(active.get("steps", [])))
        return (
            f"Active guide: {active.get('title', 'unknown')}. "
            f"Step {index + 1} of {total}. Say next step or help me from step {index + 1}."
        )
    return recall_history(user_id, kind="guides", limit=3)
