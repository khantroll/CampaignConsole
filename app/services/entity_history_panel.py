"""Unified entity History panel for entity detail pages."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Type

from sqlmodel import Session, select

from app.models import (
    Creature,
    CreatureFactionLink,
    CreatureLocationLink,
    CreaturePlotThreadLink,
    Faction,
    FactionPlotThreadLink,
    Item,
    ItemFactionLink,
    ItemLocationLink,
    ItemNPCLink,
    ItemPlotThreadLink,
    Location,
    LocationFactionLink,
    LocationPlotThreadLink,
    LocationRelatedLocationLink,
    NPC,
    NPCFactionLink,
    NPCLocationLink,
    NPCPlotThreadLink,
    PlotThread,
    PlotThreadRelatedPlotThreadLink,
    PCLocationLink,
    PCFactionLink,
    PCPlotThreadLink,
    PlayerCharacterNote,
)
from app.services.campaign_intelligence import get_entity_session_history, get_intelligence_gap
from app.services.world_state import (
    entity_world_status,
    lines_to_clue_list,
    mystery_status_label,
    world_status_badge_class,
    world_status_label,
)
from app.services.entity_health import ENTITY_EDIT_URLS
from app.services.entity_session_presence import EntitySessionPresenceIndex

NEW_SESSION_WINDOW = 2

RELATED_KIND_LABELS = {
    "npcs": "Related NPCs",
    "pcs": "Related Party Members",
    "locations": "Related Locations",
    "factions": "Related Factions",
    "threads": "Related Plot Threads",
    "items": "Related Items",
    "creatures": "Related Creatures",
}

# Outbound entity-to-entity links (owner -> related)
OUTBOUND_RELATIONS: Dict[str, List[Tuple[Any, str, str, str, Type, str]]] = {
    "npcs": [
        (NPCFactionLink, "npc_id", "faction_id", "factions", Faction, "name"),
        (NPCLocationLink, "npc_id", "location_id", "locations", Location, "name"),
        (NPCPlotThreadLink, "npc_id", "plot_thread_id", "threads", PlotThread, "title"),
    ],
    "locations": [
        (LocationRelatedLocationLink, "location_id", "related_location_id", "locations", Location, "name"),
        (NPCLocationLink, "location_id", "npc_id", "npcs", NPC, "name"),
        (LocationFactionLink, "location_id", "faction_id", "factions", Faction, "name"),
        (LocationPlotThreadLink, "location_id", "plot_thread_id", "threads", PlotThread, "title"),
        (CreatureLocationLink, "location_id", "creature_id", "creatures", Creature, "name"),
    ],
    "creatures": [
        (CreatureFactionLink, "creature_id", "faction_id", "factions", Faction, "name"),
        (CreatureLocationLink, "creature_id", "location_id", "locations", Location, "name"),
        (CreaturePlotThreadLink, "creature_id", "plot_thread_id", "threads", PlotThread, "title"),
    ],
    "items": [
        (ItemFactionLink, "item_id", "faction_id", "factions", Faction, "name"),
        (ItemLocationLink, "item_id", "location_id", "locations", Location, "name"),
        (ItemPlotThreadLink, "item_id", "plot_thread_id", "threads", PlotThread, "title"),
    ],
    "factions": [
        (NPCFactionLink, "faction_id", "npc_id", "npcs", NPC, "name"),
        (PCFactionLink, "faction_id", "pc_note_id", "pcs", PlayerCharacterNote, "character_name"),
        (LocationFactionLink, "faction_id", "location_id", "locations", Location, "name"),
        (FactionPlotThreadLink, "faction_id", "plot_thread_id", "threads", PlotThread, "title"),
        (CreatureFactionLink, "faction_id", "creature_id", "creatures", Creature, "name"),
    ],
    "threads": [
        (NPCPlotThreadLink, "plot_thread_id", "npc_id", "npcs", NPC, "name"),
        (PCPlotThreadLink, "plot_thread_id", "pc_note_id", "pcs", PlayerCharacterNote, "character_name"),
        (LocationPlotThreadLink, "plot_thread_id", "location_id", "locations", Location, "name"),
        (FactionPlotThreadLink, "plot_thread_id", "faction_id", "factions", Faction, "name"),
        (PlotThreadRelatedPlotThreadLink, "plot_thread_id", "related_plot_thread_id", "threads", PlotThread, "title"),
        (ItemPlotThreadLink, "plot_thread_id", "item_id", "items", Item, "name"),
        (CreaturePlotThreadLink, "plot_thread_id", "creature_id", "creatures", Creature, "name"),
    ],
    "pcs": [
        (PCLocationLink, "pc_note_id", "location_id", "locations", Location, "name"),
        (PCFactionLink, "pc_note_id", "faction_id", "factions", Faction, "name"),
        (PCPlotThreadLink, "pc_note_id", "plot_thread_id", "threads", PlotThread, "title"),
    ],
}


def _entity_display_name(entity: Any, section_key: str) -> str:
    if section_key == "pcs":
        return getattr(entity, "character_name", "") or "PC"
    if section_key == "threads":
        return getattr(entity, "title", "") or "Plot Thread"
    return getattr(entity, "name", "") or "Entity"


def _related_row(
    db: Session,
    campaign_id: int,
    related_kind: str,
    related_id: int,
    model: Type,
    name_attr: str,
) -> Optional[Dict[str, Any]]:
    entity = db.get(model, related_id)
    if not entity or getattr(entity, "campaign_id", None) != campaign_id:
        return None
    name = getattr(entity, name_attr, "") or f"#{related_id}"
    url_template = ENTITY_EDIT_URLS.get(related_kind)
    return {
        "kind": related_kind,
        "id": related_id,
        "name": name,
        "edit_url": url_template.format(campaign_id=campaign_id, entity_id=related_id)
        if url_template
        else None,
    }


def _load_related_entities(
    db: Session,
    campaign_id: int,
    section_key: str,
    entity_id: int,
) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    seen: Dict[str, set[int]] = {}

    for link_model, owner_field, related_field, related_kind, model, name_attr in OUTBOUND_RELATIONS.get(
        section_key, []
    ):
        rows = db.exec(select(link_model).where(getattr(link_model, owner_field) == entity_id)).all()
        for row in rows:
            related_id = getattr(row, related_field, None)
            if not related_id:
                continue
            seen.setdefault(related_kind, set())
            if related_id in seen[related_kind]:
                continue
            entry = _related_row(db, campaign_id, related_kind, related_id, model, name_attr)
            if entry:
                seen[related_kind].add(related_id)
                grouped.setdefault(related_kind, []).append(entry)

    for related_kind in grouped:
        grouped[related_kind].sort(key=lambda row: (row["name"] or "").lower())
    return grouped


def _entity_status_badge(
    index: EntitySessionPresenceIndex,
    section_key: str,
    entity_id: int,
    *,
    gap: int,
) -> Optional[str]:
    presence = index.presence(section_key, entity_id)
    if not presence:
        return None

    if not index.rank:
        return "active"

    current_rank = max(index.rank.values())
    first_rank = index.rank.get(presence["first"].id, current_rank)
    last_rank = index.rank.get(presence["last"].id, current_rank)

    if current_rank - first_rank < NEW_SESSION_WINDOW:
        return "new"
    if current_rank - last_rank >= gap:
        return "dormant"
    return "active"


def build_entity_history_panel(
    db: Session,
    campaign_id: int,
    section_key: str,
    entity_id: int,
    entity: Any,
) -> Dict[str, Any]:
    index = EntitySessionPresenceIndex(db, campaign_id)
    session_history = get_entity_session_history(db, campaign_id, section_key, entity_id)
    related = _load_related_entities(db, campaign_id, section_key, entity_id)
    relationship_count = sum(len(rows) for rows in related.values())
    gap = get_intelligence_gap()

    created_at = getattr(entity, "created_at", None)
    updated_at = getattr(entity, "updated_at", None)

    world_status_value = entity_world_status(entity, section_key)
    world_status_kind = section_key
    state_notes = getattr(entity, "state_notes", None)
    mystery_status = getattr(entity, "mystery_status", None) if section_key == "threads" else None
    open_clues = lines_to_clue_list(getattr(entity, "open_clues", None)) if section_key == "threads" else []

    return {
        "entity_name": _entity_display_name(entity, section_key),
        "section_key": section_key,
        "first_seen": session_history.get("first") if session_history else None,
        "last_seen": session_history.get("last") if session_history else None,
        "sessions": session_history.get("sessions", []) if session_history else [],
        "session_count": session_history.get("session_count", 0) if session_history else 0,
        "related": related,
        "relationship_count": relationship_count,
        "created_at": created_at,
        "updated_at": updated_at,
        "status_badge": _entity_status_badge(index, section_key, entity_id, gap=gap),
        "world_status": world_status_value,
        "world_status_label": world_status_label(world_status_value, world_status_kind),
        "world_status_badge_class": world_status_badge_class(world_status_value, world_status_kind),
        "state_notes": state_notes,
        "mystery_status_label": mystery_status_label(mystery_status) if mystery_status else None,
        "open_clues": open_clues,
        "has_sessions": bool(session_history and session_history.get("sessions")),
        "has_related": relationship_count > 0,
    }
