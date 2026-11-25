"""Owner-only test profiles for guest and admin feature checks."""

from __future__ import annotations

import json
import re

from silva.config import CONFIG_DIR
from silva.users.manager import (
    add_user,
    get_owner,
    identify_and_set_active,
    is_owner,
    load_store,
    save_store,
)

TEST_STATE_FILE = CONFIG_DIR / "test_account_session.json"


def _load_session() -> dict:
    if not TEST_STATE_FILE.exists():
        return {}
    try:
        data = json.loads(TEST_STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_session(session: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    TEST_STATE_FILE.write_text(json.dumps(session, indent=2, sort_keys=True), encoding="utf-8")


def create_test_account(reviewer: dict | None, name: str, role: str) -> tuple[bool, dict | None, str]:
    if not is_owner(reviewer):
        return False, None, "Only the owner can create test accounts."
    clean_name = re.sub(r"[^A-Za-z0-9 _-]", "", str(name or "")).strip()
    if not clean_name:
        return False, None, "Enter a name for the test account."
    normalized_role = "admin" if str(role).strip().lower() in {"admin", "administrator", "tier 4"} else "guest"
    tier = 4 if normalized_role == "admin" else 1
    user = add_user(f"Test {clean_name}", tier=tier)
    store = load_store()
    entry = store["users"][user["id"]]
    entry["test_account"] = True
    entry["test_role"] = normalized_role
    entry["role"] = normalized_role
    save_store(store)
    return True, entry, f"Created test {normalized_role} {entry.get('name', user['id'])}."


def list_test_accounts() -> list[dict]:
    return [user for user in load_store()["users"].values() if user.get("test_account")]


def activate_test_account(reviewer: dict | None, user_id: str) -> tuple[bool, dict | None, str]:
    if not is_owner(reviewer):
        return False, None, "Only the owner can switch to a test account."
    target = load_store()["users"].get(str(user_id))
    if target is None or not target.get("test_account"):
        return False, None, "Choose a test account."
    owner = get_owner()
    _save_session(
        {
            "active_test_user_id": str(target["id"]),
            "return_user_id": str(owner["id"]),
        }
    )
    identify_and_set_active(str(target["id"]))
    return True, target, f"Testing as {target.get('name', target['id'])}. Return to owner when finished."


def return_to_owner() -> tuple[bool, dict | None, str]:
    owner = get_owner()
    identify_and_set_active(str(owner["id"]))
    if TEST_STATE_FILE.exists():
        TEST_STATE_FILE.unlink()
    return True, owner, f"Back to {owner.get('name', owner['id'])}."


def is_test_session_active() -> bool:
    return bool(_load_session().get("active_test_user_id"))


def active_test_session() -> dict:
    return _load_session()
