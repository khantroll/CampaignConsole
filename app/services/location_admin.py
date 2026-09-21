"""Location merge and bulk admin operations."""

from typing import Iterable, List, Optional

from sqlmodel import Session, delete, select

from app.models import (
    ItemLocationLink,
    Location,
    LocationFactionLink,
    LocationPlotThreadLink,
    LocationRelatedLocationLink,
    NPCLocationLink,
    PCLocationLink,
    SessionLocationLink,
)
from app.services.entity_deletion import delete_location_cascade

LOCATION_LINK_MODELS = (
    (SessionLocationLink, "location_id", "session_id"),
    (NPCLocationLink, "location_id", "npc_id"),
    (PCLocationLink, "location_id", "pc_note_id"),
    (LocationFactionLink, "location_id", "faction_id"),
    (LocationPlotThreadLink, "location_id", "plot_thread_id"),
    (ItemLocationLink, "location_id", "item_id"),
)


def _existing_peer_ids(db: Session, link_model, location_field: str, peer_field: str, location_id: int) -> set:
    rows = db.exec(select(link_model).where(getattr(link_model, location_field) == location_id)).all()
    return {getattr(row, peer_field) for row in rows}


def relink_location_id(db: Session, from_id: int, to_id: int) -> None:
    if from_id == to_id:
        return
    for link_model, location_field, peer_field in LOCATION_LINK_MODELS:
        existing_peers = _existing_peer_ids(db, link_model, location_field, peer_field, to_id)
        rows = db.exec(select(link_model).where(getattr(link_model, location_field) == from_id)).all()
        for row in rows:
            peer_id = getattr(row, peer_field)
            if peer_id in existing_peers:
                db.delete(row)
                continue
            setattr(row, location_field, to_id)
            db.add(row)
            existing_peers.add(peer_id)


def merge_locations(
    db: Session,
    campaign_id: int,
    canonical_id: int,
    duplicate_ids: Iterable[int],
) -> Optional[Location]:
    canonical = db.get(Location, canonical_id)
    if not canonical or canonical.campaign_id != campaign_id:
        return None

    for duplicate_id in duplicate_ids:
        if duplicate_id == canonical_id:
            continue
        duplicate = db.get(Location, duplicate_id)
        if not duplicate or duplicate.campaign_id != campaign_id:
            continue
        if duplicate.description and not canonical.description:
            canonical.description = duplicate.description
        if duplicate.notes and not canonical.notes:
            canonical.notes = duplicate.notes
        elif duplicate.notes and canonical.notes and duplicate.notes not in canonical.notes:
            canonical.notes = f"{canonical.notes}\n\n{duplicate.notes}"
        relink_location_id(db, duplicate.id, canonical.id)
        from app.services.location_links import relink_location_related_links

        relink_location_related_links(db, duplicate.id, canonical.id)
        db.delete(duplicate)

    db.add(canonical)
    db.flush()
    return canonical


def bulk_delete_locations(db: Session, campaign_id: int, location_ids: Iterable[int]) -> int:
    deleted = 0
    for location_id in location_ids:
        location = db.get(Location, location_id)
        if location and location.campaign_id == campaign_id:
            delete_location_cascade(db, location)
            deleted += 1
    return deleted


def update_location_types(
    db: Session,
    campaign_id: int,
    updates: dict[int, str],
) -> int:
    changed = 0
    for location_id, location_type in updates.items():
        location = db.get(Location, location_id)
        if location and location.campaign_id == campaign_id and location_type:
            location.location_type = location_type
            db.add(location)
            changed += 1
    return changed
