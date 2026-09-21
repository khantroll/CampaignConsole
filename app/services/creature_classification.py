"""Creature type labels for forms and display."""

import re
from typing import Optional, Tuple

CREATURE_TYPE_BEAST = "beast"
CREATURE_TYPE_MONSTER = "monster"
CREATURE_TYPE_UNDEAD = "undead"
CREATURE_TYPE_WILDLIFE = "wildlife"
CREATURE_TYPE_HOSTILE = "hostile"
CREATURE_TYPE_OTHER = "other"

CREATURE_TYPE_LABELS = {
    CREATURE_TYPE_BEAST: "Beast",
    CREATURE_TYPE_MONSTER: "Monster",
    CREATURE_TYPE_UNDEAD: "Undead",
    CREATURE_TYPE_WILDLIFE: "Wildlife",
    CREATURE_TYPE_HOSTILE: "Hostile Creature",
    CREATURE_TYPE_OTHER: "Other",
}

CREATURE_TYPE_CHOICES: Tuple[Tuple[str, str], ...] = tuple(CREATURE_TYPE_LABELS.items())

PRESET_CREATURE_TYPE_KEYS = frozenset(key for key in CREATURE_TYPE_LABELS if key != CREATURE_TYPE_OTHER)


def slugify_creature_type(text: str) -> str:
    normalized = str(text or "").strip().lower()
    normalized = normalized.replace("-", " ").replace("_", " ")
    normalized = re.sub(r"[^\w\s]+", "", normalized)
    normalized = re.sub(r"\s+", "_", normalized).strip("_")
    return normalized[:64]


def creature_type_label(value: Optional[str]) -> str:
    if not value:
        return "Unspecified"
    return CREATURE_TYPE_LABELS.get(value, value.replace("_", " ").title())


def normalize_creature_type(value: Optional[str]) -> Optional[str]:
    if not value or not str(value).strip():
        return None
    normalized = slugify_creature_type(str(value))
    if not normalized:
        return None
    if normalized in CREATURE_TYPE_LABELS:
        return normalized
    aliases = {
        "enemy": CREATURE_TYPE_HOSTILE,
        "enemies": CREATURE_TYPE_HOSTILE,
        "animal": CREATURE_TYPE_WILDLIFE,
        "animals": CREATURE_TYPE_WILDLIFE,
    }
    return aliases.get(normalized, normalized)


def creature_type_form_values(stored: Optional[str]) -> Tuple[str, str]:
    if not stored:
        return "", ""
    if stored in PRESET_CREATURE_TYPE_KEYS or stored == CREATURE_TYPE_OTHER:
        return stored, ""
    return CREATURE_TYPE_OTHER, creature_type_label(stored)


def resolve_creature_type(selected: Optional[str], custom: Optional[str] = None) -> Optional[str]:
    selected_value = (selected or "").strip()
    custom_value = (custom or "").strip()
    if not selected_value:
        return None
    if selected_value != CREATURE_TYPE_OTHER:
        return normalize_creature_type(selected_value)
    if custom_value:
        return normalize_creature_type(custom_value)
    return CREATURE_TYPE_OTHER
