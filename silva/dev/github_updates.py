from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import json
import re

from silva.config import load_config
from silva.logger import log_error

DEFAULT_REPOSITORY = "SilusSolden/silva"
DEFAULT_SUPPORT_EMAIL = "SilusSolden@gmail.com"


def configured_repo() -> str:
    config = load_config()
    value = str(
        config.get("github_repository")
        or config.get("github_repo")
        or         config.get("update_github_repository")
        or DEFAULT_REPOSITORY
    ).strip()

    if value:
        return value.strip("/")
    return detect_repo_from_git()


def detect_repo_from_git() -> str:
    git_config = Path(__file__).resolve().parents[2] / ".git" / "config"
    if not git_config.exists():
        return ""
    try:
        raw = git_config.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    match = re.search(r"url\s*=\s*(?:git@github\.com:|https://github\.com/)([^\s]+?)(?:\.git)?\s*$", raw, re.M | re.I)
    if not match:
        return ""
    slug = match.group(1).strip().strip("/")
    return slug if "/" in slug else ""


def repo_web_url(repo: str | None = None) -> str:
    slug = (repo or configured_repo()).strip("/")
    return f"https://github.com/{slug}" if slug else ""


def repo_api_url(repo: str | None = None) -> str:
    slug = (repo or configured_repo()).strip("/")
    return f"https://api.github.com/repos/{slug}" if slug else ""


def issues_url(repo: str | None = None) -> str:
    base = repo_web_url(repo)
    return f"{base}/issues" if base else ""


def new_issue_url(repo: str | None = None, *, kind: str = "bug") -> str:
    base = repo_web_url(repo)
    if not base:
        return ""
    labels = "bug" if kind == "bug" else "enhancement"
    title = "Bug report" if kind == "bug" else "Feature request"
    body = "What happened:\n\nWhat I expected:\n\nSteps to reproduce:\n"
    from urllib.parse import urlencode

    return f"{base}/issues/new?{urlencode({'title': title, 'body': body, 'labels': labels})}"


def support_email_url() -> str:
    from urllib.parse import quote

    config = load_config()
    email = str(
        config.get("github_issues_email")
        or         config.get("support_email")
        or config.get("update_contact_email")
        or DEFAULT_SUPPORT_EMAIL
    ).strip()
    if not email:
        return ""
    subject = quote("Silva information, update path, or question")

    return f"mailto:{email}?subject={subject}"


def _fetch_json(url: str) -> dict:
    if not url:
        return {}
    try:
        request = Request(url, headers={"User-Agent": "Silva-Update-Check"})
        with urlopen(request, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError, ValueError) as exc:
        log_error("GitHub update check failed", exc=exc)
        return {}


def latest_release_manifest() -> dict:
    slug = configured_repo()
    if not slug:
        return {}
    release = _fetch_json(f"{repo_api_url(slug)}/releases/latest")
    if not release:
        return {}
    tag = str(release.get("tag_name") or "").strip()
    body = str(release.get("body") or "").strip()
    changelog = [line.strip(" -*\t") for line in body.splitlines() if line.strip(" -*\t")]
    manifest_asset = None
    for asset in release.get("assets") or []:
        name = str(asset.get("name") or "").lower()
        if name in {"manifest.json", "release_manifest.json", "silva_manifest.json"}:
            manifest_asset = asset
            break
    if manifest_asset:
        downloaded = _fetch_json(str(manifest_asset.get("browser_download_url") or ""))
        if downloaded:
            downloaded.setdefault("version", tag)
            downloaded["source"] = "github_release_asset"
            return downloaded
    if not tag:
        return {}
    return {
        "version": tag,
        "features": [],
        "changelog": changelog[:12] or [f"GitHub release {tag}"],
        "fingerprint": "",
        "source": "github_release",
    }


def github_status_lines() -> list[str]:
    slug = configured_repo()
    if not slug:
        return [
            "GitHub updates are not configured for this build.",
            "Ask the owner to set github_repository in ~/.silva/config.json.",
        ]
    lines = [
        f"Project page: {repo_web_url(slug)}",
        "The repository is private for now. The owner will make it public when ready.",
        "Update path: say update check, or use the terminal update command when the owner or an admin allows it.",
    ]
    email_link = support_email_url()
    if email_link:
        lines.append(
            f"Information, update paths, bugs, features, and questions: {email_link}"
        )
    issue_link = issues_url(slug)
    if issue_link:
        lines.append(f"Planned public issue page: {issue_link}")
    return lines
