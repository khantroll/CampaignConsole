"""Sessions where related entities appeared together (via session links)."""

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
    NPC,
    NPCFactionLink,
    NPCLocationLink,
    NPCPlotThreadLink,
    PCFactionLink,
    PCPlotThreadLink,
    PlayerCharacterNote,
    PlotThread,
)
from app.services.entity_health import ENTITY_EDIT_URLS
from app.services.entity_session_presence import EntitySessionPresenceIndex

KIND_LABELS = {
    "npcs": "NPC",
    "pcs": "Party Member",
    "factions": "Faction",
    "locations": "Location",
    "items": "Item",
    "creatures": "Creature",
    "threads": "Plot Thread",
}

ENTITY_RELATION_CONFIG: Dict[str, List[Tuple[Any, str, str, str, Type, str]]] = {
    "npcs": [
        (NPCFactionLink, "npc_id", "faction_id", "factions", Faction, "name"),
        (NPCLocationLink, "npc_id", "location_id", "locations", Location, "name"),
        (NPCPlotThreadLink, "npc_id", "plot_thread_id", "threads", PlotThread, "title"),
    ],
    "locations": [
        (NPCLocationLink, "location_id", "npc_id", "npcs", NPC, "name"),
        (LocationFactionLink, "location_id", "faction_id", "factions", Faction, "name"),
        (LocationPlotThreadLink, "location_id", "plot_thread_id", "threads", PlotThread, "title"),
    ],
    "items": [
        (ItemFactionLink, "item_id", "faction_id", "factions", Faction, "name"),
        (ItemLocationLink, "item_id", "location_id", "locations", Location, "name"),
        (ItemPlotThreadLink, "item_id", "plot_thread_id", "threads", PlotThread, "title"),
    ],
    "creatures": [
        (CreatureFactionLink, "creature_id", "faction_id", "factions", Faction, "name"),
        (CreatureLocationLink, "creature_id", "location_id", "locations", Location, "name"),
        (CreaturePlotThreadLink, "creature_id", "plot_thread_id", "threads", PlotThread, "title"),
    ],
    "factions": [
        (NPCFactionLink, "faction_id", "npc_id", "npcs", NPC, "name"),
        (PCFactionLink, "faction_id", "pc_note_id", "pcs", PlayerCharacterNote, "character_name"),
        (LocationFactionLink, "faction_id", "location_id", "locations", Location, "name"),
        (FactionPlotThreadLink, "faction_id", "plot_thread_id", "threads", PlotThread, "title"),
        (CreatureFactionLink, "faction_id", "creature_id", "creatures", Creature, "name"),
    ],
    "threads": [],
    "pcs": [
        (PCFactionLink, "pc_note_id", "faction_id", "factions", Faction, "name"),
        (PCPlotThreadLink, "pc_note_id", "plot_thread_id", "threads", PlotThread, "title"),
    ],
}


def _entity_name(entity, kind: str, name_attr: str) -> str:
    value = getattr(entity, name_attr, "") or ""
    if value:
        return value
    entity_id = getattr(entity, "id", None)
    return f"#{entity_id}" if entity_id else "Unknown"


def get_entity_coappearance_timeline(
    db: Session,
    campaign_id: int,
    entity_kind: str,
    entity_id: int,
    *,
    limit: int = 12,
) -> Optional[Dict[str, Any]]:
    configs = ENTITY_RELATION_CONFIG.get(entity_kind) or []
    if not configs:
        return None

    index = EntitySessionPresenceIndex(db, campaign_id)
    entity_sessions = set(index._entity_sessions.get(entity_kind, {}).get(entity_id) or [])
    if not entity_sessions:
        return None

    session_partners: Dict[int, List[Dict[str, Any]]] = {}

    for link_model, owner_field, related_field, related_kind, related_model, name_attr in configs:
        rows = db.exec(
            select(link_model).where(getattr(link_model, owner_field) == entity_id)
        ).all()
        related_ids = [
            getattr(row, related_field)
            for row in rows
            if getattr(row, related_field, None) is not None
        ]
        if not related_ids:
            continue

        for related_id in related_ids:
            partner_sessions = set(index._entity_sessions.get(related_kind, {}).get(related_id) or [])
            shared = entity_sessions & partner_sessions
            if not shared:
                continue

            partner = db.get(related_model, related_id)
            if not partner or getattr(partner, "campaign_id", None) != campaign_id:
                continue

            url_template = ENTITY_EDIT_URLS.get(related_kind)
            partner_row = {
                "kind": related_kind,
                "kind_label": KIND_LABELS.get(related_kind, related_kind.title()),
                "id": related_id,
                "name": _entity_name(partner, related_kind, name_attr),
                "edit_url": url_template.format(campaign_id=campaign_id, entity_id=related_id)
                if url_template
                else None,
            }
            for session_id in shared:
                session_partners.setdefault(session_id, []).append(partner_row)

    if not session_partners:
        return None

    entries: List[Dict[str, Any]] = []
    for session_id, partners in session_partners.items():
        session = index.sessions_by_id.get(session_id)
        if not session:
            continue
        deduped: Dict[Tuple[str, int], Dict[str, Any]] = {}
        for partner in partners:
            deduped[(partner["kind"], partner["id"])] = partner
        entries.append(
            {
                "session": session,
                "partners": sorted(deduped.values(), key=lambda p: (p["kind"], p["name"].lower())),
            }
        )

    entries.sort(key=lambda row: index.rank.get(row["session"].id, 9999), reverse=True)
    entries = entries[:limit]
    if not entries:
        return None

    return {
        "entries": entries,
        "entry_count": len(entries),
    }
