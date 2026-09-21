"""Extended workspace routes for narrative blocks (Phase 3)."""

from typing import List, Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from app.database import get_session
from app.deps import get_campaign_or_none, get_entity_or_none
from app.models import Encounter, Objective, Scene, SessionModel
from app.services.narrative_blocks import (
    clear_active_scene,
    create_encounter,
    create_objective,
    create_scene,
    reorder_block,
    set_active_scene,
)
from app.services.mission_control_ui import resolve_workspace_mode, workspace_url

router = APIRouter()


def _redirect_workspace(campaign_id: int, session_id: int, mode: str, message: Optional[str] = None):
    url = workspace_url(campaign_id, session_id=session_id, mode=mode)
    if message:
        url = f"{url}&message={message}" if "?" in url else f"{url}?message={message}"
    return RedirectResponse(url=url, status_code=303)


@router.post("/campaigns/{campaign_id}/workspace/scenes")
def workspace_create_scene(
    request: Request,
    campaign_id: int,
    session_id: int = Form(...),
    mode: str = Form("prep"),
    title: str = Form(...),
    narrative_goal: str = Form(""),
    summary: str = Form(""),
    location_id: str = Form(""),
    npc_ids: Optional[List[str]] = Form(None),
    thread_ids: Optional[List[str]] = Form(None),
    db: Session = Depends(get_session),
):
    campaign = get_campaign_or_none(db, campaign_id)
    session_model = get_entity_or_none(db, SessionModel, campaign_id, session_id)
    if not campaign or not session_model:
        return RedirectResponse(url="/", status_code=303)

    loc_id = int(location_id) if location_id.isdigit() else None
    create_scene(
        db,
        campaign_id,
        session_id=session_id,
        title=title,
        narrative_goal=narrative_goal,
        summary=summary,
        location_id=loc_id,
        npc_ids=npc_ids,
        thread_ids=thread_ids,
    )
    db.commit()
    return _redirect_workspace(campaign_id, session_id, resolve_workspace_mode(request, campaign_id, mode))


@router.post("/campaigns/{campaign_id}/workspace/encounters")
def workspace_create_encounter(
    request: Request,
    campaign_id: int,
    session_id: int = Form(...),
    mode: str = Form("prep"),
    scene_id: str = Form(""),
    title: str = Form(...),
    encounter_type: str = Form("other"),
    objective: str = Form(""),
    stakes: str = Form(""),
    npc_ids: Optional[List[str]] = Form(None),
    thread_ids: Optional[List[str]] = Form(None),
    db: Session = Depends(get_session),
):
    campaign = get_campaign_or_none(db, campaign_id)
    session_model = get_entity_or_none(db, SessionModel, campaign_id, session_id)
    if not campaign or not session_model:
        return RedirectResponse(url="/", status_code=303)

    sid = int(scene_id) if scene_id.isdigit() else None
    create_encounter(
        db,
        campaign_id,
        session_id=session_id,
        scene_id=sid,
        title=title,
        encounter_type=encounter_type,
        objective=objective,
        stakes=stakes,
        npc_ids=npc_ids,
        thread_ids=thread_ids,
    )
    db.commit()
    return _redirect_workspace(campaign_id, session_id, resolve_workspace_mode(request, campaign_id, mode))


@router.post("/campaigns/{campaign_id}/workspace/objectives")
def workspace_create_objective(
    request: Request,
    campaign_id: int,
    session_id: int = Form(...),
    mode: str = Form("prep"),
    scene_id: str = Form(""),
    encounter_id: str = Form(""),
    title: str = Form(...),
    description: str = Form(""),
    objective_type: str = Form("other"),
    priority: str = Form("normal"),
    npc_ids: Optional[List[str]] = Form(None),
    thread_ids: Optional[List[str]] = Form(None),
    db: Session = Depends(get_session),
):
    campaign = get_campaign_or_none(db, campaign_id)
    session_model = get_entity_or_none(db, SessionModel, campaign_id, session_id)
    if not campaign or not session_model:
        return RedirectResponse(url="/", status_code=303)

    sid = int(scene_id) if scene_id.isdigit() else None
    eid = int(encounter_id) if encounter_id.isdigit() else None
    create_objective(
        db,
        campaign_id,
        session_id=session_id,
        scene_id=sid,
        encounter_id=eid,
        title=title,
        description=description,
        objective_type=objective_type,
        priority=priority,
        npc_ids=npc_ids,
        thread_ids=thread_ids,
    )
    db.commit()
    return _redirect_workspace(campaign_id, session_id, resolve_workspace_mode(request, campaign_id, mode))


@router.post("/campaigns/{campaign_id}/workspace/scenes/{scene_id}/activate")
def workspace_activate_scene(
    request: Request,
    campaign_id: int,
    scene_id: int,
    session_id: int = Form(...),
    mode: str = Form("run"),
    db: Session = Depends(get_session),
):
    campaign = get_campaign_or_none(db, campaign_id)
    if not campaign:
        return RedirectResponse(url="/", status_code=303)
    try:
        set_active_scene(db, campaign_id, session_id, scene_id)
        db.commit()
    except ValueError:
        pass
    resolved = resolve_workspace_mode(request, campaign_id, mode or "run")
    return _redirect_workspace(campaign_id, session_id, resolved, message="scene_active")


@router.post("/campaigns/{campaign_id}/workspace/scenes/clear-active")
def workspace_clear_active_scene(
    request: Request,
    campaign_id: int,
    session_id: int = Form(...),
    mode: str = Form("prep"),
    db: Session = Depends(get_session),
):
    campaign = get_campaign_or_none(db, campaign_id)
    if not campaign:
        return RedirectResponse(url="/", status_code=303)
    clear_active_scene(db, campaign_id, session_id)
    db.commit()
    return _redirect_workspace(campaign_id, session_id, resolve_workspace_mode(request, campaign_id, mode))


@router.post("/campaigns/{campaign_id}/workspace/scenes/{scene_id}/reorder")
def workspace_reorder_scene(
    request: Request,
    campaign_id: int,
    scene_id: int,
    session_id: int = Form(...),
    mode: str = Form("prep"),
    direction: str = Form("up"),
    db: Session = Depends(get_session),
):
    campaign = get_campaign_or_none(db, campaign_id)
    if not campaign:
        return RedirectResponse(url="/", status_code=303)
    reorder_block(db, Scene, scene_id, direction)
    db.commit()
    return _redirect_workspace(campaign_id, session_id, resolve_workspace_mode(request, campaign_id, mode))


@router.post("/campaigns/{campaign_id}/workspace/encounters/{encounter_id}/reorder")
def workspace_reorder_encounter(
    request: Request,
    campaign_id: int,
    encounter_id: int,
    session_id: int = Form(...),
    mode: str = Form("prep"),
    direction: str = Form("up"),
    db: Session = Depends(get_session),
):
    campaign = get_campaign_or_none(db, campaign_id)
    if not campaign:
        return RedirectResponse(url="/", status_code=303)
    reorder_block(db, Encounter, encounter_id, direction)
    db.commit()
    return _redirect_workspace(campaign_id, session_id, resolve_workspace_mode(request, campaign_id, mode))


@router.post("/campaigns/{campaign_id}/workspace/objectives/{objective_id}/reorder")
def workspace_reorder_objective(
    request: Request,
    campaign_id: int,
    objective_id: int,
    session_id: int = Form(...),
    mode: str = Form("prep"),
    direction: str = Form("up"),
    db: Session = Depends(get_session),
):
    campaign = get_campaign_or_none(db, campaign_id)
    if not campaign:
        return RedirectResponse(url="/", status_code=303)
    reorder_block(db, Objective, objective_id, direction)
    db.commit()
    return _redirect_workspace(campaign_id, session_id, resolve_workspace_mode(request, campaign_id, mode))
