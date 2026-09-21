"""Scene, Encounter, and Objective narrative block services (Phase 3)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple, Type

from sqlmodel import Session, select

from app.models import (
    Encounter,
    EncounterFactionLink,
    EncounterItemLink,
    EncounterLocationLink,
    EncounterNPCLink,
    EncounterPCLink,
    EncounterPlotThreadLink,
    Faction,
    Item,
    Location,
    NPC,
    Objective,
    ObjectiveFactionLink,
    ObjectiveItemLink,
    ObjectiveLocationLink,
    ObjectiveNPCLink,
    ObjectivePCLink,
    ObjectivePlotThreadLink,
    PlayerCharacterNote,
    PlotThread,
    Scene,
    SceneFactionLink,
    SceneItemLink,
    SceneLocationLink,
    SceneNPCLink,
    ScenePCLink,
    ScenePlotThreadLink,
    SessionModel,
)
from app.services.entity_links import (
    load_campaign_entities_by_ids,
    related_ids_from_links,
    replace_many_to_many_links,
)
from app.services.world_state import lines_to_clue_list
from app.utils.time import utc_now

SCENE_STATUSES = ("planned", "active", "completed", "skipped", "archived")
ENCOUNTER_TYPES = ("social", "exploration", "combat", "puzzle", "hazard", "travel", "downtime", "other")
ENCOUNTER_STATUSES = SCENE_STATUSES
OBJECTIVE_TYPES = ("party_goal", "gm_goal", "npc_goal", "faction_goal", "clue", "consequence", "other")
OBJECTIVE_STATUSES = ("open", "in_progress", "completed", "failed", "abandoned", "archived")
OBJECTIVE_PRIORITIES = ("low", "normal", "high", "critical")

SCENE_STATUS_BADGE = {
    "planned": "secondary",
    "active": "info",
    "completed": "success",
    "skipped": "warning",
    "archived": "secondary",
}
ENCOUNTER_TYPE_BADGE = {
    "social": "info",
    "exploration": "primary",
    "combat": "danger",
    "puzzle": "warning",
    "hazard": "danger",
    "travel": "secondary",
    "downtime": "secondary",
    "other": "secondary",
}
OBJECTIVE_TYPE_BADGE = {
    "party_goal": "primary",
    "gm_goal": "secondary",
    "npc_goal": "info",
    "faction_goal": "warning",
    "clue": "success",
    "consequence": "danger",
    "other": "secondary",
}
OBJECTIVE_PRIORITY_BADGE = {
    "low": "secondary",
    "normal": "info",
    "high": "warning",
    "critical": "danger",
}
OBJECTIVE_STATUS_BADGE = {
    "open": "secondary",
    "in_progress": "info",
    "completed": "success",
    "failed": "danger",
    "abandoned": "warning",
    "archived": "secondary",
}

BLOCK_LINK_CONFIG: Dict[str, Dict[str, Tuple[Any, str, str]]] = {
    "scenes": {
        "npcs": (SceneNPCLink, "scene_id", "npc_id"),
        "pcs": (ScenePCLink, "scene_id", "pc_note_id"),
        "locations": (SceneLocationLink, "scene_id", "location_id"),
        "factions": (SceneFactionLink, "scene_id", "faction_id"),
        "items": (SceneItemLink, "scene_id", "item_id"),
        "threads": (ScenePlotThreadLink, "scene_id", "plot_thread_id"),
    },
    "encounters": {
        "npcs": (EncounterNPCLink, "encounter_id", "npc_id"),
        "pcs": (EncounterPCLink, "encounter_id", "pc_note_id"),
        "locations": (EncounterLocationLink, "encounter_id", "location_id"),
        "factions": (EncounterFactionLink, "encounter_id", "faction_id"),
        "items": (EncounterItemLink, "encounter_id", "item_id"),
        "threads": (EncounterPlotThreadLink, "encounter_id", "plot_thread_id"),
    },
    "objectives": {
        "npcs": (ObjectiveNPCLink, "objective_id", "npc_id"),
        "pcs": (ObjectivePCLink, "objective_id", "pc_note_id"),
        "locations": (ObjectiveLocationLink, "objective_id", "location_id"),
        "factions": (ObjectiveFactionLink, "objective_id", "faction_id"),
        "items": (ObjectiveItemLink, "objective_id", "item_id"),
        "threads": (ObjectivePlotThreadLink, "objective_id", "plot_thread_id"),
    },
}

ENTITY_MODELS = {
    "npcs": NPC,
    "pcs": PlayerCharacterNote,
    "locations": Location,
    "factions": Faction,
    "items": Item,
    "threads": PlotThread,
}


def _normalize_enum(value: Optional[str], allowed: Sequence[str], default: str) -> str:
    key = (value or "").strip().lower()
    return key if key in allowed else default


def _next_sort_order(db: Session, model: Type, campaign_id: int, session_id: Optional[int], **filters) -> int:
    query = select(model).where(model.campaign_id == campaign_id)
    if session_id is not None:
        query = query.where(model.session_id == session_id)
    for field, val in filters.items():
        if val is None:
            query = query.where(getattr(model, field).is_(None))
        else:
            query = query.where(getattr(model, field) == val)
    rows = db.exec(query).all()
    if not rows:
        return 0
    return max(getattr(row, "sort_order", 0) or 0 for row in rows) + 1


def load_session_narrative_blocks(db: Session, campaign_id: int, session_id: int) -> Dict[str, List[Any]]:
    scenes = db.exec(
        select(Scene)
        .where(Scene.campaign_id == campaign_id, Scene.session_id == session_id)
        .order_by(Scene.sort_order, Scene.id)
    ).all()
    encounters = db.exec(
        select(Encounter)
        .where(Encounter.campaign_id == campaign_id, Encounter.session_id == session_id)
        .order_by(Encounter.sort_order, Encounter.id)
    ).all()
    objectives = db.exec(
        select(Objective)
        .where(Objective.campaign_id == campaign_id, Objective.session_id == session_id)
        .order_by(Objective.sort_order, Objective.id)
    ).all()
    return {"scenes": list(scenes), "encounters": list(encounters), "objectives": list(objectives)}


def _hydrate_block_links(db: Session, campaign_id: int, block_kind: str, block) -> Dict[str, List[Any]]:
    config = BLOCK_LINK_CONFIG[block_kind]
    result: Dict[str, List[Any]] = {}
    for kind, (link_model, owner_field, related_field) in config.items():
        ids = related_ids_from_links(db, link_model, owner_field, block.id, related_field)
        result[kind] = load_campaign_entities_by_ids(
            db, ENTITY_MODELS[kind], campaign_id, [str(i) for i in ids]
        )
    return result


def build_block_card(
    db: Session,
    campaign_id: int,
    block_kind: str,
    block,
    *,
    primary_location: Optional[Location] = None,
) -> Dict[str, Any]:
    links = _hydrate_block_links(db, campaign_id, block_kind, block)
    location = primary_location
    if block_kind == "scenes" and not location and getattr(block, "location_id", None):
        location = db.get(Location, block.location_id)

    open_clues: List[str] = []
    for thread in links.get("threads", []):
        open_clues.extend(lines_to_clue_list(getattr(thread, "open_clues", None)))

    return {
        "block": block,
        "kind": block_kind,
        "links": links,
        "primary_location": location,
        "open_clues": open_clues,
    }


def build_session_builder_cards(
    db: Session,
    campaign_id: int,
    session_id: int,
    *,
    active_scene_id: Optional[int] = None,
) -> Dict[str, Any]:
    blocks = load_session_narrative_blocks(db, campaign_id, session_id)
    scene_cards = [build_block_card(db, campaign_id, "scenes", scene) for scene in blocks["scenes"]]
    for card in scene_cards:
        card["is_active"] = bool(active_scene_id and card["block"].id == active_scene_id)

    encounter_cards = []
    for enc in blocks["encounters"]:
        card = build_block_card(db, campaign_id, "encounters", enc)
        card["parent_scene"] = db.get(Scene, enc.scene_id) if enc.scene_id else None
        encounter_cards.append(card)

    objective_cards = []
    for obj in blocks["objectives"]:
        card = build_block_card(db, campaign_id, "objectives", obj)
        card["parent_scene"] = db.get(Scene, obj.scene_id) if obj.scene_id else None
        card["parent_encounter"] = db.get(Encounter, obj.encounter_id) if obj.encounter_id else None
        objective_cards.append(card)

    active_scene = db.get(Scene, active_scene_id) if active_scene_id else None
    return {
        "scenes": scene_cards,
        "encounters": encounter_cards,
        "objectives": objective_cards,
        "active_scene": active_scene,
        "active_scene_card": build_block_card(db, campaign_id, "scenes", active_scene) if active_scene else None,
    }


def replace_block_links(
    db: Session,
    campaign_id: int,
    block_kind: str,
    block_id: int,
    *,
    npc_ids: Optional[List[str]] = None,
    pc_ids: Optional[List[str]] = None,
    location_ids: Optional[List[str]] = None,
    faction_ids: Optional[List[str]] = None,
    item_ids: Optional[List[str]] = None,
    thread_ids: Optional[List[str]] = None,
    session_id: Optional[int] = None,
) -> None:
    config = BLOCK_LINK_CONFIG[block_kind]
    owner_field = {"scenes": "scene_id", "encounters": "encounter_id", "objectives": "objective_id"}[block_kind]
    mapping = {
        "npcs": (npc_ids, NPC),
        "pcs": (pc_ids, PlayerCharacterNote),
        "locations": (location_ids, Location),
        "factions": (faction_ids, Faction),
        "items": (item_ids, Item),
        "threads": (thread_ids, PlotThread),
    }
    for kind, (ids, model) in mapping.items():
        if ids is None:
            continue
        link_model, _, related_field = config[kind]
        entities = load_campaign_entities_by_ids(db, model, campaign_id, ids)
        replace_many_to_many_links(
            db,
            block_id,
            link_model,
            owner_field,
            related_field,
            entities,
            campaign_id=campaign_id,
            owner_kind=block_kind,
            related_kind=kind,
            session_id=session_id,
        )


def create_scene(
    db: Session,
    campaign_id: int,
    *,
    session_id: Optional[int],
    title: str,
    narrative_goal: str = "",
    summary: str = "",
    status: str = "planned",
    location_id: Optional[int] = None,
    notes: str = "",
    gm_only_notes: str = "",
    npc_ids: Optional[List[str]] = None,
    pc_ids: Optional[List[str]] = None,
    location_ids: Optional[List[str]] = None,
    faction_ids: Optional[List[str]] = None,
    item_ids: Optional[List[str]] = None,
    thread_ids: Optional[List[str]] = None,
) -> Scene:
    scene = Scene(
        campaign_id=campaign_id,
        session_id=session_id,
        title=title.strip(),
        narrative_goal=narrative_goal.strip() or None,
        summary=summary.strip() or None,
        status=_normalize_enum(status, SCENE_STATUSES, "planned"),
        location_id=location_id,
        notes=notes.strip() or None,
        gm_only_notes=gm_only_notes.strip() or None,
        sort_order=_next_sort_order(db, Scene, campaign_id, session_id),
    )
    db.add(scene)
    db.flush()
    replace_block_links(
        db,
        campaign_id,
        "scenes",
        scene.id,
        npc_ids=npc_ids,
        pc_ids=pc_ids,
        location_ids=location_ids,
        faction_ids=faction_ids,
        item_ids=item_ids,
        thread_ids=thread_ids,
        session_id=session_id,
    )
    return scene


def create_encounter(
    db: Session,
    campaign_id: int,
    *,
    session_id: Optional[int],
    scene_id: Optional[int] = None,
    title: str,
    encounter_type: str = "other",
    objective: str = "",
    stakes: str = "",
    setup: str = "",
    outcome: str = "",
    status: str = "planned",
    notes: str = "",
    gm_only_notes: str = "",
    npc_ids: Optional[List[str]] = None,
    pc_ids: Optional[List[str]] = None,
    location_ids: Optional[List[str]] = None,
    faction_ids: Optional[List[str]] = None,
    item_ids: Optional[List[str]] = None,
    thread_ids: Optional[List[str]] = None,
) -> Encounter:
    encounter = Encounter(
        campaign_id=campaign_id,
        session_id=session_id,
        scene_id=scene_id,
        title=title.strip(),
        encounter_type=_normalize_enum(encounter_type, ENCOUNTER_TYPES, "other"),
        objective=objective.strip() or None,
        stakes=stakes.strip() or None,
        setup=setup.strip() or None,
        outcome=outcome.strip() or None,
        status=_normalize_enum(status, ENCOUNTER_STATUSES, "planned"),
        notes=notes.strip() or None,
        gm_only_notes=gm_only_notes.strip() or None,
        sort_order=_next_sort_order(db, Encounter, campaign_id, session_id, scene_id=scene_id),
    )
    db.add(encounter)
    db.flush()
    replace_block_links(
        db,
        campaign_id,
        "encounters",
        encounter.id,
        npc_ids=npc_ids,
        pc_ids=pc_ids,
        location_ids=location_ids,
        faction_ids=faction_ids,
        item_ids=item_ids,
        thread_ids=thread_ids,
        session_id=session_id,
    )
    return encounter


def create_objective(
    db: Session,
    campaign_id: int,
    *,
    session_id: Optional[int],
    scene_id: Optional[int] = None,
    encounter_id: Optional[int] = None,
    title: str,
    description: str = "",
    objective_type: str = "other",
    status: str = "open",
    priority: str = "normal",
    notes: str = "",
    gm_only_notes: str = "",
    npc_ids: Optional[List[str]] = None,
    pc_ids: Optional[List[str]] = None,
    location_ids: Optional[List[str]] = None,
    faction_ids: Optional[List[str]] = None,
    item_ids: Optional[List[str]] = None,
    thread_ids: Optional[List[str]] = None,
) -> Objective:
    objective = Objective(
        campaign_id=campaign_id,
        session_id=session_id,
        scene_id=scene_id,
        encounter_id=encounter_id,
        title=title.strip(),
        description=description.strip() or None,
        objective_type=_normalize_enum(objective_type, OBJECTIVE_TYPES, "other"),
        status=_normalize_enum(status, OBJECTIVE_STATUSES, "open"),
        priority=_normalize_enum(priority, OBJECTIVE_PRIORITIES, "normal"),
        notes=notes.strip() or None,
        gm_only_notes=gm_only_notes.strip() or None,
        sort_order=_next_sort_order(
            db, Objective, campaign_id, session_id, scene_id=scene_id, encounter_id=encounter_id
        ),
    )
    db.add(objective)
    db.flush()
    replace_block_links(
        db,
        campaign_id,
        "objectives",
        objective.id,
        npc_ids=npc_ids,
        pc_ids=pc_ids,
        location_ids=location_ids,
        faction_ids=faction_ids,
        item_ids=item_ids,
        thread_ids=thread_ids,
        session_id=session_id,
    )
    return objective


def set_active_scene(db: Session, campaign_id: int, session_id: int, scene_id: int) -> Scene:
    scene = db.get(Scene, scene_id)
    if not scene or scene.campaign_id != campaign_id or scene.session_id != session_id:
        raise ValueError("Scene not found for this session")
    session = db.get(SessionModel, session_id)
    if not session or session.campaign_id != campaign_id:
        raise ValueError("Session not found")

    for other in db.exec(
        select(Scene).where(Scene.campaign_id == campaign_id, Scene.session_id == session_id, Scene.status == "active")
    ).all():
        if other.id != scene_id:
            other.status = "planned"
            other.updated_at = utc_now()
            db.add(other)

    scene.status = "active"
    scene.updated_at = utc_now()
    session.active_scene_id = scene_id
    session.updated_at = utc_now()
    db.add(scene)
    db.add(session)
    return scene


def clear_active_scene(db: Session, campaign_id: int, session_id: int) -> None:
    session = db.get(SessionModel, session_id)
    if not session or session.campaign_id != campaign_id:
        return
    if session.active_scene_id:
        scene = db.get(Scene, session.active_scene_id)
        if scene and scene.status == "active":
            scene.status = "planned"
            scene.updated_at = utc_now()
            db.add(scene)
    session.active_scene_id = None
    session.updated_at = utc_now()
    db.add(session)


def reorder_block(db: Session, model: Type, block_id: int, direction: str) -> None:
    block = db.get(model, block_id)
    if not block:
        return
    siblings = db.exec(
        select(model)
        .where(
            model.campaign_id == block.campaign_id,
            model.session_id == block.session_id,
        )
        .order_by(model.sort_order, model.id)
    ).all()
    if getattr(block, "scene_id", None) is not None:
        siblings = [s for s in siblings if getattr(s, "scene_id", None) == block.scene_id]
    index = next((i for i, s in enumerate(siblings) if s.id == block_id), None)
    if index is None:
        return
    swap_index = index - 1 if direction == "up" else index + 1
    if swap_index < 0 or swap_index >= len(siblings):
        return
    other = siblings[swap_index]
    block.sort_order, other.sort_order = other.sort_order, block.sort_order
    block.updated_at = utc_now()
    other.updated_at = utc_now()
    db.add(block)
    db.add(other)


def collect_scene_feed_entities(db: Session, campaign_id: int, scene: Scene) -> Dict[str, List[Any]]:
    links = _hydrate_block_links(db, campaign_id, "scenes", scene)
    npcs = list(links.get("npcs", []))
    locations = list(links.get("locations", []))
    if scene.location_id:
        primary = db.get(Location, scene.location_id)
        if primary and primary not in locations:
            locations.insert(0, primary)
    return {
        "npcs": npcs,
        "locations": locations,
        "factions": links.get("factions", []),
        "items": links.get("items", []),
        "threads": links.get("threads", []),
        "pcs": links.get("pcs", []),
    }


def find_blocks_for_entity(
    db: Session,
    campaign_id: int,
    entity_kind: str,
    entity_id: int,
) -> Dict[str, List[Dict[str, Any]]]:
    """Inverse lookup: scenes/encounters/objectives linked to an entity."""
    if entity_kind not in ENTITY_MODELS and entity_kind != "locations":
        return {"scenes": [], "encounters": [], "objectives": []}

    result: Dict[str, List[Dict[str, Any]]] = {"scenes": [], "encounters": [], "objectives": []}
    seen_scenes: set = set()
    if entity_kind == "locations":
        for scene in db.exec(select(Scene).where(Scene.campaign_id == campaign_id, Scene.location_id == entity_id)).all():
            if scene.id not in seen_scenes:
                seen_scenes.add(scene.id)
                result["scenes"].append(
                    {"block": scene, "session": db.get(SessionModel, scene.session_id) if scene.session_id else None}
                )

    if entity_kind in ENTITY_MODELS:
        for block_kind in ("scenes", "encounters", "objectives"):
            if entity_kind not in BLOCK_LINK_CONFIG[block_kind]:
                continue
            link_model, owner_field, related_field = BLOCK_LINK_CONFIG[block_kind][entity_kind]
            rows = db.exec(select(link_model).where(getattr(link_model, related_field) == entity_id)).all()
            model = {"scenes": Scene, "encounters": Encounter, "objectives": Objective}[block_kind]
            for row in rows:
                block = db.get(model, getattr(row, owner_field))
                if block and block.campaign_id == campaign_id:
                    key = block.id
                    if block_kind == "scenes" and key in seen_scenes:
                        continue
                    if block_kind == "scenes":
                        seen_scenes.add(key)
                    result[block_kind].append(
                        {
                            "block": block,
                            "session": db.get(SessionModel, block.session_id) if block.session_id else None,
                        }
                    )
    return result


def parse_ai_narrative_suggestions(prep_text: str) -> Dict[str, List[Dict[str, str]]]:
    """Heuristic parse of AI prep text into suggested narrative blocks."""
    suggestions: Dict[str, List[Dict[str, str]]] = {
        "scenes": [],
        "encounters": [],
        "objectives": [],
    }
    if not prep_text:
        return suggestions

    section = None
    for line in prep_text.splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        if lower.startswith("opening scene") or lower.startswith("## scene") or lower == "scenes:":
            section = "scenes"
            continue
        if "encounter" in lower and (lower.endswith(":") or lower.startswith("##")):
            section = "encounters"
            continue
        if "objective" in lower and (lower.endswith(":") or lower.startswith("##")):
            section = "objectives"
            continue
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            stripped = stripped[2:].strip()
        if not stripped:
            continue
        if section == "scenes":
            suggestions["scenes"].append({"title": stripped[:120], "narrative_goal": stripped})
        elif section == "encounters":
            suggestions["encounters"].append({"title": stripped[:120], "stakes": stripped})
        elif section == "objectives":
            suggestions["objectives"].append({"title": stripped[:120], "description": stripped})
    return suggestions
