"""Optional Gyazo upload — local files always saved regardless."""

from __future__ import annotations

from pathlib import Path

import requests

from silva.config import CONFIG_DIR
from silva.logger import log_error, log_info

SECRETS_FILE = CONFIG_DIR / "owner_secrets.json"


def _token() -> str | None:
    if not SECRETS_FILE.exists():
        return None
    try:
        import json

        data = json.loads(SECRETS_FILE.read_text(encoding="utf-8"))
        token = str(data.get("gyazo_access_token", "")).strip()
        return token or None
    except (OSError, json.JSONDecodeError):
        return None


def gyazo_configured() -> bool:
    return _token() is not None


def upload_image(path: Path, *, title: str = "Silva capture") -> str | None:
    token = _token()
    if not token or not path.exists():
        return None
    try:
        with path.open("rb") as handle:
            resp = requests.post(
                "https://upload.gyazo.com/api/upload",
                headers={"Authorization": f"Bearer {token}"},
                files={"imagedata": (path.name, handle, "image/png")},
                data={"title": title[:200]},
                timeout=30,
            )
        resp.raise_for_status()
        url = resp.json().get("url")
        if url:
            log_info(f"Gyazo upload ok: {url}")
        return url
    except Exception as exc:
        log_error("Gyazo upload failed", exc=exc)
        return None
