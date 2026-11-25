"""Voice commands to record, assign, and edit custom word pronunciations."""

from __future__ import annotations

from silva.logger import log_info


def handle_pronunciation_speech(assistant, text: str) -> bool:
    from silva.commands.help_phrases import should_yield_to_feature_help
    from silva.commands.pronunciation_phrases import match_pronunciation_speech
    from silva.users.manager import get_active_user

    if should_yield_to_feature_help(text):
        return False

    match = match_pronunciation_speech(text)
    if match is None:
        return False

    user = get_active_user() or {}
    user_id = str(user.get("id") or "").strip()
    log_info(f"Pronunciation command ({match.action}): {text[:120]}")
    if match.action == "ask":
        from silva.conversation.correction_repair import note_pronunciation_question

        note_pronunciation_question(assistant, text, match.word or "")
        return _tell_how_said(assistant, match.word)
    if not user_id or user_id == "guest":
        assistant.say(
            "Open your profile first, or say who am I so I know where to save the word recording.",
            interruptible=False,
        )
        return True
    if match.action == "edit":
        return _open_editor(assistant, user_id, match.word)
    return _record_and_remember(assistant, user_id, match.word)


def _tell_how_said(assistant, word: str | None) -> bool:
    from silva.users.word_pronunciations import (
        active_word_variants,
        normalize_spoken,
        normalize_word,
        pick_single_word,
    )

    target = normalize_word(pick_single_word(word or ""))
    if not target:
        assistant.say("Tell me the word and I will say it.", interruptible=False)
        return True
    rows = [
        row
        for row in active_word_variants()
        if normalize_word(str(getattr(row, "word", "") or "")) == target
    ]
    active = [row for row in rows if getattr(row, "active", False)]
    chosen = (active or rows)[0] if rows else None
    learned = normalize_spoken(str(getattr(chosen, "spoken_as", "") or "")) if chosen else ""
    learned = learned or target
    log_info(f"Pronunciation ask: {target} -> {learned}")
    if chosen:
        assistant.say(f"For that word, I say {learned}.", interruptible=False)
    else:
        assistant.say(f"I say {target}.", interruptible=False)
    return True


def _record_and_remember(assistant, user_id: str, word: str | None) -> bool:
    from silva.gui.word_pronunciation_dialog import (
        run_pronunciation_assign_blocking,
        run_pronunciation_record_blocking,
    )
    from silva.users.word_pronunciations import remember_word_from_clip

    if word:
        assistant.say(
            f'Say only "{word}". I will remember that word and speak it myself.',
            interruptible=False,
        )
    else:
        assistant.say(
            "Say only the word. I will listen, save that word, and speak it in my voice from now on.",
            interruptible=False,
        )

    recorded = run_pronunciation_record_blocking(user_id, word)
    if not recorded.saved:
        assistant.say("Pronunciation recording cancelled.", interruptible=False)
        return True

    try:
        mapped = remember_word_from_clip(user_id, recorded.clip_id, expected_word=word)
        log_info(f"Pronunciation memory saved: {mapped.word!r} -> {mapped.wav_file}")
        assistant.say(f"Saved {mapped.word}.", interruptible=False)
        return True
    except RuntimeError:
        pass

    assistant.say("I did not catch the word or phrase. Type what this recording is for.", interruptible=False)
    assigned = run_pronunciation_assign_blocking(user_id, clip_id=recorded.clip_id, word=word)
    if assigned.saved:
        assistant.say(f"Saved {assigned.word}.", interruptible=False)
        return True
    assistant.say("Pronunciation was not saved.", interruptible=False)
    return True


def _open_editor(assistant, user_id: str, word: str | None) -> bool:
    from silva.gui.word_pronunciation_dialog import run_pronunciation_editor_blocking

    if word:
        assistant.say(
            f'Opening pronunciation editor for "{word}".',
            interruptible=False,
        )
    else:
        assistant.say("Opening pronunciation editor.", interruptible=False)
    run_pronunciation_editor_blocking(user_id, word)
    assistant.say("Pronunciation editor closed.", interruptible=False)
    return True
