"""Voice commands for opening the Silva System Panel."""

from __future__ import annotations

import re
from dataclasses import dataclass

from silva.dev.panel_instance import open_system_panel
from silva.logger import log_info
from silva.users.manager import get_active_user, is_owner
from silva.users.profile_access import can_open_control_panel
from silva.users.system_identity import is_main_owner_system

_OPEN_WORD_RE = re.compile(
    r"\b(open|show|launch|start|bring up|pull up|display|take me to)\b",
    re.I,
)
_PANEL_RE = re.compile(r"\b(?:system|dev(?:eloper)?)\s+panel\b", re.I)

_TAB_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "dev_branch_votes",
        "13. Dev Branch & Votes",
        re.compile(r"\b(?:dev branch|feature votes?|voting panel)\b", re.I),
    ),
    (
        "crosschat_stream_deck",
        "11. CrossChat & Deck",
        re.compile(r"\b(?:cross ?chat|stream deck|deck tile|deck button|custom instructions?)\b", re.I),
    ),
    (
        "team_updates",
        "10. Team Updates",
        re.compile(r"\b(?:team updates?|submit update|approve update|reject update)\b", re.I),
    ),
    (
        "future_tasks",
        "9. Future Tasks",
        re.compile(r"\b(?:future tasks?|future updates?|task list)\b", re.I),
    ),
    (
        "admin_access",
        "8. Admin Access",
        re.compile(r"\b(?:admin access|admin controls?|access controls?)\b", re.I),
    ),
    (
        "voice_access_requests",
        "7. Voice Access",
        re.compile(r"\b(?:voice access|voice controls?|voice requests?)\b", re.I),
    ),
    (
        "feature_request_review",
        "4. Requests",
        re.compile(r"\b(?:feature requests?|requests? (?:panel|tab)|request review)\b", re.I),
    ),
    (
        "admin_update_queue",
        "5. Update Queue",
        re.compile(r"\b(?:update queue|staged updates?|admin update queue)\b", re.I),
    ),
    (
        "code_lab",
        "6. Code Lab",
        re.compile(r"\b(?:code lab|code check(?:er)?|static code checks?)\b", re.I),
    ),
    (
        "live_update",
        "3. Live Update",
        re.compile(r"\b(?:live update|update tab)\b", re.I),
    ),
    (
        "train",
        "2. Train",
        re.compile(r"\b(?:train tab|training tab|speech training)\b", re.I),
    ),
    (
        "test",
        "1. Test",
        re.compile(r"\b(?:test tab|testing tab)\b", re.I),
    ),
)


@dataclass(frozen=True)
class SystemPanelSpeech:
    tab_id: str | None = None
    title: str | None = None


def match_system_panel_speech(text: str) -> SystemPanelSpeech | None:
    stripped = str(text or "").strip()
    if not stripped:
        return None
    wants_panel = bool(_PANEL_RE.search(stripped))
    wants_open = bool(_OPEN_WORD_RE.search(stripped))
    if not wants_panel and not wants_open:
        return None

    if not (wants_panel and wants_open):
        from silva.commands.help_phrases import is_capability_ask, is_feature_detail_ask, is_help_request

        if is_help_request(stripped) or is_feature_detail_ask(stripped) or is_capability_ask(stripped):
            return None

    for tab_id, title, pattern in _TAB_PATTERNS:
        if pattern.search(stripped):
            return SystemPanelSpeech(tab_id=tab_id, title=title)

    if wants_panel:
        return SystemPanelSpeech()
    return None


def _panel_user(user: dict | None) -> dict:
    candidate = user or {}
    if can_open_control_panel(candidate):
        return candidate
    candidate_id = str(candidate.get("id") or "")
    stale_local_identity = candidate_id in {"", "guest"}
    if is_main_owner_system() and (stale_local_identity or is_owner(candidate)):
        fresh = get_active_user() or {}
        if is_owner(fresh):
            log_info("Main-system owner refreshed for System Panel voice access.")
            return fresh
    return candidate


def handle_system_panel_speech(assistant, text: str, user: dict) -> bool:
    speech = match_system_panel_speech(text)
    if speech is None:
        return False

    user = _panel_user(user)
    if not can_open_control_panel(user):
        assistant.say(
            "Only the owner or a tier 4 admin can open the System Panel.",
            interruptible=False,
        )
        return True

    from silva.security.owner_reconfirm import require_owner_confirmation

    if not require_owner_confirmation(assistant, action="System Panel"):
        return True

    open_system_panel(tab_id=speech.tab_id, title=speech.title)
    label = speech.title or "system panel"
    log_info(f"Opened System Panel by voice: {label}")
    assistant.say(f"Opening {label}.", interruptible=False)
    return True
