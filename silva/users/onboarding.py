"""First-run summary and spoken examples for new Silva users."""

from __future__ import annotations

ONBOARDING_SUMMARY = (
    "I can take notes and to-dos, set reminders, check weather and news, answer questions, "
    "open the planner, and help with calls and media. Say what you want in plain words and I'll do my best."
)

ONBOARDING_EXAMPLES = (
    "add this to my to-do list: call the plumber",
    "what's on my to do list",
    "note that the keys are on the counter",
    "remind me at 6 pm to take a walk",
    "what's the weather",
    "what's in the newest update",
    "open the planner",
    "go to sleep",
    "wake up Silva",
)

ADMIN_SUMMARY = (
    "As an admin, you can also add and remove users, review feature requests, "
    "and use the terminal commands scan, update, and revert."
)

ADMIN_EXAMPLES = (
    "show pending requests",
    "list users",
    "add user",
    "remove user",
)


def _is_admin(user: dict | None) -> bool:
    if not user:
        return False
    from silva.users.admin_access import is_capability_enabled
    from silva.users.manager import is_owner

    return is_owner(user) or is_capability_enabled(user, "open_control_panel")


def summary_for_user(user: dict | None) -> str:
    parts = [ONBOARDING_SUMMARY]
    if _is_admin(user):
        parts.append(ADMIN_SUMMARY)
    return " ".join(parts)


def examples_for_user(user: dict | None) -> tuple[str, ...]:
    examples = list(ONBOARDING_EXAMPLES)
    if _is_admin(user):
        examples.extend(ADMIN_EXAMPLES)
    return tuple(examples)


def first_run_details(user: dict | None) -> str:
    from silva.dev.github_updates import github_status_lines

    lines = [
        "First-time setup",
        "",
        "Choose a profile level. A guest can chat and use basic commands.",
        "Make a profile for notes, reminders, voice training, and saved settings.",
        "Admin access is only a request until the owner approves it.",
        "",
        "Updates",
        "Silva checks files and changelogs first. If nothing changed, she stays on the current build.",
        "You can accept or decline update notices here. Owners and approved admins can apply updates.",
        "",
        "Bugs, features, and release news",
    ]
    lines.extend(github_status_lines())
    lines.extend(
        [
            "",
            "Scroll with the mouse wheel, the scrollbar, arrow keys, Page Up/Down, Home/End, or Space.",
        ]
    )
    if _is_admin(user):
        lines.extend(
            [
                "",
                "Admin commands",
                *ADMIN_EXAMPLES,
                "update check",
                "scan",
                "update",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "Admin-only details stay hidden until an owner grants admin access to your profile.",
            ]
        )
    return "\n".join(lines)
