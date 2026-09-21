"""Structured preset values for entity profile fields."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.services.text_similarity import normalize_text

PRESET_OTHER = "other"
LOCATION_CUSTOM = "__custom__"

ALIVE_OR_DEAD_LABELS: Dict[str, str] = {
    "alive": "Alive",
    "dead": "Dead",
    "undead": "Undead / Other",
    PRESET_OTHER: "Custom…",
}

CURRENT_STATUS_LABELS: Dict[str, str] = {
    "active": "Active",
    "missing": "Missing",
    "imprisoned": "Imprisoned",
    "hidden": "Hidden",
    "retired": "Retired",
    "unknown": "Unknown",
    PRESET_OTHER: "Custom…",
}

PLOT_THREAD_STATUS_LABELS: Dict[str, str] = {
    "active": "Active",
    "dormant": "Dormant",
    "resolved": "Resolved",
    "stalled": "Stalled",
    "unknown": "Unknown",
    PRESET_OTHER: "Custom…",
}

PLOT_THREAD_TYPE_LABELS: Dict[str, str] = {
    "main": "Main Plot",
    "side": "Side Quest",
    "personal": "Personal Arc",
    "faction": "Faction Arc",
    "mystery": "Mystery",
    "other_arc": "Other",
    PRESET_OTHER: "Custom…",
}

THREAT_LEVEL_LABELS: Dict[str, str] = {
    "trivial": "Trivial",
    "low": "Low",
    "medium": "Medium",
    "high": "High",
    "deadly": "Deadly",
    "legendary": "Legendary",
    PRESET_OTHER: "Custom…",
}

HABITAT_LABELS: Dict[str, str] = {
    "urban": "Urban",
    "wilderness": "Wilderness",
    "underground": "Underground",
    "aquatic": "Aquatic",
    "planar": "Planar",
    "any": "Any / Wandering",
    PRESET_OTHER: "Custom…",
}

ALIVE_OR_DEAD_CHOICES: Tuple[Tuple[str, str], ...] = tuple(ALIVE_OR_DEAD_LABELS.items())
CURRENT_STATUS_CHOICES: Tuple[Tuple[str, str], ...] = tuple(CURRENT_STATUS_LABELS.items())
PLOT_THREAD_STATUS_CHOICES: Tuple[Tuple[str, str], ...] = tuple(PLOT_THREAD_STATUS_LABELS.items())
PLOT_THREAD_TYPE_CHOICES: Tuple[Tuple[str, str], ...] = tuple(PLOT_THREAD_TYPE_LABELS.items())
THREAT_LEVEL_CHOICES: Tuple[Tuple[str, str], ...] = tuple(THREAT_LEVEL_LABELS.items())
HABITAT_CHOICES: Tuple[Tuple[str, str], ...] = tuple(HABITAT_LABELS.items())

PRESET_ALIVE_KEYS = frozenset(key for key in ALIVE_OR_DEAD_LABELS if key != PRESET_OTHER)
PRESET_STATUS_KEYS = frozenset(key for key in CURRENT_STATUS_LABELS if key != PRESET_OTHER)
PRESET_THREAD_STATUS_KEYS = frozenset(key for key in PLOT_THREAD_STATUS_LABELS if key != PRESET_OTHER)
PRESET_THREAD_TYPE_KEYS = frozenset(key for key in PLOT_THREAD_TYPE_LABELS if key != PRESET_OTHER)
PRESET_THREAT_KEYS = frozenset(key for key in THREAT_LEVEL_LABELS if key != PRESET_OTHER)
PRESET_HABITAT_KEYS = frozenset(key for key in HABITAT_LABELS if key != PRESET_OTHER)


def _label_for_key(labels: Dict[str, str], key: str) -> str:
    return labels.get(key, key.replace("_", " ").title())


def preset_form_values(
    stored: Optional[str],
    labels: Dict[str, str],
    preset_keys: frozenset[str],
) -> Tuple[str, str]:
    if not stored or not str(stored).strip():
        return "", ""
    normalized = str(stored).strip().lower().replace(" ", "_")
    if normalized in preset_keys or normalized == PRESET_OTHER:
        return normalized, ""
    for key, label in labels.items():
        if key != PRESET_OTHER and normalize_text(label) == normalize_text(stored):
            return key, ""
    return PRESET_OTHER, str(stored).strip()


def resolve_preset_or_custom(
    selected: Optional[str],
    custom: Optional[str],
    labels: Dict[str, str],
) -> Optional[str]:
    selected_value = (selected or "").strip()
    custom_value = (custom or "").strip()
    if not selected_value:
        return custom_value or None
    if selected_value == PRESET_OTHER:
        return custom_value or None
    return _label_for_key(labels, selected_value)


def match_location_id_by_name(locations, stored_text: Optional[str]) -> Tuple[str, str]:
    if not stored_text or not str(stored_text).strip():
        return "", ""
    target = normalize_text(stored_text)
    for location in locations:
        if normalize_text(location.name) == target:
            return str(location.id), ""
    return LOCATION_CUSTOM, str(stored_text).strip()


def resolve_primary_location_text(
    locations,
    selected_id: Optional[str],
    custom_text: Optional[str],
) -> Optional[str]:
    selected = (selected_id or "").strip()
    custom = (custom_text or "").strip()
    if not selected:
        return custom or None
    if selected == LOCATION_CUSTOM:
        return custom or None
    if selected.isdigit():
        for location in locations:
            if location.id == int(selected):
                return location.name
    return custom or None


def preset_select_field(
    name: str,
    label: str,
    choices: Sequence[Tuple[str, str]],
    selected_key: str,
    custom_name: str,
    custom_value: str,
) -> List[Dict[str, Any]]:
    options: List[Dict[str, Any]] = [
        {"value": "", "label": "— Unspecified —", "selected": not selected_key},
    ]
    for value, opt_label in choices:
        options.append({"value": value, "label": opt_label, "selected": value == selected_key})
    return [
        {
            "name": name,
            "label": label,
            "type": "select",
            "options": options,
            "reveals": custom_name,
        },
        {
            "name": custom_name,
            "label": f"Custom {label}",
            "type": "text",
            "value": custom_value,
            "reveal_target": custom_name,
            "initially_visible": selected_key == PRESET_OTHER,
        },
    ]
