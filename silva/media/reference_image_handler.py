"""Voice handling for importing and matching stored reference images."""

from __future__ import annotations


def _copy_to_clipboard(text: str) -> None:
    try:
        from silva.gui.media_library_popup import _overlay_parent

        root = _overlay_parent()
        if root is None:
            return
        root.clipboard_clear()
        root.clipboard_append(text)
    except Exception:
        return


def _speak_reference(assistant, text: str) -> None:
    speaker = getattr(assistant, "_speak_now", None)
    if callable(speaker):
        speaker(text)
        return
    assistant.say(text, interruptible=False)


def handle_reference_image_speech(assistant, text: str) -> bool:
    from silva.media.reference_image_phrases import (
        match_reference_image_speech,
        reference_query,
    )
    from silva.users.manager import get_active_user, is_owner

    action = match_reference_image_speech(text)
    if action is None:
        return False

    user = get_active_user() or {}
    if not is_owner(user):
        _speak_reference(assistant, "Only the owner can manage reference images.")
        return True

    if action == "open":
        from silva.gui.media_library_popup import show_media_library_popup

        opened = show_media_library_popup(owner_id=str(user.get("id") or "owner"))
        _speak_reference(
            assistant,
            "Image library popup is open." if opened else "Image library popup could not be opened here.",
        )
        return True

    if action == "scan":
        from silva.media.reference_images import CATEGORY_LABELS, scan_downloads

        records = scan_downloads(added_by=str(user.get("id") or "owner"))
        if not records:
            _speak_reference(assistant, "No new images found in Downloads.")
            return True
        counts = {
            category: sum(1 for record in records if record.get("category") == category)
            for category in CATEGORY_LABELS
        }
        parts = [
            f"{count} {CATEGORY_LABELS[category].lower()}"
            for category, count in counts.items()
            if count
        ]
        detail = ", ".join(parts)
        _speak_reference(
            assistant,
            f"Stored {len(records)} new reference image(s) from Downloads: {detail}.",
        )
        return True

    from silva.media.reference_images import CATEGORY_LABELS, find_references

    query = reference_query(text)
    records = find_references(query, limit=3)
    if not records:
        _speak_reference(assistant, "I don't have a reference image matching that yet.")
        return True
    summaries = []
    for record in records:
        label = str(record.get("label") or record.get("name") or "image")
        category = CATEGORY_LABELS.get(record.get("category"), "Object")
        summaries.append(f"{label} in {category}")
    _speak_reference(assistant, "I found " + "; ".join(summaries) + ".")
    return True

