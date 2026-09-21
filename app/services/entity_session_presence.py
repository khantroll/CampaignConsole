"""First / last session presence for campaign entities via session link tables."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from sqlmodel import Session, select

from app.models import (
    Creature,
    Faction,
    Item,
    Location,
    NPC,
    PlotThread,
    PlayerCharacterNote,
    SessionCreatureLink,
    SessionFactionLink,
    SessionItemLink,
    SessionLocationLink,
    SessionModel,
    SessionNPCLink,
    SessionPartyMemberLink,
    SessionPlotThreadLink,
)

SESSION_LINK_CONFIG: Dict[str, Tuple[Any, str]] = {
    "npcs": (SessionNPCLink, "npc_id"),
    "locations": (SessionLocationLink, "location_id"),
    "factions": (SessionFactionLink, "faction_id"),
    "items": (SessionItemLink, "item_id"),
    "creatures": (SessionCreatureLink, "creature_id"),
    "threads": (SessionPlotThreadLink, "plot_thread_id"),
    "pcs": (SessionPartyMemberLink, "pc_note_id"),
}

ENTITY_SESSION_METADATA: Dict[str, Tuple[Any, str]] = {
    "npcs": (NPC, "last_seen_session_id"),
    "locations": (Location, "last_seen_session_id"),
    "factions": (Faction, "last_seen_session_id"),
    "items": (Item, "last_seen_session_id"),
    "creatures": (Creature, "last_seen_session_id"),
    "threads": (PlotThread, "last_touched_session_id"),
}


class EntitySessionPresenceIndex:
    def __init__(self, db: Session, campaign_id: int):
        from app.deps import sort_sessions_chronologically

        self.db = db
        self.campaign_id = campaign_id
        sessions = db.exec(
            select(SessionModel).where(SessionModel.campaign_id == campaign_id)
        ).all()
        self.sessions_by_id: Dict[int, SessionModel] = {s.id: s for s in sessions if s.id}
        ordered = sort_sessions_chronologically(list(self.sessions_by_id.values()))
        self.rank: Dict[int, int] = {s.id: idx for idx, s in enumerate(ordered)}
        self._entity_sessions: Dict[str, Dict[int, List[int]]] = {}
        for section_key, (link_model, entity_field) in SESSION_LINK_CONFIG.items():
            self._entity_sessions[section_key] = self._load_link_map(link_model, entity_field)

    def _load_link_map(self, link_model, entity_field: str) -> Dict[int, List[int]]:
        rows = self.db.exec(select(link_model)).all()
        mapping: Dict[int, List[int]] = {}
        for row in rows:
            session_id = getattr(row, "session_id", None)
            entity_id = getattr(row, entity_field, None)
            if not session_id or not entity_id:
                continue
            if session_id not in self.sessions_by_id:
                continue
            mapping.setdefault(entity_id, []).append(session_id)
        return mapping

    def presence(self, section_key: str, entity_id: int) -> Optional[Dict[str, Any]]:
        session_ids = self._entity_sessions.get(section_key, {}).get(entity_id) or []
        if not session_ids:
            return None
        ordered_ids = sorted(session_ids, key=lambda sid: self.rank.get(sid, 9999))
        first = self.sessions_by_id.get(ordered_ids[0])
        last = self.sessions_by_id.get(ordered_ids[-1])
        if not first or not last:
            return None
        return {"first": first, "last": last, "session_count": len(ordered_ids)}


def get_entity_session_presence(
    db: Session,
    campaign_id: int,
    section_key: str,
    entity_id: int,
) -> Optional[Dict[str, Any]]:
    index = EntitySessionPresenceIndex(db, campaign_id)
    return index.presence(section_key, entity_id)


def refresh_entity_session_metadata(
    db: Session,
    campaign_id: int,
    section_key: str,
    entity_id: int,
) -> None:
    config = ENTITY_SESSION_METADATA.get(section_key)
    if not config:
        return

    model, field_name = config
    index = EntitySessionPresenceIndex(db, campaign_id)
    presence = index.presence(section_key, entity_id)
    last_session_id = presence["last"].id if presence else None

    entity = db.get(model, entity_id)
    if entity and entity.campaign_id == campaign_id:
        setattr(entity, field_name, last_session_id)
        db.add(entity)


def refresh_session_link_metadata(db: Session, campaign_id: int, session_id: int) -> None:
    """Recompute stored last-seen / last-touched fields for entities affected by a session."""
    for section_key, (link_model, entity_field) in SESSION_LINK_CONFIG.items():
        config = ENTITY_SESSION_METADATA.get(section_key)
        if not config:
            continue

        model, field_name = config
        affected: set[int] = set()

        rows = db.exec(select(link_model).where(link_model.session_id == session_id)).all()
        for row in rows:
            entity_id = getattr(row, entity_field, None)
            if entity_id:
                affected.add(entity_id)

        stale = db.exec(
            select(model).where(
                model.campaign_id == campaign_id,
                getattr(model, field_name) == session_id,
            )
        ).all()
        for entity in stale:
            if entity.id:
                affected.add(entity.id)

        for entity_id in affected:
            refresh_entity_session_metadata(db, campaign_id, section_key, entity_id)


def hydrate_last_seen_for_display(
    db: Session,
    campaign_id: int,
    section_key: str,
    entities: List[Any],
) -> None:
    """Fill missing last-seen fields in memory from session links (no DB write)."""
    config = ENTITY_SESSION_METADATA.get(section_key)
    if not config or not entities:
        return

    _, field_name = config
    needs_index = any(getattr(entity, field_name, None) is None for entity in entities)
    if not needs_index:
        return

    index = EntitySessionPresenceIndex(db, campaign_id)
    for entity in entities:
        if getattr(entity, field_name, None) is not None or not getattr(entity, "id", None):
            continue
        presence = index.presence(section_key, entity.id)
        if presence:
            setattr(entity, field_name, presence["last"].id)
