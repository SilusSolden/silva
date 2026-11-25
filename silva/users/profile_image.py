"""Optional profile picture that is not used for face matching."""

from __future__ import annotations

import shutil
from pathlib import Path

from silva.config import CONFIG_DIR
from silva.logger import log_info
from silva.users.manager import load_store, save_store

PROFILE_IMAGES_DIR = CONFIG_DIR / "profile_images"


def avatar_path(user_id: str) -> Path:
    folder = PROFILE_IMAGES_DIR / user_id
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        path = folder / f"avatar{ext}"
        if path.exists():
            return path
    return folder / "avatar.jpg"


def has_profile_image(user_id: str) -> bool:
    path = avatar_path(user_id)
    return path.exists() and path.stat().st_size > 0


def save_profile_image(user_id: str, source: Path | str) -> tuple[bool, str]:
    src = Path(source)
    if not src.is_file():
        return False, "That image file was not found."
    suffix = src.suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
        return False, "Please pick a jpg, png, or webp image."
    dest_dir = PROFILE_IMAGES_DIR / user_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"avatar{suffix if suffix != '.jpeg' else '.jpg'}"
    for old in dest_dir.glob("avatar.*"):
        if old != dest:
            try:
                old.unlink()
            except OSError:
                pass
    shutil.copy2(src, dest)
    store = load_store()
    user = store.get("users", {}).get(user_id)
    if user is not None:
        user["profile_image"] = str(dest)
        save_store(store)
    log_info(f"Profile image saved for {user_id}: {dest.name}")
    return True, "Profile image saved. Your face photos stay private unless you use a camera feature."


def clear_profile_image(user_id: str) -> bool:
    dest_dir = PROFILE_IMAGES_DIR / user_id
    removed = False
    if dest_dir.exists():
        for old in dest_dir.glob("avatar.*"):
            try:
                old.unlink()
                removed = True
            except OSError:
                pass
    store = load_store()
    user = store.get("users", {}).get(user_id)
    if user is not None and user.get("profile_image"):
        user["profile_image"] = ""
        save_store(store)
        removed = True
    return removed
