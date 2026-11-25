"""Owner-only SMS alerts — text messages only, never voice calls."""

from silva.notifications.sms import send_owner_sms, sms_configured

__all__ = ["send_owner_sms", "sms_configured"]
