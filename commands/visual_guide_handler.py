"""Capture screen/video and build searchable step guides."""

from __future__ import annotations

from silva.commands.visual_guide_phrases import VisualGuideSpeech, match_visual_guide_speech
from silva.commands.visual_guide_search import build_steps_from_results, search_snippets
from silva.commands.visual_guide_store import (
    load_latest_guide,
    mark_step_complete,
    new_guide_id,
    reset_steps,
    save_guide,
    update_guide,
)
from silva.config import CONFIG_DIR, load_config
from silva.media.gyazo import upload_image
from silva.media.screen_record import record_screen
from silva.media.screenshot import SCREENSHOT_DIR, capture_screen

CAPTURE_ROOT = CONFIG_DIR / "captures"


def is_visual_guide_enabled() -> bool:
    return bool(load_config().get("visual_guide_enabled", True))


def _capture(*, want_video: bool, track_mouse: bool) -> tuple[str, str, list[tuple[int, int, float]]]:
    CAPTURE_ROOT.mkdir(parents=True, exist_ok=True)
    mouse_log: list[tuple[int, int, float]] = []
    if want_video:
        path, mouse_log = record_screen(track_mouse=track_mouse)
        return str(path), "video", mouse_log
    _frame, path = capture_screen(save=True)
    if path is None:
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        path = SCREENSHOT_DIR / "screen_latest.png"
    return str(path), "screenshot", mouse_log


def start_visual_guide(text: str, speech: VisualGuideSpeech) -> tuple[str, dict | None]:
    track_mouse = bool(load_config().get("visual_guide_track_mouse", True))
    want_video = speech.want_video or speech.kind == "analyze"
    if "game" in text.lower() or "mod" in text.lower():
        want_video = want_video or bool(load_config().get("visual_guide_video_for_games", True))

    capture_path, capture_kind, mouse_log = _capture(
        want_video=want_video,
        track_mouse=track_mouse and want_video,
    )

    gyazo_url = None
    if capture_kind == "screenshot":
        gyazo_url = upload_image(__import__("pathlib").Path(capture_path), title=speech.query[:120])

    query = speech.query or "what is on screen"
    lower_q = query.lower()
    if any(
        phrase in lower_q
        for phrase in (
            "what is this",
            "what does this mean",
            "what does that mean",
            "explain this",
            "explain that",
            "what am i looking at",
        )
    ):
        search_q = query
    else:
        search_q = query + " how to guide game mod steam reddit youtube"

    results = search_snippets(search_q)
    steps = build_steps_from_results(query, results)
    guide_id = new_guide_id()
    save_guide(
        guide_id=guide_id,
        query=query,
        steps=steps,
        capture_path=capture_path,
        capture_kind=capture_kind,
        search_results=results,
        mouse_log=mouse_log,
        gyazo_url=gyazo_url,
    )
    guide = load_latest_guide()
    summary = (
        f"I saved a {capture_kind} to your captures folder and built {len(steps)} steps. "
        f"Say 'give me step by step' to walk through them."
    )
    if gyazo_url:
        summary += f" Gyazo link saved in the guide."
    return summary, {"guide_id": guide_id, "phase": "ready", "guide": guide}


def begin_step_by_step(guide: dict) -> tuple[str, dict]:
    index = int(guide.get("current_step", 0))
    steps = guide.get("steps", [])
    if not steps:
        return "This guide has no steps yet.", {"phase": "ready", "guide": guide}
    guide["phase"] = "step_active"
    update_guide(guide)
    return f"Step {index + 1}: {steps[index]}", {"phase": "step_active", "guide": guide, "step_index": index}


def advance_step(guide: dict) -> tuple[str, dict]:
    index = int(guide.get("current_step", 0))
    steps = guide.get("steps", [])
    if not steps:
        return "No active guide steps.", {"phase": "ready", "guide": guide}
    mark_step_complete(guide, index, done=True)
    guide = load_latest_guide() or guide
    next_index = int(guide.get("current_step", 0))
    if next_index >= len(steps):
        return "All steps are complete. Say restart steps if you want to run through again.", {
            "phase": "done",
            "guide": guide,
        }
    return f"Step {next_index + 1}: {steps[next_index]}", {
        "phase": "step_active",
        "guide": guide,
        "step_index": next_index,
    }


def handle_visual_guide_speech(text: str) -> tuple[str | None, dict | None]:
    if not is_visual_guide_enabled():
        return "Visual guides are turned off in settings.", None

    speech = match_visual_guide_speech(text)
    if speech is None:
        return None, None

    if speech.kind == "step_done":
        guide = load_latest_guide()
        if not guide:
            return "No guide is active. Ask what is this or how does this work first.", None
        msg, flow = advance_step(guide)
        return msg, flow

    if speech.kind == "restart_steps":
        guide = load_latest_guide()
        if not guide:
            return "No guide to restart.", None
        reset_steps(guide)
        guide = load_latest_guide() or guide
        return "Steps reset. Say give me step by step when you're ready.", {"phase": "ready", "guide": guide}

    if speech.kind == "step_by_step":
        guide = load_latest_guide()
        if not guide:
            return "Capture something first — say what is this or record my screen.", None
        return begin_step_by_step(guide)

    if speech.kind in {"analyze", "capture"}:
        return start_visual_guide(text, speech)

    return None, None
