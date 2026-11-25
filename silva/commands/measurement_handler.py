"""Assistant-facing measurement command helpers."""

from __future__ import annotations

from silva.commands.measurement import capture_and_measure, format_measurement
from silva.commands.measurement_phrases import match_measurement_speech
from silva.history_store import get_recent_measurements, record_measurement


def handle_measurement_speech(user_id: str, text: str) -> tuple[str | None, dict | None]:
    speech = match_measurement_speech(text)
    if speech is None:
        return None, None

    if speech.action == "recall":
        items = get_recent_measurements(user_id, limit=1)
        if not items:
            return "You have no saved measurements yet.", None
        last = items[0]
        return last.get("summary") or "I saved a measurement but have no details.", None

    if speech.action == "history":
        items = get_recent_measurements(user_id, limit=5)
        if not items:
            return "You have no measurement history yet.", None
        lines = ["Here are your recent measurements:"]
        for item in items:
            lines.append(f"- {item.get('summary', item.get('query', 'measurement'))}")
        return "\n".join(lines), None

    if speech.action == "measure":
        try:
            result = capture_and_measure(source=speech.source, query=speech.query)
        except RuntimeError as exc:
            return str(exc), None
        except Exception as exc:
            return f"I could not capture an image to measure: {exc}", None

        summary = format_measurement(result)
        record_measurement(
            user_id,
            query=speech.query or text,
            source=speech.source,
            summary=summary,
            width_px=result.width_px,
            height_px=result.height_px,
            width_mm=result.width_mm,
            height_mm=result.height_mm,
            confidence=result.confidence,
            image_path=result.image_path,
        )
        return summary, None

    return None, None
