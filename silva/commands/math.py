"""Math evaluation from basic arithmetic through algebra and unit conversion."""

from __future__ import annotations

import ast
import math
import operator
import re
from collections.abc import Callable
from typing import Any

from silva.commands.math_phrases import match_math_speech
from silva.commands.math_money import try_money_math
from silva.history_store import get_recent_calculations, record_calculation

_WORD_NUMBERS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
    "hundred": 100,
    "thousand": 1000,
}

_UNIT_ALIASES = {
    "meter": "m",
    "meters": "m",
    "metre": "m",
    "metres": "m",
    "foot": "ft",
    "feet": "ft",
    "inch": "in",
    "inches": "in",
    "centimeter": "cm",
    "centimeters": "cm",
    "centimetre": "cm",
    "centimetres": "cm",
    "kilometer": "km",
    "kilometers": "km",
    "kilometre": "km",
    "kilometres": "km",
    "mile": "mi",
    "miles": "mi",
    "pound": "lb",
    "pounds": "lb",
    "kilogram": "kg",
    "kilograms": "kg",
    "ounce": "oz",
    "ounces": "oz",
    "gram": "g",
    "grams": "g",
    "liter": "l",
    "liters": "l",
    "litre": "l",
    "litres": "l",
    "gallon": "gal",
    "gallons": "gal",
}

_TO_METERS = {"m": 1.0, "ft": 0.3048, "in": 0.0254, "cm": 0.01, "km": 1000.0, "mi": 1609.344}
_TO_KG = {"kg": 1.0, "lb": 0.453592, "oz": 0.0283495, "g": 0.001}
_TO_LITERS = {"l": 1.0, "gal": 3.78541}

_SAFE_FUNCTIONS: dict[str, Callable[..., float]] = {
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log10,
    "ln": math.log,
    "abs": abs,
    "round": round,
    "pow": pow,
}


class _SafeEvaluator(ast.NodeVisitor):
    """Evaluate numeric expressions without calling eval()."""

    def visit(self, node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return self.visit(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError("Only numbers are allowed.")
        if isinstance(node, ast.Num):
            return node.n
        if isinstance(node, ast.BinOp):
            left = self.visit(node.left)
            right = self.visit(node.right)
            return _BIN_OPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp):
            value = self.visit(node.operand)
            return _UNARY_OPS[type(node.op)](value)
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ValueError("Unsupported function call.")
            func = _SAFE_FUNCTIONS.get(node.func.id)
            if func is None:
                raise ValueError(f"Function '{node.func.id}' is not supported.")
            args = [self.visit(arg) for arg in node.args]
            return func(*args)
        if isinstance(node, ast.Name):
            if node.id == "pi":
                return math.pi
            if node.id == "e":
                return math.e
            raise ValueError(f"Unknown name '{node.id}'.")
        raise ValueError("Unsupported expression.")

    def visit_Module(self, node: ast.Module) -> Any:
        raise ValueError("Unsupported expression.")


_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
}

_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _normalize_query(text: str) -> str:
    text = text.strip().lower()
    text = text.replace("'", "")
    text = text.replace("×", "*").replace("÷", "/")
    text = re.sub(r"\bplus\b", "+", text)
    text = re.sub(r"\bminus\b", "-", text)
    text = re.sub(r"\bequals\b|\bequal to\b", "=", text)
    text = re.sub(r"\btimes\b|\bmultiplied by\b|\bx\b(?=\s*\d)", "*", text)
    text = re.sub(r"\bdivided by\b|\bover\b", "/", text)
    text = re.sub(r"\bsquared\b", "** 2", text)
    text = re.sub(r"\bcubed\b", "** 3", text)
    text = re.sub(r"\bsquare root of\b|\bsqrt of\b|\bsqrt\b", "sqrt", text)
    text = re.sub(r"\bto the power of\b|\braised to\b", "**", text)
    text = re.sub(r"\^", "**", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _words_to_numbers(text: str) -> str:
    for word, value in sorted(_WORD_NUMBERS.items(), key=lambda item: -len(item[0])):
        text = re.sub(rf"\b{word}\b", str(value), text)
    return text


def _format_number(value: float | int | str) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, float):
        rounded = round(value, 6)
        text = f"{rounded:.6f}".rstrip("0").rstrip(".")
        return text or "0"
    return str(value)


def _try_percent(text: str) -> str | None:
    match = re.search(
        r"(\d+(?:\.\d+)?)\s*%\s*of\s*(\d+(?:\.\d+)?)|"
        r"(\d+(?:\.\d+)?)\s*percent\s*of\s*(\d+(?:\.\d+)?)",
        text,
    )
    if not match:
        return None
    pct = float(match.group(1) or match.group(3))
    base = float(match.group(2) or match.group(4))
    result = base * pct / 100.0
    return f"{pct}% of {base} is {_format_number(result)}"


def _try_factorial(text: str) -> str | None:
    match = re.search(r"(\d+)\s*factorial|factorial\s*of\s*(\d+)", text)
    if not match:
        return None
    n = int(match.group(1) or match.group(2))
    if n < 0 or n > 170:
        raise ValueError("Factorial input must be between 0 and 170.")
    return f"{n} factorial is {_format_number(math.factorial(n))}"


def _try_unit_conversion(text: str) -> str | None:
    match = re.search(
        r"(\d+(?:\.\d+)?)\s*([a-z]+)\s*(?:to|in)\s*([a-z]+)",
        text,
    )
    if not match:
        return None
    amount = float(match.group(1))
    src = _UNIT_ALIASES.get(match.group(2), match.group(2))
    dst = _UNIT_ALIASES.get(match.group(3), match.group(3))

    if src in _TO_METERS and dst in _TO_METERS:
        meters = amount * _TO_METERS[src]
        result = meters / _TO_METERS[dst]
        return f"{amount} {match.group(2)} equals {_format_number(result)} {match.group(3)}"

    if src in _TO_KG and dst in _TO_KG:
        kg = amount * _TO_KG[src]
        result = kg / _TO_KG[dst]
        return f"{amount} {match.group(2)} equals {_format_number(result)} {match.group(3)}"

    if src in _TO_LITERS and dst in _TO_LITERS:
        liters = amount * _TO_LITERS[src]
        result = liters / _TO_LITERS[dst]
        return f"{amount} {match.group(2)} equals {_format_number(result)} {match.group(3)}"

    return None


def _try_algebra(text: str) -> str | None:
    text = _normalize_query(text)
    if "=" not in text and "solve" not in text:
        return None
    try:
        import sympy
        from sympy import Eq, Symbol, solve
    except ImportError:
        return None

    expr = text
    expr = re.sub(r"^solve\s+(for\s+)?[a-z]\s+(in\s+)?", "", expr)
    expr = expr.replace("=", " = ")
    if "=" not in expr:
        return None

    left, right = [part.strip() for part in expr.split("=", 1)]
    x = Symbol("x")
    symbols_map = {"x": x}

    def _sympy_expr(part: str):
        part = part.replace("^", "**")
        part = re.sub(r"(\d)([a-z])", r"\1*\2", part)
        part = re.sub(r"([a-z])(\d)", r"\1*\2", part)
        return sympy.sympify(part, locals=symbols_map)

    try:
        equation = Eq(_sympy_expr(left), _sympy_expr(right))
        solutions = solve(equation, x)
    except Exception:
        return None

    if not solutions:
        return "I could not find a solution for that equation."
    if len(solutions) == 1:
        return f"x equals {_format_number(float(solutions[0]))}"
    joined = ", ".join(_format_number(float(item)) for item in solutions)
    return f"The solutions are x equals {joined}"


def _try_expression(text: str) -> str | None:
    cleaned = _words_to_numbers(_normalize_query(text))
    cleaned = cleaned.replace("=", "").strip()
    cleaned = re.sub(r"(\d)([a-z])", r"\1*\2", cleaned)
    if not re.search(r"[\d+\-*/().]", cleaned):
        return None
    tree = ast.parse(cleaned, mode="eval")
    result = _SafeEvaluator().visit(tree)
    return _format_number(result)


def _try_money(text: str) -> str | None:
    return try_money_math(text)


_CALCULATORS: list[Callable[[str], str | None]] = [
    _try_money,
    _try_percent,
    _try_factorial,
    _try_unit_conversion,
    _try_algebra,
    _try_expression,
]


def evaluate_math(query: str) -> tuple[str, str]:
    """Return (result_text, category)."""
    text = query.strip()
    if not text:
        raise ValueError("Tell me what to calculate.")

    for calculator in _CALCULATORS:
        try:
            result = calculator(text)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        except Exception:
            result = None
        if result is not None:
            category = calculator.__name__.replace("_try_", "")
            return result, category

    raise ValueError("I couldn't figure out that math problem. Try rephrasing it.")


def handle_math_speech(user_id: str, text: str) -> str | None:
    speech = match_math_speech(text)
    if speech is None:
        return None

    if speech.action == "recall":
        items = get_recent_calculations(user_id, limit=1)
        if not items:
            return "You have no saved calculations yet."
        last = items[0]
        return f"Your last calculation was {last['query']}. The answer is {last['result']}."

    if speech.action == "history":
        items = get_recent_calculations(user_id, limit=5)
        if not items:
            return "You have no calculation history yet."
        lines = ["Here are your recent calculations:"]
        for item in items:
            lines.append(f"- {item['query']} = {item['result']}")
        return "\n".join(lines)

    if speech.action == "calculate":
        result, category = evaluate_math(speech.query)
        record_calculation(user_id, query=speech.query, result=result, category=category)
        return result

    return None
