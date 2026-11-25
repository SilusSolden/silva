"""Codebase-aware feature planning that writes placement notes without editing source."""

from __future__ import annotations

import ast
import json
import re
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from silva.config import CONFIG_DIR, load_config

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = CONFIG_DIR / "code_assist"
STATE_FILE = CONFIG_DIR / "code_assist_state.json"
_LOCK = threading.Lock()
_PENDING: dict[str, datetime] = {}

_PLAIN_SCRIPT_EXPLANATIONS = {
    "silva/commands/help_handler.py": (
        "That script decides how I answer help and tell-me-more questions. It checks what you asked, "
        "answers with a built-in explanation when it knows the feature, explains a local script when you name one, "
        "and can skim the web for general topics. If it cannot tell which feature you meant, it remembers the question "
        "so a correction can point it to the right answer."
    ),
    "silva/commands/help_phrases.py": (
        "That script teaches me to recognize help wording, like what a feature does, tell me more, and describe in detail. "
        "It also learns names such as screen monitor and STT fillers so I can answer without running the tool."
    ),
    "silva/conversation/correction_repair.py": (
        "That script fixes a misheard question or pronunciation ask. It remembers the last question, notices phrases like "
        "no I said or I meant, replaces the wrong words, and sends the corrected question back through the normal route."
    ),
    "silva/dev/code_assist.py": (
        "That script lets me read the codebase and explain where a new feature belongs. It writes a plain text placement note, "
        "and it never edits the source code itself."
    ),
    "silva/dev/runtime_hooks.py": (
        "That script applies live patches while I am running, so an update can take effect without a full restart. It also "
        "refreshes changed command words and rebinds the speech handlers to the new versions."
    ),
    "silva/dev/auto_update.py": (
        "That script gathers and reads the list of changed files during an update, then turns those changes into a short "
        "plain-language summary of what is new."
    ),
    "silva/media/image_generator_phrases.py": (
        "That script recognizes Image Studio wording, such as generate, edit, describe this image, save, and close the library. "
        "It helps prevent a normal word like describe from being mistaken for an image command."
    ),
    "silva/stt_fillers.py": (
        "That script spots filler sounds and short movement noises in speech, so a cough, breath, or bump near the microphone "
        "does not become a command."
    ),
    "silva/dev/stream_deck.py": (
        "That script holds Stream Deck bindings and the dynamic weather tile. It maps a button or typed slot name to the same "
        "commands you can say out loud."
    ),
    "silva/dev/screen_monitor.py": (
        "That script can watch the screen only after owner approval. It sends screenshots to a configured helper and learns "
        "wording from what the helper reports; it is off by default."
    ),
    "silva/conversation/crosschat_memory.py": (
        "That script stores the custom tone, traits, ratings, and remembered wording from CrossChat, then applies those style "
        "rules to my replies."
    ),
    "silva/conversation/learned_phrases.py": (
        "That script stores phrases you teach me and the replies you correct, so I can reuse them later instead of guessing."
    ),
}

_START_RE = re.compile(
    r"\b(?:help me (?:code|write|build|add)|help (?:me )?code|code this|add a feature|feature code)\b",
    re.I,
)
_TYPED_INPUT_RE = re.compile(
    r"\b(?:open|show|bring up)\s+(?:the\s+|a\s+)?(?:text\s+)?(?:box|popup|input)\b"
    r"|\b(?:let me|i(?:'ll| will))\s+type\b",
    re.I,
)
_CODE_INTENT_RE = re.compile(
    r"\b(?:add|create|build|implement|write|make|change|fix|update|refactor|design|plan|"
    r"wire|register|handle|support|how to|what i want|code this|add this)\b",
    re.I,
)
_CODE_OBJECT_RE = re.compile(
    r"\b(?:code|codebase|feature|function|module|panel|popup|tile|command|handler|script|"
    r"tool|report|api|test|gui|bug|database|file|class|route|service|stt|tts|silva)\b",
    re.I,
)
_PENDING_TIMEOUT_SECONDS = 300
_STOP_WORDS = {
    "add",
    "also",
    "and",
    "any",
    "can",
    "for",
    "from",
    "help",
    "into",
    "like",
    "make",
    "me",
    "please",
    "that",
    "the",
    "this",
    "to",
    "with",
    "would",
    "you",
    "feature",
    "features",
    "something",
}
_EXCLUDE_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "logs",
    "node_modules",
    "venv",
}


@dataclass(frozen=True)
class CodeSpot:
    path: str
    line_number: int
    reason: str
    code: str


def _key(user_id: str) -> str:
    return str(user_id or "guest")


def enabled() -> bool:
    state = _load_state()
    if state.get("enabled") is False:
        return False
    return bool(load_config().get("code_assist_enabled", True)) and bool(
        load_config().get("code_assist_admins_enabled", True)
    )


def is_allowed(user_id: str = "") -> bool:
    if not enabled():
        return False
    from silva.conversation.speech_policy import is_privileged

    return is_privileged(_key(user_id))


def set_enabled(value: bool) -> bool:
    from silva.conversation.speech_policy import is_privileged
    from silva.users.manager import get_active_user

    user = get_active_user() or {}
    actor = str(user.get("id") or "")
    if not is_privileged(actor):
        return False
    with _LOCK:
        state = _load_state()
        state["enabled"] = bool(value)
        state["updated_at"] = datetime.now().isoformat(timespec="seconds")
        _save_state(state)
    return True


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp = STATE_FILE.with_suffix(".json.tmp")
        temp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        temp.replace(STATE_FILE)
    except OSError:
        pass


def _tokens(definition: str) -> set[str]:
    words = re.findall(r"[a-z0-9_]+", str(definition or "").lower())
    return {word for word in words if len(word) >= 3 and word not in _STOP_WORDS}


def _is_code_request(value: str) -> bool:
    text = str(value or "").strip()
    if not text or _TYPED_INPUT_RE.search(text):
        return False
    words = re.findall(r"[a-z0-9_]+", text.lower())
    if len(words) < 3:
        return False
    return bool(_CODE_INTENT_RE.search(text) or _CODE_OBJECT_RE.search(text))


def scan_codebase(definition: str, *, root: Path | None = None) -> list[CodeSpot]:
    tokens = _tokens(definition)
    if not tokens:
        return []
    base = Path(root or PROJECT_ROOT)
    results: list[CodeSpot] = []
    for path in base.rglob("*.py"):
        if any(part in _EXCLUDE_DIRS for part in path.parts):
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        best: list[tuple[int, int, str]] = []
        for index, line in enumerate(lines, start=1):
            lowered = line.lower()
            score = sum(1 for token in tokens if token in lowered)
            if score <= 0:
                continue
            if re.search(r"\b(?:def|class|register|dispatch|handler|command|import)\b", lowered):
                score += 2
            if lowered.strip().startswith("#"):
                score -= 1
            if score > 0:
                best.append((score, index, line.rstrip()))
        if not best:
            continue
        best.sort(key=lambda item: (-item[0], item[1]))
        for score, index, line in best[:2]:
            reason = "matching feature words" if score <= len(tokens) else "strong handler/config match"
            results.append(
                CodeSpot(
                    path=str(path.relative_to(base)).replace("\\", "/"),
                    line_number=index,
                    reason=reason,
                    code=line[:240],
                )
            )
    results.sort(key=lambda item: item.path)
    return results[:40]


def build_report_text(definition: str, spots: list[CodeSpot]) -> str:
    lines = [
        "Silva code-assist placement report",
        "=" * 36,
        f"Created: {datetime.now():%Y-%m-%d %H:%M:%S}",
        f"Feature definition: {str(definition or '').strip()}",
        "",
        "Silva did not edit any source files.",
        "Add each snippet manually at the listed baseline-code location.",
        "",
        f"Suggested locations: {len(spots)}",
        "",
    ]
    if not spots:
        lines.append("No matching baseline locations were found. Add more specific words and try again.")
        return "\n".join(lines) + "\n"
    for number, spot in enumerate(spots, start=1):
        lines.extend(
            [
                f"{number}. {spot.path}:{spot.line_number}",
                f"   Why: {spot.reason}",
                "   Baseline code:",
                f"   {spot.code}",
                "",
            ]
        )
    lines.extend(
        [
            "Typical placement order:",
            "1. Add config defaults in silva/config.py and config.example.json.",
            "2. Add the feature module beside similar modules.",
            "3. Add phrase detection in silva/commands/intent.py and silva/stt_quick_commands.py.",
            "4. Add the handler in silva/assistant.py and silva/dev/runtime_hooks.py.",
            "5. Add help text, panel controls, and tests.",
            "",
        ]
    )
    return "\n".join(lines)


def write_placement_report(definition: str, *, root: Path | None = None) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = REPORT_DIR / f"code_assist_{stamp}.txt"
    spots = scan_codebase(definition, root=root)
    path.write_text(build_report_text(definition, spots), encoding="utf-8")
    return path


def latest_report_path() -> Path | None:
    if not REPORT_DIR.exists():
        return None
    reports = sorted(REPORT_DIR.glob("code_assist_*.txt"), key=lambda item: item.stat().st_mtime)
    return reports[-1] if reports else None


def has_pending(user_id: str) -> bool:
    key = _key(user_id)
    started = _PENDING.get(key)
    if started is None:
        return False
    if (datetime.now() - started).total_seconds() > _PENDING_TIMEOUT_SECONDS:
        _PENDING.pop(key, None)
        return False
    return True


def begin_request(user_id: str) -> None:
    _PENDING[_key(user_id)] = datetime.now()


def clear_request(user_id: str) -> None:
    _PENDING.pop(_key(user_id), None)


def complete_request(assistant, definition: str) -> bool:
    value = str(definition or "").strip()
    getter = getattr(assistant, "_user_id", None)
    user_id = getter() if callable(getter) else "guest"
    if not _is_code_request(value) or not is_allowed(user_id):
        return False
    path = write_placement_report(value)
    clear_request(user_id)
    assistant.say(
        f"I skimmed the codebase and saved the placement notes to {path}. I did not edit the source.",
        interruptible=False,
    )
    return True


def request_definition(assistant, *, popup: bool = False) -> bool:
    getter = getattr(assistant, "_user_id", None)
    user_id = getter() if callable(getter) else "guest"
    if not is_allowed(user_id):
        assistant.say("Code assist is available to the owner and admins.", interruptible=False)
        return False
    begin_request(user_id)
    assistant.say(
        "Type your code idea in the text box." if popup else
        "Tell me what feature to add, and I'll find the exact baseline spots.",
        interruptible=False,
    )
    if popup or not bool(getattr(assistant, "_voice_mode", True)):
        from silva.gui.text_input_popup import show_text_input_popup

        def _submit(value: str) -> None:
            if not complete_request(assistant, value):
                assistant.say(
                    "That didn't sound like a code change. Describe what to add or change in the code.",
                    interruptible=False,
                )

        show_text_input_popup(
            "Silva code assist",
            "Describe the feature you want to add. Silva will write placement notes only.",
            _submit,
            width=620,
        )
    return True


def parse_code_assist_speech(text: str, *, user_id: str = "") -> dict | None:
    value = str(text or "").strip()
    if not value or not enabled():
        return None
    if has_pending(user_id):
        if _TYPED_INPUT_RE.search(value):
            return {"action": "popup"}
        if _is_code_request(value):
            return {"action": "definition", "value": value}
        return {"action": "clarify"}
    if _START_RE.search(value):
        if _TYPED_INPUT_RE.search(value):
            return {"action": "popup"}
        detail = ""
        match = re.search(r"\b(?:to|for|that|add)\s+(.{8,})$", value, re.I)
        if match:
            detail = match.group(1).strip(" .")
        return {"action": "start", "value": detail}
    return None


def explain_script(topic: str) -> str:
    value = str(topic or "").strip().lower()
    value = re.sub(r"\.(?:py|txt|json)$", "", value)
    value = re.sub(r"\b(?:script|file|module|source|py)\b", " ", value)
    ignored = set(_STOP_WORDS) - {"help"}
    tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", value)
        if token and token not in ignored
    ]
    if not tokens:
        return ""
    candidates = {"_".join(tokens), "".join(tokens)}
    match: Path | None = None
    for path in PROJECT_ROOT.rglob("*.py"):
        if any(part in _EXCLUDE_DIRS for part in path.relative_to(PROJECT_ROOT).parts):
            continue
        stem = path.stem.lower()
        if stem in candidates or stem.replace("_", "") in candidates:
            match = path
            break
    if match is None:
        return ""
    try:
        source = match.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError, UnicodeDecodeError):
        return ""
    relative = match.relative_to(PROJECT_ROOT).as_posix()
    plain = _PLAIN_SCRIPT_EXPLANATIONS.get(relative)
    if plain:
        return plain
    doc = (ast.get_docstring(tree) or "").strip().splitlines()
    summary = (doc[0] if doc else "code for this part of Silva").rstrip(" .")
    readable_name = match.stem.replace("_", " ")
    return (
        f"That script handles {readable_name}. In plain terms: {summary}. "
        "Tell me the part you want if you need a more specific explanation."
    )


def handle_code_assist_speech(assistant, text: str) -> bool:
    getter = getattr(assistant, "_user_id", None)
    user_id = getter() if callable(getter) else "guest"
    action = parse_code_assist_speech(text, user_id=user_id)
    if action is None:
        return False
    if action.get("action") == "start":
        detail = str(action.get("value") or "").strip()
        if detail and _is_code_request(detail):
            return complete_request(assistant, detail)
        return request_definition(assistant)
    if action.get("action") == "popup":
        return request_definition(assistant, popup=True)
    if action.get("action") == "definition":
        return complete_request(assistant, str(action.get("value") or ""))
    if action.get("action") == "clarify":
        return False
    return False


def is_code_assist_command(text: str, *, user_id: str = "") -> bool:
    action = parse_code_assist_speech(text, user_id=user_id)
    return action is not None and action.get("action") != "clarify"
