"""Deterministic Campaign Briefing section builders (Phase 1)."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set

from sqlmodel import Session, select

from app.models import NPC, PlotThread, SessionModel
from app.services.ai_workflow import session_has_analysis
from app.services.campaign_intelligence import (
    find_dormant_threads,
    get_intelligence_gap,
    is_active_thread_status,
)
from app.services.world_state import world_status_label
from app.services.world_state_briefing import build_world_state_briefing
from app.services.entity_health import build_campaign_completeness_overview
from app.services.entity_session_presence import EntitySessionPresenceIndex

QUESTION_LINE = re.compile(r".*\?\s*$")
RECENT_SESSION_LIMIT = 3
DEVELOPMENT_PREVIEW = 220
QUESTION_PREVIEW = 200


def _preview(text: Optional[str], limit: int = DEVELOPMENT_PREVIEW) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    raw = re.sub(r"\s+", " ", raw)
    if len(raw) <= limit:
        return raw
    return raw[: limit - 1].rstrip() + "…"


def _session_recap_text(session: SessionModel) -> str:
    for field in (session.player_recap, session.recap, session.analysis, session.notes):
        preview = _preview(field)
        if preview:
            return preview
    return ""


def _last_chronological_session(sorted_sessions: List[SessionModel]) -> Optional[SessionModel]:
    return sorted_sessions[-1] if sorted_sessions else None


def build_last_session_section(sorted_sessions: List[SessionModel]) -> Optional[Dict[str, Any]]:
    session = _last_chronological_session(sorted_sessions)
    if not session:
        return None
    recap = _preview(session.player_recap) or _preview(session.recap) or _preview(session.analysis)
    return {
        "session": session,
        "recap_preview": recap,
        "has_analysis": session_has_analysis(session),
    }


def _thread_importance_rank(thread: PlotThread) -> int:
    importance = (thread.importance or "").strip().lower()
    if importance in {"critical", "high", "urgent"}:
        return 0
    if importance in {"medium", "moderate"}:
        return 1
    status = (thread.status or "").strip().lower()
    if status in {"active", "open", "in progress", "ongoing"} or not status:
        return 2
    return 3


def build_active_threads_section(
    db: Session,
    campaign_id: int,
    threads: List[PlotThread],
    index: EntitySessionPresenceIndex,
    *,
    limit: int = 12,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for thread in threads:
        if not is_active_thread_status(thread.status):
            continue
        presence = index.presence("threads", thread.id)
        rows.append(
            {
                "thread": thread,
                "presence": presence,
                "last_session": presence["last"] if presence else None,
                "session_count": presence["session_count"] if presence else 0,
                "importance_rank": _thread_importance_rank(thread),
            }
        )
    rows.sort(
        key=lambda row: (
            row["importance_rank"],
            -(row["session_count"] or 0),
            (row["thread"].title or "").lower(),
        )
    )
    return rows[:limit]


def build_important_npcs_section(
    db: Session,
    campaign_id: int,
    npcs: List[NPC],
    active_thread_ids: Set[int],
    index: EntitySessionPresenceIndex,
    sessions_by_id: Dict[int, SessionModel],
    *,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    from sqlmodel import select as sql_select

    from app.models import NPCPlotThreadLink

    thread_link_counts: Dict[int, int] = {}
    if active_thread_ids:
        links = db.exec(sql_select(NPCPlotThreadLink)).all()
        for link in links:
            if link.npc_id and link.plot_thread_id in active_thread_ids:
                thread_link_counts[link.npc_id] = thread_link_counts.get(link.npc_id, 0) + 1

    scored: Dict[int, Dict[str, Any]] = {}
    current_rank = max(index.rank.values()) if index.rank else -1

    for npc in npcs:
        if not npc.id:
            continue
        presence = index.presence("npcs", npc.id)
        if not presence:
            continue
        last_rank = index.rank.get(presence["last"].id, -1)
        recency = current_rank - last_rank
        thread_links = thread_link_counts.get(npc.id, 0)
        score = (10 - min(recency, 10)) + thread_links * 3
        if score <= 0 and recency > 5:
            continue
        last_session = sessions_by_id.get(npc.last_seen_session_id) if npc.last_seen_session_id else presence["last"]
        scored[npc.id] = {
            "npc": npc,
            "status": world_status_label(npc.world_status or npc.current_status, "npcs") or npc.role or "",
            "last_session": last_session,
            "last_seen_title": last_session.title if last_session else None,
            "thread_link_count": thread_links,
            "score": score,
        }

    rows = sorted(scored.values(), key=lambda row: (-row["score"], (row["npc"].name or "").lower()))
    return rows[:limit]


def build_recent_developments_section(
    sorted_sessions: List[SessionModel],
    index: EntitySessionPresenceIndex,
    *,
    limit: int = 8,
) -> List[Dict[str, Any]]:
    developments: List[Dict[str, Any]] = []
    recent = list(reversed(sorted_sessions[-RECENT_SESSION_LIMIT:]))

    for session in recent:
        if not session.id:
            continue
        recap = _session_recap_text(session)
        if recap:
            developments.append(
                {
                    "kind": "session_recap",
                    "label": "Session recap",
                    "session": session,
                    "text": recap,
                }
            )

        sid = session.id
        for section_key, label in (
            ("locations", "New location"),
            ("factions", "Faction activity"),
            ("items", "Item surfaced"),
        ):
            for entity_id, session_ids in index._entity_sessions.get(section_key, {}).items():
                if sid not in session_ids:
                    continue
                ordered = sorted(session_ids, key=lambda x: index.rank.get(x, 9999))
                if ordered[0] != sid:
                    continue
                developments.append(
                    {
                        "kind": section_key,
                        "label": label,
                        "session": session,
                        "entity_id": entity_id,
                        "section_key": section_key,
                        "text": f"{label} linked in this session.",
                    }
                )

    # Enrich entity names in a second pass - we'll fix in build function with db
    return developments[:limit]


def _enrich_development_names(db: Session, campaign_id: int, developments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    from app.models import Faction, Item, Location

    models = {
        "locations": (Location, "name"),
        "factions": (Faction, "name"),
        "items": (Item, "name"),
    }
    enriched: List[Dict[str, Any]] = []
    for row in developments:
        if row.get("kind") in models and row.get("entity_id"):
            model, attr = models[row["kind"]]
            entity = db.get(model, row["entity_id"])
            if entity and entity.campaign_id == campaign_id:
                name = getattr(entity, attr, "") or f"#{row['entity_id']}"
                row = {**row, "text": f"{row['label']}: {name}"}
        enriched.append(row)
    return enriched


def _extract_questions_from_text(text: Optional[str], source: str, *, session: Optional[SessionModel] = None) -> List[Dict[str, Any]]:
    if not text or not str(text).strip():
        return []
    rows: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for line in str(text).splitlines():
        candidate = line.strip().lstrip("-•*0123456789.) ").strip()
        if len(candidate) < 12:
            continue
        if not QUESTION_LINE.match(candidate):
            continue
        key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "text": _preview(candidate, QUESTION_PREVIEW),
                "source": source,
                "session": session,
            }
        )
    return rows


def build_unresolved_questions_section(
    sorted_sessions: List[SessionModel],
    threads: List[PlotThread],
    *,
    limit: int = 12,
) -> List[Dict[str, Any]]:
    questions: List[Dict[str, Any]] = []
    seen: Set[str] = set()

    def add_rows(rows: List[Dict[str, Any]]) -> None:
        for row in rows:
            key = row["text"].lower()
            if key in seen:
                continue
            seen.add(key)
            questions.append(row)

    for thread in threads:
        if not is_active_thread_status(thread.status):
            continue
        for field, label in ((thread.details, f"Thread: {thread.title}"), (thread.related_npcs, thread.title)):
            add_rows(_extract_questions_from_text(field, label))

    for session in reversed(sorted_sessions[-RECENT_SESSION_LIMIT:]):
        add_rows(_extract_questions_from_text(session.next_session_prep, "Session prep", session=session))
        add_rows(_extract_questions_from_text(session.analysis, f"Analysis: {session.title}", session=session))

    return questions[:limit]


def build_dormant_threads_section(
    db: Session,
    campaign_id: int,
    current_session: Optional[SessionModel],
    *,
    gap: Optional[int] = None,
    limit: int = 12,
) -> List[Dict[str, Any]]:
    resolved_gap = gap if gap is not None else get_intelligence_gap()
    dormant = find_dormant_threads(db, campaign_id, current_session=current_session, gap=resolved_gap, limit=limit)
    rows: List[Dict[str, Any]] = []
    for row in dormant:
        sessions_since = row.get("sessions_behind")
        rows.append(
            {
                "thread": row["thread"],
                "last_session": row.get("last_session"),
                "reason": row.get("reason"),
                "sessions_since": sessions_since,
                "never_linked": row.get("reason") == "never_linked",
            }
        )
    return rows


def build_needs_attention_summary(
    needs_attention: List[Dict[str, Any]],
    sorted_sessions: List[SessionModel],
    dormant_threads: List[Dict[str, Any]],
    stale_count: int,
    mystery_attention: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    by_type: Dict[str, int] = {}
    for item in needs_attention:
        key = item.get("section_key", "other")
        by_type[key] = by_type.get(key, 0) + 1

    unanalyzed = [
        s
        for s in sorted_sessions
        if (s.notes or "").strip() and not session_has_analysis(s)
    ]

    lines: List[Dict[str, str]] = []
    if by_type.get("npcs"):
        n = by_type["npcs"]
        lines.append({"text": f"{n} NPC{'s' if n != 1 else ''} incomplete", "anchor": "needs-attention"})
    if by_type.get("locations"):
        n = by_type["locations"]
        lines.append({"text": f"{n} Location{'s' if n != 1 else ''} incomplete", "anchor": "needs-attention"})
    if by_type.get("factions"):
        n = by_type["factions"]
        lines.append({"text": f"{n} Faction{'s' if n != 1 else ''} incomplete", "anchor": "needs-attention"})
    if by_type.get("items"):
        n = by_type["items"]
        lines.append({"text": f"{n} Item{'s' if n != 1 else ''} incomplete", "anchor": "needs-attention"})
    if by_type.get("threads"):
        n = by_type["threads"]
        lines.append({"text": f"{n} Plot thread{'s' if n != 1 else ''} incomplete", "anchor": "needs-attention"})
    if unanalyzed:
        n = len(unanalyzed)
        lines.append({"text": f"{n} Session{'s' if n != 1 else ''} not analyzed", "anchor": "needs-attention"})
    if dormant_threads:
        n = len(dormant_threads)
        lines.append({"text": f"{n} Dormant thread{'s' if n != 1 else ''}", "anchor": "dormant-threads"})
    if stale_count:
        lines.append({"text": f"{stale_count} Stale entit{'ies' if stale_count != 1 else 'y'}", "anchor": "attention-required"})
    for row in mystery_attention or []:
        thread = row.get("thread")
        reason = row.get("reason", "Mystery needs attention")
        title = getattr(thread, "title", "Plot thread") if thread else "Plot thread"
        lines.append({"text": f"{title}: {reason}", "anchor": "open-mysteries"})

    return {
        "lines": lines,
        "incomplete_entities": len(needs_attention),
        "unanalyzed_sessions": unanalyzed,
        "unanalyzed_count": len(unanalyzed),
        "dormant_count": len(dormant_threads),
        "stale_count": stale_count,
        "by_type": by_type,
        "needs_attention_items": needs_attention,
        "mystery_attention": mystery_attention or [],
    }


def build_quick_actions(
    campaign_id: int,
    last_session: Optional[SessionModel],
    current_session: Optional[SessionModel],
) -> List[Dict[str, str]]:
    from app.services.mission_control_ui import session_workflow_url, workspace_url

    actions: List[Dict[str, str]] = []
    focus = current_session or last_session
    if last_session and last_session.id:
        actions.append(
            {
                "label": "Analyze Last Session",
                "href": session_workflow_url(campaign_id, last_session.id),
            }
        )
    if focus and focus.id:
        actions.append(
            {
                "label": "Open Workspace",
                "href": workspace_url(campaign_id, session_id=focus.id, mode="prep"),
            }
        )
    actions.append({"label": "Review Active Threads", "href": f"/campaigns/{campaign_id}/briefing#active-threads"})
    actions.append({"label": "Review Dormant Threads", "href": f"/campaigns/{campaign_id}/briefing#dormant-threads"})
    return actions


def build_campaign_briefing_sections(
    db: Session,
    campaign_id: int,
    *,
    sorted_sessions: List[SessionModel],
    entity_lists: Dict[str, List[Any]],
    dashboard_summary: Dict[str, Any],
    signals: Dict[str, Any],
    current_session: Optional[SessionModel],
    completeness_overview: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    index = EntitySessionPresenceIndex(db, campaign_id)
    threads = entity_lists.get("threads") or []
    npcs = entity_lists.get("npcs") or []
    active_thread_ids = {t.id for t in threads if t.id and is_active_thread_status(t.status)}

    last_session = build_last_session_section(sorted_sessions)
    active_threads = build_active_threads_section(db, campaign_id, threads, index)
    important_npcs = build_important_npcs_section(
        db,
        campaign_id,
        npcs,
        active_thread_ids,
        index,
        index.sessions_by_id,
    )
    developments = _enrich_development_names(
        db,
        campaign_id,
        build_recent_developments_section(sorted_sessions, index),
    )
    unresolved = build_unresolved_questions_section(sorted_sessions, threads)
    dormant = build_dormant_threads_section(db, campaign_id, current_session)
    world_state = build_world_state_briefing(
        threads,
        entity_lists.get("factions") or [],
        entity_lists.get("locations") or [],
    )

    needs = build_needs_attention_summary(
        dashboard_summary.get("needs_attention") or [],
        sorted_sessions,
        dormant,
        signals.get("stale_count") or 0,
        mystery_attention=world_state.get("mystery_needs_attention"),
    )

    if completeness_overview is None:
        completeness_overview = build_campaign_completeness_overview(db, campaign_id)

    coverage = {}
    for section in completeness_overview.get("sections") or []:
        key = section.get("key")
        if key in {"npcs", "locations", "threads"}:
            coverage[key] = section.get("average_score", 0)

    return {
        "last_session": last_session,
        "active_threads": active_threads,
        "important_npcs": important_npcs,
        "recent_developments": developments,
        "unresolved_questions": unresolved,
        "dormant_threads": dormant,
        "needs_attention": needs,
        "world_state": world_state,
        "campaign_health": {
            "average": completeness_overview.get("campaign_average", 0),
            "badge_class": completeness_overview.get("campaign_badge_class", "secondary"),
            "npc_coverage": coverage.get("npcs", 0),
            "location_coverage": coverage.get("locations", 0),
            "thread_coverage": coverage.get("threads", 0),
            "overview": completeness_overview,
        },
        "quick_actions": build_quick_actions(campaign_id, last_session["session"] if last_session else None, current_session),
    }
