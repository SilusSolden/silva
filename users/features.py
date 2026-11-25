"""Universal and per-user feature access."""

from __future__ import annotations

from silva.config import load_config
from silva.users.manager import is_owner, load_store, save_store
from silva.users.tiers import normalize_tier

FEATURE_WEATHER = "weather"
FEATURE_WIKIPEDIA = "wikipedia"
FEATURE_BUG_REPORT = "bug_report"
FEATURE_CONVERSATION = "conversation"
FEATURE_APPOINTMENTS = "appointments"
FEATURE_MATH = "math"
FEATURE_MEASUREMENT = "measurement"
FEATURE_VISUAL_GUIDE = "visual_guide"
FEATURE_AUDIO_CONTROL = "audio_control"
FEATURE_MEDIA_PLAYBACK = "media_playback"
FEATURE_NOTES = "notes"
FEATURE_PLANNER = "planner"
FEATURE_VOICE_CONTROL_ACCESS = "voice_control_access"

FEATURE_LABELS: dict[str, str] = {
    FEATURE_WEATHER: "Weather",
    FEATURE_WIKIPEDIA: "Wikipedia",
    FEATURE_BUG_REPORT: "Bug reports",
    FEATURE_CONVERSATION: "Conversation",
    FEATURE_APPOINTMENTS: "Appointments",
    FEATURE_MATH: "Math",
    FEATURE_MEASUREMENT: "Measurement",
    FEATURE_VISUAL_GUIDE: "Visual guides",
    FEATURE_AUDIO_CONTROL: "App audio control",
    FEATURE_MEDIA_PLAYBACK: "Video play and pause",
    FEATURE_NOTES: "Notes and to-do list",
    FEATURE_PLANNER: "3D planner",
    FEATURE_VOICE_CONTROL_ACCESS: "Voice access and approved controls",
}

ADMIN_FEATURE_KEYS = frozenset({FEATURE_VOICE_CONTROL_ACCESS})

FEATURE_ALIASES: dict[str, str] = {
    "audio": FEATURE_AUDIO_CONTROL,
    "mic": FEATURE_AUDIO_CONTROL,
    "microphone": FEATURE_AUDIO_CONTROL,
    "sound": FEATURE_AUDIO_CONTROL,
    "wiki": FEATURE_WIKIPEDIA,
    "wikipedia": FEATURE_WIKIPEDIA,
    "video": FEATURE_MEDIA_PLAYBACK,
    "media": FEATURE_MEDIA_PLAYBACK,
    "playback": FEATURE_MEDIA_PLAYBACK,
    "todo": FEATURE_NOTES,
    "todos": FEATURE_NOTES,
    "notes": FEATURE_NOTES,
    "chat": FEATURE_CONVERSATION,
    "talk": FEATURE_CONVERSATION,
    "conversation": FEATURE_CONVERSATION,
    "guide": FEATURE_VISUAL_GUIDE,
    "visual": FEATURE_VISUAL_GUIDE,
    "bug": FEATURE_BUG_REPORT,
    "bugs": FEATURE_BUG_REPORT,
    "measure": FEATURE_MEASUREMENT,
    "calendar": FEATURE_APPOINTMENTS,
    "appointment": FEATURE_APPOINTMENTS,
    "planner": FEATURE_PLANNER,
    "floor_plan": FEATURE_PLANNER,
    "floorplan": FEATURE_PLANNER,
    "blueprint": FEATURE_PLANNER,
    "3d_graph": FEATURE_PLANNER,
    "3d_planner": FEATURE_PLANNER,
    "voice_control": FEATURE_VOICE_CONTROL_ACCESS,
    "voice_controls": FEATURE_VOICE_CONTROL_ACCESS,
    "voice_control_access": FEATURE_VOICE_CONTROL_ACCESS,
    "admin_voice": FEATURE_VOICE_CONTROL_ACCESS,
}

DEFAULT_UNIVERSAL_FEATURES = [
    FEATURE_WEATHER,
    FEATURE_WIKIPEDIA,
    FEATURE_BUG_REPORT,
    FEATURE_APPOINTMENTS,
    FEATURE_MATH,
    FEATURE_MEASUREMENT,
    FEATURE_VISUAL_GUIDE,
    FEATURE_AUDIO_CONTROL,
    FEATURE_MEDIA_PLAYBACK,
    FEATURE_NOTES,
    FEATURE_PLANNER,
]


def normalize_feature_key(raw: str) -> str | None:
    key = str(raw or "").strip().lower().replace(" ", "_")
    if not key:
        return None
    key = FEATURE_ALIASES.get(key, key)
    if key in FEATURE_LABELS:
        return key
    return None


def feature_label(key: str) -> str:
    normalized = normalize_feature_key(key) or str(key or "").strip()
    return FEATURE_LABELS.get(normalized, normalized.replace("_", " ").title() or "Feature")


def universal_features() -> set[str]:
    items = load_config().get("universal_features", DEFAULT_UNIVERSAL_FEATURES)
    if not isinstance(items, list):
        return set(DEFAULT_UNIVERSAL_FEATURES)
    normalized = {key for item in items if (key := normalize_feature_key(str(item)))}
    return normalized or set(DEFAULT_UNIVERSAL_FEATURES)


def features_for_user(user: dict) -> set[str]:
    keys = set(universal_features())
    if is_owner(user) or user.get("voice_enrolled"):
        keys.update(ADMIN_FEATURE_KEYS)
    return keys


def can_edit_user_features(viewer: dict) -> bool:
    tier = normalize_tier(viewer.get("tier", 1))
    return is_owner(viewer) or tier >= 3


def get_user_feature_overrides(user_id: str) -> dict[str, bool]:
    store = load_store()
    user = store["users"].get(user_id, {})
    overrides = user.get("feature_overrides", {})
    return overrides if isinstance(overrides, dict) else {}


def save_user_feature_overrides(user_id: str, overrides: dict[str, bool]) -> None:
    store = load_store()
    if user_id not in store["users"]:
        return
    store["users"][user_id]["feature_overrides"] = overrides
    save_store(store)


def feature_allowed(user: dict, feature: str) -> bool:
    if is_owner(user):
        return True
    if feature == FEATURE_VOICE_CONTROL_ACCESS and user.get("voice_enrolled"):
        return True
    if feature not in universal_features() and feature not in FEATURE_LABELS:
        return True

    overrides = user.get("feature_overrides") or {}
    if feature in overrides:
        return bool(overrides[feature])

    return feature in universal_features()


def editable_features_for_target(viewer: dict, target: dict) -> list[tuple[str, str]]:
    if not can_edit_user_features(viewer):
        return []
    viewer_tier = normalize_tier(viewer.get("tier", 1))
    target_tier = normalize_tier(target.get("tier", 1))
    if not is_owner(viewer) and target_tier >= viewer_tier:
        return []
    keys = set(universal_features())
    if is_owner(viewer) and (target_tier >= 4 or target.get("voice_enrolled")):
        keys.update(ADMIN_FEATURE_KEYS)
    return [(key, feature_label(key)) for key in sorted(keys) if key in FEATURE_LABELS]
