"""Weather command for Silva."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import requests

from silva.config import load_config, save_config
from silva.gui.weather_popup import ForecastDayDisplay, WeatherDisplay, show_weather_popup
from silva.location import ResolvedLocation, is_wifi_connected, resolve_location

REQUEST_TIMEOUT = 10


@dataclass
class WeatherReport:
    city: str
    temp_f: int
    humidity: int
    wind_mph: int
    conditions: str
    is_day: bool
    latitude: float
    longitude: float
    source: str

    def to_speech(self) -> str:
        period = "daytime" if self.is_day else "nighttime"
        return (
            f"The {period} weather in {self.city} is {self.conditions} with a "
            f"temperature of {self.temp_f} degrees Fahrenheit, humidity at "
            f"{self.humidity} percent, and wind speeds around {self.wind_mph} "
            f"miles per hour."
        )

    def to_display(self, forecast_days: tuple[ForecastDayDisplay, ...] = ()) -> WeatherDisplay:
        return WeatherDisplay(
            city=self.city,
            temp_f=self.temp_f,
            humidity=self.humidity,
            wind_mph=self.wind_mph,
            conditions=self.conditions,
            is_day=self.is_day,
            forecast_days=forecast_days,
        )


def _forecast_days_for_popup() -> tuple[ForecastDayDisplay, ...]:
    """Attach the saved (or freshly skimmed) multi-day outlook to the weather GUI."""
    try:
        from silva.commands.weather_forecast import load_saved_forecast, refresh_forecast

        report = load_saved_forecast()
        if report is None:
            try:
                report = refresh_forecast()
            except Exception:
                return ()
        if report is None or not report.days:
            return ()
        return tuple(
            ForecastDayDisplay(
                weekday=day.weekday,
                high_f=day.high_f,
                low_f=day.low_f,
                conditions=day.conditions,
                rain_chance=day.rain_chance,
            )
            for day in report.days
        )
    except Exception:
        return ()


def _weather_description(code: int) -> str:
    descriptions = {
        0: "clear skies",
        1: "mainly clear",
        2: "partly cloudy",
        3: "overcast",
        45: "foggy",
        48: "foggy",
        51: "light drizzle",
        53: "drizzle",
        55: "heavy drizzle",
        61: "light rain",
        63: "rain",
        65: "heavy rain",
        71: "light snow",
        73: "snow",
        75: "heavy snow",
        80: "rain showers",
        81: "rain showers",
        82: "heavy rain showers",
        95: "thunderstorms",
        96: "thunderstorms with hail",
        99: "thunderstorms with hail",
    }
    return descriptions.get(code, "variable conditions")


def _fetch_open_meteo(location: ResolvedLocation) -> WeatherReport:
    resp = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": location.latitude,
            "longitude": location.longitude,
            "current": (
                "temperature_2m,relative_humidity_2m,weather_code,"
                "wind_speed_10m,is_day"
            ),
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "timezone": "auto",
        },
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    current = resp.json()["current"]

    return WeatherReport(
        city=location.city,
        temp_f=round(current["temperature_2m"]),
        humidity=current["relative_humidity_2m"],
        wind_mph=round(current["wind_speed_10m"]),
        conditions=_weather_description(current["weather_code"]),
        is_day=bool(current["is_day"]),
        latitude=location.latitude,
        longitude=location.longitude,
        source=location.source,
    )


def _fetch_wttr(location: ResolvedLocation) -> WeatherReport:
    resp = requests.get(
        f"http://wttr.in/{location.latitude},{location.longitude}?format=j1",
        timeout=REQUEST_TIMEOUT,
        headers={"User-Agent": "Silva/0.1"},
    )
    resp.raise_for_status()
    data = resp.json()
    current = data["current_condition"][0]
    area = data["nearest_area"][0]["areaName"][0]["value"]

    return WeatherReport(
        city=area,
        temp_f=int(current["temp_F"]),
        humidity=int(current["humidity"]),
        wind_mph=int(current["windspeedMiles"]),
        conditions=current["weatherDesc"][0]["value"].lower().strip(),
        is_day=current.get("is_day") == "yes",
        latitude=location.latitude,
        longitude=location.longitude,
        source=location.source,
    )


def _cache_report(report: WeatherReport) -> None:
    config = load_config()
    config["city"] = report.city
    config["latitude"] = report.latitude
    config["longitude"] = report.longitude
    config["last_weather"] = {
        "city": report.city,
        "temp_f": report.temp_f,
        "humidity": report.humidity,
        "wind_mph": report.wind_mph,
        "conditions": report.conditions,
        "is_day": report.is_day,
        "latitude": report.latitude,
        "longitude": report.longitude,
        "source": report.source,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    config["weather_last_updated"] = config["last_weather"]["updated_at"]
    save_config(config)
    try:
        from silva.dev.stream_deck import publish_weather_tile

        publish_weather_tile()
    except Exception:
        pass


def get_system_weather_report() -> WeatherReport | None:
    """Return the latest cached system weather without hitting the network."""
    return _load_cached_report()


def apply_user_weather_overlay(report: WeatherReport, user_id: str | None) -> WeatherReport:
    """Merge an active user weather report into forecast conditions for display/speech."""
    if not user_id:
        return report
    from silva.commands.weather_feedback import get_active_weather_report

    active = get_active_weather_report(user_id)
    if not active or not active.get("conditions"):
        return report

    return WeatherReport(
        city=report.city,
        temp_f=report.temp_f,
        humidity=report.humidity,
        wind_mph=report.wind_mph,
        conditions=str(active["conditions"]),
        is_day=report.is_day,
        latitude=report.latitude,
        longitude=report.longitude,
        source=f"{report.source}+user_report",
    )


def _load_cached_report() -> WeatherReport | None:
    cached = load_config().get("last_weather")
    if not cached:
        return None
    try:
        return WeatherReport(
            city=cached["city"],
            temp_f=int(cached["temp_f"]),
            humidity=int(cached["humidity"]),
            wind_mph=int(cached["wind_mph"]),
            conditions=cached["conditions"],
            is_day=bool(cached["is_day"]),
            latitude=float(cached["latitude"]),
            longitude=float(cached["longitude"]),
            source=cached.get("source", "cached"),
        )
    except (KeyError, TypeError, ValueError):
        return None


def fetch_weather_report() -> WeatherReport:
    on_wifi = is_wifi_connected()

    if on_wifi:
        location = resolve_location(require_wifi=True, prefer_fresh=True)
        try:
            report = _fetch_open_meteo(location)
        except requests.RequestException:
            report = _fetch_wttr(location)
        _cache_report(report)
        return report

    cached = _load_cached_report()
    if cached:
        return cached

    raise RuntimeError(
        "Not connected to Wi-Fi and no saved weather data is available. "
        "Connect to Wi-Fi for live weather updates."
    )


def show_scheduled_weather_popup(*, user_id: str | None = None) -> bool:
    """Refresh weather and show the popup silently (no speech). Returns True if shown."""
    config = load_config()
    if not config.get("weather_popup_enabled", True):
        return False

    try:
        report = fetch_weather_report()
    except Exception:
        report = get_system_weather_report()
        if report is None:
            return False

    display_report = apply_user_weather_overlay(report, user_id)
    duration = int(config.get("weather_popup_duration", 12))
    forecast_days = _forecast_days_for_popup()
    if forecast_days:
        duration = max(duration, 16)
    show_weather_popup(display_report.to_display(forecast_days), duration=duration)
    return True


def get_weather(*, user_id: str | None = None, refresh: bool = True) -> str:
    from silva.commands.weather_feedback import format_correction_overlay, get_active_weather_report

    config = load_config()
    if refresh:
        report = fetch_weather_report()
    else:
        report = get_system_weather_report()
        if report is None:
            report = fetch_weather_report()

    user_report = get_active_weather_report(user_id or "guest") if user_id else None
    display_report = apply_user_weather_overlay(report, user_id)

    if config.get("weather_popup_enabled", True):
        duration = int(config.get("weather_popup_duration", 12))
        forecast_days = _forecast_days_for_popup()
        if forecast_days:
            duration = max(duration, 16)
        show_weather_popup(display_report.to_display(forecast_days), duration=duration)

    speech_report = display_report if user_report else report
    speech = speech_report.to_speech()
    if user_id and user_report:
        overlay = format_correction_overlay(user_id, report.conditions)
        if overlay:
            speech = overlay + " " + speech
    elif refresh:
        speech = f"Updated just now. {speech}"

    if not is_wifi_connected() and report.source in {"cached", "saved_config_offline"}:
        prefix = "You are offline. Here is your last saved weather report. "
        return prefix + speech

    return speech
