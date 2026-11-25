"""Send SMS to the owner via Twilio — text only, no calls."""

from __future__ import annotations

import threading

import requests

from silva.config import load_config
from silva.logger import log_error, log_info
from silva.notifications.owner_secrets import owner_phone, twilio_settings
from silva.users.manager import get_owner, is_owner

_lock = threading.Lock()
_last_send_at = 0.0


def sms_configured() -> bool:
    return owner_phone() is not None and twilio_settings() is not None


def _sms_enabled() -> bool:
    config = load_config()
    if bool(config.get("sms_dormant", False)):
        return False
    return bool(config.get("sms_alerts_enabled", True))


def _min_interval_seconds() -> int:
    try:
        return max(30, int(load_config().get("sms_min_interval_seconds", 120)))
    except (TypeError, ValueError):
        return 120


def send_owner_sms(message: str, *, reason: str = "alert", force: bool = False) -> bool:
    """Send a short SMS to the owner. Returns True when sent."""
    if not _sms_enabled() and not force:
        return False

    phone = owner_phone()
    twilio = twilio_settings()
    if not phone or not twilio:
        log_info(f"SMS skipped ({reason}): owner phone or Twilio not configured.")
        return False

    body = message.strip()
    if not body:
        return False
    if len(body) > 320:
        body = body[:317] + "..."

    global _last_send_at
    now = __import__("time").time()
    with _lock:
        if not force and now - _last_send_at < _min_interval_seconds():
            return False
        _last_send_at = now

    sid, token, from_number = twilio
    try:
        resp = requests.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
            auth=(sid, token),
            data={"To": phone, "From": from_number, "Body": body},
            timeout=15,
        )
        resp.raise_for_status()
        owner = get_owner()
        log_info(f"SMS sent to owner ({owner.get('name', 'owner')}) — {reason}.")
        return True
    except Exception as exc:
        log_error(f"SMS send failed ({reason})", exc=exc)
        return False


def send_owner_sms_async(message: str, *, reason: str = "alert", force: bool = False) -> None:
    threading.Thread(
        target=send_owner_sms,
        kwargs={"message": message, "reason": reason, "force": force},
        name=f"silva-sms-{reason}",
        daemon=True,
    ).start()


def may_send_weather_sms() -> bool:
    config = load_config()
    if bool(config.get("sms_dormant", False)):
        return False
    return bool(config.get("sms_weather_alerts_enabled", True))


def may_send_startup_sms() -> bool:
    config = load_config()
    if bool(config.get("sms_dormant", False)):
        return False
    return bool(config.get("sms_startup_ping_enabled", True))


def owner_can_use_sms(user: dict | None = None) -> bool:
    user = user or get_owner()
    return is_owner(user) and sms_configured() and _sms_enabled()
