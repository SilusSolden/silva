"""Natural-language math phrase matching."""

from __future__ import annotations

import re
from dataclasses import dataclass

MATH_PREFIXES: tuple[str, ...] = (
    "what is",
    "whats",
    "what's",
    "calculate",
    "compute",
    "solve",
    "work out",
    "figure out",
    "how much is",
    "tell me",
    "evaluate",
    "find",
)

MATH_KEYWORDS: tuple[str, ...] = (
    "plus",
    "minus",
    "times",
    "multiplied",
    "divide",
    "divided",
    "percent",
    "percentage",
    "square root",
    "sqrt",
    "power",
    "squared",
    "cubed",
    "factorial",
    "equals",
    "algebra",
    "equation",
    "convert",
    "conversion",
    "to meters",
    "to feet",
    "to inches",
    "to centimeters",
    "to kilometers",
    "to miles",
    "to pounds",
    "to kilograms",
    "to ounces",
    "to grams",
    "to liters",
    "to gallons",
    "earn",
    "earning",
    "earnings",
    "salary",
    "wage",
    "income",
    "paid",
    "pay",
    "profit",
    "commission",
    "tax",
    "overtime",
    "dollars",
    "bucks",
    "tip",
    "bill",
    "margin",
    "markup",
    "take home",
    "per hour",
    "per day",
    "per week",
    "per month",
    "per year",
    "a month",
    "this month",
    "a week",
    "a day",
    "an hour",
    "annual",
    "monthly",
    "weekly",
    "hourly",
    "worked",
    "compare",
    "versus",
    "price point",
    "price",
    "sale",
    "sales",
    "unit",
    "units",
    "sell",
    "selling",
    "customer",
    "order",
    "revenue",
    "each",
    "per sale",
    "per unit",
    "this price",
    "this number",
    "this amount",
    "that price",
    "number",
    "amount",
)

RECALL_PHRASES: tuple[str, ...] = (
    "recall my last calculation",
    "recall last calculation",
    "what was my last calculation",
    "what did you calculate",
    "repeat my last math",
    "last math result",
    "my last calculation",
)

LIST_HISTORY_PHRASES: tuple[str, ...] = (
    "show my calculations",
    "list my calculations",
    "calculation history",
    "math history",
)


@dataclass
class MathSpeech:
    action: str
    query: str = ""


def _normalize(text: str) -> str:
    text = text.strip().lower()
    text = text.replace("'", "")
    return re.sub(r"\s+", " ", text)


_WEATHER_WORDS: tuple[str, ...] = (
    "weather",
    "forecast",
    "forcast",
    "outlook",
    "rain",
    "raining",
    "storm",
    "temperature",
)

def _is_weather_context(text: str) -> bool:
    return any(word in text for word in _WEATHER_WORDS)


def _is_schedule_context(text: str) -> bool:
    normalized = _normalize(text)
    if re.search(r"\b(remind|reminder|todo|meds|medication|medicine|pills|appointment)\b", normalized):
        return True
    if "to do" in normalized:
        return True
    if re.search(r"\b\d{1,2}(:\d{2})?\s*(a\.?\s*m\.?|p\.?\s*m\.?|am|pm)\b", normalized):
        return True
    if "in the morning" in normalized or "in the afternoon" in normalized or "in the evening" in normalized:
        return True
    return False


def _has_math_operator(text: str) -> bool:
    return bool(
        re.search(r"\b\d+\s*[+\-*/^=]\s*\d+", text)
        or re.search(r"\b\d+\s*x\b|\bx\s*[=+\-]", text)
    )


def _looks_like_math(text: str, *, allow_bare_digits: bool = False) -> bool:
    normalized = _normalize(text)
    if _is_weather_context(normalized) or _is_schedule_context(normalized):
        return False
    if _has_math_operator(normalized):
        return True
    if any(word in normalized for word in MATH_KEYWORDS):
        return True
    if allow_bare_digits and any(ch.isdigit() for ch in normalized):
        return True
    return False


def match_math_speech(text: str) -> MathSpeech | None:
    from silva.commands.help_phrases import should_yield_to_feature_help

    if should_yield_to_feature_help(text):
        return None
    normalized = _normalize(text)
    if not normalized:
        return None

    for phrase in RECALL_PHRASES:
        if normalized == phrase or normalized.startswith(phrase):
            return MathSpeech("recall")

    for phrase in LIST_HISTORY_PHRASES:
        if normalized == phrase or normalized.startswith(phrase):
            return MathSpeech("history")

    for prefix in MATH_PREFIXES:
        if normalized.startswith(prefix + " "):
            query = normalized[len(prefix) + 1 :].strip()
            if query and _looks_like_math(query, allow_bare_digits=True):
                return MathSpeech("calculate", query)

    if _looks_like_math(normalized, allow_bare_digits=False):
        return MathSpeech("calculate", normalized)

    return None


def is_math_command(text: str) -> bool:
    return match_math_speech(text) is not None
