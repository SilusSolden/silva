"""Money, earnings, salary, and financial scenario calculations."""

from __future__ import annotations

import re
from collections.abc import Callable

WORKING_DAYS_PER_MONTH = 22
CALENDAR_DAYS_PER_MONTH = 30
WEEKS_PER_MONTH = 52 / 12
WEEKS_PER_YEAR = 52
MONTHS_PER_YEAR = 12


def _normalize(text: str) -> str:
    text = text.strip().lower()
    text = text.replace("'", "")
    text = text.replace("$", " ")
    text = text.replace(",", "")
    text = re.sub(r"\bbucks?\b", " dollars ", text)
    text = re.sub(r"\bper\b", " a ", text)
    text = re.sub(r"\bthis price\b|\bthat price\b", " price ", text)
    text = re.sub(r"\bthis number\b|\bthat number\b", " number ", text)
    text = re.sub(r"\bthis amount\b|\bthat amount\b", " amount ", text)
    text = re.sub(r"\ban hour\b", " a hour ", text)
    text = re.sub(r"\ba day\b", " a day ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_amount(text: str) -> float | None:
    match = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:dollars|dollar|usd)?|"
        r"(?:dollars|dollar|usd)\s*(\d+(?:\.\d+)?)",
        text,
    )
    if match:
        return float(match.group(1) or match.group(2))
    match = re.search(r"\b(\d+(?:\.\d+)?)\b", text)
    if match:
        return float(match.group(1))
    return None


def _format_money(value: float) -> str:
    rounded = round(value, 2)
    if abs(rounded - round(rounded)) < 0.005:
        return f"${int(round(rounded)):,}"
    return f"${rounded:,.2f}"


def _period_days(period: str) -> float:
    period = period.lower().strip()
    if period in {"day", "days"}:
        return 1.0
    if period in {"week", "weeks"}:
        return 7.0
    if period in {"month", "months"}:
        return float(CALENDAR_DAYS_PER_MONTH)
    if period in {"year", "years"}:
        return 365.0
    return 1.0


def _working_days_in_period(period: str, count: float = 1.0) -> float:
    period = period.lower().strip()
    if period in {"day", "days"}:
        return count
    if period in {"week", "weeks"}:
        return 5.0 * count
    if period in {"month", "months"}:
        return WORKING_DAYS_PER_MONTH * count
    if period in {"year", "years"}:
        return WORKING_DAYS_PER_MONTH * MONTHS_PER_YEAR * count
    return count


def _rate_times_period(rate: float, rate_unit: str, span: float, span_unit: str) -> tuple[float, str]:
    """Convert earnings across time units."""
    rate_unit = rate_unit.rstrip("s")
    span_unit = span_unit.rstrip("s")

    if rate_unit == "hour":
        if span_unit == "hour":
            total = rate * span
            return total, f"{_format_money(rate)} an hour for {span:g} hours is {_format_money(total)}"
        if span_unit == "day":
            total = rate * span * 8
            return total, (
                f"{_format_money(rate)} an hour for {span:g} days at 8 hours a day "
                f"is {_format_money(total)}"
            )
        if span_unit == "week":
            total = rate * span * 40
            return total, (
                f"{_format_money(rate)} an hour for {span:g} weeks at 40 hours a week "
                f"is {_format_money(total)}"
            )
        if span_unit == "month":
            total = rate * span * WORKING_DAYS_PER_MONTH * 8
            return total, (
                f"{_format_money(rate)} an hour for {span:g} month(s) at 8 hours a day, "
                f"{WORKING_DAYS_PER_MONTH} working days a month, is {_format_money(total)}"
            )
        if span_unit == "year":
            total = rate * span * WORKING_DAYS_PER_MONTH * MONTHS_PER_YEAR * 8
            return total, (
                f"{_format_money(rate)} an hour for {span:g} year(s) is about {_format_money(total)}"
            )

    if rate_unit == "day":
        if span_unit == "day":
            total = rate * span
            return total, f"{_format_money(rate)} a day for {span:g} days is {_format_money(total)}"
        if span_unit == "week":
            total = rate * span * 7
            return total, f"{_format_money(rate)} a day for {span:g} weeks is {_format_money(total)}"
        if span_unit == "month":
            days = CALENDAR_DAYS_PER_MONTH * span
            total = rate * days
            return total, (
                f"{_format_money(rate)} a day for {span:g} month(s) "
                f"({days:g} days) is {_format_money(total)}"
            )
        if span_unit == "year":
            total = rate * 365 * span
            return total, f"{_format_money(rate)} a day for {span:g} year(s) is about {_format_money(total)}"

    if rate_unit == "week":
        if span_unit == "week":
            total = rate * span
            return total, f"{_format_money(rate)} a week for {span:g} weeks is {_format_money(total)}"
        if span_unit == "month":
            total = rate * span * WEEKS_PER_MONTH
            return total, (
                f"{_format_money(rate)} a week for {span:g} month(s) "
                f"is about {_format_money(total)}"
            )
        if span_unit == "year":
            total = rate * span * WEEKS_PER_YEAR
            return total, f"{_format_money(rate)} a week for {span:g} year(s) is {_format_money(total)}"

    if rate_unit == "month":
        if span_unit == "month":
            total = rate * span
            return total, f"{_format_money(rate)} a month for {span:g} month(s) is {_format_money(total)}"
        if span_unit == "year":
            total = rate * span * MONTHS_PER_YEAR
            return total, f"{_format_money(rate)} a month for {span:g} year(s) is {_format_money(total)}"

    if rate_unit == "year":
        if span_unit == "month":
            total = rate / MONTHS_PER_YEAR * span
            return total, f"{_format_money(rate)} a year is about {_format_money(total)} per month"
        if span_unit == "year":
            return rate * span, f"{_format_money(rate)} a year for {span:g} year(s) is {_format_money(rate * span)}"

    total = rate * span
    return total, f"{_format_money(rate)} for {span:g} {span_unit}(s) is {_format_money(total)}"


def _try_rate_for_period(text: str) -> str | None:
    """e.g. 50 dollars a day for a month, 15 an hour for 40 hours a week."""
    patterns = [
        r"(\d+(?:\.\d+)?)\s*(?:dollars?\s*)?(?:a|an)\s*(hour|day|week|month|year)"
        r".*?(?:for|in)\s*(?:a|one|\d+(?:\.\d+)?)?\s*(hour|day|week|month|year)s?",
        r"(?:earn|make|making|paid|pay)\s*(?:at|of)?\s*(\d+(?:\.\d+)?)\s*(?:dollars?\s*)?(?:a|an)\s*(hour|day|week|month|year)"
        r".*?(?:for|in|this)\s*(?:a|one|\d+(?:\.\d+)?)?\s*(hour|day|week|month|year)s?",
        r"(\d+(?:\.\d+)?)\s*(?:dollars?\s*)?(?:a|an)\s*(hour|day|week|month|year)"
        r".*?(?:this|the)\s*(hour|day|week|month|year)s?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        rate = float(match.group(1))
        rate_unit = match.group(2)
        span_unit = match.group(3)
        span_match = re.search(
            rf"(?:for|in)\s*(?:a|one|the)?\s*(\d+(?:\.\d+)?)?\s*{span_unit}s?",
            text,
        )
        span = 1.0
        if span_match and span_match.group(1):
            span = float(span_match.group(1))
        elif f"this {span_unit}" in text or f"the {span_unit}" in text:
            span = 1.0
        _, message = _rate_times_period(rate, rate_unit, span, span_unit)
        return message
    return None


def _try_hourly_schedule(text: str) -> str | None:
    """e.g. 20 an hour 8 hours a day 5 days a week, how much a month."""
    match = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:dollars?\s*)?(?:a|an)\s*hour"
        r".*?(\d+(?:\.\d+)?)\s*hours?\s*(?:a|per|each)\s*day"
        r".*?(\d+(?:\.\d+)?)\s*days?\s*(?:a|per|each)\s*week",
        text,
    )
    if not match:
        return None

    hourly = float(match.group(1))
    hours_per_day = float(match.group(2))
    days_per_week = float(match.group(3))
    weekly = hourly * hours_per_day * days_per_week
    monthly = weekly * WEEKS_PER_MONTH
    yearly = weekly * WEEKS_PER_YEAR

    parts = [
        f"At {_format_money(hourly)} an hour, {hours_per_day:g} hours a day, "
        f"{days_per_week:g} days a week:",
        f"about {_format_money(weekly)} a week,",
        f"about {_format_money(monthly)} a month,",
        f"and about {_format_money(yearly)} a year.",
    ]
    return " ".join(parts)


def _try_salary_conversion(text: str) -> str | None:
    """Annual salary to monthly/weekly/daily or reverse."""
    if not any(w in text for w in ("salary", "year", "annual", "monthly", "month", "week")):
        return None

    match = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:dollars?\s*)?(?:a|an|per)\s*(year|month|week|day)",
        text,
    )
    if not match:
        match = re.search(r"(?:salary|earn|make|making|paid)\s*(?:of|is)?\s*(\d+(?:\.\d+)?)", text)
        if not match:
            return None
        amount = float(match.group(1))
        if "month" in text:
            source_unit = "month"
        elif "week" in text:
            source_unit = "week"
        elif "day" in text:
            source_unit = "day"
        else:
            source_unit = "year"
    else:
        amount = float(match.group(1))
        source_unit = match.group(2)

    targets = []
    if "month" in text or "monthly" in text:
        targets.append("month")
    if "week" in text or "weekly" in text:
        targets.append("week")
    if "day" in text or "daily" in text:
        targets.append("day")
    if "hour" in text or "hourly" in text:
        targets.append("hour")
    if not targets:
        targets = ["month"]

    lines = [f"From {_format_money(amount)} a {source_unit}:"]
    for target in targets:
        if target == source_unit:
            continue
        if source_unit == "year" and target == "month":
            lines.append(f"about {_format_money(amount / MONTHS_PER_YEAR)} a month")
        elif source_unit == "year" and target == "week":
            lines.append(f"about {_format_money(amount / WEEKS_PER_YEAR)} a week")
        elif source_unit == "year" and target == "day":
            lines.append(f"about {_format_money(amount / 365)} a day")
        elif source_unit == "year" and target == "hour":
            lines.append(
                f"about {_format_money(amount / (WORKING_DAYS_PER_MONTH * MONTHS_PER_YEAR * 8))} an hour "
                f"at 8 hours a day"
            )
        elif source_unit == "month" and target == "year":
            lines.append(f"about {_format_money(amount * MONTHS_PER_YEAR)} a year")
        elif source_unit == "month" and target == "week":
            lines.append(f"about {_format_money(amount / WEEKS_PER_MONTH)} a week")
        elif source_unit == "month" and target == "day":
            lines.append(f"about {_format_money(amount / CALENDAR_DAYS_PER_MONTH)} a day")
        elif source_unit == "week" and target == "month":
            lines.append(f"about {_format_money(amount * WEEKS_PER_MONTH)} a month")
        elif source_unit == "week" and target == "year":
            lines.append(f"about {_format_money(amount * WEEKS_PER_YEAR)} a year")
        elif source_unit == "day" and target == "month":
            lines.append(f"about {_format_money(amount * CALENDAR_DAYS_PER_MONTH)} a month")
        else:
            _, msg = _rate_times_period(amount, source_unit, 1, target)
            lines.append(msg.split(" is ", 1)[-1] if " is " in msg else msg)

    if len(lines) == 1:
        return None
    return ". ".join(lines) + "."


def _try_worked_days(text: str) -> str | None:
    """e.g. worked 15 days at 100 a day, or this month I worked 10 days at 50."""
    match = re.search(
        r"(?:worked|work|working)\s*(\d+(?:\.\d+)?)\s*days?"
        r".*?(?:at|for|making|earning|earn|make)\s*(\d+(?:\.\d+)?)\s*(?:dollars?\s*)?(?:a|an)\s*day",
        text,
    )
    if not match:
        match = re.search(
            r"(\d+(?:\.\d+)?)\s*days?\s*(?:at|for)\s*(\d+(?:\.\d+)?)\s*(?:dollars?\s*)?(?:a|an)\s*day",
            text,
        )
    if not match:
        return None

    days = float(match.group(1))
    rate = float(match.group(2))
    total = days * rate
    return (
        f"Working {days:g} days at {_format_money(rate)} a day "
        f"earns {_format_money(total)} this period."
    )


def _try_overtime(text: str) -> str | None:
    """e.g. 20 an hour 40 hours plus 10 overtime at time and a half."""
    if "overtime" not in text and "time and a half" not in text and " ot " not in f" {text} ":
        return None

    match = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:dollars?\s*)?(?:a|an)\s*hour"
        r".*?(\d+(?:\.\d+)?)\s*(?:regular\s*)?hours?"
        r".*?(?:plus|and)\s*(\d+(?:\.\d+)?)\s*(?:overtime|ot)\s*hours?",
        text,
    )
    if not match:
        return None

    rate = float(match.group(1))
    regular_hours = float(match.group(2))
    ot_hours = float(match.group(3))
    ot_multiplier = 1.5 if "time and a half" in text or "time-and-a-half" in text else 1.5
    multiplier_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:times|x)\s*(?:pay|rate)", text)
    if multiplier_match:
        ot_multiplier = float(multiplier_match.group(1))

    regular_pay = rate * regular_hours
    ot_pay = rate * ot_multiplier * ot_hours
    total = regular_pay + ot_pay
    return (
        f"At {_format_money(rate)} an hour: "
        f"{regular_hours:g} regular hours is {_format_money(regular_pay)}, "
        f"{ot_hours:g} overtime hours at {ot_multiplier:g}x is {_format_money(ot_pay)}, "
        f"for a total of {_format_money(total)}."
    )


def _try_after_tax(text: str) -> str | None:
    """e.g. 50000 after 22 percent tax, or take home pay on 4000 a month at 15 tax."""
    if "tax" not in text and "take home" not in text:
        return None

    amount = _parse_amount(text)
    tax_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:percent|%)\s*(?:tax|taxes)", text)
    if amount is None or tax_match is None:
        return None

    tax_rate = float(tax_match.group(1))
    tax_amount = amount * tax_rate / 100.0
    net = amount - tax_amount
    return (
        f"Starting from {_format_money(amount)} at {tax_rate:g}% tax: "
        f"tax is {_format_money(tax_amount)}, take-home is {_format_money(net)}."
    )


def _try_commission(text: str) -> str | None:
    """e.g. 5 percent commission on 10000 in sales."""
    if "commission" not in text:
        return None

    match = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:percent|%)\s*commission\s*(?:on|of|from)\s*(\d+(?:\.\d+)?)",
        text,
    )
    if not match:
        return None

    pct = float(match.group(1))
    sales = float(match.group(2))
    commission = sales * pct / 100.0
    return (
        f"{pct:g}% commission on {_format_money(sales)} in sales "
        f"is {_format_money(commission)}."
    )


def _try_profit(text: str) -> str | None:
    """e.g. sell at 50 cost 30 for 100 units, profit margin."""
    if not any(w in text for w in ("profit", "margin", "markup", "revenue")):
        return None

    sell_match = re.search(r"(?:sell(?:ing)?|sold|price|revenue)\s*(?:at|for|of)?\s*(\d+(?:\.\d+)?)", text)
    cost_match = re.search(r"(?:cost(?:s)?|buy(?:ing)?|purchase)\s*(?:at|of|is)?\s*(\d+(?:\.\d+)?)", text)
    qty_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:units|items|products|pieces)", text)

    if not sell_match or not cost_match:
        return None

    sell = float(sell_match.group(1))
    cost = float(cost_match.group(1))
    qty = float(qty_match.group(1)) if qty_match else 1.0
    profit_each = sell - cost
    total_profit = profit_each * qty
    margin = (profit_each / sell * 100.0) if sell else 0.0

    return (
        f"Selling at {_format_money(sell)} with cost {_format_money(cost)} "
        f"is {_format_money(profit_each)} profit each"
        f"{f' times {qty:g} units is {_format_money(total_profit)} total profit' if qty != 1 else ''}"
        f", a {margin:.1f}% margin."
    )


def _try_split_tip(text: str) -> str | None:
    """e.g. split 120 bill 4 ways with 18 percent tip."""
    if "split" not in text and "tip" not in text:
        return None

    bill = _parse_amount(text)
    if bill is None:
        return None

    ways_match = re.search(r"(\d+)\s*(?:ways|people|person)", text)
    tip_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:percent|%)\s*tip", text)
    ways = int(ways_match.group(1)) if ways_match else 1
    tip_pct = float(tip_match.group(1)) if tip_match else 0.0

    tip = bill * tip_pct / 100.0
    total = bill + tip
    per_person = total / ways

    parts = [f"Bill {_format_money(bill)}"]
    if tip_pct:
        parts.append(f"plus {tip_pct:g}% tip ({_format_money(tip)})")
    parts.append(f"is {_format_money(total)} total")
    if ways > 1:
        parts.append(f"or {_format_money(per_person)} each split {ways} ways")
    return ", ".join(parts) + "."


def _try_compare_income(text: str) -> str | None:
    """e.g. compare 25 an hour vs 52000 a year which is better."""
    if "compare" not in text and " vs " not in text and " versus " not in text:
        return None

    rates = re.findall(
        r"(\d+(?:\.\d+)?)\s*(?:dollars?\s*)?(?:a|an)\s*(hour|day|week|month|year)",
        text,
    )
    if len(rates) < 2:
        return None

    annualized: list[tuple[float, str]] = []
    for amount, unit in rates:
        amount_f = float(amount)
        if unit == "hour":
            annual = amount_f * WORKING_DAYS_PER_MONTH * MONTHS_PER_YEAR * 8
        elif unit == "day":
            annual = amount_f * WORKING_DAYS_PER_MONTH * MONTHS_PER_YEAR
        elif unit == "week":
            annual = amount_f * WEEKS_PER_YEAR
        elif unit == "month":
            annual = amount_f * MONTHS_PER_YEAR
        else:
            annual = amount_f
        annualized.append((annual, f"{_format_money(amount_f)} a {unit}"))

    annualized.sort(reverse=True)
    best = annualized[0]
    second = annualized[1]
    diff = best[0] - second[0]
    return (
        f"Comparing annual income: {best[1]} is about {_format_money(best[0])} a year, "
        f"and {second[1]} is about {_format_money(second[0])} a year. "
        f"The better option earns about {_format_money(diff)} more per year."
    )


def _try_multiple_income_streams(text: str) -> str | None:
    """e.g. 200 a day for 10 days plus 150 a day for 5 days."""
    if "plus" not in text and "and" not in text:
        return None

    streams = re.findall(
        r"(\d+(?:\.\d+)?)\s*(?:dollars?\s*)?(?:a|an)\s*day\s*for\s*(\d+(?:\.\d+)?)\s*days?",
        text,
    )
    if len(streams) < 2:
        return None

    total = 0.0
    parts = []
    for rate, days in streams:
        rate_f = float(rate)
        days_f = float(days)
        subtotal = rate_f * days_f
        total += subtotal
        parts.append(f"{_format_money(rate_f)} a day for {days_f:g} days ({_format_money(subtotal)})")

    return f"Combined income: {' plus '.join(parts)} equals {_format_money(total)} total."


def _try_monthly_earnings_question(text: str) -> str | None:
    """Catch-all for 'how much will I earn this month at X per day'."""
    if not any(w in text for w in ("earn", "make", "income", "paid", "pay")):
        return None
    if "month" not in text:
        return None

    match = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:dollars?\s*)?(?:a|an)\s*(hour|day|week)",
        text,
    )
    if not match:
        return None

    rate = float(match.group(1))
    unit = match.group(2)
    if unit == "hour":
        total = rate * 8 * WORKING_DAYS_PER_MONTH
        return (
            f"This month at {_format_money(rate)} an hour, 8 hours a day, "
            f"{WORKING_DAYS_PER_MONTH} working days, you would earn about {_format_money(total)}."
        )
    if unit == "day":
        total = rate * WORKING_DAYS_PER_MONTH
        return (
            f"This month at {_format_money(rate)} a day for {WORKING_DAYS_PER_MONTH} working days, "
            f"you would earn about {_format_money(total)}."
        )
    if unit == "week":
        total = rate * WEEKS_PER_MONTH
        return (
            f"This month at {_format_money(rate)} a week, "
            f"you would earn about {_format_money(total)}."
        )
    return None


def _extract_price_point(text: str) -> float | None:
    """Pull a unit/sale price from price-point phrasing."""
    patterns = [
        r"(\d+(?:\.\d+)?)\s*(?:dollar\s*)?price\s*(?:point|points)?",
        r"price\s*(?:point|points)?\s*(?:of|at|is)\s*(\d+(?:\.\d+)?)",
        r"(?:sell(?:ing)?|sold|sale)\s*(?:price|at|for)\s*(\d+(?:\.\d+)?)",
        r"(\d+(?:\.\d+)?)\s*(?:dollars?\s*)?(?:each|a piece|a unit|per\s*(?:sale|unit|item|product|customer|order))",
        r"at\s*(?:a|this|the)?\s*(\d+(?:\.\d+)?)\s*(?:dollar\s*)?(?:price\s*(?:point|points)?)?",
        r"for\s*(?:a|this|the)?\s*(\d+(?:\.\d+)?)\s*(?:dollar\s*)?(?:price\s*(?:point|points)?)?",
        r"(\d+(?:\.\d+)?)\s*(?:dollar\s*)?(?:price\s*(?:point|points)?)",
        r"price\s*(?:of|at|is)\s*(\d+(?:\.\d+)?)",
        r"for\s*(\d+(?:\.\d+)?)\s*(?:dollars?\s*)?(?:a|an)\s*(?:sale|unit|item|each)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return float(match.group(1))
    return None


def _extract_price_volume_pair(text: str) -> tuple[float, float] | None:
    """Parse 'at 25 for 10' or 'for 10 at 25' as price × daily volume."""
    patterns = [
        r"(?:at)\s*(\d+(?:\.\d+)?)\s*(?:for|with)\s*(\d+(?:\.\d+)?)",
        r"(?:for|with)\s*(\d+(?:\.\d+)?)\s*at\s*(\d+(?:\.\d+)?)",
        r"(?:earn|make|income|get)\s*(?:a|per)?\s*day\s*(?:for|with)\s*(\d+(?:\.\d+)?)\s*at\s*(\d+(?:\.\d+)?)",
        r"(?:earn|make|income|get)\s*(?:a|per)?\s*day\s*at\s*(\d+(?:\.\d+)?)\s*(?:for|with)\s*(\d+(?:\.\d+)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        first = float(match.group(1))
        second = float(match.group(2))
        if pattern.startswith(r"(?:for|with)") or "day for" in pattern:
            return second, first
        return first, second
    return None


def _daily_earnings_summary(daily: float, *, detail: str = "") -> str:
    prefix = f"{detail} " if detail else ""
    return (
        f"{prefix}About {_format_money(daily)} a day, "
        f"{_format_money(daily * 7)} a week, "
        f"{_format_money(daily * CALENDAR_DAYS_PER_MONTH)} a month, "
        f"and {_format_money(daily * 365)} a year."
    )


def _extract_sales_volume(text: str) -> tuple[float, str] | None:
    """Return units sold and time period (day/week/month)."""
    patterns = [
        r"(\d+(?:\.\d+)?)\s*(?:sales|units|items|products|customers|orders|pieces)\s*(?:a|an|per|each)\s*(day|week|month)",
        r"sell(?:ing)?\s*(\d+(?:\.\d+)?)\s*(?:a|an|per|each)\s*(day|week|month)",
        r"(\d+(?:\.\d+)?)\s*(?:sales|units|items|products)\s*(?:every|each)\s*(day|week|month)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return float(match.group(1)), match.group(2)

    # "10 per day" when talking about sales/units/earn
    if any(w in text for w in ("sale", "unit", "sell", "customer", "order", "item", "product", "earn", "make")):
        match = re.search(r"(\d+(?:\.\d+)?)\s*(?:a|an|per)\s*(day|week|month)\b", text)
        if match:
            return float(match.group(1)), match.group(2)
    return None


def _try_casual_daily_earnings(text: str) -> str | None:
    """Casual phrasing: how much a day at 25, for 10 at 25, for this price 40."""
    wants_daily = any(p in text for p in ("a day", "per day", "daily", "how much day"))
    wants_earn = any(w in text for w in ("earn", "make", "income", "get", "bring", "how much"))
    if not wants_daily and not re.search(r"how much.*day|day.*how much", text):
        return None
    if not wants_earn and "price" not in text:
        return None

    pair = _extract_price_volume_pair(text)
    if pair:
        price, volume = pair
        daily = price * volume
        return _daily_earnings_summary(
            daily,
            detail=f"At {_format_money(price)} with {volume:g} a day, you would earn",
        )

    single_patterns = [
        r"how much (?:will i|do i|would i|can i)?\s*(?:earn|make|get)?\s*(?:a|per)?\s*day\s*(?:at|for)\s*(\d+(?:\.\d+)?)",
        r"how much (?:a|per)\s*day\s*(?:at|for)\s*(\d+(?:\.\d+)?)",
        r"(?:earn|make|get)\s*(?:a|per)\s*day\s*(?:at|for)\s*(\d+(?:\.\d+)?)",
        r"(?:at|for)\s*(\d+(?:\.\d+)?)\s*(?:how much|what).*(?:a|per)\s*day",
        r"for (?:this )?price\s*(?:of|at|is)?\s*(\d+(?:\.\d+)?).*(?:how much|earn|make).*(?:a|per)\s*day",
        r"price\s*(?:of|at|is)\s*(\d+(?:\.\d+)?).*(?:how much|earn|make).*(?:a|per)\s*day",
        r"how much (?:will i|do i|would i|can i)?\s*(?:earn|make|get)\s*(?:a|per)\s*day\s*(?:for|at)\s*(?:this )?(?:price|number|amount)\s*(\d+(?:\.\d+)?)",
        r"(?:for|at)\s*(?:this )?(?:price|number|amount)\s*(\d+(?:\.\d+)?).*(?:how much|earn|make).*(?:a|per)\s*day",
    ]
    for pattern in single_patterns:
        match = re.search(pattern, text)
        if match:
            amount = float(match.group(1))
            return _daily_earnings_summary(
                amount,
                detail=f"At {_format_money(amount)} a day, you would earn",
            )

    # "how much a day at 25" without explicit earn
    match = re.search(r"how much (?:a|per)\s*day\s*(?:at|for)\s*(\d+(?:\.\d+)?)", text)
    if match:
        amount = float(match.group(1))
        return _daily_earnings_summary(amount, detail=f"At {_format_money(amount)},")

    return None


def _revenue_breakdown(price: float, units: float, unit_period: str) -> str:
    """Daily/weekly/monthly/yearly revenue from price × volume."""
    unit_period = unit_period.rstrip("s")

    if unit_period == "day":
        daily = price * units
        weekly = daily * 7
        monthly = daily * CALENDAR_DAYS_PER_MONTH
        yearly = daily * 365
        per_label = f"{units:g} sales a day"
    elif unit_period == "week":
        weekly = price * units
        daily = weekly / 7
        monthly = weekly * WEEKS_PER_MONTH
        yearly = weekly * WEEKS_PER_YEAR
        per_label = f"{units:g} sales a week"
    else:
        monthly = price * units
        daily = monthly / CALENDAR_DAYS_PER_MONTH
        weekly = monthly / WEEKS_PER_MONTH
        yearly = monthly * MONTHS_PER_YEAR
        per_label = f"{units:g} sales a month"

    return (
        f"At {_format_money(price)} per sale with {per_label}: "
        f"about {_format_money(daily)} a day, "
        f"{_format_money(weekly)} a week, "
        f"{_format_money(monthly)} a month, "
        f"and {_format_money(yearly)} a year."
    )


def _try_price_point_sales(text: str) -> str | None:
    """e.g. 25 dollar price point 10 sales a day, how much will I earn at 50 price point per day."""
    if any(w in text for w in ("cost", "profit", "margin", "markup")):
        return None

    has_price_hint = any(
        w in text
        for w in (
            "price point",
            "price points",
            "price",
            "each",
            "per sale",
            "per unit",
            "selling at",
            "sell at",
            "sale price",
        )
    )
    has_sales_hint = any(
        w in text for w in ("sale", "unit", "sell", "customer", "order", "item", "product", "piece")
    )
    if not has_price_hint and not ("price" in text and has_sales_hint):
        return None

    price = _extract_price_point(text)
    if price is None:
        return None

    volume = _extract_sales_volume(text)
    if volume is None:
        # "at 50 price point per day" or "earn at 25 per day" with price phrasing
        if "per day" in text or "a day" in text or "daily" in text:
            volume = (1.0, "day")
        elif "per week" in text or "a week" in text or "weekly" in text:
            volume = (1.0, "week")
        elif "per month" in text or "a month" in text or "monthly" in text or "this month" in text:
            volume = (1.0, "month")
        elif has_sales_hint:
            return None
        else:
            volume = (1.0, "day")

    units, period = volume
    return _revenue_breakdown(price, units, period)


def _try_price_point_earnings_question(text: str) -> str | None:
    """Catch phrasing like how much will I earn at this price point."""
    if not any(w in text for w in ("earn", "make", "income", "revenue", "bring in", "gross")):
        return None

    price = _extract_price_point(text)
    if price is None:
        # "how much at 40 per sale 12 per day"
        match = re.search(
            r"(\d+(?:\.\d+)?)\s*(?:dollars?\s*)?(?:a|an|per)\s*(sale|unit|item|product|customer|order)",
            text,
        )
        if match:
            price = float(match.group(1))
        else:
            return None

    volume = _extract_sales_volume(text)
    if volume is None:
        # Try "X per day" as volume when earn question present
        match = re.search(r"(\d+(?:\.\d+)?)\s*(?:a|an|per)\s*(day|week|month)\b", text)
        if match and float(match.group(1)) != price:
            volume = (float(match.group(1)), match.group(2))
        elif "per day" in text or "a day" in text or "daily" in text:
            volume = (1.0, "day")
        elif "per week" in text or "a week" in text:
            volume = (1.0, "week")
        elif "per month" in text or "a month" in text or "this month" in text:
            volume = (1.0, "month")
        else:
            return None

    units, period = volume
    prefix = "You would earn "
    if units == 1.0 and period == "day":
        prefix = "At one sale a day, you would earn "
    elif units == 1.0:
        prefix = f"At one sale a {period}, you would earn "
    return prefix + _revenue_breakdown(price, units, period).split(": ", 1)[1]


def _try_units_needed_for_target(text: str) -> str | None:
    """e.g. how many sales at 25 to make 500 a day."""
    if not any(w in text for w in ("how many", "units needed", "sales needed", "to make", "to earn")):
        return None

    price = _extract_price_point(text)
    if price is None:
        match = re.search(
            r"(?:at|for)\s*(\d+(?:\.\d+)?)\s*(?:dollars?\s*)?(?:each|a|an|per\s*(?:sale|unit))",
            text,
        )
        if match:
            price = float(match.group(1))
        else:
            return None

    target_match = re.search(
        r"(?:make|earn|gross|bring in|need)\s*(\d+(?:\.\d+)?)\s*(?:dollars?\s*)?(?:a|an|per)\s*(day|week|month)",
        text,
    )
    if not target_match:
        target_match = re.search(
            r"(\d+(?:\.\d+)?)\s*(?:dollars?\s*)?(?:a|an|per)\s*(day|week|month)",
            text,
        )
    if not target_match:
        return None

    target = float(target_match.group(1))
    period = target_match.group(2)
    if price <= 0:
        return None

    units_needed = target / price
    if period == "week":
        units_per_day = units_needed / 7
        return (
            f"To earn {_format_money(target)} a week at {_format_money(price)} per sale, "
            f"you need about {units_needed:.1f} sales a week, or {units_per_day:.1f} sales a day."
        )
    if period == "month":
        units_per_day = units_needed / CALENDAR_DAYS_PER_MONTH
        return (
            f"To earn {_format_money(target)} a month at {_format_money(price)} per sale, "
            f"you need about {units_needed:.1f} sales a month, or {units_per_day:.1f} sales a day."
        )
    return (
        f"To earn {_format_money(target)} a day at {_format_money(price)} per sale, "
        f"you need about {units_needed:.1f} sales a day."
    )


def _try_price_with_cost_profit(text: str) -> str | None:
    """e.g. sell at 50 price point cost 30 with 10 sales a day how much profit."""
    if "cost" not in text:
        return None

    price = _extract_price_point(text)
    cost_match = re.search(r"cost(?:s)?\s*(?:of|is|at)?\s*(\d+(?:\.\d+)?)", text)
    if price is None or cost_match is None:
        return None

    cost = float(cost_match.group(1))
    volume = _extract_sales_volume(text)
    if volume is None:
        return None
    units, period = volume

    profit_each = price - cost
    if period == "day":
        total_profit = profit_each * units
        period_label = f"{units:g} sales a day"
    elif period == "week":
        total_profit = profit_each * units
        period_label = f"{units:g} sales a week"
    else:
        total_profit = profit_each * units
        period_label = f"{units:g} sales a month"

    daily = total_profit / (1 if period == "day" else (7 if period == "week" else CALENDAR_DAYS_PER_MONTH))
    monthly = daily * CALENDAR_DAYS_PER_MONTH

    return (
        f"At {_format_money(price)} price point, {_format_money(cost)} cost, "
        f"and {period_label}: "
        f"{_format_money(profit_each)} profit per sale, "
        f"{_format_money(total_profit)} profit that period, "
        f"about {_format_money(daily)} profit a day "
        f"and {_format_money(monthly)} a month."
    )


_MONEY_CALCULATORS: list[Callable[[str], str | None]] = [
    _try_compare_income,
    _try_multiple_income_streams,
    _try_casual_daily_earnings,
    _try_units_needed_for_target,
    _try_price_point_earnings_question,
    _try_price_point_sales,
    _try_overtime,
    _try_hourly_schedule,
    _try_worked_days,
    _try_commission,
    _try_price_with_cost_profit,
    _try_profit,
    _try_after_tax,
    _try_split_tip,
    _try_salary_conversion,
    _try_monthly_earnings_question,
    _try_rate_for_period,
]


def try_money_math(text: str) -> str | None:
    """Run money/earnings scenario calculators on spoken text."""
    normalized = _normalize(text)
    if not normalized:
        return None

    money_hints = (
        "earn", "earning", "earnings", "salary", "wage", "pay", "paid", "income",
        "profit", "commission", "tax", "take home", "overtime", "dollars", "buck",
        "tip", "split", "bill", "margin", "markup", "revenue", "cost", "sell",
        "compare", "versus", " vs ", "worked", "working", "month", "week", "hour",
        "day", "year", "annual", "monthly", "weekly", "hourly",
        "price point", "price", "sale", "sales", "unit", "units", "sell", "selling",
        "customer", "order", "revenue", "gross", "each", "piece",
        "this price", "this number", "this amount", "number", "amount",
    )
    if not any(hint in normalized for hint in money_hints):
        return None
    if not re.search(r"\d", normalized):
        return None

    for calculator in _MONEY_CALCULATORS:
        try:
            result = calculator(normalized)
        except Exception:
            result = None
        if result is not None:
            return result
    return None
