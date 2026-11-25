"""Voice + GUI flow for camera plug-in detect, combo warnings, and test runs."""

from __future__ import annotations

from silva.commands.camera_setup_phrases import (
    is_camera_cancel_speech,
    is_camera_setup_command,
    parse_test_duration,
)
from silva.media.camera import (
    CAMERA_MISSING_MESSAGE,
    COMBO_HEAT_WARNING,
    ensure_camera_ready,
    is_combo_camera,
    is_dedicated_camera,
    usable_camera_names,
)
from silva.media.perf_guard import guard_camera_command

SKIP_TEST_MESSAGE = (
    "Okay, I'll skip the camera test. I can still use it for normal camera commands if you ask."
)


def pick_camera_offer(names: list[str] | None = None) -> dict | None:
    names = names if names is not None else usable_camera_names(force=True)
    if not names:
        return None
    dedicated = [name for name in names if is_dedicated_camera(name)]
    combo = [name for name in names if is_combo_camera(name)]
    if dedicated:
        name = dedicated[0]
    elif combo:
        name = combo[0]
    else:
        name = names[0]
    return {"name": name, "is_combo": is_combo_camera(name)}


def _offer_message(offer: dict) -> str:
    name = offer["name"]
    if offer.get("is_combo"):
        return (
            f"I found {name}. {COMBO_HEAT_WARNING} "
            "Would you like a test run anyway? Say 30 seconds or one minute. "
            "Say no to skip the test — I can still use it for normal camera commands if you ask."
        )
    return (
        f"I found a new camera, {name}. Want a test run? "
        "Say 30 seconds or one minute. Say no to skip the test — "
        "I can still use it for normal camera commands."
    )


def offer_for_camera(name: str, *, is_combo: bool | None = None) -> tuple[str, dict]:
    combo = is_combo_camera(name) if is_combo is None else bool(is_combo)
    offer = {"name": name, "is_combo": combo}
    flow = {"phase": "open_warning" if combo else "await_choice", **offer}
    return _offer_message(offer), flow


def gate_camera_test(offer: dict) -> str | None:
    """Silent Hub + CPU/RAM check. Returns a spoken refusal, or None if it is safe."""
    return guard_camera_command(str(offer.get("name") or ""))


def start_camera_test(offer: dict, duration: int) -> tuple[str, dict]:
    extra = f" {COMBO_HEAT_WARNING}" if offer.get("is_combo") else ""
    refusal = gate_camera_test(offer)
    if refusal:
        return refusal, {"phase": "blocked", "seconds": duration, **offer}
    return (
        f"Starting a {duration}-second camera test.{extra}",
        {"phase": "open_preview", "seconds": duration, **offer},
    )


def handle_camera_setup_speech(text: str) -> tuple[str | None, dict | None]:
    if not is_camera_setup_command(text):
        return None, None

    missing = ensure_camera_ready()
    if missing:
        return missing, None

    offer = pick_camera_offer()
    if offer is None:
        return CAMERA_MISSING_MESSAGE, None

    duration = parse_test_duration(text)
    if duration:
        return start_camera_test(offer, duration)
    return offer_for_camera(offer["name"], is_combo=offer["is_combo"])


def continue_camera_setup_flow(text: str, flow: dict) -> tuple[str, dict | None]:
    normalized = text.strip().lower()
    offer = {
        "name": str(flow.get("name") or "this camera"),
        "is_combo": bool(flow.get("is_combo")),
    }
    phase = str(flow.get("phase") or "")

    if is_camera_cancel_speech(text):
        return SKIP_TEST_MESSAGE, None

    if phase == "preview":
        return "", dict(flow)

    duration = parse_test_duration(text)
    if duration is None and normalized in {"yes", "yeah", "yep", "yup", "sure", "ok", "okay", "test it", "use it"}:
        return (
            "30 seconds or one minute?",
            {"phase": "await_choice", **offer},
        )
    if duration is None:
        return "Say 30 seconds, one minute, or no.", {"phase": "await_choice", **offer}

    return start_camera_test(offer, duration)
