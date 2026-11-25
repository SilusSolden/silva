from __future__ import annotations

from silva.logger import log_error, log_info


def _speak(assistant, text: str) -> None:
    speaker = getattr(assistant, "_speak_now", None)
    if callable(speaker):
        speaker(text)
        return
    assistant.say(text, interruptible=False)


def _refusal(record: dict | None) -> str:
    if isinstance(record, dict):
        return str(record.get("refusal") or "")
    return ""


def _open_viewer(record: dict, user_id: str) -> None:
    from silva.gui.media_library_popup import show_image_viewer
    from silva.media.image_generator import save_generated_to_library

    image_id = str(record.get("id") or "")
    show_image_viewer(
        str(record.get("path") or ""),
        title=str(record.get("prompt") or "Generated image")[:70],
        notes=str(record.get("description") or ""),
        save_callback=lambda: save_generated_to_library(image_id, user_id=user_id),
    )


def handle_image_generation_speech(assistant, text: str) -> bool:
    from silva.media.image_generator import (
        active_image_for,
        describe_generated_image,
        edit_image,
        generate_image,
        save_generated_to_library,
    )
    from silva.media.image_generator_phrases import (
        edit_prompt,
        image_prompt,
        match_image_generation_speech,
    )
    from silva.users.manager import get_active_user

    action = match_image_generation_speech(text)
    if action is None:
        return False

    log_info(f"Image Studio voice command: {action} | {text[:120]}")
    user = get_active_user() or {}
    user_id = str(user.get("id") or "default")

    if action == "open":
        from silva.gui.image_generator_popup import show_image_generator_popup

        opened = show_image_generator_popup(user_id=user_id)
        _speak(
            assistant,
            "Image Studio is open." if opened else "Image Studio could not be opened here.",
        )
        return True

    if action == "status":
        from silva.media.image_generator_gpu import startup_check

        result = startup_check()
        _speak(assistant, str(result.get("message") or "Image generation status is unavailable."))
        return True

    if action == "test":
        from silva.media.image_generator import generate_gpu_test_image

        _speak(assistant, "Running a small GPU image test now.")
        try:
            record = generate_gpu_test_image(user_id=user_id)
        except Exception as exc:
            log_error("Image Studio GPU test failed", exc=exc)
            _speak(assistant, "The GPU test hit an error. Check the Silva log for details.")
            return True
        refusal = _refusal(record)
        if refusal:
            _speak(assistant, refusal)
            return True
        if record is None:
            _speak(assistant, "I could not finish the GPU test.")
            return True
        _open_viewer(record, user_id)
        _speak(assistant, "GPU test image ready. Check the viewer to see it.")
        return True

    if action == "generate":
        _speak(assistant, "Building your image now.")
        try:
            record = generate_image(image_prompt(text), user_id=user_id)
        except Exception as exc:
            log_error("Image Studio generation failed", exc=exc)
            _speak(assistant, "Image generation hit an error. Check the Silva log for details.")
            return True
        refusal = _refusal(record)
        if refusal:
            _speak(assistant, refusal)
            return True
        if record is None:
            _speak(assistant, "I could not build that image.")
            return True
        log_info(f"Image Studio voice generation ready: {record.get('id')}")
        _open_viewer(record, user_id)
        _speak(
            assistant,
            "Image ready. You can say add a moon, describe this image, or save this image.",
        )
        return True

    active = active_image_for(user_id)
    if active is None:
        _speak(assistant, "There is no active generated image yet. Ask me to make an image first.")
        return True

    if action == "edit":
        _speak(assistant, "Adding that to the image.")
        try:
            record = edit_image(str(active["id"]), edit_prompt(text), user_id=user_id)
        except Exception as exc:
            log_error("Image Studio edit failed", exc=exc)
            _speak(assistant, "The image edit hit an error. Check the Silva log for details.")
            return True
        refusal = _refusal(record)
        if refusal:
            _speak(assistant, refusal)
            return True
        if record is None:
            _speak(assistant, "I could not update that image.")
            return True
        _open_viewer(record, user_id)
        _speak(assistant, "Image updated. You can keep adding details or save this image.")
        return True

    if action == "describe":
        description = describe_generated_image(str(active["id"]))
        try:
            from silva.gui.media_library_popup import _overlay_parent

            root = _overlay_parent()
            if root is not None:
                root.clipboard_clear()
                root.clipboard_append(description)
        except Exception:
            pass
        _speak(assistant, description)
        return True

    record = save_generated_to_library(str(active["id"]), user_id=user_id)
    if record is None:
        _speak(assistant, "That image is already in the library or could not be saved.")
        return True
    _speak(assistant, "Saved to the image library. The viewer can stay open.")
    return True
