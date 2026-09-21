from sqlmodel import Session, delete, select

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
    LoreChunk,
    NPC,
    NPCFactionLink,
    NPCLocationLink,
    NPCPlotThreadLink,
    PCLocationLink,
    PCFactionLink,
    PCPlotThreadLink,
    PlayerCharacterNote,
    PlotThread,
    PlotThreadRelatedPlotThreadLink,
    SessionFactionLink,
    SessionCreatureLink,
    SessionItemLink,
    SessionLocationLink,
    SessionModel,
    SessionNPCLink,
    SessionPartyMemberLink,
    SessionPlotThreadLink,
)


def _delete_links(db: Session, link_model, field_name: str, entity_id: int) -> None:
    db.exec(delete(link_model).where(getattr(link_model, field_name) == entity_id))


def _session_linked_ids(db: Session, link_model, entity_field: str, session_id: int) -> list[int]:
    rows = db.exec(select(link_model).where(link_model.session_id == session_id)).all()
    ids: list[int] = []
    for row in rows:
        entity_id = getattr(row, entity_field, None)
        if entity_id is not None:
            ids.append(entity_id)
    return ids


def _entity_has_session_links(db: Session, link_model, entity_field: str, entity_id: int) -> bool:
    row = db.exec(
        select(link_model).where(getattr(link_model, entity_field) == entity_id)
    ).first()
    return row is not None


def _delete_session_exclusive_entities(
    db: Session,
    campaign_id: int,
    linked_ids: list[int],
    link_model,
    entity_field: str,
    entity_model,
    delete_cascade_fn,
) -> None:
    for entity_id in linked_ids:
        if _entity_has_session_links(db, link_model, entity_field, entity_id):
            continue
        entity = db.get(entity_model, entity_id)
        if entity and entity.campaign_id == campaign_id:
            delete_cascade_fn(db, entity)


def delete_session_cascade(db: Session, session_model: SessionModel) -> None:
    session_id = session_model.id
    campaign_id = session_model.campaign_id

    linked_npc_ids = _session_linked_ids(db, SessionNPCLink, "npc_id", session_id)
    linked_location_ids = _session_linked_ids(db, SessionLocationLink, "location_id", session_id)
    linked_faction_ids = _session_linked_ids(db, SessionFactionLink, "faction_id", session_id)
    linked_item_ids = _session_linked_ids(db, SessionItemLink, "item_id", session_id)
    linked_creature_ids = _session_linked_ids(db, SessionCreatureLink, "creature_id", session_id)
    linked_thread_ids = _session_linked_ids(db, SessionPlotThreadLink, "plot_thread_id", session_id)

    db.exec(
        delete(LoreChunk).where(
            LoreChunk.campaign_id == campaign_id,
            LoreChunk.source_type == "session",
            LoreChunk.source_id == session_id,
        )
    )

    for link_model in (
        SessionNPCLink,
        SessionLocationLink,
        SessionFactionLink,
        SessionItemLink,
        SessionCreatureLink,
        SessionPlotThreadLink,
        SessionPartyMemberLink,
    ):
        _delete_links(db, link_model, "session_id", session_id)

    for npc in db.exec(select(NPC).where(NPC.last_seen_session_id == session_id)).all():
        npc.last_seen_session_id = None
        db.add(npc)
    for location in db.exec(select(Location).where(Location.last_seen_session_id == session_id)).all():
        location.last_seen_session_id = None
        db.add(location)
    for faction in db.exec(select(Faction).where(Faction.last_seen_session_id == session_id)).all():
        faction.last_seen_session_id = None
        db.add(faction)
    for item in db.exec(select(Item).where(Item.last_seen_session_id == session_id)).all():
        item.last_seen_session_id = None
        db.add(item)
    for creature in db.exec(select(Creature).where(Creature.last_seen_session_id == session_id)).all():
        creature.last_seen_session_id = None
        db.add(creature)
    for thread in db.exec(select(PlotThread).where(PlotThread.last_touched_session_id == session_id)).all():
        thread.last_touched_session_id = None
        db.add(thread)

    _delete_session_exclusive_entities(
        db, campaign_id, linked_npc_ids, SessionNPCLink, "npc_id", NPC, delete_npc_cascade
    )
    _delete_session_exclusive_entities(
        db, campaign_id, linked_location_ids, SessionLocationLink, "location_id", Location, delete_location_cascade
    )
    _delete_session_exclusive_entities(
        db, campaign_id, linked_faction_ids, SessionFactionLink, "faction_id", Faction, delete_faction_cascade
    )
    _delete_session_exclusive_entities(
        db, campaign_id, linked_item_ids, SessionItemLink, "item_id", Item, delete_item_cascade
    )
    _delete_session_exclusive_entities(
        db, campaign_id, linked_creature_ids, SessionCreatureLink, "creature_id", Creature, delete_creature_cascade
    )
    _delete_session_exclusive_entities(
        db, campaign_id, linked_thread_ids, SessionPlotThreadLink, "plot_thread_id", PlotThread, delete_plot_thread_cascade
    )

    db.delete(session_model)


def delete_npc_cascade(db: Session, npc: NPC) -> None:
    npc_id = npc.id
    for item in db.exec(select(Item).where(Item.owner_npc_id == npc_id)).all():
        item.owner_npc_id = None
        db.add(item)
    for link_model in (
        SessionNPCLink,
        NPCFactionLink,
        NPCLocationLink,
        NPCPlotThreadLink,
        ItemNPCLink,
    ):
        _delete_links(db, link_model, "npc_id", npc_id)
    db.delete(npc)


def delete_location_cascade(db: Session, location: Location) -> None:
    location_id = location.id
    for link_model in (
        SessionLocationLink,
        NPCLocationLink,
        PCLocationLink,
        LocationFactionLink,
        LocationPlotThreadLink,
        LocationRelatedLocationLink,
        ItemLocationLink,
        CreatureLocationLink,
    ):
        _delete_links(db, link_model, "location_id", location_id)
    db.exec(
        delete(LocationRelatedLocationLink).where(
            LocationRelatedLocationLink.related_location_id == location_id
        )
    )
    for faction in db.exec(select(Faction).where(Faction.hq_location_id == location_id)).all():
        faction.hq_location_id = None
        db.add(faction)
    db.delete(location)


def delete_pc_cascade(db: Session, pc: PlayerCharacterNote) -> None:
    pc_id = pc.id
    for item in db.exec(select(Item).where(Item.owner_pc_id == pc_id)).all():
        item.owner_pc_id = None
        db.add(item)
    for link_model in (
        SessionPartyMemberLink,
        PCLocationLink,
        PCFactionLink,
        PCPlotThreadLink,
    ):
        _delete_links(db, link_model, "pc_note_id", pc_id)
    db.delete(pc)


def delete_faction_cascade(db: Session, faction: Faction) -> None:
    faction_id = faction.id
    for link_model in (
        SessionFactionLink,
        NPCFactionLink,
        PCFactionLink,
        LocationFactionLink,
        FactionPlotThreadLink,
        ItemFactionLink,
        CreatureFactionLink,
    ):
        _delete_links(db, link_model, "faction_id", faction_id)
    db.delete(faction)


def delete_item_cascade(db: Session, item: Item) -> None:
    item_id = item.id
    for link_model in (
        SessionItemLink,
        ItemNPCLink,
        ItemFactionLink,
        ItemLocationLink,
        ItemPlotThreadLink,
    ):
        _delete_links(db, link_model, "item_id", item_id)
    db.delete(item)


def delete_creature_cascade(db: Session, creature: Creature) -> None:
    creature_id = creature.id
    for link_model in (
        SessionCreatureLink,
        CreatureFactionLink,
        CreatureLocationLink,
        CreaturePlotThreadLink,
    ):
        _delete_links(db, link_model, "creature_id", creature_id)
    db.delete(creature)


def delete_plot_thread_cascade(db: Session, thread: PlotThread) -> None:
    thread_id = thread.id
    for link_model in (
        SessionPlotThreadLink,
        NPCPlotThreadLink,
        LocationPlotThreadLink,
        ItemPlotThreadLink,
        CreaturePlotThreadLink,
        FactionPlotThreadLink,
        PCPlotThreadLink,
        PlotThreadRelatedPlotThreadLink,
    ):
        _delete_links(db, link_model, "plot_thread_id", thread_id)
    db.exec(
        delete(PlotThreadRelatedPlotThreadLink).where(
            PlotThreadRelatedPlotThreadLink.related_plot_thread_id == thread_id
        )
    )
    db.delete(thread)
