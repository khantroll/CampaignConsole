from typing import List, Optional

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from app.database import get_session
from app.deps import get_campaign_or_none, get_entity_or_none, render_markdown, templates
from app.models import (
    Campaign,
    Encounter,
    Faction,
    Item,
    Location,
    NPC,
    Objective,
    PlotThread,
    Scene,
    SessionFactionLink,
    SessionItemLink,
    SessionLocationLink,
    SessionModel,
    SessionNPCLink,
    SessionPlotThreadLink,
)
from app.services import rule_indexer as rule_indexer_module
from app.services.entity_links import load_campaign_entities_by_ids, related_ids_from_links
from app.services.narrative_blocks import (
    build_session_builder_cards,
    collect_scene_feed_entities,
)
from app.services.campaign_intelligence import build_workspace_intelligence
from app.services.mission_control_ui import (
    mc_context,
    resolve_workspace_mode,
    resolve_workspace_session,
    workspace_needs_canonical_redirect,
    workspace_url,
)
from app.utils.time import utc_now

router = APIRouter()


class MarkdownRenderBody(BaseModel):
    snippets: List[str] = []


@router.post("/api/workspace/render-markdown")
def workspace_render_markdown(body: MarkdownRenderBody):
    return {"html": [str(render_markdown(snippet)) for snippet in body.snippets]}


@router.get("/api/workspace/rules-lookup")
def workspace_rules_lookup(
    request: Request,
    campaign_id: int = Query(...),
    text: str = Query(""),
    db: Session = Depends(get_session),
):
    campaign = get_campaign_or_none(db, campaign_id)
    if not campaign:
        return []

    indexer = getattr(request.app.state, "rule_indexer", None) or rule_indexer_module.rule_indexer
    if not indexer:
        return []

    return indexer.lookup_rules_in_text(campaign.system, text)


def _session_linked_entities(db: Session, campaign_id: int, session_model: SessionModel):
    npc_ids = related_ids_from_links(db, SessionNPCLink, "session_id", session_model.id, "npc_id")
    location_ids = related_ids_from_links(
        db, SessionLocationLink, "session_id", session_model.id, "location_id"
    )
    faction_ids = related_ids_from_links(
        db, SessionFactionLink, "session_id", session_model.id, "faction_id"
    )
    item_ids = related_ids_from_links(db, SessionItemLink, "session_id", session_model.id, "item_id")
    thread_ids = related_ids_from_links(
        db, SessionPlotThreadLink, "session_id", session_model.id, "plot_thread_id"
    )
    npcs = load_campaign_entities_by_ids(db, NPC, campaign_id, [str(i) for i in npc_ids])
    locations = load_campaign_entities_by_ids(db, Location, campaign_id, [str(i) for i in location_ids])
    factions = load_campaign_entities_by_ids(db, Faction, campaign_id, [str(i) for i in faction_ids])
    items = load_campaign_entities_by_ids(db, Item, campaign_id, [str(i) for i in item_ids])
    threads = load_campaign_entities_by_ids(db, PlotThread, campaign_id, [str(i) for i in thread_ids])
    return npcs, locations, factions, items, threads


def _workspace_context(
    request: Request,
    db: Session,
    campaign: Campaign,
    *,
    session_model: Optional[SessionModel],
    mode: str,
    message: Optional[str] = None,
):
    sessions = db.exec(
        select(SessionModel).where(SessionModel.campaign_id == campaign.id).order_by(SessionModel.id.desc())
    ).all()

    npcs: List[NPC] = []
    locations: List[Location] = []
    factions: List[Faction] = []
    items: List[Item] = []
    threads: List[PlotThread] = []
    if session_model:
        session_builder = build_session_builder_cards(
            db, campaign.id, session_model.id, active_scene_id=session_model.active_scene_id
        )
        active_scene = session_builder.get("active_scene")
        if active_scene:
            feed = collect_scene_feed_entities(db, campaign.id, active_scene)
            npcs = feed["npcs"]
            locations = feed["locations"]
            factions = feed["factions"]
            items = feed["items"]
            threads = feed["threads"]
            ref_source = "active_scene"
        else:
            npcs, locations, factions, items, threads = _session_linked_entities(db, campaign.id, session_model)
            ref_source = "session"
        workspace_intel = build_workspace_intelligence(
            db,
            campaign.id,
            session_model,
            linked_npcs=npcs,
            linked_locations=locations,
            linked_factions=factions,
            linked_items=items,
            linked_threads=threads,
            active_scene=active_scene,
            active_scene_card=session_builder.get("active_scene_card"),
        )
        campaign_locations = db.exec(
            select(Location).where(Location.campaign_id == campaign.id).order_by(Location.name)
        ).all()
    else:
        workspace_intel = None
        session_builder = None
        campaign_locations = []
        ref_source = None

    ctx = mc_context(
        db,
        campaign=campaign,
        session=session_model,
        active_nav="workspace",
        layout="workspace",
        mode=mode,
        request=request,
    )
    ctx.update(
        {
            "request": request,
            "message": message,
            "linked_npcs": npcs,
            "linked_locations": locations,
            "linked_factions": factions,
            "linked_items": items,
            "linked_threads": threads,
            "workspace_intel": workspace_intel,
            "session_builder": session_builder,
            "campaign_locations": campaign_locations,
            "ref_source": ref_source,
        }
    )
    return ctx


@router.get("/campaigns/{campaign_id}/workspace", response_class=HTMLResponse)
def session_workspace(
    request: Request,
    campaign_id: int,
    session_id: Optional[int] = Query(None),
    mode: Optional[str] = Query(None),
    message: Optional[str] = Query(None),
    db: Session = Depends(get_session),
):
    campaign = get_campaign_or_none(db, campaign_id)
    if not campaign:
        return RedirectResponse(url="/", status_code=303)

    session_model = resolve_workspace_session(db, request, campaign_id, session_id)
    resolved_mode = resolve_workspace_mode(request, campaign_id, mode)

    if workspace_needs_canonical_redirect(request, session_model, resolved_mode):
        url = workspace_url(campaign_id, session_id=session_model.id, mode=resolved_mode)
        if message:
            url = f"{url}&message={message}" if "?" in url else f"{url}?message={message}"
        return RedirectResponse(url=url, status_code=303)

    return templates.TemplateResponse(
        "session_workspace.html",
        _workspace_context(request, db, campaign, session_model=session_model, mode=resolved_mode, message=message),
    )


@router.post("/campaigns/{campaign_id}/workspace/save")
def save_workspace(
    request: Request,
    campaign_id: int,
    session_id: int = Form(...),
    workspace_notes: str = Form(""),
    mode: str = Form("prep"),
    db: Session = Depends(get_session),
):
    campaign = get_campaign_or_none(db, campaign_id)
    session_model = get_entity_or_none(db, SessionModel, campaign_id, session_id)
    if not campaign or not session_model:
        return RedirectResponse(url="/", status_code=303)

    session_model.workspace_notes = workspace_notes or None
    session_model.updated_at = utc_now()
    db.add(session_model)
    db.commit()

    resolved_mode = resolve_workspace_mode(request, campaign_id, mode)
    return RedirectResponse(
        url=f"{workspace_url(campaign_id, session_id=session_id, mode=resolved_mode)}&message=saved",
        status_code=303,
    )


@router.post("/campaigns/{campaign_id}/workspace/copy-prep")
def copy_prep_to_workspace(
    request: Request,
    campaign_id: int,
    session_id: int = Form(...),
    mode: str = Form("prep"),
    db: Session = Depends(get_session),
):
    campaign = get_campaign_or_none(db, campaign_id)
    session_model = get_entity_or_none(db, SessionModel, campaign_id, session_id)
    if not campaign or not session_model:
        return RedirectResponse(url="/", status_code=303)

    prep = (session_model.next_session_prep or "").strip()
    if prep:
        existing = (session_model.workspace_notes or "").strip()
        if existing:
            session_model.workspace_notes = f"{existing}\n\n---\n\n## AI Session Prep\n\n{prep}"
        else:
            session_model.workspace_notes = f"## AI Session Prep\n\n{prep}"
        session_model.updated_at = utc_now()
        db.add(session_model)
        db.commit()
        msg = "copied"
    else:
        msg = "no_prep"

    resolved_mode = resolve_workspace_mode(request, campaign_id, mode)
    return RedirectResponse(
        url=f"{workspace_url(campaign_id, session_id=session_id, mode=resolved_mode)}&message={msg}",
        status_code=303,
    )
