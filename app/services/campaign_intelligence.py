"""Campaign intelligence: history, dormancy, briefing, workspace signals."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple, Type

from fastapi import Request
from sqlmodel import Session, select

from app.models import Campaign, Creature, Faction, Item, Location, NPC, PlotThread, SessionModel
from app.services.ai_workflow import session_has_analysis
from app.services.entity_health import ENTITY_EDIT_URLS
from app.services.entity_session_presence import EntitySessionPresenceIndex, SESSION_LINK_CONFIG
from app.services.mission_control_ui import resolve_persisted_session

# Sessions since last appearance before flagged dormant/stale
DEFAULT_INTELLIGENCE_GAP = 2

STALE_ENTITY_SECTIONS: Dict[str, Tuple[Type, str, str]] = {
    "npcs": (NPC, "npc", "name"),
    "locations": (Location, "location", "name"),
    "factions": (Faction, "faction", "name"),
    "items": (Item, "item", "name"),
    "creatures": (Creature, "creature", "name"),
}


def get_intelligence_gap() -> int:
    raw = os.environ.get("INTELLIGENCE_GAP", "").strip()
    if raw.isdigit():
        return max(1, int(raw))
    return DEFAULT_INTELLIGENCE_GAP


def is_active_thread_status(status: Optional[str]) -> bool:
    text = (status or "").strip().lower()
    if not text:
        return True
    inactive = {"resolved", "closed", "complete", "completed", "done", "archived", "inactive"}
    return text not in inactive


def _campaign_session_index(db: Session, campaign_id: int) -> EntitySessionPresenceIndex:
    return EntitySessionPresenceIndex(db, campaign_id)


def _current_session_rank(index: EntitySessionPresenceIndex, current: Optional[SessionModel]) -> int:
    if not current or not current.id:
        return max(index.rank.values()) if index.rank else -1
    return index.rank.get(current.id, -1)


def _entity_history_from_index(
    index: EntitySessionPresenceIndex,
    section_key: str,
    entity_id: int,
) -> Optional[Dict[str, Any]]:
    session_ids = index._entity_sessions.get(section_key, {}).get(entity_id) or []
    if not session_ids:
        return None
    ordered_ids = sorted(session_ids, key=lambda sid: index.rank.get(sid, 9999))
    sessions = [index.sessions_by_id[sid] for sid in ordered_ids if sid in index.sessions_by_id]
    if not sessions:
        return None
    return {
        "sessions": sessions,
        "first": sessions[0],
        "last": sessions[-1],
        "session_count": len(sessions),
    }


def get_entity_session_history(
    db: Session,
    campaign_id: int,
    section_key: str,
    entity_id: int,
) -> Optional[Dict[str, Any]]:
    index = _campaign_session_index(db, campaign_id)
    return _entity_history_from_index(index, section_key, entity_id)


def _build_entity_histories(
    index: EntitySessionPresenceIndex,
    section_key: str,
    entities: List[Any],
) -> Dict[int, Dict[str, Any]]:
    histories: Dict[int, Dict[str, Any]] = {}
    for entity in entities:
        entity_id = getattr(entity, "id", None)
        if not entity_id:
            continue
        history = _entity_history_from_index(index, section_key, entity_id)
        if history:
            histories[entity_id] = history
    return histories


def find_dormant_threads(
    db: Session,
    campaign_id: int,
    *,
    current_session: Optional[SessionModel] = None,
    gap: int = DEFAULT_INTELLIGENCE_GAP,
    limit: int = 8,
) -> List[Dict[str, Any]]:
    index = _campaign_session_index(db, campaign_id)
    current_rank = _current_session_rank(index, current_session)
    threads = db.exec(select(PlotThread).where(PlotThread.campaign_id == campaign_id)).all()
    rows: List[Dict[str, Any]] = []

    for thread in threads:
        if not is_active_thread_status(thread.status):
            continue
        presence = index.presence("threads", thread.id)
        if not presence:
            rows.append(
                {
                    "thread": thread,
                    "reason": "never_linked",
                    "last_session": None,
                    "sessions_behind": None,
                }
            )
            continue
        last_rank = index.rank.get(presence["last"].id, -1)
        behind = current_rank - last_rank
        if behind >= gap:
            rows.append(
                {
                    "thread": thread,
                    "reason": "not_recent",
                    "last_session": presence["last"],
                    "sessions_behind": behind,
                }
            )

    rows.sort(key=lambda r: (r["sessions_behind"] is None, -(r["sessions_behind"] or 0), (r["thread"].title or "").lower()))
    return rows[:limit]


def find_stale_entities_for_section(
    db: Session,
    campaign_id: int,
    section_key: str,
    *,
    current_session: Optional[SessionModel] = None,
    gap: Optional[int] = None,
    limit: int = 8,
) -> List[Dict[str, Any]]:
    config = STALE_ENTITY_SECTIONS.get(section_key)
    if not config:
        return []

    model, entity_key, name_attr = config
    resolved_gap = gap if gap is not None else get_intelligence_gap()
    index = _campaign_session_index(db, campaign_id)
    current_rank = _current_session_rank(index, current_session)
    entities = db.exec(select(model).where(model.campaign_id == campaign_id)).all()
    rows: List[Dict[str, Any]] = []

    for entity in entities:
        if not entity.id:
            continue
        presence = index.presence(section_key, entity.id)
        if not presence:
            continue
        last_rank = index.rank.get(presence["last"].id, -1)
        behind = current_rank - last_rank
        if behind >= resolved_gap:
            name = getattr(entity, name_attr, "") or f"#{entity.id}"
            url_template = ENTITY_EDIT_URLS.get(section_key)
            rows.append(
                {
                    entity_key: entity,
                    "entity": entity,
                    "section_key": section_key,
                    "name": name,
                    "edit_url": url_template.format(campaign_id=campaign_id, entity_id=entity.id)
                    if url_template
                    else None,
                    "last_session": presence["last"],
                    "sessions_behind": behind,
                }
            )

    rows.sort(key=lambda r: (-r["sessions_behind"], (r["name"] or "").lower()))
    return rows[:limit]


def find_stale_npcs(
    db: Session,
    campaign_id: int,
    *,
    current_session: Optional[SessionModel] = None,
    gap: Optional[int] = None,
    limit: int = 8,
) -> List[Dict[str, Any]]:
    return find_stale_entities_for_section(
        db,
        campaign_id,
        "npcs",
        current_session=current_session,
        gap=gap,
        limit=limit,
    )


def find_stale_locations(
    db: Session,
    campaign_id: int,
    *,
    current_session: Optional[SessionModel] = None,
    gap: Optional[int] = None,
    limit: int = 8,
) -> List[Dict[str, Any]]:
    return find_stale_entities_for_section(
        db,
        campaign_id,
        "locations",
        current_session=current_session,
        gap=gap,
        limit=limit,
    )


def find_stale_factions(
    db: Session,
    campaign_id: int,
    *,
    current_session: Optional[SessionModel] = None,
    gap: Optional[int] = None,
    limit: int = 8,
) -> List[Dict[str, Any]]:
    return find_stale_entities_for_section(
        db,
        campaign_id,
        "factions",
        current_session=current_session,
        gap=gap,
        limit=limit,
    )


def find_stale_items(
    db: Session,
    campaign_id: int,
    *,
    current_session: Optional[SessionModel] = None,
    gap: Optional[int] = None,
    limit: int = 8,
) -> List[Dict[str, Any]]:
    return find_stale_entities_for_section(
        db,
        campaign_id,
        "items",
        current_session=current_session,
        gap=gap,
        limit=limit,
    )


def find_stale_creatures(
    db: Session,
    campaign_id: int,
    *,
    current_session: Optional[SessionModel] = None,
    gap: Optional[int] = None,
    limit: int = 8,
) -> List[Dict[str, Any]]:
    return find_stale_entities_for_section(
        db,
        campaign_id,
        "creatures",
        current_session=current_session,
        gap=gap,
        limit=limit,
    )


def build_intelligence_signals(
    db: Session,
    campaign_id: int,
    *,
    current_session: Optional[SessionModel] = None,
    gap: Optional[int] = None,
) -> Dict[str, Any]:
    resolved_gap = gap if gap is not None else get_intelligence_gap()
    dormant = find_dormant_threads(db, campaign_id, current_session=current_session, gap=resolved_gap)
    stale_npcs = find_stale_npcs(db, campaign_id, current_session=current_session, gap=resolved_gap)
    stale_locations = find_stale_locations(db, campaign_id, current_session=current_session, gap=resolved_gap)
    stale_factions = find_stale_factions(db, campaign_id, current_session=current_session, gap=resolved_gap)
    stale_items = find_stale_items(db, campaign_id, current_session=current_session, gap=resolved_gap)
    stale_creatures = find_stale_creatures(db, campaign_id, current_session=current_session, gap=resolved_gap)
    stale_count = len(stale_npcs) + len(stale_locations) + len(stale_factions) + len(stale_items) + len(stale_creatures)
    return {
        "dormant_threads": dormant,
        "stale_npcs": stale_npcs,
        "stale_locations": stale_locations,
        "stale_factions": stale_factions,
        "stale_items": stale_items,
        "stale_creatures": stale_creatures,
        "dormant_count": len(dormant),
        "stale_count": stale_count,
        "gap": resolved_gap,
    }


def _presence_workspace_flag(
    index: EntitySessionPresenceIndex,
    section_key: str,
    entity_id: int,
    session_id: int,
) -> Optional[str]:
    presence = index.presence(section_key, entity_id)
    if not presence:
        return None
    if presence["session_count"] == 1 and presence["first"].id == session_id:
        return "new"
    if presence["last"].id == session_id and presence["session_count"] > 1:
        if presence["first"].id != session_id:
            return "returning"
    return None


def _entity_workspace_flag(index: EntitySessionPresenceIndex, section_key: str, entity_id: int, session_id: int) -> Optional[str]:
    return _presence_workspace_flag(index, section_key, entity_id, session_id)


def _npc_workspace_flag(index: EntitySessionPresenceIndex, npc: NPC, session_id: int) -> Optional[str]:
    return _entity_workspace_flag(index, "npcs", npc.id, session_id)


def _location_workspace_flag(index: EntitySessionPresenceIndex, location, session_id: int) -> Optional[str]:
    return _entity_workspace_flag(index, "locations", location.id, session_id)


def _faction_workspace_flag(index: EntitySessionPresenceIndex, faction, session_id: int) -> Optional[str]:
    return _entity_workspace_flag(index, "factions", faction.id, session_id)


def _item_workspace_flag(index: EntitySessionPresenceIndex, item, session_id: int) -> Optional[str]:
    return _entity_workspace_flag(index, "items", item.id, session_id)


def _thread_workspace_flag(index: EntitySessionPresenceIndex, thread: PlotThread, session_id: int, gap: int) -> Optional[str]:
    if not is_active_thread_status(thread.status):
        return None
    presence = index.presence("threads", thread.id)
    current_rank = index.rank.get(session_id, -1)
    if not presence:
        return "unlinked"
    last_rank = index.rank.get(presence["last"].id, -1)
    if presence["last"].id != session_id and current_rank - last_rank >= gap:
        return "dormant"
    if presence["last"].id == session_id and presence["session_count"] == 1:
        return "new"
    return None


def build_workspace_intelligence(
    db: Session,
    campaign_id: int,
    session_model: SessionModel,
    *,
    linked_npcs: List[NPC],
    linked_locations: List,
    linked_factions: List,
    linked_items: List,
    linked_threads: List[PlotThread],
    gap: Optional[int] = None,
    active_scene=None,
    active_scene_card: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    resolved_gap = gap if gap is not None else get_intelligence_gap()
    index = _campaign_session_index(db, campaign_id)
    sid = session_model.id

    npc_flags = {npc.id: _npc_workspace_flag(index, npc, sid) for npc in linked_npcs}
    location_flags = {loc.id: _location_workspace_flag(index, loc, sid) for loc in linked_locations}
    faction_flags = {f.id: _faction_workspace_flag(index, f, sid) for f in linked_factions}
    item_flags = {i.id: _item_workspace_flag(index, i, sid) for i in linked_items}
    thread_flags = {t.id: _thread_workspace_flag(index, t, sid, resolved_gap) for t in linked_threads}

    npc_histories = _build_entity_histories(index, "npcs", linked_npcs)
    location_histories = _build_entity_histories(index, "locations", linked_locations)
    faction_histories = _build_entity_histories(index, "factions", linked_factions)
    item_histories = _build_entity_histories(index, "items", linked_items)
    thread_histories = _build_entity_histories(index, "threads", linked_threads)

    from app.services.world_state import (
        lines_to_clue_list,
        mystery_status_label,
        world_status_badge_class,
        world_status_label,
    )

    thread_open_clues = {
        thread.id: lines_to_clue_list(thread.open_clues)
        for thread in linked_threads
        if thread.id and lines_to_clue_list(thread.open_clues)
    }

    has_notes = bool((session_model.notes or "").strip())
    has_analysis = session_has_analysis(session_model)
    has_prep = bool((session_model.next_session_prep or "").strip())

    prep_gap = None
    if has_notes and not has_analysis:
        prep_gap = "needs_analysis"
    elif has_analysis and not has_prep:
        prep_gap = "needs_prep"

    return {
        "npc_flags": npc_flags,
        "location_flags": location_flags,
        "faction_flags": faction_flags,
        "item_flags": item_flags,
        "thread_flags": thread_flags,
        "npc_histories": npc_histories,
        "location_histories": location_histories,
        "faction_histories": faction_histories,
        "item_histories": item_histories,
        "thread_histories": thread_histories,
        "thread_open_clues": thread_open_clues,
        "world_status_label": world_status_label,
        "world_status_badge_class": world_status_badge_class,
        "mystery_status_label": mystery_status_label,
        "active_scene": active_scene,
        "active_scene_card": active_scene_card,
        "scene_open_clues": (active_scene_card or {}).get("open_clues", []),
        "prep_gap": prep_gap,
        "has_notes": has_notes,
        "has_analysis": has_analysis,
        "has_prep": has_prep,
        "gap": resolved_gap,
    }


def build_campaign_briefing(
    db: Session,
    campaign_id: int,
    *,
    request: Optional[Request] = None,
    dashboard_summary: Optional[Dict[str, Any]] = None,
    gap: Optional[int] = None,
) -> Dict[str, Any]:
    from app.deps import sort_sessions_chronologically

    sessions = db.exec(
        select(SessionModel).where(SessionModel.campaign_id == campaign_id)
    ).all()
    sorted_sessions = sort_sessions_chronologically(sessions)
    current = resolve_persisted_session(db, request, campaign_id)
    if not current and sorted_sessions:
        current = sorted_sessions[-1]

    signals = build_intelligence_signals(db, campaign_id, current_session=current, gap=gap)
    index = _campaign_session_index(db, campaign_id)

    returning_npcs: List[Dict[str, Any]] = []
    if current and current.id:
        for npc in db.exec(select(NPC).where(NPC.campaign_id == campaign_id)).all():
            flag = _npc_workspace_flag(index, npc, current.id)
            if flag == "returning":
                returning_npcs.append({"npc": npc, "flag": flag})

    briefing_threads: List[Dict[str, Any]] = []
    if dashboard_summary:
        for thread in dashboard_summary.get("active_threads") or []:
            presence = index.presence("threads", thread.id)
            briefing_threads.append({"thread": thread, "presence": presence})

    return {
        "current_session": current,
        "sorted_sessions": sorted_sessions,
        "signals": signals,
        "returning_npcs": returning_npcs[:8],
        "briefing_threads": briefing_threads,
        "dashboard_summary": dashboard_summary,
        "last_analyzed": dashboard_summary.get("last_analyzed") if dashboard_summary else None,
        "next_session": dashboard_summary.get("next_session") if dashboard_summary else None,
    }


def load_campaign_briefing_data(
    db: Session,
    campaign_id: int,
    *,
    request: Optional[Request] = None,
) -> Dict[str, Any]:
    from app.services.briefing_narrative import build_briefing_narrative_context
    from app.services.campaign_dashboard import build_campaign_dashboard_summary
    from app.services.entity_health import prepare_entity_lists

    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        return {}

    _health_service, entity_context = prepare_entity_lists(db, campaign_id)
    entity_lists = {
        "npcs": entity_context["npcs"],
        "locations": entity_context["locations"],
        "factions": entity_context["factions"],
        "items": entity_context["items"],
        "threads": entity_context["threads"],
        "pcs": entity_context["pc_notes"],
    }
    dashboard_summary = build_campaign_dashboard_summary(
        db,
        campaign_id,
        request=request,
        health_maps=entity_context["health_maps"],
        entity_lists=entity_lists,
    )
    briefing = build_campaign_briefing(
        db,
        campaign_id,
        request=request,
        dashboard_summary=dashboard_summary,
    )
    briefing["narrative"] = build_briefing_narrative_context(campaign, briefing)
    from app.services.briefing_sections import build_campaign_briefing_sections

    briefing["sections"] = build_campaign_briefing_sections(
        db,
        campaign_id,
        sorted_sessions=briefing.get("sorted_sessions") or [],
        entity_lists=entity_lists,
        dashboard_summary=dashboard_summary,
        signals=briefing.get("signals") or {},
        current_session=briefing.get("current_session"),
        completeness_overview=entity_context.get("completeness_overview"),
    )
    return briefing
