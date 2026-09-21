"""Item type labels for forms and display."""

import re
from typing import Any, Dict, List, Optional, Tuple

from sqlmodel import Session, select

from app.models import Item

ITEM_TYPE_MAGIC_WEAPON = "magic_weapon"
ITEM_TYPE_WONDROUS = "wondrous_item"
ITEM_TYPE_QUEST = "quest_item"
ITEM_TYPE_RELIC = "relic"
ITEM_TYPE_CONSUMABLE = "consumable"
ITEM_TYPE_OTHER = "other"

ITEM_TYPE_LABELS = {
    ITEM_TYPE_MAGIC_WEAPON: "Magic Weapon",
    ITEM_TYPE_WONDROUS: "Wondrous Item",
    ITEM_TYPE_QUEST: "Quest Item",
    ITEM_TYPE_RELIC: "Relic",
    ITEM_TYPE_CONSUMABLE: "Consumable",
    ITEM_TYPE_OTHER: "Other",
}

ITEM_TYPE_CHOICES: Tuple[Tuple[str, str], ...] = tuple(ITEM_TYPE_LABELS.items())

PRESET_ITEM_TYPE_KEYS = frozenset(key for key in ITEM_TYPE_LABELS if key != ITEM_TYPE_OTHER)


def slugify_item_type(text: str) -> str:
    normalized = str(text or "").strip().lower()
    normalized = normalized.replace("-", " ").replace("_", " ")
    normalized = re.sub(r"[^\w\s]+", "", normalized)
    normalized = re.sub(r"\s+", "_", normalized).strip("_")
    return normalized[:64]


def item_type_label(value: Optional[str]) -> str:
    if not value:
        return "Unspecified"
    return ITEM_TYPE_LABELS.get(value, value.replace("_", " ").title())


def normalize_item_type(value: Optional[str]) -> Optional[str]:
    if not value or not str(value).strip():
        return None
    normalized = slugify_item_type(str(value))
    if not normalized:
        return None
    if normalized in ITEM_TYPE_LABELS:
        return normalized
    aliases = {
        "weapon": ITEM_TYPE_MAGIC_WEAPON,
        "magic": ITEM_TYPE_MAGIC_WEAPON,
        "wondrous": ITEM_TYPE_WONDROUS,
        "quest": ITEM_TYPE_QUEST,
    }
    return aliases.get(normalized, normalized)


def item_type_form_values(stored: Optional[str]) -> Tuple[str, str]:
    if not stored:
        return "", ""
    if stored == ITEM_TYPE_OTHER:
        return stored, ""
    if stored in PRESET_ITEM_TYPE_KEYS:
        return stored, ""
    return stored, ""


def campaign_item_type_values(db: Session, campaign_id: int) -> List[str]:
    rows = db.exec(
        select(Item.item_type)
        .where(Item.campaign_id == campaign_id)
        .where(Item.item_type.isnot(None))
        .distinct()
    ).all()
    custom_types: List[str] = []
    for row in rows:
        value = row[0] if isinstance(row, tuple) else row
        if value and value not in PRESET_ITEM_TYPE_KEYS and value != ITEM_TYPE_OTHER:
            custom_types.append(value)
    return sorted(custom_types, key=lambda item_type: item_type_label(item_type).lower())


def build_item_type_options(
    db: Session,
    campaign_id: int,
    stored: Optional[str] = None,
) -> List[Dict[str, Any]]:
    select_value, _custom_value = item_type_form_values(stored)
    options: List[Dict[str, Any]] = [
        {
            "value": "",
            "label": "— Unspecified —",
            "selected": not stored,
        }
    ]
    seen = {""}
    for value, label in ITEM_TYPE_CHOICES:
        options.append(
            {
                "value": value,
                "label": label,
                "selected": value == select_value,
            }
        )
        seen.add(value)
    for value in campaign_item_type_values(db, campaign_id):
        if value in seen:
            continue
        seen.add(value)
        options.append(
            {
                "value": value,
                "label": item_type_label(value),
                "selected": value == stored,
            }
        )
    return options


def resolve_item_type(selected: Optional[str], custom: Optional[str] = None) -> Optional[str]:
    selected_value = (selected or "").strip()
    custom_value = (custom or "").strip()
    if not selected_value:
        return None
    if selected_value != ITEM_TYPE_OTHER:
        return normalize_item_type(selected_value)
    if not custom_value:
        return ITEM_TYPE_OTHER
    normalized = normalize_item_type(custom_value)
    if normalized and normalized != ITEM_TYPE_OTHER:
        return normalized
    slug = slugify_item_type(custom_value)
    if slug and slug != ITEM_TYPE_OTHER:
        return slug
    return ITEM_TYPE_OTHER


def item_owner_options(npcs, pcs, item) -> list[dict]:
    options = [
        {
            "value": "",
            "label": "— Unassigned —",
            "selected": not getattr(item, "owner_npc_id", None) and not getattr(item, "owner_pc_id", None),
        }
    ]
    for npc in npcs:
        options.append(
            {
                "value": f"npc-{npc.id}",
                "label": f"NPC: {npc.name}",
                "selected": getattr(item, "owner_npc_id", None) == npc.id,
            }
        )
    for pc in pcs:
        options.append(
            {
                "value": f"pc-{pc.id}",
                "label": f"PC: {pc.character_name}",
                "selected": getattr(item, "owner_pc_id", None) == pc.id,
            }
        )
    return options


def parse_item_owner(value: Optional[str]) -> Tuple[Optional[int], Optional[int]]:
    raw = (value or "").strip()
    if raw.startswith("npc-") and raw[4:].isdigit():
        return int(raw[4:]), None
    if raw.startswith("pc-") and raw[3:].isdigit():
        return None, int(raw[3:])
    return None, None
