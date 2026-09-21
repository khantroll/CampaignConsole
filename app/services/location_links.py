"""Symmetric location-to-location relationship links."""

from __future__ import annotations

from typing import List, Optional, Set

from sqlmodel import Session, delete, select

from app.models import Location, LocationRelatedLocationLink
from app.services.entity_links import parse_form_id_list


def related_location_ids(db: Session, location_id: int) -> List[int]:
    rows = db.exec(
        select(LocationRelatedLocationLink).where(LocationRelatedLocationLink.location_id == location_id)
    ).all()
    return [row.related_location_id for row in rows if row.related_location_id is not None]


def load_related_locations(db: Session, campaign_id: int, location_id: int) -> List[Location]:
    ids = related_location_ids(db, location_id)
    if not ids:
        return []
    return db.exec(
        select(Location).where(Location.campaign_id == campaign_id, Location.id.in_(ids)).order_by(Location.name)
    ).all()


def _link_exists(db: Session, left_id: int, right_id: int) -> bool:
    return (
        db.exec(
            select(LocationRelatedLocationLink).where(
                LocationRelatedLocationLink.location_id == left_id,
                LocationRelatedLocationLink.related_location_id == right_id,
            )
        ).first()
        is not None
    )


def _add_symmetric_link(db: Session, left_id: int, right_id: int) -> None:
    if left_id == right_id:
        return
    if not _link_exists(db, left_id, right_id):
        db.add(LocationRelatedLocationLink(location_id=left_id, related_location_id=right_id))
    if not _link_exists(db, right_id, left_id):
        db.add(LocationRelatedLocationLink(location_id=right_id, related_location_id=left_id))


def _remove_symmetric_link(db: Session, left_id: int, right_id: int) -> None:
    db.exec(
        delete(LocationRelatedLocationLink).where(
            LocationRelatedLocationLink.location_id == left_id,
            LocationRelatedLocationLink.related_location_id == right_id,
        )
    )
    db.exec(
        delete(LocationRelatedLocationLink).where(
            LocationRelatedLocationLink.location_id == right_id,
            LocationRelatedLocationLink.related_location_id == left_id,
        )
    )


def replace_location_related_links(
    db: Session,
    campaign_id: int,
    location_id: int,
    related_locations: List[Location],
    *,
    session_id: Optional[int] = None,
) -> None:
    old_related_ids: Set[int] = set(related_location_ids(db, location_id))
    new_related_ids: Set[int] = {
        loc.id for loc in related_locations if loc.id and loc.id != location_id
    }

    for related_id in old_related_ids - new_related_ids:
        _remove_symmetric_link(db, location_id, related_id)

    for related_id in new_related_ids - old_related_ids:
        _add_symmetric_link(db, location_id, related_id)

    from app.services.relationship_history import log_relationship_diff

    log_relationship_diff(
        db,
        campaign_id,
        "locations",
        location_id,
        "locations",
        old_related_ids,
        new_related_ids,
        session_id=session_id,
    )


def relink_location_related_links(db: Session, from_id: int, to_id: int) -> None:
    if from_id == to_id:
        return

    for row in db.exec(
        select(LocationRelatedLocationLink).where(LocationRelatedLocationLink.location_id == from_id)
    ).all():
        peer_id = row.related_location_id
        db.delete(row)
        if peer_id and peer_id not in (from_id, to_id):
            _add_symmetric_link(db, to_id, peer_id)

    for row in db.exec(
        select(LocationRelatedLocationLink).where(LocationRelatedLocationLink.related_location_id == from_id)
    ).all():
        owner_id = row.location_id
        db.delete(row)
        if owner_id and owner_id not in (from_id, to_id):
            _add_symmetric_link(db, owner_id, to_id)

    _remove_symmetric_link(db, to_id, to_id)


def load_related_location_options(
    db: Session,
    campaign_id: int,
    location_id: int,
    selected_ids: Optional[List[str]] = None,
) -> List[dict]:
    from app.deps import related_options

    locations = db.exec(select(Location).where(Location.campaign_id == campaign_id).order_by(Location.name)).all()
    choices = [loc for loc in locations if loc.id != location_id]
    current_ids = set(parse_form_id_list(selected_ids)) if selected_ids is not None else set(related_location_ids(db, location_id))
    return related_options(choices, current_ids)
