"""Keep the Silva window readable: speech, typed lines, and errors only."""

from __future__ import annotations

_clean = True


def enable_clean_console(enabled: bool = True) -> None:
    global _clean
    _clean = bool(enabled)


def is_clean_console() -> bool:
    return _clean


def print_banner() -> None:
    return


def print_error(message: str) -> None:
    text = str(message or "").strip()
    if not text:
        return
    print(f"Error: {text}")
