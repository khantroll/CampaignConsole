from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from app.database import get_session
from app.deps import templates
from app.models import Campaign, CampaignMembership, PlayerReveal, RevealAudience, SessionModel
from app.services.player_console import (
    ENTITY_LABELS,
    ENTITY_MODELS,
    load_membership,
    load_player_campaign,
    load_player_campaigns,
    load_player_character,
    load_player_home,
    load_player_lore_entry,
    load_player_reveals,
    load_player_session,
    load_player_sessions,
)
from app.services.mission_control_ui import mc_context
from app.utils.time import utc_now

router = APIRouter()


def _membership_or_404(db: Session, request: Request, campaign_id: int) -> CampaignMembership:
    membership = load_membership(db, request.state.current_user.id, campaign_id)
    if not membership:
        raise HTTPException(status_code=404, detail="Player campaign not found.")
    return membership


@router.get("/player", response_class=HTMLResponse)
def player_index(request: Request, db: Session = Depends(get_session)):
    campaigns = load_player_campaigns(db, request.state.current_user.id)
    return templates.TemplateResponse(
        "player_index.html",
        {"request": request, "player_campaigns": campaigns},
    )


@router.get("/player/campaigns/{campaign_id}", response_class=HTMLResponse)
def player_home(request: Request, campaign_id: int, db: Session = Depends(get_session)):
    membership = _membership_or_404(db, request, campaign_id)
    ctx = load_player_home(db, membership)
    if not ctx["campaign"]:
        raise HTTPException(status_code=404, detail="Player campaign not found.")
    return templates.TemplateResponse(
        "player_home.html",
        {"request": request, **ctx, "active_player_nav": "home"},
    )


@router.get("/player/campaigns/{campaign_id}/lore", response_class=HTMLResponse)
def player_lore(request: Request, campaign_id: int, db: Session = Depends(get_session)):
    membership = _membership_or_404(db, request, campaign_id)
    campaign = load_player_campaign(db, membership)
    reveals = load_player_reveals(db, membership)
    grouped = {kind: [] for kind in ENTITY_LABELS}
    for reveal in reveals:
        grouped[reveal["entity_kind"]].append(reveal)
    return templates.TemplateResponse(
        "player_lore.html",
        {
            "request": request,
            "campaign": campaign,
            "lore_groups": grouped,
            "entity_labels": ENTITY_LABELS,
            "active_player_nav": "lore",
        },
    )


@router.get(
    "/player/campaigns/{campaign_id}/lore/{entity_kind}/{entity_id}",
    response_class=HTMLResponse,
)
def player_lore_entry(
    request: Request,
    campaign_id: int,
    entity_kind: str,
    entity_id: int,
    db: Session = Depends(get_session),
):
    membership = _membership_or_404(db, request, campaign_id)
    entry = load_player_lore_entry(db, membership, entity_kind, entity_id)
    if not entry:
        # Same response for nonexistent, wrong-campaign, and unrevealed IDs.
        raise HTTPException(status_code=404, detail="Lore entry not found.")
    return templates.TemplateResponse(
        "player_lore_entry.html",
        {
            "request": request,
            "campaign": load_player_campaign(db, membership),
            "entry": entry,
            "active_player_nav": "lore",
        },
    )


@router.get("/player/campaigns/{campaign_id}/sessions", response_class=HTMLResponse)
def player_sessions(request: Request, campaign_id: int, db: Session = Depends(get_session)):
    membership = _membership_or_404(db, request, campaign_id)
    return templates.TemplateResponse(
        "player_sessions.html",
        {
            "request": request,
            "campaign": load_player_campaign(db, membership),
            "player_sessions": load_player_sessions(db, membership),
            "active_player_nav": "sessions",
        },
    )


@router.get("/player/campaigns/{campaign_id}/sessions/{session_id}", response_class=HTMLResponse)
def player_session(
    request: Request,
    campaign_id: int,
    session_id: int,
    db: Session = Depends(get_session),
):
    membership = _membership_or_404(db, request, campaign_id)
    session_view = load_player_session(db, membership, session_id)
    if not session_view:
        raise HTTPException(status_code=404, detail="Session not found.")
    return templates.TemplateResponse(
        "player_session.html",
        {
            "request": request,
            "campaign": load_player_campaign(db, membership),
            "player_session": session_view,
            "active_player_nav": "sessions",
        },
    )


@router.get("/player/campaigns/{campaign_id}/character", response_class=HTMLResponse)
def player_character(request: Request, campaign_id: int, db: Session = Depends(get_session)):
    membership = _membership_or_404(db, request, campaign_id)
    return templates.TemplateResponse(
        "player_character.html",
        {
            "request": request,
            "campaign": load_player_campaign(db, membership),
            "character": load_player_character(db, membership),
            "active_player_nav": "character",
        },
    )


# Minimal Phase 2 GM authoring surface. Full reveal-management UX remains deferred.
@router.get("/campaigns/{campaign_id}/player-reveals", response_class=HTMLResponse)
def reveal_admin(request: Request, campaign_id: int, db: Session = Depends(get_session)):
    memberships = db.exec(
        select(CampaignMembership).where(CampaignMembership.campaign_id == campaign_id)
    ).all()
    reveals = db.exec(
        select(PlayerReveal)
        .where(PlayerReveal.campaign_id == campaign_id)
        .order_by(PlayerReveal.revealed_at.desc())
    ).all()
    campaign = db.get(Campaign, campaign_id)
    ctx = mc_context(db, campaign=campaign, request=request, layout="dashboard", include_campaigns=True)
    ctx.update({
        "request": request,
        "campaign_id": campaign_id,
        "memberships": memberships,
        "reveals": reveals,
        "entity_kinds": ENTITY_LABELS,
        "active_nav": "dashboard",
    })
    return templates.TemplateResponse("player_reveal_admin.html", ctx)


@router.post("/campaigns/{campaign_id}/player-reveals")
def create_reveal(
    request: Request,
    campaign_id: int,
    entity_kind: str = Form(...),
    entity_id: int = Form(...),
    title: str = Form(""),
    public_summary: str = Form(...),
    revealed_session_id: str = Form(""),
    audience_memberships: str = Form(""),
    db: Session = Depends(get_session),
):
    model_info = ENTITY_MODELS.get(entity_kind)
    if not model_info or not public_summary.strip():
        raise HTTPException(status_code=400, detail="Invalid reveal.")
    model, _ = model_info
    entity = db.get(model, entity_id)
    if not entity or entity.campaign_id != campaign_id:
        raise HTTPException(status_code=400, detail="Invalid reveal entity.")

    session_id = int(revealed_session_id) if revealed_session_id.isdigit() else None
    if session_id is not None:
        session_model = db.get(SessionModel, session_id)
        if not session_model or session_model.campaign_id != campaign_id:
            raise HTTPException(status_code=400, detail="Invalid reveal session.")

    selected_ids = {
        int(value.strip())
        for value in audience_memberships.split(",")
        if value.strip().isdigit()
    }
    if selected_ids:
        valid_ids = set(
            db.exec(
                select(CampaignMembership.id).where(
                    CampaignMembership.campaign_id == campaign_id,
                    CampaignMembership.id.in_(selected_ids),
                )
            ).all()
        )
        if valid_ids != selected_ids:
            raise HTTPException(status_code=400, detail="Invalid reveal audience.")

    reveal = PlayerReveal(
        campaign_id=campaign_id,
        entity_kind=entity_kind,
        entity_id=entity_id,
        title=title.strip() or None,
        public_summary=public_summary.strip(),
        audience_mode="selected" if selected_ids else "campaign",
        revealed_session_id=session_id,
        created_by_user_id=request.state.current_user.id,
    )
    db.add(reveal)
    db.commit()
    db.refresh(reveal)
    for membership_id in selected_ids:
        db.add(RevealAudience(reveal_id=reveal.id, membership_id=membership_id))
    db.commit()
    return RedirectResponse(f"/campaigns/{campaign_id}/player-reveals", status_code=303)


@router.post("/campaigns/{campaign_id}/player-reveals/{reveal_id}/update")
def update_reveal(
    request: Request,
    campaign_id: int,
    reveal_id: int,
    title: str = Form(""),
    public_summary: str = Form(...),
    db: Session = Depends(get_session),
):
    reveal = db.get(PlayerReveal, reveal_id)
    if not reveal or reveal.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail="Reveal not found.")
    reveal.title = title.strip() or None
    reveal.public_summary = public_summary.strip()
    reveal.updated_at = utc_now()
    db.add(reveal)
    db.commit()
    return RedirectResponse(f"/campaigns/{campaign_id}/player-reveals", status_code=303)


@router.post("/campaigns/{campaign_id}/player-reveals/{reveal_id}/revoke")
def revoke_reveal(
    request: Request,
    campaign_id: int,
    reveal_id: int,
    db: Session = Depends(get_session),
):
    reveal = db.get(PlayerReveal, reveal_id)
    if reveal and reveal.campaign_id == campaign_id:
        reveal.is_active = False
        reveal.updated_at = utc_now()
        db.add(reveal)
        db.commit()
    return RedirectResponse(f"/campaigns/{campaign_id}/player-reveals", status_code=303)
