"""Silent background weather polling while Silva is active."""

from __future__ import annotations

import threading
import time

from silva.config import load_config
from silva.location import is_wifi_connected
from silva.logger import log_error, log_info

_state = {
    "last_poll": 0.0,
    "in_flight": False,
}
_lock = threading.Lock()


def _poll_interval_seconds() -> int:
    config = load_config()
    try:
        minutes = int(config.get("weather_poll_interval_minutes", 10))
    except (TypeError, ValueError):
        minutes = 10
    return max(1, minutes) * 60


def background_poll_enabled() -> bool:
    return bool(load_config().get("weather_background_poll_enabled", True))


def seconds_until_next_poll() -> float:
    if not background_poll_enabled():
        return float("inf")
    elapsed = time.time() - _state["last_poll"]
    return max(0.0, _poll_interval_seconds() - elapsed)


def silent_weather_refresh(*, force: bool = False) -> bool:
    """Fetch live weather quietly and update the system cache. Returns True if refreshed."""
    if not background_poll_enabled() and not force:
        return False
    if not is_wifi_connected():
        return False

    now = time.time()
    with _lock:
        if not force and now - _state["last_poll"] < _poll_interval_seconds():
            return False
        if _state["in_flight"]:
            return False
        _state["in_flight"] = True

    try:
        from silva.commands.weather import fetch_weather_report
        from silva.commands.weather_forecast import refresh_forecast

        report = fetch_weather_report()
        try:
            forecast = refresh_forecast()
            if forecast.changed:
                log_info(f"Forecast file updated for {forecast.city} ({len(forecast.days)} days).")
        except Exception as forecast_exc:
            log_error("Silent forecast refresh failed", exc=forecast_exc)
        with _lock:
            _state["last_poll"] = time.time()
        log_info(
            f"Weather silently updated: {report.conditions}, {report.temp_f}F "
            f"in {report.city} ({report.source})."
        )
        return True
    except Exception as exc:
        log_error("Silent weather refresh failed", exc=exc)
        return False
    finally:
        with _lock:
            _state["in_flight"] = False


def reset_poll_timer() -> None:
    with _lock:
        _state["last_poll"] = 0.0
