"""Faction type labels for forms and display."""

import re
from typing import Optional, Tuple

FACTION_TYPE_GUILD = "guild"
FACTION_TYPE_RELIGIOUS_ORDER = "religious_order"
FACTION_TYPE_CULT = "cult"
FACTION_TYPE_MERCENARY = "mercenary_company"
FACTION_TYPE_CRIMINAL = "criminal_syndicate"
FACTION_TYPE_OTHER = "other"

FACTION_TYPE_LABELS = {
    FACTION_TYPE_GUILD: "Guild",
    FACTION_TYPE_RELIGIOUS_ORDER: "Religious Order",
    FACTION_TYPE_CULT: "Cult",
    FACTION_TYPE_MERCENARY: "Mercenary Company",
    FACTION_TYPE_CRIMINAL: "Criminal Syndicate",
    FACTION_TYPE_OTHER: "Other",
}

FACTION_TYPE_CHOICES: Tuple[Tuple[str, str], ...] = tuple(FACTION_TYPE_LABELS.items())

PRESET_FACTION_TYPE_KEYS = frozenset(
    key for key in FACTION_TYPE_LABELS if key != FACTION_TYPE_OTHER
)


def slugify_faction_type(text: str) -> str:
    normalized = str(text or "").strip().lower()
    normalized = normalized.replace("-", " ").replace("_", " ")
    normalized = re.sub(r"[^\w\s]+", "", normalized)
    normalized = re.sub(r"\s+", "_", normalized).strip("_")
    return normalized[:64]


def faction_type_label(value: Optional[str]) -> str:
    if not value:
        return "Unspecified"
    return FACTION_TYPE_LABELS.get(value, value.replace("_", " ").title())


def normalize_faction_type(value: Optional[str]) -> Optional[str]:
    if not value or not str(value).strip():
        return None
    normalized = slugify_faction_type(str(value))
    if not normalized:
        return None
    if normalized in FACTION_TYPE_LABELS:
        return normalized
    aliases = {
        "religious": FACTION_TYPE_RELIGIOUS_ORDER,
        "order": FACTION_TYPE_RELIGIOUS_ORDER,
        "mercenary": FACTION_TYPE_MERCENARY,
        "criminal": FACTION_TYPE_CRIMINAL,
        "syndicate": FACTION_TYPE_CRIMINAL,
    }
    return aliases.get(normalized, normalized)


def faction_type_form_values(stored: Optional[str]) -> Tuple[str, str]:
    if not stored:
        return "", ""
    if stored in PRESET_FACTION_TYPE_KEYS or stored == FACTION_TYPE_OTHER:
        return stored, ""
    return FACTION_TYPE_OTHER, faction_type_label(stored)


def resolve_faction_type(selected: Optional[str], custom: Optional[str] = None) -> Optional[str]:
    selected_value = (selected or "").strip()
    custom_value = (custom or "").strip()
    if not selected_value:
        return None
    if selected_value != FACTION_TYPE_OTHER:
        return normalize_faction_type(selected_value)
    if custom_value:
        return normalize_faction_type(custom_value)
    return FACTION_TYPE_OTHER
