"""Paths for Silva developer panel state."""

from __future__ import annotations

from pathlib import Path

from silva.config import CONFIG_DIR

DEV_DIR = CONFIG_DIR / "dev"
SPEECH_TRAINING_FILE = DEV_DIR / "speech_training.json"
PENDING_UPDATE_FILE = DEV_DIR / "pending_update.json"
RELOAD_FLAG_FILE = DEV_DIR / "reload_requested"
PROGRESS_FILE = DEV_DIR / "update_progress.json"
DEV_STATE_FILE = DEV_DIR / "dev_state.json"
APPLIED_UPDATE_FILE = DEV_DIR / "last_applied_update.json"
LAST_CODE_STORY_FILE = DEV_DIR / "last_code_story.json"
WHATS_NEW_STATE_FILE = DEV_DIR / "whats_new_state.json"
RELEASE_NOTES_DIR = DEV_DIR / "release_notes"
INSTALLED_MANIFEST_FILE = DEV_DIR / "installed_manifest.json"
PUBLISHED_MANIFEST_FILE = DEV_DIR / "published_release_manifest.json"


def ensure_dev_dir() -> Path:
    DEV_DIR.mkdir(parents=True, exist_ok=True)
    return DEV_DIR
