"""Storage paths for Silva multi-day weather forecasts."""

from __future__ import annotations

from pathlib import Path

from silva.config import CONFIG_DIR

WEATHER_DIR = CONFIG_DIR / "weather"
FORECAST_TXT = WEATHER_DIR / "forecast.txt"
FORECAST_JSON = WEATHER_DIR / "forecast.json"


def ensure_weather_dir() -> None:
    WEATHER_DIR.mkdir(parents=True, exist_ok=True)
