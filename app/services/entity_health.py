"""Entity completeness scoring and campaign health overview."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

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
    PCFactionLink,
    PCLocationLink,
    PCPlotThreadLink,
    PlayerCharacterNote,
    PlotThread,
    PlotThreadRelatedPlotThreadLink,
    SessionCreatureLink,
    SessionFactionLink,
    SessionItemLink,
    SessionLocationLink,
    SessionNPCLink,
    SessionPartyMemberLink,
    SessionPlotThreadLink,
)
from app.services.location_classification import filter_locations_by_type

ENTITY_TYPE_BADGES = {
    "npcs": "NPC",
    "locations": "LOCATION",
    "factions": "FACTION",
    "items": "ITEM",
    "creatures": "CREATURE",
    "threads": "THREAD",
    "pcs": "PC",
}

STATUS_COMPLETE = "complete"
STATUS_PARTIAL = "partial"
STATUS_MINIMAL = "minimal"

STATUS_BADGE_CLASS = {
    STATUS_COMPLETE: "success",
    STATUS_PARTIAL: "warning",
    STATUS_MINIMAL: "danger",
}

STATUS_LABEL = {
    STATUS_COMPLETE: "Complete",
    STATUS_PARTIAL: "Partial",
    STATUS_MINIMAL: "Minimal",
}


def _filled(value: Optional[str]) -> bool:
    return bool(str(value or "").strip())


def _status_from_score(score: int) -> str:
    if score >= 80:
        return STATUS_COMPLETE
    if score >= 40:
        return STATUS_PARTIAL
    return STATUS_MINIMAL


def _build_health(
    *,
    has_description: bool,
    has_notes: bool,
    has_relationships: bool,
    include_description: bool = True,
    include_notes: bool = True,
) -> Dict[str, Any]:
    categories = []
    if include_description:
        categories.append(("Description", has_description))
    if include_notes:
        categories.append(("Notes", has_notes))
    categories.append(("Relationships", has_relationships))

    weight = 100 / len(categories)
    score = round(sum(weight for _, present in categories if present))
    missing = [label for label, present in categories if not present]
    return {
        "score": score,
        "status": _status_from_score(score),
        "status_label": STATUS_LABEL[_status_from_score(score)],
        "badge_class": STATUS_BADGE_CLASS[_status_from_score(score)],
        "missing": missing,
        "has_description": has_description,
        "has_notes": has_notes,
        "has_relationships": has_relationships,
    }


def _link_counts(db: Session, link_model, entity_field: str, entity_ids: List[int]) -> Dict[int, int]:
    if not entity_ids:
        return {}
    rows = db.exec(select(link_model)).all()
    counts: Dict[int, int] = {entity_id: 0 for entity_id in entity_ids}
    for row in rows:
        entity_id = getattr(row, entity_field, None)
        if entity_id in counts:
            counts[entity_id] += 1
    return counts


def _sum_counts(*count_maps: Dict[int, int], entity_id: int) -> int:
    return sum(count_map.get(entity_id, 0) for count_map in count_maps)


class CampaignEntityHealth:
    def __init__(self, db: Session, campaign_id: int):
        self.db = db
        self.campaign_id = campaign_id
        self._npc_ids = list(db.exec(select(NPC.id).where(NPC.campaign_id == campaign_id)).all())
        self._location_ids = list(db.exec(select(Location.id).where(Location.campaign_id == campaign_id)).all())
        self._faction_ids = list(db.exec(select(Faction.id).where(Faction.campaign_id == campaign_id)).all())
        self._item_ids = list(db.exec(select(Item.id).where(Item.campaign_id == campaign_id)).all())
        self._creature_ids = list(db.exec(select(Creature.id).where(Creature.campaign_id == campaign_id)).all())
        self._thread_ids = list(db.exec(select(PlotThread.id).where(PlotThread.campaign_id == campaign_id)).all())
        self._pc_ids = list(
            db.exec(select(PlayerCharacterNote.id).where(PlayerCharacterNote.campaign_id == campaign_id)).all()
        )

        self.npc_faction = _link_counts(db, NPCFactionLink, "npc_id", self._npc_ids)
        self.npc_location = _link_counts(db, NPCLocationLink, "npc_id", self._npc_ids)
        self.npc_thread = _link_counts(db, NPCPlotThreadLink, "npc_id", self._npc_ids)
        self.npc_item = _link_counts(db, ItemNPCLink, "npc_id", self._npc_ids)
        self.npc_session = _link_counts(db, SessionNPCLink, "npc_id", self._npc_ids)

        self.location_faction = _link_counts(db, LocationFactionLink, "location_id", self._location_ids)
        self.location_thread = _link_counts(db, LocationPlotThreadLink, "location_id", self._location_ids)
        self.location_item = _link_counts(db, ItemLocationLink, "location_id", self._location_ids)
        self.location_creature = _link_counts(db, CreatureLocationLink, "location_id", self._location_ids)
        self.location_npc = _link_counts(db, NPCLocationLink, "location_id", self._location_ids)
        self.location_related = _link_counts(db, LocationRelatedLocationLink, "location_id", self._location_ids)
        self.location_session = _link_counts(db, SessionLocationLink, "location_id", self._location_ids)

        self.faction_npc = _link_counts(db, NPCFactionLink, "faction_id", self._faction_ids)
        self.faction_pc = _link_counts(db, PCFactionLink, "faction_id", self._faction_ids)
        self.faction_location = _link_counts(db, LocationFactionLink, "faction_id", self._faction_ids)
        self.faction_thread = _link_counts(db, FactionPlotThreadLink, "faction_id", self._faction_ids)
        self.faction_creature = _link_counts(db, CreatureFactionLink, "faction_id", self._faction_ids)
        self.faction_session = _link_counts(db, SessionFactionLink, "faction_id", self._faction_ids)

        self.item_npc = _link_counts(db, ItemNPCLink, "item_id", self._item_ids)
        self.item_faction = _link_counts(db, ItemFactionLink, "item_id", self._item_ids)
        self.item_location = _link_counts(db, ItemLocationLink, "item_id", self._item_ids)
        self.item_thread = _link_counts(db, ItemPlotThreadLink, "item_id", self._item_ids)
        self.item_session = _link_counts(db, SessionItemLink, "item_id", self._item_ids)

        self.creature_faction = _link_counts(db, CreatureFactionLink, "creature_id", self._creature_ids)
        self.creature_location = _link_counts(db, CreatureLocationLink, "creature_id", self._creature_ids)
        self.creature_thread = _link_counts(db, CreaturePlotThreadLink, "creature_id", self._creature_ids)
        self.creature_session = _link_counts(db, SessionCreatureLink, "creature_id", self._creature_ids)

        self.thread_npc = _link_counts(db, NPCPlotThreadLink, "plot_thread_id", self._thread_ids)
        self.thread_location = _link_counts(db, LocationPlotThreadLink, "plot_thread_id", self._thread_ids)
        self.thread_item = _link_counts(db, ItemPlotThreadLink, "plot_thread_id", self._thread_ids)
        self.thread_creature = _link_counts(db, CreaturePlotThreadLink, "plot_thread_id", self._thread_ids)
        self.thread_session = _link_counts(db, SessionPlotThreadLink, "plot_thread_id", self._thread_ids)
        self.thread_related = _link_counts(db, PlotThreadRelatedPlotThreadLink, "plot_thread_id", self._thread_ids)
        self.thread_faction = _link_counts(db, FactionPlotThreadLink, "plot_thread_id", self._thread_ids)

        self.pc_session = _link_counts(db, SessionPartyMemberLink, "pc_note_id", self._pc_ids)
        self.pc_location = _link_counts(db, PCLocationLink, "pc_note_id", self._pc_ids)
        self.pc_faction = _link_counts(db, PCFactionLink, "pc_note_id", self._pc_ids)
        self.pc_thread = _link_counts(db, PCPlotThreadLink, "pc_note_id", self._pc_ids)

        self.thread_pc = _link_counts(db, PCPlotThreadLink, "plot_thread_id", self._thread_ids)

    def score_npc(self, npc: NPC) -> Dict[str, Any]:
        rel_count = _sum_counts(
            self.npc_faction,
            self.npc_location,
            self.npc_thread,
            self.npc_item,
            self.npc_session,
            entity_id=npc.id,
        )
        has_notes = any(
            _filled(getattr(npc, field, None))
            for field in (
                "role",
                "goals",
                "secrets",
                "current_status",
                "relationship_to_party",
                "current_location",
                "alive_or_dead",
            )
        )
        return _build_health(
            has_description=_filled(npc.description),
            has_notes=has_notes,
            has_relationships=rel_count > 0,
        )

    def score_location(self, location: Location) -> Dict[str, Any]:
        rel_count = _sum_counts(
            self.location_faction,
            self.location_thread,
            self.location_item,
            self.location_creature,
            self.location_npc,
            self.location_related,
            self.location_session,
            entity_id=location.id,
        )
        return _build_health(
            has_description=_filled(location.description),
            has_notes=_filled(location.notes),
            has_relationships=rel_count > 0,
        )

    def score_faction(self, faction: Faction) -> Dict[str, Any]:
        rel_count = _sum_counts(
            self.faction_npc,
            self.faction_pc,
            self.faction_location,
            self.faction_thread,
            self.faction_creature,
            self.faction_session,
            entity_id=faction.id,
        )
        has_hq = faction.hq_location_id is not None
        return _build_health(
            has_description=_filled(faction.summary),
            has_notes=_filled(faction.plot_notes) or has_hq,
            has_relationships=rel_count > 0,
        )

    def score_item(self, item: Item) -> Dict[str, Any]:
        rel_count = _sum_counts(
            self.item_faction,
            self.item_location,
            self.item_thread,
            self.item_session,
            entity_id=item.id,
        )
        has_owner = item.owner_npc_id is not None or item.owner_pc_id is not None
        return _build_health(
            has_description=_filled(item.description),
            has_notes=_filled(item.plot_notes) or _filled(item.origin) or has_owner,
            has_relationships=rel_count > 0,
        )

    def score_creature(self, creature: Creature) -> Dict[str, Any]:
        rel_count = _sum_counts(
            self.creature_faction,
            self.creature_location,
            self.creature_thread,
            self.creature_session,
            entity_id=creature.id,
        )
        return _build_health(
            has_description=_filled(creature.physical_description) or _filled(creature.description),
            has_notes=any(
                _filled(getattr(creature, field, None))
                for field in (
                    "classification",
                    "habitat",
                    "threat_level",
                    "special_traits",
                    "campaign_context_tactics",
                    "notes",
                )
            ),
            has_relationships=rel_count > 0,
        )

    def score_thread(self, thread: PlotThread) -> Dict[str, Any]:
        rel_count = _sum_counts(
            self.thread_npc,
            self.thread_pc,
            self.thread_location,
            self.thread_item,
            self.thread_creature,
            self.thread_session,
            self.thread_related,
            self.thread_faction,
            entity_id=thread.id,
        )
        has_notes = any(
            _filled(getattr(thread, field, None))
            for field in ("status", "thread_type", "plot_significance_notes", "importance", "related_npcs", "related_locations", "resolution_notes")
        )
        return _build_health(
            has_description=_filled(thread.details),
            has_notes=has_notes,
            has_relationships=rel_count > 0,
        )

    def score_pc(self, pc: PlayerCharacterNote) -> Dict[str, Any]:
        rel_count = _sum_counts(
            self.pc_session,
            self.pc_location,
            self.pc_faction,
            self.pc_thread,
            entity_id=pc.id,
        )
        has_profile_notes = any(
            _filled(getattr(pc, field, None))
            for field in (
                "character_archetype",
                "signature_gear",
                "key_ties_history",
                "campaign_role_plot_notes",
                "notes",
            )
        )
        return _build_health(
            has_description=_filled(pc.description),
            has_notes=has_profile_notes,
            has_relationships=rel_count > 0,
        )

    def score_entity(self, section_key: str, entity: Any) -> Dict[str, Any]:
        scorers = {
            "npcs": self.score_npc,
            "locations": self.score_location,
            "factions": self.score_faction,
            "items": self.score_item,
            "creatures": self.score_creature,
            "threads": self.score_thread,
            "pcs": self.score_pc,
        }
        scorer = scorers.get(section_key)
        if not scorer:
            return _build_health(has_description=False, has_notes=False, has_relationships=False)
        return scorer(entity)

    def health_map(self, section_key: str, entities: List[Any]) -> Dict[int, Dict[str, Any]]:
        return {entity.id: self.score_entity(section_key, entity) for entity in entities}


def health_tooltip(health: Dict[str, Any]) -> str:
    missing = health.get("missing") or []
    if not missing:
        return "All tracked fields complete."
    return "Missing: " + ", ".join(missing)


def sort_entities(section_key: str, entities: List[Any], health_map: Dict[int, Dict[str, Any]], sort_key: str) -> List[Any]:
    if sort_key == "updated":
        return sorted(entities, key=lambda item: getattr(item, "updated_at", None) or "", reverse=True)
    if sort_key == "completeness":
        return sorted(
            entities,
            key=lambda item: (health_map.get(item.id, {}).get("score", 0), _entity_sort_name(section_key, item)),
            reverse=True,
        )
    return sorted(entities, key=lambda item: _entity_sort_name(section_key, item).lower())


def _entity_sort_name(section_key: str, entity: Any) -> str:
    if section_key == "pcs":
        return getattr(entity, "character_name", "") or ""
    return getattr(entity, "name", None) or getattr(entity, "title", "") or ""


def _summarize_group(entities: List[Any], health_map: Dict[int, Dict[str, Any]]) -> Dict[str, Any]:
    if not entities:
        return {
            "count": 0,
            "average_score": 0,
            "complete": 0,
            "partial": 0,
            "minimal": 0,
        }
    scores = [health_map.get(entity.id, {}).get("score", 0) for entity in entities]
    statuses = [health_map.get(entity.id, {}).get("status", STATUS_MINIMAL) for entity in entities]
    return {
        "count": len(entities),
        "average_score": round(sum(scores) / len(scores)),
        "complete": statuses.count(STATUS_COMPLETE),
        "partial": statuses.count(STATUS_PARTIAL),
        "minimal": statuses.count(STATUS_MINIMAL),
    }


def build_campaign_completeness_overview(
    db: Session,
    campaign_id: int,
    *,
    location_filter: str = "major_sub",
) -> Dict[str, Any]:
    health_service = CampaignEntityHealth(db, campaign_id)

    npcs = db.exec(select(NPC).where(NPC.campaign_id == campaign_id)).all()
    all_locations = db.exec(select(Location).where(Location.campaign_id == campaign_id)).all()
    locations = filter_locations_by_type(all_locations, location_filter)
    factions = db.exec(select(Faction).where(Faction.campaign_id == campaign_id)).all()
    items = db.exec(select(Item).where(Item.campaign_id == campaign_id)).all()
    creatures = db.exec(select(Creature).where(Creature.campaign_id == campaign_id)).all()
    threads = db.exec(select(PlotThread).where(PlotThread.campaign_id == campaign_id)).all()
    pcs = db.exec(select(PlayerCharacterNote).where(PlayerCharacterNote.campaign_id == campaign_id)).all()

    groups = [
        ("npcs", "NPCs", npcs),
        ("locations", "Locations", locations),
        ("factions", "Factions", factions),
        ("items", "Items", items),
        ("creatures", "Creatures", creatures),
        ("threads", "Plot Threads", threads),
        ("pcs", "Party Members", pcs),
    ]

    sections = []
    total_entities = 0
    total_score = 0

    for key, label, entities in groups:
        health_map = health_service.health_map(key, entities)
        summary = _summarize_group(entities, health_map)
        sections.append(
            {
                "key": key,
                "label": label,
                "type_badge": ENTITY_TYPE_BADGES.get(key, key.upper()),
                **summary,
            }
        )
        total_entities += summary["count"]
        total_score += summary["average_score"] * summary["count"]

    campaign_average = round(total_score / total_entities) if total_entities else 0
    return {
        "campaign_average": campaign_average,
        "campaign_status": _status_from_score(campaign_average),
        "campaign_badge_class": STATUS_BADGE_CLASS[_status_from_score(campaign_average)],
        "sections": sections,
        "total_entities": total_entities,
    }


def prepare_entity_lists(
    db: Session,
    campaign_id: int,
    *,
    location_filter: str = "major_sub",
    entity_sort: str = "name",
) -> Tuple[CampaignEntityHealth, Dict[str, Any]]:
    health_service = CampaignEntityHealth(db, campaign_id)

    npcs = db.exec(select(NPC).where(NPC.campaign_id == campaign_id)).all()
    all_locations = db.exec(select(Location).where(Location.campaign_id == campaign_id)).all()
    locations = filter_locations_by_type(all_locations, location_filter)
    factions = db.exec(select(Faction).where(Faction.campaign_id == campaign_id)).all()
    items = db.exec(select(Item).where(Item.campaign_id == campaign_id)).all()
    creatures = db.exec(select(Creature).where(Creature.campaign_id == campaign_id)).all()
    threads = db.exec(select(PlotThread).where(PlotThread.campaign_id == campaign_id)).all()
    pcs = db.exec(select(PlayerCharacterNote).where(PlayerCharacterNote.campaign_id == campaign_id)).all()

    lists = {
        "npcs": npcs,
        "locations": locations,
        "factions": factions,
        "items": items,
        "creatures": creatures,
        "threads": threads,
        "pcs": pcs,
    }

    from app.services.entity_session_presence import hydrate_last_seen_for_display

    for section_key in ("npcs", "locations", "factions", "items", "creatures", "threads"):
        hydrate_last_seen_for_display(db, campaign_id, section_key, lists[section_key])

    health_maps: Dict[str, Dict[int, Dict[str, Any]]] = {}
    sorted_lists: Dict[str, List[Any]] = {}
    for key, entities in lists.items():
        health_maps[key] = health_service.health_map(key, entities)
        sorted_lists[key] = sort_entities(key, entities, health_maps[key], entity_sort)

    overview = build_campaign_completeness_overview(db, campaign_id, location_filter=location_filter)

    return health_service, {
        "npcs": sorted_lists["npcs"],
        "locations": sorted_lists["locations"],
        "factions": sorted_lists["factions"],
        "items": sorted_lists["items"],
        "creatures": sorted_lists["creatures"],
        "threads": sorted_lists["threads"],
        "pc_notes": sorted_lists["pcs"],
        "health_maps": health_maps,
        "entity_sort": entity_sort,
        "completeness_overview": overview,
        "entity_type_badges": ENTITY_TYPE_BADGES,
    }


ENTITY_EDIT_URLS = {
    "npcs": "/campaigns/{campaign_id}/npcs/{entity_id}/edit",
    "locations": "/campaigns/{campaign_id}/locations/{entity_id}/edit",
    "factions": "/campaigns/{campaign_id}/factions/{entity_id}/edit",
    "items": "/campaigns/{campaign_id}/items/{entity_id}/edit",
    "creatures": "/campaigns/{campaign_id}/creatures/{entity_id}/edit",
    "threads": "/campaigns/{campaign_id}/threads/{entity_id}/edit",
    "pcs": "/campaigns/{campaign_id}/pcs/{entity_id}/edit",
}


def build_needs_attention_list(
    campaign_id: int,
    health_maps: Dict[str, Dict[int, Dict[str, Any]]],
    entity_lists: Dict[str, List[Any]],
    *,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for section_key, entities in entity_lists.items():
        url_template = ENTITY_EDIT_URLS.get(section_key)
        if not url_template:
            continue
        health_map = health_maps.get(section_key) or {}
        for entity in entities:
            health = health_map.get(entity.id) or {}
            if health.get("status") == STATUS_COMPLETE:
                continue
            entries.append(
                {
                    "section_key": section_key,
                    "type_badge": ENTITY_TYPE_BADGES.get(section_key, section_key.upper()),
                    "name": _entity_sort_name(section_key, entity),
                    "score": health.get("score", 0),
                    "status": health.get("status"),
                    "badge_class": health.get("badge_class", "danger"),
                    "missing": health.get("missing") or [],
                    "edit_url": url_template.format(campaign_id=campaign_id, entity_id=entity.id),
                }
            )
    entries.sort(key=lambda row: (row["score"], row["name"].lower()))
    return entries[:limit]
