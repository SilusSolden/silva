"""Weather correction and local condition reporting."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from silva.config import CONFIG_DIR, load_config

FEEDBACK_FILE = CONFIG_DIR / "weather_feedback.json"
DEFAULT_CORRECTION_HOURS = 6

DISPUTE_PHRASES: tuple[str, ...] = (
    "that weather is not right",
    "that weather isn't right",
    "the weather is not right",
    "the weather isn't right",
    "weather is not right",
    "weather isn't right",
    "weather is wrong",
    "weather report is wrong",
    "weather forecast is wrong",
    "that forecast is wrong",
    "forecast is not right",
    "forecast isn't right",
    "you got the weather wrong",
    "that's not the right weather",
    "that is not the right weather",
    "weather is not accurate",
    "weather is inaccurate",
    "that's not what's outside",
    "that is not what's outside",
    "that's not what it is outside",
)

REPORT_PREFIXES: tuple[str, ...] = (
    "it's",
    "its",
    "it is",
    "actually it's",
    "actually its",
    "actually it is",
    "outside it's",
    "outside its",
    "outside it is",
    "right now it's",
    "right now its",
    "currently it's",
    "currently its",
    "weather is actually",
    "it's actually",
)

CLEAR_PHRASES: tuple[str, ...] = (
    "clear weather correction",
    "clear my weather correction",
    "forget weather correction",
    "forget my weather report",
    "use the forecast again",
    "use forecast again",
    "ignore my weather report",
    "reset weather report",
)

RECALL_PHRASES: tuple[str, ...] = (
    "what did i report about the weather",
    "what did i say about the weather",
    "my weather report",
    "what weather did i report",
)

CONDITION_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b(thunderstorms?|thundering|thunder)\b", "thunderstorms"),
    (r"\b(storming|storm|storms)\b", "storming"),
    (r"\b(hailing|hail)\b", "hail"),
    (r"\b(heavy rain|pouring|downpour)\b", "heavy rain"),
    (r"\b(raining|rain|rainy|showers?)\b", "rain"),
    (r"\b(drizzling|drizzle)\b", "drizzle"),
    (r"\b(snowing|snow|snowy|blizzard)\b", "snow"),
    (r"\b(sleeting|sleet)\b", "sleet"),
    (r"\b(foggy|fog|misty|mist)\b", "fog"),
    (r"\b(overcast|cloudy|clouds)\b", "cloudy"),
    (r"\b(partly cloudy|partly sunny)\b", "partly cloudy"),
    (r"\b(clear|sunny|sunshine|bright)\b", "clear skies"),
    (r"\b(windy|wind|gusty)\b", "windy"),
    (r"\b(hot|heat wave|scorching)\b", "hot"),
    (r"\b(cold|freezing|icy|ice)\b", "cold"),
    (r"\b(humid|muggy)\b", "humid"),
    (r"\b(tornado|hurricane)\b", "severe weather"),
)


@dataclass
class WeatherFeedbackSpeech:
    action: str
    conditions: str = ""
    raw: str = ""


def _normalize(text: str) -> str:
    text = text.strip().lower()
    text = text.replace("'", "")
    return re.sub(r"\s+", " ", text)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _correction_hours() -> int:
    value = load_config().get("weather_correction_hours", DEFAULT_CORRECTION_HOURS)
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return DEFAULT_CORRECTION_HOURS


def _load() -> dict:
    if not FEEDBACK_FILE.exists():
        return {}
    try:
        data = json.loads(FEEDBACK_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    FEEDBACK_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _user_key(user_id: str) -> str:
    return user_id or "guest"


def extract_conditions(text: str) -> str | None:
    normalized = _normalize(text)
    for pattern, label in CONDITION_PATTERNS:
        if re.search(pattern, normalized):
            return label
    return None


def match_weather_feedback(text: str) -> WeatherFeedbackSpeech | None:
    normalized = _normalize(text)
    if not normalized:
        return None

    for phrase in CLEAR_PHRASES:
        if normalized == phrase or normalized.startswith(phrase):
            return WeatherFeedbackSpeech("clear")

    for phrase in RECALL_PHRASES:
        if normalized == phrase or phrase in normalized:
            return WeatherFeedbackSpeech("recall")

    conditions = extract_conditions(normalized)
    if conditions:
        for phrase in DISPUTE_PHRASES:
            if phrase in normalized:
                return WeatherFeedbackSpeech("report", conditions, normalized)
        for prefix in REPORT_PREFIXES:
            if normalized.startswith(prefix + " ") or prefix in normalized:
                return WeatherFeedbackSpeech("report", conditions, normalized)
        if "outside" in normalized or "out here" in normalized or "out there" in normalized:
            return WeatherFeedbackSpeech("report", conditions, normalized)
        if "actually" in normalized and any(
            w in normalized for w in ("weather", "forecast", "raining", "storm", "snow", "sun")
        ):
            return WeatherFeedbackSpeech("report", conditions, normalized)

    for phrase in DISPUTE_PHRASES:
        if phrase in normalized:
            return WeatherFeedbackSpeech("dispute", raw=normalized)

    if normalized.startswith("actually ") and conditions:
        return WeatherFeedbackSpeech("report", conditions, normalized)

    report_triggers = (
        "report weather",
        "report the weather",
        "update the weather",
        "update weather",
        "correct the weather",
        "fix the weather",
    )
    for phrase in report_triggers:
        if normalized.startswith(phrase):
            tail = normalized[len(phrase) :].strip(" ,.")
            found = extract_conditions(tail) or tail
            if found:
                return WeatherFeedbackSpeech("report", found if isinstance(found, str) else tail, normalized)

    return None


def is_weather_feedback_command(text: str) -> bool:
    return match_weather_feedback(text) is not None


def save_weather_report(
    user_id: str,
    *,
    conditions: str,
    disputed: bool = False,
    note: str = "",
) -> dict:
    data = _load()
    key = _user_key(user_id)
    entry = {
        "conditions": conditions.strip(),
        "disputed": disputed,
        "note": note.strip(),
        "time": _now(),
    }
    bucket = data.setdefault(key, {"active": None, "history": []})
    bucket["active"] = entry
    history = bucket.setdefault("history", [])
    history.append(entry)
    bucket["history"] = history[-100:]
    _save(data)
    return entry


def clear_weather_report(user_id: str) -> bool:
    data = _load()
    key = _user_key(user_id)
    if key not in data or not data[key].get("active"):
        return False
    data[key]["active"] = None
    _save(data)
    return True


def get_active_weather_report(user_id: str) -> dict | None:
    data = _load()
    active = data.get(_user_key(user_id), {}).get("active")
    if not isinstance(active, dict):
        return None
    try:
        reported_at = datetime.strptime(active["time"], "%Y-%m-%d %H:%M:%S")
    except (KeyError, ValueError):
        return None
    if datetime.now() - reported_at > timedelta(hours=_correction_hours()):
        return None
    return active


def format_correction_overlay(user_id: str, forecast_conditions: str) -> str:
    active = get_active_weather_report(user_id)
    if not active:
        return ""

    reported = active.get("conditions", "different conditions")
    disputed = active.get("disputed", False)
    if disputed:
        return (
            f"You reported it's {reported} outside, which differs from the forecast of "
            f"{forecast_conditions}."
        )
    return (
        f"Using your report that it's {reported} outside. "
        f"The forecast still shows {forecast_conditions}."
    )


def _refresh_forecast() -> None:
    try:
        from silva.commands.weather import fetch_weather_report

        fetch_weather_report()
    except Exception:
        pass


def continue_weather_feedback_flow(user_id: str, text: str, flow: dict) -> tuple[str, dict | None]:
    phase = flow.get("phase")
    if phase == "await_condition":
        conditions = extract_conditions(text) or text.strip()
        if not conditions or len(conditions) < 3:
            return "Tell me what's actually happening outside, like storming or raining.", flow
        save_weather_report(user_id, conditions=conditions, disputed=True, note=text.strip())
        _refresh_forecast()
        return (
            f"Got it. I've updated your local weather to {conditions}. "
            "I'll remember that for the next few hours.",
            None,
        )
    return "I lost track of that weather update.", None


def handle_weather_feedback(user_id: str, text: str) -> tuple[str | None, dict | None]:
    speech = match_weather_feedback(text)
    if speech is None:
        return None, None

    if speech.action == "clear":
        if clear_weather_report(user_id):
            _refresh_forecast()
            return "Okay, I'll use the live forecast again.", None
        return "You don't have an active weather report saved.", None

    if speech.action == "recall":
        active = get_active_weather_report(user_id)
        if not active:
            return "You haven't reported different weather recently.", None
        return (
            f"You reported {active.get('conditions', 'different weather')} outside "
            f"at {active.get('time', 'recently')}.",
            None,
        )

    if speech.action == "report":
        conditions = speech.conditions or extract_conditions(text) or "updated conditions"
        save_weather_report(
            user_id,
            conditions=conditions,
            disputed=any(p in _normalize(text) for p in DISPUTE_PHRASES),
            note=text.strip(),
        )
        _refresh_forecast()
        return (
            f"Thanks. I've noted that it's {conditions} outside and refreshed the forecast. "
            "I'll use your report for conditions over the next few hours.",
            None,
        )

    if speech.action == "dispute":
        return (
            "Okay. What's it actually like outside? You can say storming, raining, sunny, and so on.",
            {"phase": "await_condition"},
        )

    return None, None
