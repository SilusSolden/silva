"""Speak the full saved local forecast, with rain chance for each day."""

from __future__ import annotations

from silva.commands.news_display import open_briefing_txt
from silva.commands.weather_forecast import load_saved_forecast, refresh_forecast
from silva.commands.weather_forecast_paths import FORECAST_TXT, ensure_weather_dir
from silva.commands.weather_forecast_phrases import is_forecast_open_file, requested_forecast_days
from silva.config import load_config


def _display_minutes() -> int:
    try:
        return max(1, int(load_config().get("weather_forecast_display_minutes", 3)))
    except (TypeError, ValueError):
        return 3


def _open_forecast_file() -> str:
    ensure_weather_dir()
    if not FORECAST_TXT.exists():
        saved = load_saved_forecast()
        if saved is None:
            return "I do not have a saved forecast file yet."
        from silva.commands.weather_forecast import save_forecast

        save_forecast(saved)
    open_briefing_txt(FORECAST_TXT, auto_close_minutes=_display_minutes())
    return (
        f"I opened the forecast text file. It will close after {_display_minutes()} minutes."
    )


def handle_forecast_speech(text: str) -> tuple[str, dict | None]:
    days = requested_forecast_days(text, default=int(load_config().get("weather_forecast_days", 7)))
    if is_forecast_open_file(text):
        try:
            refresh_forecast(days=days)
        except Exception:
            pass
        return _open_forecast_file(), None

    try:
        report = refresh_forecast(days=days)
    except Exception as exc:
        saved = load_saved_forecast()
        if saved is None:
            return (
                f"I could not skim the public forecast right now. {exc}",
                None,
            )
        report = saved

    return report.to_full_speech(), None


def continue_forecast_flow(
    text: str,
    flow: dict,
    *,
    is_yes: bool,
    is_no: bool,
) -> tuple[str, dict | None]:
    if is_forecast_open_file(text) or "all days" in text.lower() or "whole week" in text.lower():
        return _open_forecast_file(), None
    if is_no:
        return "Okay.", None
    report = load_saved_forecast()
    if report is None:
        return handle_forecast_speech(text)
    return report.to_full_speech(), None
