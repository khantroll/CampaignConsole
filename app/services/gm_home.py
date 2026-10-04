"""GM home presentation: one next action, open threads, and recent records.

Uses campaign records that already exist. Does not invent activity.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlmodel import Session, func, select

from app.models import (
    Campaign,
    Creature,
    Faction,
    Item,
    Location,
    NPC,
    PlayerCharacterNote,
    PlotThread,
    SessionModel,
)
from app.services.ai_workflow import session_has_analysis
from app.services.campaign_intelligence import is_active_thread_status
from app.services.mission_control_ui import append_return_to, workspace_url

NAV_COUNT_MODELS = {
    "npcs": NPC,
    "locations": Location,
    "factions": Faction,
    "items": Item,
    "creatures": Creature,
    "threads": PlotThread,
    "pcs": PlayerCharacterNote,
    "sessions": SessionModel,
}

ENTITY_LIST_KEYS = ("npcs", "locations", "factions", "items", "creatures", "threads", "pcs")

_KIND_FIELDS = {
    "npcs": ("NPC", "name", "npcs"),
    "locations": ("Location", "name", "locations"),
    "factions": ("Faction", "name", "factions"),
    "items": ("Item", "name", "items"),
    "creatures": ("Creature", "name", "creatures"),
    "threads": ("Thread", "title", "threads"),
    "pcs": ("Party", "character_name", "pcs"),
}


def entity_list_path(campaign_id: int, section_key: Optional[str]) -> Optional[str]:
    if section_key in ENTITY_LIST_KEYS:
        return f"/campaigns/{campaign_id}/{section_key}"
    return None


def load_nav_counts(db: Session, campaign_id: int) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for key, model in NAV_COUNT_MODELS.items():
        value = db.exec(
            select(func.count()).select_from(model).where(model.campaign_id == campaign_id)
        ).one()
        counts[key] = int(value or 0)
    return counts


def lore_is_empty(counts: Dict[str, int]) -> bool:
    return all(int(counts.get(key) or 0) == 0 for key in ENTITY_LIST_KEYS)


def session_prep_gap(session_model: Optional[SessionModel]) -> Optional[str]:
    """Same gap the workspace already surfaces: notes without analysis, or analysis without prep."""
    if session_model is None:
        return None
    has_notes = bool((session_model.notes or "").strip())
    has_prep = bool((session_model.next_session_prep or "").strip())
    if has_notes and not session_has_analysis(session_model):
        return "needs_analysis"
    if session_has_analysis(session_model) and not has_prep:
        return "needs_prep"
    return None


def build_home_next_action(
    *,
    campaign_id: int,
    counts: Dict[str, int],
    current_session: Optional[SessionModel] = None,
    next_session: Optional[SessionModel] = None,
    mode: str = "prep",
) -> Dict[str, str]:
    """One next step already implied by campaign data. Empty lore uses the approved NPC prompt."""
    if lore_is_empty(counts):
        return {
            "title": "Next: name the first NPC",
            "detail": (
                "The lore lists are empty. One named person gives the threats "
                "and the session something to attach to."
            ),
            "label": "Add NPC",
            "href": f"/campaigns/{campaign_id}/npcs#add-form",
        }

    gap = session_prep_gap(current_session)
    if gap == "needs_analysis" and current_session and current_session.id:
        return {
            "title": f"Next: analyze {current_session.title}",
            "detail": "Session has notes but no AI analysis yet.",
            "label": "Open session",
            "href": f"/campaigns/{campaign_id}/sessions/{current_session.id}",
        }
    if gap == "needs_prep" and current_session and current_session.id:
        return {
            "title": f"Next: draft prep for {current_session.title}",
            "detail": "Analysis complete but no prep draft.",
            "label": "Open session",
            "href": f"/campaigns/{campaign_id}/sessions/{current_session.id}",
        }

    if int(counts.get("sessions") or 0) == 0:
        return {
            "title": "Next: add a session",
            "detail": "Notes, analysis, and prep are recorded on a session.",
            "label": "Add session",
            "href": f"/campaigns/{campaign_id}/sessions#add-form",
        }

    if (
        next_session
        and next_session.id
        and (not current_session or next_session.id != current_session.id)
        and not (next_session.notes or "").strip()
    ):
        detail = next_session.date or "This session has no notes yet."
        return {
            "title": f"Next: open {next_session.title}",
            "detail": detail,
            "label": "Open session",
            "href": f"/campaigns/{campaign_id}/sessions/{next_session.id}",
        }

    if current_session and current_session.id:
        return {
            "title": f"Next: resume {current_session.title}",
            "detail": current_session.date or "No date set.",
            "label": "Open session",
            "href": workspace_url(campaign_id, session_id=current_session.id, mode=mode),
        }

    return {
        "title": "Next: add a session",
        "detail": "Notes, analysis, and prep are recorded on a session.",
        "label": "Add session",
        "href": f"/campaigns/{campaign_id}/sessions#add-form",
    }


def open_plot_threads(threads: List[PlotThread]) -> List[PlotThread]:
    return [thread for thread in threads if is_active_thread_status(thread.status)]


def _when(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    return ""


def _stamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.min


def build_what_changed(
    campaign_id: int,
    sessions: List[SessionModel],
    entities_by_key: Dict[str, List[Any]],
    *,
    limit: int = 6,
) -> Dict[str, Any]:
    """Recent records by their stored timestamps. Empty lore and sessions stay an empty state."""
    home = f"/campaigns/{campaign_id}"
    rows: List[Dict[str, Any]] = []
    for session_model in sessions:
        if not session_model.id:
            continue
        rows.append(
            {
                "kind": "Session",
                "name": session_model.title,
                "href": f"/campaigns/{campaign_id}/sessions/{session_model.id}",
                "when": _when(session_model.updated_at or session_model.created_at),
                "at": _stamp(session_model.updated_at or session_model.created_at),
            }
        )
    for key, (kind, field, section) in _KIND_FIELDS.items():
        for entity in entities_by_key.get(key) or []:
            entity_id = getattr(entity, "id", None)
            if not entity_id:
                continue
            name = getattr(entity, field, None) or kind
            edit = f"/campaigns/{campaign_id}/{section}/{entity_id}/edit"
            rows.append(
                {
                    "kind": kind,
                    "name": name,
                    "href": append_return_to(edit, home),
                    "when": _when(getattr(entity, "updated_at", None) or getattr(entity, "created_at", None)),
                    "at": _stamp(getattr(entity, "updated_at", None) or getattr(entity, "created_at", None)),
                }
            )
    rows.sort(key=lambda row: row["at"], reverse=True)
    visible = [{k: row[k] for k in ("kind", "name", "href", "when")} for row in rows[:limit]]
    return {"empty": not visible, "items": visible}


def load_last_session_by_campaign(db: Session) -> Dict[int, SessionModel]:
    from app.deps import sort_sessions_chronologically

    grouped: Dict[int, List[SessionModel]] = {}
    for row in db.exec(select(SessionModel)).all():
        grouped.setdefault(row.campaign_id, []).append(row)
    last: Dict[int, SessionModel] = {}
    for campaign_id, sessions in grouped.items():
        ordered = sort_sessions_chronologically(sessions)
        if ordered:
            last[campaign_id] = ordered[-1]
    return last


def campaign_created_label(campaign: Campaign) -> str:
    when = _when(getattr(campaign, "created_at", None))
    if when:
        return f"Campaign created · {when}"
    return "Campaign created"
