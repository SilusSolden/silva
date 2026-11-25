"""Owner-only secrets (phone, SMS API keys) — never loaded for other profiles."""

from __future__ import annotations

import json
from pathlib import Path

from silva.config import CONFIG_DIR

SECRETS_FILE = CONFIG_DIR / "owner_secrets.json"
EXAMPLE_FILE = Path(__file__).resolve().parents[2] / "owner_secrets.example.json"


def _load_raw() -> dict:
    if not SECRETS_FILE.exists():
        return {}
    try:
        with SECRETS_FILE.open(encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def owner_phone() -> str | None:
    phone = str(_load_raw().get("owner_phone", "")).strip()
    return phone or None


def twilio_settings() -> tuple[str, str, str] | None:
    raw = _load_raw()
    sid = str(raw.get("twilio_account_sid", "")).strip()
    token = str(raw.get("twilio_auth_token", "")).strip()
    from_number = str(raw.get("twilio_from_number", "")).strip()
    if sid and token and from_number:
        return sid, token, from_number
    return None


def email_settings() -> tuple[str, int, str, str, list[str]] | None:
    raw = _load_raw()
    host = str(raw.get("smtp_host", "")).strip()
    user = str(raw.get("smtp_user", "")).strip()
    password = str(raw.get("smtp_password", "")).strip()
    try:
        port = int(raw.get("smtp_port", 587))
    except (TypeError, ValueError):
        port = 587
    recipients = [
        item.strip()
        for item in str(raw.get("admin_emails", "")).split(",")
        if item.strip()
    ]
    if host and user and password:
        return host, port, user, password, recipients
    return None


def phone_visible_to_user(user: dict) -> bool:
    from silva.users.manager import is_owner

    if not is_owner(user):
        return False
    return bool(_load_raw().get("owner_may_view_phone", False))


def telegram_settings() -> tuple[str, str] | None:
    """Return (bot_token, default_chat_id) when configured."""
    raw = _load_raw()
    token = str(raw.get("telegram_bot_token", "")).strip()
    chat_id = str(raw.get("telegram_chat_id", "")).strip()
    if token and chat_id:
        return token, chat_id
    return None


def telegram_chat_id() -> str | None:
    settings = telegram_settings()
    return settings[1] if settings else None

