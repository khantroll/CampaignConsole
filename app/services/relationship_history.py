"""Audit log and display for entity-to-entity relationship changes."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from sqlmodel import Session, select

from app.models import (
    Creature,
    EntityRelationshipEvent,
    Faction,
    Item,
    Location,
    NPC,
    PlayerCharacterNote,
    PlotThread,
    SessionModel,
)
from app.services.entity_health import ENTITY_EDIT_URLS

KIND_LABELS = {
    "npcs": "NPC",
    "pcs": "Party Member",
    "factions": "Faction",
    "locations": "Location",
    "items": "Item",
    "creatures": "Creature",
    "threads": "Plot Thread",
}

ACTION_LABELS = {
    "linked": "Linked",
    "unlinked": "Unlinked",
}

ENTITY_MODELS = {
    "npcs": NPC,
    "pcs": PlayerCharacterNote,
    "factions": Faction,
    "locations": Location,
    "items": Item,
    "creatures": Creature,
    "threads": PlotThread,
}

RELATIONSHIP_TYPE_KINDS = {
    "npc_faction": ("npcs", "factions"),
    "pc_faction": ("pcs", "factions"),
    "npc_location": ("npcs", "locations"),
    "npc_thread": ("npcs", "threads"),
    "pc_location": ("pcs", "locations"),
    "pc_thread": ("pcs", "threads"),
    "item_npc": ("items", "npcs"),
    "item_faction": ("items", "factions"),
    "item_location": ("items", "locations"),
    "item_thread": ("items", "threads"),
    "creature_faction": ("creatures", "factions"),
    "creature_location": ("creatures", "locations"),
    "creature_thread": ("creatures", "threads"),
    "location_thread": ("locations", "threads"),
    "location_location": ("locations", "locations"),
    "faction_thread": ("factions", "threads"),
    "thread_thread": ("threads", "threads"),
}


def log_relationship_event(
    db: Session,
    campaign_id: int,
    source_kind: str,
    source_id: int,
    target_kind: str,
    target_id: int,
    action: str,
    *,
    session_id: Optional[int] = None,
) -> None:
    db.add(
        EntityRelationshipEvent(
            campaign_id=campaign_id,
            source_kind=source_kind,
            source_id=source_id,
            target_kind=target_kind,
            target_id=target_id,
            action=action,
            session_id=session_id,
        )
    )


def log_relationship_diff(
    db: Session,
    campaign_id: int,
    owner_kind: str,
    owner_id: int,
    related_kind: str,
    old_related_ids: Set[int],
    new_related_ids: Set[int],
    *,
    session_id: Optional[int] = None,
) -> None:
    for related_id in new_related_ids - old_related_ids:
        log_relationship_event(
            db,
            campaign_id,
            owner_kind,
            owner_id,
            related_kind,
            related_id,
            "linked",
            session_id=session_id,
        )
    for related_id in old_related_ids - new_related_ids:
        log_relationship_event(
            db,
            campaign_id,
            owner_kind,
            owner_id,
            related_kind,
            related_id,
            "unlinked",
            session_id=session_id,
        )


def _entity_name(db: Session, kind: str, entity_id: int) -> str:
    model = ENTITY_MODELS.get(kind)
    if not model:
        return f"#{entity_id}"
    entity = db.get(model, entity_id)
    if not entity:
        return f"#{entity_id}"
    if kind == "threads":
        return getattr(entity, "title", "") or f"#{entity_id}"
    if kind == "pcs":
        return getattr(entity, "character_name", "") or f"#{entity_id}"
    return getattr(entity, "name", "") or f"#{entity_id}"


def _partner_for_event(
    event: EntityRelationshipEvent,
    entity_kind: str,
    entity_id: int,
) -> Tuple[str, int]:
    if event.source_kind == entity_kind and event.source_id == entity_id:
        return event.target_kind, event.target_id
    return event.source_kind, event.source_id


def get_entity_relationship_history(
    db: Session,
    campaign_id: int,
    entity_kind: str,
    entity_id: int,
    *,
    limit: int = 50,
) -> Optional[Dict[str, Any]]:
    events = db.exec(
        select(EntityRelationshipEvent)
        .where(EntityRelationshipEvent.campaign_id == campaign_id)
        .where(
            (
                (EntityRelationshipEvent.source_kind == entity_kind)
                & (EntityRelationshipEvent.source_id == entity_id)
            )
            | (
                (EntityRelationshipEvent.target_kind == entity_kind)
                & (EntityRelationshipEvent.target_id == entity_id)
            )
        )
        .order_by(EntityRelationshipEvent.created_at.desc())
        .limit(limit)
    ).all()
    if not events:
        return None

    session_ids = {event.session_id for event in events if event.session_id}
    sessions_by_id: Dict[int, SessionModel] = {}
    if session_ids:
        sessions = db.exec(select(SessionModel).where(SessionModel.id.in_(session_ids))).all()
        sessions_by_id = {session.id: session for session in sessions if session.id}

    rows: List[Dict[str, Any]] = []
    for event in events:
        partner_kind, partner_id = _partner_for_event(event, entity_kind, entity_id)
        url_template = ENTITY_EDIT_URLS.get(partner_kind)
        partner_edit_url = (
            url_template.format(campaign_id=campaign_id, entity_id=partner_id) if url_template else None
        )
        session = sessions_by_id.get(event.session_id) if event.session_id else None
        rows.append(
            {
                "action": event.action,
                "action_label": ACTION_LABELS.get(event.action, event.action.title()),
                "partner_kind": partner_kind,
                "partner_kind_label": KIND_LABELS.get(partner_kind, partner_kind.title()),
                "partner_id": partner_id,
                "partner_name": _entity_name(db, partner_kind, partner_id),
                "partner_edit_url": partner_edit_url,
                "session_id": event.session_id,
                "session_title": session.title if session else None,
                "created_at": event.created_at,
                "source_label": session.title if session else "via entity edit",
            }
        )

    return {
        "events": rows,
        "event_count": len(rows),
    }
