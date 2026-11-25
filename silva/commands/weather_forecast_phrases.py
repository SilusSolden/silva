"""Speech patterns for multi-day weather forecasts."""

from __future__ import annotations

import re

# Common spoken/typed misspellings of forecast.
_SPELLING_FIXES: tuple[tuple[str, str], ...] = (
    (r"\bforcasts\b", "forecasts"),
    (r"\bforcast\b", "forecast"),
    (r"\bforcaste\b", "forecast"),
    (r"\bforecaste\b", "forecast"),
    (r"\bforecst\b", "forecast"),
    (r"\bforecase\b", "forecast"),
    (r"\bforcasts\b", "forecasts"),
    (r"\bwether\b", "weather"),
    (r"\bweater\b", "weather"),
    (r"\bweaher\b", "weather"),
)

FORECAST_PHRASES: tuple[str, ...] = (
    "weather forecast",
    "local forecast",
    "my forecast",
    "my local forecast",
    "the local forecast",
    "the forecast",
    "extended forecast",
    "weekly forecast",
    "week forecast",
    "7 day forecast",
    "7-day forecast",
    "seven day forecast",
    "3 day forecast",
    "3-day forecast",
    "three day forecast",
    "5 day forecast",
    "five day forecast",
    "what's my local forecast",
    "whats my local forecast",
    "what is my local forecast",
    "what's the local forecast",
    "whats the local forecast",
    "what is the local forecast",
    "what's my forecast",
    "whats my forecast",
    "what is my forecast",
    "what's the forecast",
    "whats the forecast",
    "what is the forecast",
    "how's my local forecast",
    "hows my local forecast",
    "how is my local forecast",
    "how's the local forecast",
    "hows the local forecast",
    "how is the local forecast",
    "how's the forecast",
    "hows the forecast",
    "how is the forecast",
    "tell me my local forecast",
    "tell me the local forecast",
    "tell me my forecast",
    "tell me the forecast",
    "give me my local forecast",
    "give me the local forecast",
    "give me my forecast",
    "give me the forecast",
    "check my local forecast",
    "check the local forecast",
    "check my forecast",
    "check the forecast",
    "get my local forecast",
    "get the local forecast",
    "get my forecast",
    "get the forecast",
    "show my local forecast",
    "show the local forecast",
    "show my forecast",
    "show the forecast",
    "show me the forecast",
    "show me my forecast",
    "open the forecast",
    "open forecast",
    "pull up the forecast",
    "pull up my forecast",
    "bring up the forecast",
    "read the forecast",
    "read me the forecast",
    "next few days",
    "next few days weather",
    "next few days forecast",
    "next couple days",
    "next couple of days",
    "coming few days",
    "upcoming days",
    "upcoming weather",
    "next 3 days",
    "next three days",
    "next 7 days",
    "next seven days",
    "next 3 to 7 days",
    "1 to 3 days",
    "1-3 days",
    "1 - 3 days",
    "one to three days",
    "3 to 7 days",
    "days of weather",
    "days weather",
    "few days of weather",
    "few days weather",
    "this week weather",
    "this weeks weather",
    "this week's weather",
    "weather this week",
    "forecast this week",
    "outlook this week",
    "weather outlook",
    "local outlook",
    "weekly outlook",
    "extended outlook",
    "will it rain this week",
    "will it rain tomorrow",
    "chance of rain this week",
    "chance of rain tomorrow",
    "rain this week",
    "rain tomorrow",
)


_FORECAST_RE = re.compile(
    r"\b("
    r"forecasts?|"
    r"outlook|"
    r"(next|upcoming|coming|following) .{0,24}(days?|nights?|week)|"
    r"(few|couple( of)?) days|"
    r"(this|the) week('s|s)? (weather|forecast|outlook)|"
    r"(weather|forecast|outlook) (this|for (the )?|for this )week|"
    r"week(ly)? (weather |local )?(forecast|outlook)|"
    r"\d+\s*(to|-|through|thru)\s*\d+\s+days?|"
    r"(one|two|three|1|2|3)\s*(to|-|through|thru)\s*(three|seven|3|7)\s+days?|"
    r"\d+[ -]?day(s)? (of )?(weather|forecast|outlook)|"
    r"(three|3|five|5|seven|7)[ -]?day (weather )?(forecast|outlook)|"
    r"days? of weather|"
    r"days? weather|"
    r"extended (weather|forecast|outlook)|"
    r"local (forecast|outlook)|"
    r"my (local )?(forecast|outlook)|"
    r"the (local )?(forecast|outlook)|"
    r"will it rain (tomorrow|this week|the rest of the week|the next few days)|"
    r"chance of rain (tomorrow|this week|the next few days)|"
    r"open (the )?(forecast|outlook)|"
    r"show (me )?(the |my )?(weather |local )?(forecast|outlook)|"
    r"pull up (the |my )?(forecast|outlook)"
    r")\b",
    re.I,
)

_NEXT_DAY_RE = re.compile(
    r"\b(next( day| one)?|continue|keep going|another day|the next one)\b",
    re.I,
)

_OPEN_FILE_RE = re.compile(
    r"\b(open (the )?(forecast|file|text file|outlook)|show (me )?(all|the whole|the full) (forecast|week)|"
    r"read (the )?file|all days)\b",
    re.I,
)

_RANGE_RE = re.compile(
    r"\b(?:(\d+|one|two|three|four|five|six|seven)\s*(?:to|-|through|thru)\s*)?"
    r"(\d+|one|two|three|four|five|six|seven|few)\s+days?\b"
    r"|(\d+|three|four|five|six|seven)[ -]?day",
    re.I,
)

_WORD_DAYS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "few": 5,
}


def normalize_forecast_text(text: str) -> str:
    normalized = (text or "").strip().lower().replace("'", "")
    normalized = normalized.replace("–", "-").replace("—", "-")
    normalized = re.sub(r"\s*-\s*", "-", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    for pattern, replacement in _SPELLING_FIXES:
        normalized = re.sub(pattern, replacement, normalized)
    return normalized


def _token_to_days(token: str) -> int | None:
    token = token.lower().strip()
    if token.isdigit():
        return int(token)
    return _WORD_DAYS.get(token)


def is_weather_forecast_command(text: str) -> bool:
    if not text or not text.strip():
        return False
    from silva.commands.help_phrases import should_yield_to_feature_help

    if should_yield_to_feature_help(text):
        return False
    normalized = normalize_forecast_text(text)
    if any(phrase in normalized for phrase in FORECAST_PHRASES):
        return True
    return bool(_FORECAST_RE.search(normalized))


def is_forecast_next_day(text: str) -> bool:
    return bool(_NEXT_DAY_RE.search(normalize_forecast_text(text)))


def is_forecast_open_file(text: str) -> bool:
    return bool(_OPEN_FILE_RE.search(normalize_forecast_text(text)))


def requested_forecast_days(text: str, default: int = 7) -> int:
    lowered = normalize_forecast_text(text)
    match = _RANGE_RE.search(lowered)
    if match:
        start_token, end_token, single_token = match.groups()
        values = []
        for token in (start_token, end_token, single_token):
            if not token:
                continue
            parsed = _token_to_days(token)
            if parsed is not None:
                values.append(parsed)
        if values:
            return max(3, min(7, max(values)))
    if "week" in lowered:
        return 7
    if "few" in lowered:
        return 5
    if "couple" in lowered:
        return 3
    return max(3, min(7, default))
