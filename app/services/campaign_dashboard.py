"""Compact Lore Board (World) dashboard summary widgets."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import Request
from sqlmodel import Session, select

from app.models import NPC, PlotThread, SessionModel
from app.services.analysis import load_ai_run_metadata
from app.services.campaign_intelligence import (
    build_intelligence_signals,
    is_active_thread_status,
)
from app.services.entity_health import build_needs_attention_list
from app.services.mission_control_ui import resolve_persisted_session


def _find_next_session(sorted_sessions: List[SessionModel], current: Optional[SessionModel]) -> Optional[SessionModel]:
    if not sorted_sessions:
        return None
    if not current:
        for session in sorted_sessions:
            if not (session.notes or "").strip():
                return session
        return sorted_sessions[-1]
    try:
        idx = next(i for i, s in enumerate(sorted_sessions) if s.id == current.id)
    except StopIteration:
        return sorted_sessions[-1] if sorted_sessions else None
    for session in sorted_sessions[idx + 1 :]:
        if not (session.notes or "").strip():
            return session
    return None


def _last_analyzed_session(sessions: List[SessionModel]) -> Optional[Dict[str, Any]]:
    candidates: List[tuple] = []
    for session in sessions:
        metadata = load_ai_run_metadata(session)
        if not metadata:
            continue
        generated = metadata.get("generated_at") or ""
        candidates.append((generated, session, metadata))
    if not candidates:
        return None
    candidates.sort(key=lambda row: row[0], reverse=True)
    _, session, metadata = candidates[0]
    return {"session": session, "metadata": metadata}


def build_campaign_dashboard_summary(
    db: Session,
    campaign_id: int,
    *,
    request: Optional[Request] = None,
    health_maps: Optional[Dict[str, Dict[int, Dict[str, Any]]]] = None,
    entity_lists: Optional[Dict[str, List[Any]]] = None,
    needs_attention_limit: int = 8,
) -> Dict[str, Any]:
    from app.deps import sort_sessions_chronologically

    sessions = db.exec(
        select(SessionModel).where(SessionModel.campaign_id == campaign_id)
    ).all()
    sorted_sessions = sort_sessions_chronologically(sessions)

    current = resolve_persisted_session(db, request, campaign_id)
    if not current and sorted_sessions:
        current = sorted_sessions[-1]

    next_session = _find_next_session(sorted_sessions, current)

    threads = db.exec(select(PlotThread).where(PlotThread.campaign_id == campaign_id)).all()
    active_threads = [t for t in threads if is_active_thread_status(t.status)]
    active_threads.sort(key=lambda t: (t.title or "").lower())

    intelligence = build_intelligence_signals(db, campaign_id, current_session=current)

    npcs = db.exec(select(NPC).where(NPC.campaign_id == campaign_id)).all()
    session_titles = {s.id: s.title for s in sessions if s.id}
    recent_npcs = sorted(
        npcs,
        key=lambda n: (
            n.last_seen_session_id or 0,
            getattr(n, "updated_at", None) or "",
        ),
        reverse=True,
    )[:5]
    recent_npc_rows = [
        {
            "npc": npc,
            "last_seen_title": session_titles.get(npc.last_seen_session_id),
            "last_seen_id": npc.last_seen_session_id,
        }
        for npc in recent_npcs
        if npc.last_seen_session_id or (npc.updated_at and npc.name)
    ]

    needs_attention: List[Dict[str, Any]] = []
    if health_maps and entity_lists:
        needs_attention = build_needs_attention_list(
            campaign_id,
            health_maps,
            entity_lists,
            limit=needs_attention_limit,
        )

    last_analyzed = _last_analyzed_session(sessions)

    from app.models import Faction, Location
    from app.services.world_state_briefing import build_world_state_briefing

    factions = db.exec(select(Faction).where(Faction.campaign_id == campaign_id)).all()
    locations = db.exec(select(Location).where(Location.campaign_id == campaign_id)).all()
    world_state = build_world_state_briefing(threads, factions, locations)

    return {
        "current_session": current,
        "next_session": next_session,
        "active_threads": active_threads[:6],
        "recent_npcs": recent_npc_rows[:5],
        "needs_attention": needs_attention,
        "last_analyzed": last_analyzed,
        "session_count": len(sessions),
        "intelligence": intelligence,
        "world_state": world_state,
    }
