from __future__ import annotations

import smtplib
from email.message import EmailMessage

from silva.logger import log_error, log_info
from silva.notifications.owner_secrets import email_settings

SUBJECT_PREFIX = "Silva update decision"


def send_email_reply(to: str, subject: str, body: str) -> bool:
    settings = email_settings()
    if settings is None:
        log_info("Email reply skipped: SMTP is not configured.")
        return False
    host, port, user, password = settings
    recipients = [item.strip() for item in str(to or "").split(",") if item.strip()]
    if not recipients:
        recipients = list(settings[4])
    if not recipients:
        log_info("Email reply skipped: no recipient configured.")
        return False
    message = EmailMessage()
    message["From"] = user
    message["To"] = ", ".join(recipients)
    message["Subject"] = f"{SUBJECT_PREFIX}: {subject}" if subject else SUBJECT_PREFIX
    message.set_content(str(body or ""))
    try:
        with smtplib.SMTP(host, port, timeout=15) as client:
            client.starttls()
            client.login(user, password)
            client.send_message(message)
        log_info(f"Email reply sent to {len(recipients)} recipient(s).")
        return True
    except Exception as exc:
        log_error("Email reply failed", exc=exc)
        return False
