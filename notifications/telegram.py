"""Telegram notifications — silent API, no browser window."""

from __future__ import annotations

import threading

import requests

from silva.logger import log_error, log_info
from silva.notifications.owner_secrets import telegram_settings


def telegram_configured() -> bool:
    return telegram_settings() is not None


def send_telegram_message(message: str, *, reason: str = "alert", chat_id: str | None = None) -> bool:
    settings = telegram_settings()
    if not settings:
        log_info(f"Telegram skipped ({reason}): not configured.")
        return False

    token, default_chat = settings
    target = (chat_id or default_chat or "").strip()
    if not target:
        log_info(f"Telegram skipped ({reason}): no chat id.")
        return False

    body = message.strip()
    if not body:
        return False
    if len(body) > 4000:
        body = body[:3997] + "..."

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": target, "text": body},
            timeout=15,
        )
        resp.raise_for_status()
        log_info(f"Telegram sent — {reason}.")
        return True
    except Exception as exc:
        log_error(f"Telegram send failed ({reason})", exc=exc)
        return False


def send_telegram_async(message: str, *, reason: str = "alert", chat_id: str | None = None) -> None:
    threading.Thread(
        target=send_telegram_message,
        kwargs={"message": message, "reason": reason, "chat_id": chat_id},
        name=f"silva-telegram-{reason}",
        daemon=True,
    ).start()
