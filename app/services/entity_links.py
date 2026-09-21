from typing import List, Optional, Type

from sqlmodel import Session, delete, select

from app.models import Faction


def parse_form_id_list(ids: Optional[List[str]]) -> List[int]:
    """Normalize checkbox/multiselect form values; empty submission clears all links."""
    if not ids:
        return []
    return [int(value) for value in ids if value and str(value).isdigit()]


def load_campaign_entities_by_ids(
    db: Session,
    model: Type,
    campaign_id: int,
    ids: Optional[List[str]],
):
    parsed = parse_form_id_list(ids)
    if not parsed:
        return []
    return db.exec(
        select(model).where(model.campaign_id == campaign_id, model.id.in_(parsed))
    ).all()


def load_factions_for_link(
    db: Session,
    campaign_id: int,
    selected_factions: Optional[List[str]],
    *,
    new_faction_name: str = "",
    new_faction_type: str = "",
    new_faction_type_custom: str = "",
) -> List[Faction]:
    """Load factions from checkbox selections and optionally create one inline."""
    factions = list(load_campaign_entities_by_ids(db, Faction, campaign_id, selected_factions))
    name = (new_faction_name or "").strip()
    if not name:
        return factions

    from app.services.faction_classification import resolve_faction_type
    from app.services.ingestion import create_entity_if_missing

    resolved_type = resolve_faction_type(new_faction_type, new_faction_type_custom)
    extra = {"faction_type": resolved_type} if resolved_type else None
    new_faction = create_entity_if_missing(db, campaign_id, Faction, "name", name, extra=extra)
    if new_faction.id not in {faction.id for faction in factions}:
        factions.append(new_faction)
    return factions


def related_ids_from_links(db: Session, link_model, owner_field: str, owner_id: int, related_field: str) -> List[int]:
    rows = db.exec(select(link_model).where(getattr(link_model, owner_field) == owner_id)).all()
    return [getattr(row, related_field) for row in rows if getattr(row, related_field, None) is not None]


def replace_many_to_many_links(
    db: Session,
    owner_id: int,
    link_model,
    owner_field: str,
    related_field: str,
    related_entities: list,
    *,
    campaign_id: Optional[int] = None,
    owner_kind: Optional[str] = None,
    related_kind: Optional[str] = None,
    session_id: Optional[int] = None,
) -> None:
    old_related_ids = set(
        related_ids_from_links(db, link_model, owner_field, owner_id, related_field)
    )
    new_related_ids = {entity.id for entity in related_entities if getattr(entity, "id", None)}

    db.exec(delete(link_model).where(getattr(link_model, owner_field) == owner_id))
    for entity in related_entities:
        db.add(link_model(**{owner_field: owner_id, related_field: entity.id}))

    if campaign_id is not None and owner_kind and related_kind:
        from app.services.relationship_history import log_relationship_diff

        log_relationship_diff(
            db,
            campaign_id,
            owner_kind,
            owner_id,
            related_kind,
            old_related_ids,
            new_related_ids,
            session_id=session_id,
        )
