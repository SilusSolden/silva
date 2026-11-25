from __future__ import annotations

import re

_OPEN_RE = re.compile(
    r"\b(?:open|show|launch|start)\s+(?:the\s+)?(?:image|picture)\s+(?:generator|studio|maker)\b|\bimage studio\b",
    re.I,
)
_GPU_STATUS_RE = re.compile(
    r"\b(?:gpu|cuda)\s+status\b|\bimage\s+(?:generation|generator|studio)\s+status\b|"
    r"\bstatus\s+of\s+(?:the\s+)?image\s+(?:generation|generator|studio)\b|"
    r"\b(?:check|show)\s+(?:the\s+)?(?:gpu|cuda)\s+(?:status|readiness)\b",
    re.I,
)
_GPU_TEST_RE = re.compile(
    r"\b(?:test|check)\s+(?:the\s+)?(?:gpu|cuda|image\s+(?:generation|generator|studio))\b|"
    r"\bimage\s+(?:generation|generator|studio)\s+(?:gpu\s+)?test\b|\bgpu\s+test\b",
    re.I,
)
_GENERATE_RE = re.compile(
    r"\b(?:generate|make|create|draw|build|render)\s+(?:me\s+)?(?:an?\s+|the\s+)?"
    r"(?:image|picture|photo|art|illustration|design|logo)\b",
    re.I,
)
_EDIT_RE = re.compile(
    r"^\s*(?:please\s+)?(?:also\s+)?(?:add|change|make it|turn it|update it|keep adding|with)\b",
    re.I,
)

_DESCRIBE_RE = re.compile(
    r"^(?:can you |could you |would you |please )?describe (?:this|that|the) "
    r"(?:image|picture|photo|art|drawing)\b|"
    r"\bwhat do you see\b|"
    r"\bwhat.s in (?:this|the) (?:image|picture)\b|"
    r"\btell me about (?:this|the) (?:image|picture)\b|"
    r"\bread (?:this|the) (?:image|picture)\b",
    re.I,
)
_DESCRIPTION_REQUEST_RE = re.compile(
    r"\b(?:generate|make|write|give me)\s+(?:me\s+)?(?:an?\s+|the\s+)?"
    r"(?:description|summary|caption)\b",
    re.I,
)
_SAVE_RE = re.compile(
    r"\b(?:save|keep)\s+(?:this|the|that)\s+(?:image|picture|art|design)\b",
    re.I,
)


def match_image_generation_speech(text: str) -> str | None:
    value = str(text or "").strip()
    if not value:
        return None
    if _OPEN_RE.search(value):
        return "open"
    if _GPU_STATUS_RE.search(value):
        return "status"
    if _GPU_TEST_RE.search(value):
        return "test"
    if _SAVE_RE.search(value):
        return "save"
    if _DESCRIPTION_REQUEST_RE.search(value):
        return "describe"
    if _GENERATE_RE.search(value):
        return "generate"
    if _DESCRIBE_RE.search(value):
        return "describe"
    if _EDIT_RE.search(value):
        return "edit"
    return None


def is_image_generation_speech(text: str) -> bool:
    return match_image_generation_speech(text) is not None


def image_prompt(text: str) -> str:
    value = str(text or "").strip()
    value = re.sub(
        r"^\s*(?:please\s+)?(?:can you\s+|could you\s+|would you\s+)?"
        r"(?:generate|make|create|draw|build|render)\s+(?:me\s+)?"
        r"(?:an?\s+|the\s+)?(?:image|picture|photo|art|illustration|design|logo)\s+(?:of\s+|showing\s+|with\s+)?",
        "",
        value,
        flags=re.I,
    )
    return value.strip(" .,!") or "Silva concept image"


def edit_prompt(text: str) -> str:
    value = str(text or "").strip()
    value = re.sub(
        r"^\s*(?:please\s+)?(?:also\s+)?(?:add|change|make it|turn it|update it|keep adding|with)\s+",
        "",
        value,
        flags=re.I,
    )
    return value.strip(" .,!") or "more detail"
