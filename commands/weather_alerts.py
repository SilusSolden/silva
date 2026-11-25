"""Major weather alert detection and instant popups."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

import requests

from silva.config import CONFIG_DIR, load_config
from silva.location import is_wifi_connected, resolve_location
from silva.logger import log_error, log_info

STATE_FILE = CONFIG_DIR / "weather_alerts_state.json"
REQUEST_TIMEOUT = 12
USER_AGENT = "SilvaAssistant/1.0 (local weather alerts)"

MAJOR_SEVERITIES = {"Extreme", "Severe"}
MAJOR_EVENT_KEYWORDS = (
    "warning",
    "emergency",
    "watch",
    "advisory",
    "storm",
    "tornado",
    "hurricane",
    "flood",
    "blizzard",
    "heat",
    "wind",
    "fire",
)

_lock_state = {"last_poll": 0.0, "in_flight": False}


@dataclass
class WeatherAlert:
    alert_id: str
    event: str
    headline: str
    description: str
    severity: str
    urgency: str
    area: str


def alert_poll_enabled() -> bool:
    return bool(load_config().get("weather_alert_poll_enabled", True))


def alert_poll_interval_seconds() -> int:
    try:
        minutes = int(load_config().get("weather_alert_poll_interval_minutes", 5))
    except (TypeError, ValueError):
        minutes = 5
    return max(1, minutes) * 60


def alert_popup_duration() -> int:
    try:
        return max(10, int(load_config().get("weather_alert_popup_duration", 30)))
    except (TypeError, ValueError):
        return 30


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _is_major_alert(props: dict) -> bool:
    severity = str(props.get("severity", ""))
    event = str(props.get("event", "")).lower()
    if severity in MAJOR_SEVERITIES:
        return True
    return any(keyword in event for keyword in MAJOR_EVENT_KEYWORDS)


def fetch_active_alerts(*, latitude: float, longitude: float) -> list[WeatherAlert]:
    try:
        resp = requests.get(
            f"https://api.weather.gov/alerts/active?point={latitude:.4f},{longitude:.4f}",
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": USER_AGENT, "Accept": "application/geo+json"},
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        log_error("Weather alert fetch failed", exc=exc)
        return []

    alerts: list[WeatherAlert] = []
    for feature in payload.get("features", []):
        props = feature.get("properties") or {}
        if not _is_major_alert(props):
            continue
        alert_id = str(props.get("id") or props.get("@id") or props.get("headline") or "")
        if not alert_id:
            continue
        alerts.append(
            WeatherAlert(
                alert_id=alert_id,
                event=str(props.get("event", "Weather Alert")),
                headline=str(props.get("headline", props.get("event", "Weather Alert"))),
                description=str(props.get("description", "")).strip(),
                severity=str(props.get("severity", "")),
                urgency=str(props.get("urgency", "")),
                area=str(props.get("areaDesc", "")),
            )
        )
    return alerts


def _known_alert_ids(state: dict) -> set[str]:
    items = state.get("known_alert_ids", [])
    if not isinstance(items, list):
        return set()
    return {str(item) for item in items}


def check_weather_alerts(*, force: bool = False, asleep: bool = False) -> list[WeatherAlert]:
    """Poll for new major alerts and show instant popups. Returns newly detected alerts."""
    if not alert_poll_enabled() and not force:
        return []
    if not is_wifi_connected():
        return []

    now = time.time()
    if not force and now - _lock_state["last_poll"] < alert_poll_interval_seconds():
        return []
    if _lock_state["in_flight"]:
        return []

    _lock_state["in_flight"] = True
    _lock_state["last_poll"] = now
    try:
        location = resolve_location()
        alerts = fetch_active_alerts(latitude=location.latitude, longitude=location.longitude)
        state = _load_state()
        known = _known_alert_ids(state)
        current_ids = {alert.alert_id for alert in alerts}
        new_alerts = [alert for alert in alerts if alert.alert_id not in known]

        state["known_alert_ids"] = sorted(current_ids)
        state["last_checked"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _save_state(state)

        if new_alerts:
            from silva.alerts.category_log import log_category_alert
            from silva.gui.weather_popup import show_weather_alert_popup

            for alert in new_alerts:
                log_category_alert(
                    "weather",
                    f"{alert.event} ({alert.severity})",
                    detail=alert.headline,
                    metadata={"area": alert.area, "alert_id": alert.alert_id},
                    asleep=asleep,
                )
                if asleep:
                    pass
                else:
                    show_weather_alert_popup(alert, duration=alert_popup_duration())
                    log_info(f"Weather alert popup shown: {alert.event} ({alert.severity}).")
                try:
                    from silva.notifications.dispatch import notify_owner_async
                    from silva.notifications.sms import may_send_weather_sms

                    if may_send_weather_sms():
                        summary = f"Weather alert: {alert.event}. {alert.headline}"[:300]
                        notify_owner_async(summary, reason="weather_alert")
                except Exception as exc:
                    log_error("Weather alert notification failed", exc=exc)
        return new_alerts
    except Exception as exc:
        log_error("Weather alert check failed", exc=exc)
        return []
    finally:
        _lock_state["in_flight"] = False


def reset_alert_state() -> None:
    _lock_state["last_poll"] = 0.0
    if STATE_FILE.exists():
        STATE_FILE.unlink(missing_ok=True)
