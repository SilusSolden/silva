"""Run Silva tests and command scenarios from the dev panel."""

from __future__ import annotations

from dataclasses import dataclass, field

from silva.commands.appointment_phrases import is_appointment_command
from silva.commands.math_phrases import is_math_command
from silva.commands.measurement_phrases import is_measurement_command
from silva.commands.registry import match_command
from silva.commands.weather_feedback import is_weather_feedback_command
from silva.commands.weather_forecast_phrases import is_weather_forecast_command


@dataclass
class ScenarioResult:
    name: str
    phrase: str
    ok: bool
    detail: str = ""


@dataclass
class TestRunResult:
    passed: bool
    tests_run: int
    failures: int
    errors: int
    output: str
    scenario_results: list[ScenarioResult] = field(default_factory=list)
    broken_items: list[str] = field(default_factory=list)


COMMAND_SCENARIOS: tuple[tuple[str, str], ...] = (
    ("weather_command", "what's my local weather"),
    ("weather_basic", "weather"),
    ("wikipedia", "what is photosynthesis"),
    ("appointment_create", "schedule appointment dentist tomorrow at 2 pm"),
    ("appointment_list", "list my appointments"),
    ("math_basic", "what is 10 plus 5"),
    ("math_money", "how much can I earn at 50 dollars a day for a month"),
    ("measurement_camera", "look at this in my hand and measure it"),
    ("measurement_screen", "measure what's on my screen"),
    ("weather_forecast", "next few days weather"),
    ("weather_feedback_dispute", "that weather is not right"),
    ("weather_feedback_report", "it's storming outside"),
    ("help_phrase", "help"),
)


def _check_scenario(name: str, phrase: str) -> ScenarioResult:
    try:
        if name.startswith("weather_command") or name == "weather_basic":
            ok = match_command(phrase) is not None and match_command(phrase).name == "weather"
            detail = "weather registry match" if ok else "no weather match"
        elif name == "wikipedia":
            ok = match_command(phrase) is not None and match_command(phrase).name == "wikipedia"
            detail = "wikipedia match" if ok else "no wikipedia match"
        elif name.startswith("appointment"):
            ok = is_appointment_command(phrase)
            detail = "appointment phrase" if ok else "appointment not detected"
        elif name.startswith("math"):
            ok = is_math_command(phrase)
            detail = "math phrase" if ok else "math not detected"
        elif name.startswith("measurement"):
            ok = is_measurement_command(phrase)
            detail = "measurement phrase" if ok else "measurement not detected"
        elif name == "weather_forecast":
            ok = is_weather_forecast_command(phrase)
            detail = "forecast phrase" if ok else "forecast not detected"
        elif name.startswith("weather_feedback"):
            ok = is_weather_feedback_command(phrase)
            detail = "weather feedback phrase" if ok else "feedback not detected"
        elif name == "help_phrase":
            from silva.commands.help_phrases import is_help_request

            ok = is_help_request(phrase)
            detail = "help phrase" if ok else "help not recognized"
        else:
            ok = False
            detail = "unknown scenario"
        return ScenarioResult(name=name, phrase=phrase, ok=ok, detail=detail)
    except Exception as exc:
        return ScenarioResult(name=name, phrase=phrase, ok=False, detail=str(exc))


def run_command_scenarios() -> list[ScenarioResult]:
    return [_check_scenario(name, phrase) for name, phrase in COMMAND_SCENARIOS]


def run_all_tests(*, include_unit_tests: bool = True) -> TestRunResult:
    scenario_results = run_command_scenarios()
    broken: list[str] = []
    for item in scenario_results:
        if not item.ok:
            broken.append(f"[scenario] {item.name}: {item.phrase} — {item.detail}")

    output_parts: list[str] = ["=== Command scenario checks ==="]
    for item in scenario_results:
        status = "OK" if item.ok else "FAIL"
        output_parts.append(f"{status}  {item.name}: {item.phrase}")
        if item.detail and not item.ok:
            output_parts.append(f"       {item.detail}")

    tests_run = 0
    failures = 0
    errors = 0

    if include_unit_tests:
        output_parts.append("")
        output_parts.append("=== Unit test suite ===")
        import subprocess
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-q"],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=180,
            )
        except Exception as exc:
            tests_run = 0
            failures = 0
            errors = 1
            output_parts.append(f"Unit tests could not start: {exc}")
            broken.append(f"[unittest] {exc}")
        else:
            output_parts.append(proc.stdout or "")
            output_parts.append(proc.stderr or "")
            tests_run = 1 if proc.returncode == 0 else 0
            failures = 0 if proc.returncode == 0 else 1
            errors = 0
            if proc.returncode != 0:
                broken.append("[unittest] suite failed in a separate process (safe for live Silva).")

    passed = not broken and failures == 0 and errors == 0
    return TestRunResult(
        passed=passed,
        tests_run=tests_run,
        failures=failures,
        errors=errors,
        output="\n".join(output_parts),
        scenario_results=scenario_results,
        broken_items=broken,
    )
