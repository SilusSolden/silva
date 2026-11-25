"""Transparent click-through weather popup for Silva."""

from __future__ import annotations

import math
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass

from silva.gui.display_manager import register, unregister, watch_shutdown
from silva.gui.monitors import geometry_on_monitor
from silva.logger import log_error, log_info

TRANSPARENT = "#010101"
TEXT_PRIMARY = "#FFFFFF"
TEXT_SECONDARY = "#F5FBFF"
TEXT_MUTED = "#ECEFF1"
SHADOW = "#000000"

# Dark outline so text stays readable with no background panel.
TEXT_OUTLINE = (
    (0, 1),
    (0, -1),
    (1, 0),
    (-1, 0),
    (1, 1),
    (-1, 1),
    (1, -1),
    (-1, -1),
    (0, 2),
    (2, 0),
    (-2, 0),
    (0, -2),
)

if sys.platform == "win32":
    import ctypes

    GWL_EXSTYLE = -20
    WS_EX_LAYERED = 0x00080000
    WS_EX_TRANSPARENT = 0x00000020
    WS_EX_TOOLWINDOW = 0x00000080


@dataclass
class ForecastDayDisplay:
    weekday: str
    high_f: int
    low_f: int
    conditions: str
    rain_chance: int


@dataclass
class WeatherDisplay:
    city: str
    temp_f: int
    humidity: int
    wind_mph: int
    conditions: str
    is_day: bool
    forecast_days: tuple[ForecastDayDisplay, ...] = ()


@dataclass
class WeatherAlertDisplay:
    event: str
    headline: str
    description: str
    area: str
    severity: str


def _apply_window_effects(root: tk.Misc) -> None:
    root.attributes("-transparentcolor", TRANSPARENT)
    root.attributes("-alpha", 1.0)

    if sys.platform != "win32":
        return

    root.update_idletasks()
    hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
    style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    style |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW
    ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)


def _draw_readable_text(
    canvas: tk.Canvas,
    x: int,
    y: int,
    text: str,
    font: tkfont.Font,
    fill: str,
    anchor: str = "nw",
) -> None:
    for offset_x, offset_y in TEXT_OUTLINE:
        canvas.create_text(
            x + offset_x,
            y + offset_y,
            text=text,
            font=font,
            fill=SHADOW,
            anchor=anchor,
        )
    canvas.create_text(x, y, text=text, font=font, fill=fill, anchor=anchor)


def _draw_sky_icon(canvas: tk.Canvas, x: int, y: int, is_day: bool, size: int = 64) -> None:
    center_x = x + size // 2
    center_y = y + size // 2
    if is_day:
        canvas.create_oval(
            x + 10,
            y + 10,
            x + size - 10,
            y + size - 10,
            fill="#FFD54F",
            outline="#FFB300",
            width=2,
        )
        for angle in range(0, 360, 45):
            rad = math.radians(angle)
            ray = size // 2 - 6
            x1 = center_x + math.cos(rad) * (ray - 4)
            y1 = center_y + math.sin(rad) * (ray - 4)
            x2 = center_x + math.cos(rad) * (ray + 4)
            y2 = center_y + math.sin(rad) * (ray + 4)
            canvas.create_line(x1, y1, x2, y2, fill="#FFB300", width=2)
    else:
        canvas.create_oval(
            x + 16,
            y + 16,
            x + size - 16,
            y + size - 16,
            fill="#ECEFF1",
            outline="#CFD8DC",
            width=2,
        )
        canvas.create_oval(x + 26, y + 14, x + 48, y + 36, fill=TRANSPARENT, outline="")


def _new_popup_window(parent: tk.Misc | None) -> tk.Misc:
    if parent is not None:
        window = tk.Toplevel(parent)
        return window
    return tk.Tk()


def _finish_popup(root: tk.Misc, duration: int, run_loop: bool, *, kind: str) -> None:
    _apply_window_effects(root)
    try:
        root.deiconify()
        root.lift()
        root.attributes("-topmost", True)
        root.update_idletasks()
    except tk.TclError:
        pass
    log_info(f"{kind} popup shown.")
    root.after(max(1, int(duration)) * 1000, root.destroy)
    if run_loop:
        root.mainloop()


def _build_popup(weather: WeatherDisplay, duration: int, *, parent: tk.Misc | None = None) -> None:
    root = _new_popup_window(parent)
    run_loop = parent is None
    root.title("Silva Weather")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.configure(bg=TRANSPARENT)

    forecast_days = tuple(weather.forecast_days or ())
    row_h = 20
    forecast_header = 24 if forecast_days else 0
    width = 360 if forecast_days else 300
    height = 178 + forecast_header + (len(forecast_days) * row_h)
    root.geometry(geometry_on_monitor(width, height, anchor="ne", margin=24))

    register(root)
    root.bind("<Destroy>", lambda _event: unregister(root))
    watch_shutdown(root)

    canvas = tk.Canvas(
        root,
        width=width,
        height=height,
        bg=TRANSPARENT,
        highlightthickness=0,
        bd=0,
    )
    canvas.pack()

    title_font = tkfont.Font(family="Segoe UI", size=12, weight="bold")
    temp_font = tkfont.Font(family="Segoe UI", size=30, weight="bold")
    detail_font = tkfont.Font(family="Segoe UI", size=11, weight="bold")
    muted_font = tkfont.Font(family="Segoe UI", size=10, weight="bold")
    row_font = tkfont.Font(family="Segoe UI", size=9, weight="bold")

    pad_x = 14
    pad_y = 12
    icon_x = pad_x
    icon_y = 38
    icon_size = 64
    text_x = icon_x + icon_size + 12

    title = f"{weather.city} Weather"
    temp = f"{weather.temp_f}°F"
    conditions = weather.conditions.title()
    details = f"Humidity {weather.humidity}%  |  Wind {weather.wind_mph} mph"
    period = "Daytime" if weather.is_day else "Nighttime"

    _draw_readable_text(canvas, pad_x, pad_y, title, title_font, TEXT_SECONDARY)
    _draw_sky_icon(canvas, icon_x, icon_y, weather.is_day, icon_size)
    _draw_readable_text(canvas, text_x, icon_y + 2, temp, temp_font, TEXT_PRIMARY)
    _draw_readable_text(canvas, text_x, icon_y + 42, conditions, detail_font, TEXT_SECONDARY)
    _draw_readable_text(canvas, text_x, icon_y + 64, details, muted_font, TEXT_MUTED)
    _draw_readable_text(canvas, pad_x, icon_y + icon_size + 8, period, muted_font, TEXT_MUTED)

    if forecast_days:
        y = icon_y + icon_size + 30
        _draw_readable_text(canvas, pad_x, y, "Forecast", title_font, TEXT_SECONDARY)
        y += 22
        for index, day in enumerate(forecast_days):
            label = "Today" if index == 0 else day.weekday[:3]
            rain = f"{day.rain_chance}%"
            rain_color = "#90CAF9" if day.rain_chance >= 40 else TEXT_MUTED
            line = (
                f"{label:<5}  {day.high_f}/{day.low_f}°  "
                f"{day.conditions.title()[:16]:<16}  rain {rain}"
            )
            _draw_readable_text(canvas, pad_x, y, line, row_font, rain_color if day.rain_chance >= 40 else TEXT_PRIMARY)
            y += row_h

    _finish_popup(root, duration, run_loop, kind="Weather")


_popup_lock = threading.Lock()


def _overlay_parent() -> tk.Misc | None:
    try:
        from silva.gui.display_host import host_root

        return host_root()
    except Exception:
        return None


def show_weather_popup(weather: WeatherDisplay, duration: int = 12) -> None:
    """Show weather on the shared display-host thread when possible (avoids Tcl crashes)."""

    def _safe_build(*, parent: tk.Misc | None = None) -> None:
        try:
            _build_popup(weather, duration, parent=parent)
        except Exception as exc:
            log_error("Weather popup failed", exc=exc)

    parent = _overlay_parent()
    if parent is None:
        log_info("Weather popup skipped — display host is not ready.")
        return
    try:
        parent.after(0, lambda: _safe_build(parent=parent))
    except Exception as exc:
        log_error("Weather popup schedule failed", exc=exc)


def _wrap_text(text: str, *, max_chars: int = 52) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if len(candidate) <= max_chars:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _build_alert_popup(alert: WeatherAlertDisplay, duration: int, *, parent: tk.Misc | None = None) -> None:
    root = _new_popup_window(parent)
    run_loop = parent is None
    root.title("Silva Weather Alert")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.configure(bg=TRANSPARENT)

    width, height = 360, 240
    root.geometry(geometry_on_monitor(width, height, anchor="ne", margin=24))

    register(root)
    root.bind("<Destroy>", lambda _event: unregister(root))
    watch_shutdown(root)

    canvas = tk.Canvas(
        root,
        width=width,
        height=height,
        bg=TRANSPARENT,
        highlightthickness=0,
        bd=0,
    )
    canvas.pack()

    title_font = tkfont.Font(family="Segoe UI", size=13, weight="bold")
    headline_font = tkfont.Font(family="Segoe UI", size=11, weight="bold")
    body_font = tkfont.Font(family="Segoe UI", size=10, weight="bold")
    muted_font = tkfont.Font(family="Segoe UI", size=9, weight="bold")

    pad_x = 14
    y = 10
    _draw_readable_text(canvas, pad_x, y, "WEATHER ALERT", title_font, "#FF8A80")
    y += 24
    _draw_readable_text(canvas, pad_x, y, alert.event, headline_font, "#FFEB3B")
    y += 22
    if alert.area:
        _draw_readable_text(canvas, pad_x, y, alert.area, muted_font, TEXT_MUTED)
        y += 18
    if alert.severity:
        _draw_readable_text(canvas, pad_x, y, f"Severity: {alert.severity}", muted_font, TEXT_MUTED)
        y += 18

    headline = alert.headline or alert.event
    for line in _wrap_text(headline, max_chars=48)[:2]:
        _draw_readable_text(canvas, pad_x, y, line, headline_font, TEXT_PRIMARY)
        y += 18

    body = (alert.description or "").replace("\n", " ").strip()
    for line in _wrap_text(body, max_chars=50)[:3]:
        _draw_readable_text(canvas, pad_x, y, line, body_font, TEXT_SECONDARY)
        y += 16

    _finish_popup(root, duration, run_loop, kind="Weather alert")


def show_weather_alert_popup(alert, duration: int = 30) -> None:
    """Instant popup for major weather alerts in the user's area."""
    from silva.commands.weather_alerts import WeatherAlert

    if isinstance(alert, WeatherAlert):
        display = WeatherAlertDisplay(
            event=alert.event,
            headline=alert.headline,
            description=alert.description,
            area=alert.area,
            severity=alert.severity,
        )
    else:
        display = alert

    def _safe_build(*, parent: tk.Misc | None = None) -> None:
        try:
            _build_alert_popup(display, duration, parent=parent)
        except Exception as exc:
            log_error("Weather alert popup failed", exc=exc)

    parent = _overlay_parent()
    if parent is None:
        log_info("Weather alert popup skipped — display host is not ready.")
        return
    try:
        parent.after(0, lambda: _safe_build(parent=parent))
    except Exception as exc:
        log_error("Weather alert popup schedule failed", exc=exc)
