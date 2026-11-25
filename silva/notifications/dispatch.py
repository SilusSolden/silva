"""Route owner/admin alerts through SMS with Telegram fallback."""

from __future__ import annotations

from silva.logger import log_info
from silva.notifications.sms import send_owner_sms, send_owner_sms_async, sms_configured
from silva.notifications.telegram import send_telegram_async, send_telegram_message, telegram_configured
from silva.users.manager import get_owner, is_owner


def notify_owner(
    message: str,
    *,
    reason: str = "alert",
    force: bool = False,
    prefer_telegram: bool = False,
    chat_id: str | None = None,
) -> bool:
    """Send alert to owner. Tries SMS first unless prefer_telegram; falls back to the other."""
    if prefer_telegram and telegram_configured():
        if send_telegram_message(message, reason=reason, chat_id=chat_id):
            return True
        if sms_configured():
            return send_owner_sms(message, reason=reason, force=force)
        return False

    if sms_configured():
        if send_owner_sms(message, reason=reason, force=force):
            return True
    if telegram_configured():
        return send_telegram_message(message, reason=reason, chat_id=chat_id)
    log_info(f"Notification skipped ({reason}): SMS and Telegram not configured.")
    return False


def notify_owner_async(
    message: str,
    *,
    reason: str = "alert",
    force: bool = False,
    prefer_telegram: bool = False,
    chat_id: str | None = None,
) -> None:
    from threading import Thread

    Thread(
        target=notify_owner,
        kwargs={
            "message": message,
            "reason": reason,
            "force": force,
            "prefer_telegram": prefer_telegram,
            "chat_id": chat_id,
        },
        name=f"silva-notify-{reason}",
        daemon=True,
    ).start()


def notify_user_protection(
    user: dict,
    message: str,
    *,
    reason: str = "protection",
    force: bool = False,
    prefer_telegram: bool = True,
) -> bool:
    """Notify owner or admin who enabled protection on their profile."""
    from silva.security.protection_protocol import protection_contact_for_user

    if is_owner(user):
        contact = protection_contact_for_user(user.get("id", ""))
        chat_id = contact.get("telegram_chat_id")
        return notify_owner(
            message,
            reason=reason,
            force=force,
            prefer_telegram=prefer_telegram,
            chat_id=chat_id,
        )

    contact = protection_contact_for_user(user.get("id", ""))
    chat_id = contact.get("telegram_chat_id")
    if chat_id and telegram_configured():
        return send_telegram_message(message, reason=reason, chat_id=chat_id)
    log_info(f"Protection notify skipped for {user.get('name')}: no contact configured.")
    return False


def notify_user_protection_async(
    user: dict,
    message: str,
    *,
    reason: str = "protection",
    force: bool = False,
) -> None:
    from threading import Thread

    Thread(
        target=notify_user_protection,
        kwargs={"message": message, "reason": reason, "force": force},
        name=f"silva-protect-notify-{reason}",
        daemon=True,
    ).start()
