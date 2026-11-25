"""Multi-day public forecast: fetch, cache to .txt, reuse until it changes."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

import requests

from silva.commands.weather import REQUEST_TIMEOUT, _weather_description
from silva.commands.weather_forecast_paths import FORECAST_JSON, FORECAST_TXT, ensure_weather_dir
from silva.config import load_config
from silva.location import ResolvedLocation, is_wifi_connected, resolve_location
from silva.logger import log_error, log_info


@dataclass(frozen=True)
class ForecastDay:
    date: str
    weekday: str
    high_f: int
    low_f: int
    conditions: str
    rain_chance: int

    def to_speech(self, *, city: str, index: int, total: int) -> str:
        label = "today" if index == 0 else self.weekday
        rain = self.rain_chance
        rain_line = (
            f"{rain} percent chance of rain"
            if rain > 0
            else "little to no chance of rain"
        )
        return (
            f"Day {index + 1} of {total} for {city}: {label}, {self.weekday} {self.date}. "
            f"{self.conditions}, high {self.high_f}, low {self.low_f}, {rain_line}."
        )

    def to_txt_line(self) -> str:
        rain = f"{self.rain_chance}% chance of rain"
        return (
            f"{self.weekday} {self.date} — {self.conditions}; "
            f"high {self.high_f}F / low {self.low_f}F; {rain}"
        )


@dataclass
class ForecastReport:
    city: str
    latitude: float
    longitude: float
    source: str
    generated_at: str
    days: list[ForecastDay]
    offline: bool = False
    changed: bool = False

    def signature(self) -> list[tuple]:
        return [
            (day.date, day.high_f, day.low_f, day.conditions, day.rain_chance)
            for day in self.days
        ]

    def to_full_speech(self) -> str:
        if not self.days:
            return "I do not have a saved forecast yet."
        if self.offline:
            prefix = f"You are offline, so here is the last saved forecast for {self.city}. "
        elif self.changed:
            prefix = f"The public outlook changed. Here is the updated forecast for {self.city}. "
        else:
            prefix = f"Here is the saved local forecast for {self.city}. "
        parts = []
        for index, day in enumerate(self.days):
            label = "Today" if index == 0 else day.weekday
            rain = (
                f"{day.rain_chance} percent chance of rain"
                if day.rain_chance > 0
                else "little to no chance of rain"
            )
            parts.append(
                f"{label}: {day.conditions}, high {day.high_f}, low {day.low_f}, {rain}."
            )
        return prefix + " ".join(parts)


def _weekday(date_text: str) -> str:
    try:
        return datetime.strptime(date_text, "%Y-%m-%d").strftime("%A")
    except ValueError:
        return date_text


def _fetch_open_meteo_forecast(location: ResolvedLocation, days: int) -> ForecastReport:
    resp = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": location.latitude,
            "longitude": location.longitude,
            "daily": (
                "weather_code,temperature_2m_max,temperature_2m_min,"
                "precipitation_probability_max"
            ),
            "temperature_unit": "fahrenheit",
            "forecast_days": days,
            "timezone": "auto",
        },
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    daily = resp.json()["daily"]
    dates = daily["time"]
    forecast_days: list[ForecastDay] = []
    for index, date_text in enumerate(dates[:days]):
        code = int(daily["weather_code"][index])
        rain = daily.get("precipitation_probability_max") or [0] * len(dates)
        forecast_days.append(
            ForecastDay(
                date=date_text,
                weekday=_weekday(date_text),
                high_f=round(daily["temperature_2m_max"][index]),
                low_f=round(daily["temperature_2m_min"][index]),
                conditions=_weather_description(code),
                rain_chance=int(rain[index] or 0),
            )
        )
    return ForecastReport(
        city=location.city,
        latitude=location.latitude,
        longitude=location.longitude,
        source="open-meteo",
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        days=forecast_days,
    )


def _fetch_wttr_forecast(location: ResolvedLocation, days: int) -> ForecastReport:
    resp = requests.get(
        f"http://wttr.in/{location.latitude},{location.longitude}?format=j1",
        timeout=REQUEST_TIMEOUT,
        headers={"User-Agent": "Silva/0.1"},
    )
    resp.raise_for_status()
    data = resp.json()
    area = data["nearest_area"][0]["areaName"][0]["value"]
    forecast_days: list[ForecastDay] = []
    for item in data.get("weather", [])[:days]:
        date_text = str(item.get("date", ""))
        hourly = item.get("hourly") or []
        rain_values = []
        for hour in hourly:
            try:
                rain_values.append(int(hour.get("chanceofrain", 0)))
            except (TypeError, ValueError):
                continue
        desc = ""
        if hourly:
            desc = str(hourly[len(hourly) // 2].get("weatherDesc", [{}])[0].get("value", "")).lower()
        forecast_days.append(
            ForecastDay(
                date=date_text,
                weekday=_weekday(date_text),
                high_f=int(item.get("maxtempF", 0)),
                low_f=int(item.get("mintempF", 0)),
                conditions=desc or "variable conditions",
                rain_chance=max(rain_values) if rain_values else 0,
            )
        )
    if not forecast_days:
        raise RuntimeError("wttr.in returned no daily forecast.")
    return ForecastReport(
        city=area or location.city,
        latitude=location.latitude,
        longitude=location.longitude,
        source="wttr.in",
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        days=forecast_days,
    )


def skim_public_forecast(*, days: int | None = None) -> ForecastReport:
    """Fetch a public 3–7 day forecast using local Wi-Fi / IP location."""
    config = load_config()
    wanted = days if days is not None else int(config.get("weather_forecast_days", 7))
    wanted = max(3, min(7, wanted))
    location = resolve_location(require_wifi=True, prefer_fresh=True)
    try:
        return _fetch_open_meteo_forecast(location, wanted)
    except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
        log_error("Open-Meteo forecast skim failed, trying wttr.in", exc=exc)
        return _fetch_wttr_forecast(location, wanted)


def format_forecast_text(report: ForecastReport) -> str:
    lines = [
        "SILVA LOCAL WEATHER FORECAST",
        f"Location: {report.city}",
        f"Updated: {report.generated_at}",
        f"Source: {report.source}",
        f"Days: {len(report.days)}",
        "",
    ]
    for day in report.days:
        lines.append(day.to_txt_line())
    lines.append("")
    lines.append("Ask Silva for the next day, or say open the forecast to view this file.")
    return "\n".join(lines) + "\n"


def _report_from_dict(data: dict[str, Any], *, offline: bool = False) -> ForecastReport | None:
    raw_days = data.get("days")
    if not isinstance(raw_days, list) or not raw_days:
        return None
    days: list[ForecastDay] = []
    for item in raw_days:
        if not isinstance(item, dict):
            continue
        try:
            days.append(
                ForecastDay(
                    date=str(item["date"]),
                    weekday=str(item.get("weekday") or _weekday(str(item["date"]))),
                    high_f=int(item["high_f"]),
                    low_f=int(item["low_f"]),
                    conditions=str(item["conditions"]),
                    rain_chance=int(item.get("rain_chance", 0)),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    if not days:
        return None
    return ForecastReport(
        city=str(data.get("city") or "your area"),
        latitude=float(data.get("latitude") or 0.0),
        longitude=float(data.get("longitude") or 0.0),
        source=str(data.get("source") or "saved"),
        generated_at=str(data.get("generated_at") or ""),
        days=days,
        offline=offline,
    )


def load_saved_forecast() -> ForecastReport | None:
    ensure_weather_dir()
    if not FORECAST_JSON.exists():
        return None
    try:
        data = json.loads(FORECAST_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return _report_from_dict(data, offline=True)


def save_forecast(report: ForecastReport) -> None:
    ensure_weather_dir()
    payload = {
        "city": report.city,
        "latitude": report.latitude,
        "longitude": report.longitude,
        "source": report.source,
        "generated_at": report.generated_at,
        "days": [asdict(day) for day in report.days],
    }
    FORECAST_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if FORECAST_TXT.exists():
        FORECAST_TXT.unlink()
    FORECAST_TXT.write_text(format_forecast_text(report), encoding="utf-8")
    log_info(f"Weather forecast saved to {FORECAST_TXT}")


def refresh_forecast(*, days: int | None = None, force: bool = False) -> ForecastReport:
    """Skim public forecast when online; keep the .txt file until the outlook changes."""
    saved = load_saved_forecast()
    if not is_wifi_connected():
        if saved is not None:
            saved.offline = True
            return saved
        raise RuntimeError(
            "Not connected to Wi-Fi and no saved forecast is available. "
            "Connect to Wi-Fi so I can skim the public outlook."
        )

    try:
        live = skim_public_forecast(days=days)
    except Exception as exc:
        log_error("Live forecast skim failed", exc=exc)
        if saved is not None:
            saved.offline = True
            return saved
        raise

    if saved is not None and saved.signature() == live.signature() and not force:
        log_info("Public forecast unchanged — keeping saved forecast.txt")
        live.changed = False
        live.generated_at = saved.generated_at
        return live

    save_forecast(live)
    live.changed = saved is not None and saved.signature() != live.signature()
    return live
