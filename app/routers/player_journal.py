from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from app.database import get_session
from app.deps import templates
from app.models import Campaign, PlayerJournalEntry
from app.services.mission_control_ui import mc_context
from app.services.player_console import load_membership, load_player_campaign
from app.services.player_journal import (
    ENTRY_TYPES,
    VISIBILITIES,
    load_gm_journal,
    load_player_journal,
    published_sessions,
    validate_reveal_link,
    validate_session_link,
    visible_reveal_map,
)
from app.utils.time import utc_now

router = APIRouter()


def _membership_or_404(db: Session, request: Request, campaign_id: int):
    membership = load_membership(db, request.state.current_user.id, campaign_id)
    if not membership:
        raise HTTPException(status_code=404, detail="Player campaign not found.")
    return membership


def _optional_int(value: str) -> Optional[int]:
    return int(value) if value and value.isdigit() else None


@router.get("/player/campaigns/{campaign_id}/journal", response_class=HTMLResponse)
def player_journal(request: Request, campaign_id: int, db: Session = Depends(get_session)):
    membership = _membership_or_404(db, request, campaign_id)
    reveal_map = visible_reveal_map(db, membership)
    return templates.TemplateResponse(
        "player_journal.html",
        {
            "request": request,
            "campaign": load_player_campaign(db, membership),
            "journal_entries": load_player_journal(
                db, membership, request.state.current_user.id
            ),
            "entry_types": ENTRY_TYPES,
            "visibilities": VISIBILITIES,
            "published_sessions": published_sessions(db, campaign_id),
            "visible_reveals": list(reveal_map.values()),
            "can_write": membership.role == "player",
            "active_player_nav": "journal",
        },
    )


@router.post("/player/campaigns/{campaign_id}/journal")
def create_player_journal_entry(
    request: Request,
    campaign_id: int,
    body: str = Form(...),
    entry_type: str = Form("note"),
    visibility: str = Form("gm"),
    title: str = Form(""),
    session_id: str = Form(""),
    linked_reveal_id: str = Form(""),
    db: Session = Depends(get_session),
):
    membership = _membership_or_404(db, request, campaign_id)
    if membership.role != "player":
        raise HTTPException(status_code=403, detail="Player membership required to add journal entries.")
    if entry_type not in ENTRY_TYPES or visibility not in VISIBILITIES or not body.strip():
        raise HTTPException(status_code=400, detail="Invalid journal entry.")

    parsed_session = _optional_int(session_id)
    parsed_reveal = _optional_int(linked_reveal_id)
    if not validate_session_link(db, campaign_id, parsed_session):
        raise HTTPException(status_code=400, detail="Invalid session link.")
    if not validate_reveal_link(db, membership, parsed_reveal):
        raise HTTPException(status_code=400, detail="Invalid lore link.")

    entry = PlayerJournalEntry(
        campaign_id=campaign_id,
        author_user_id=request.state.current_user.id,
        author_display_name=request.state.current_user.display_name,
        entry_type=entry_type,
        visibility=visibility,
        title=title.strip() or None,
        body=body.strip(),
        session_id=parsed_session,
        linked_reveal_id=parsed_reveal,
    )
    db.add(entry)
    db.commit()
    return RedirectResponse(f"/player/campaigns/{campaign_id}/journal", status_code=303)


@router.post("/player/campaigns/{campaign_id}/journal/{entry_id}/update")
def update_player_journal_entry(
    request: Request,
    campaign_id: int,
    entry_id: int,
    body: str = Form(...),
    entry_type: str = Form("note"),
    visibility: str = Form("gm"),
    title: str = Form(""),
    session_id: str = Form(""),
    linked_reveal_id: str = Form(""),
    db: Session = Depends(get_session),
):
    membership = _membership_or_404(db, request, campaign_id)
    entry = db.get(PlayerJournalEntry, entry_id)
    if (
        membership.role != "player"
        or not entry
        or entry.campaign_id != campaign_id
        or entry.author_user_id != request.state.current_user.id
    ):
        raise HTTPException(status_code=404, detail="Journal entry not found.")
    if entry_type not in ENTRY_TYPES or visibility not in VISIBILITIES or not body.strip():
        raise HTTPException(status_code=400, detail="Invalid journal entry.")

    parsed_session = _optional_int(session_id)
    parsed_reveal = _optional_int(linked_reveal_id)
    if not validate_session_link(db, campaign_id, parsed_session):
        raise HTTPException(status_code=400, detail="Invalid session link.")
    if not validate_reveal_link(db, membership, parsed_reveal):
        raise HTTPException(status_code=400, detail="Invalid lore link.")

    entry.entry_type = entry_type
    entry.visibility = visibility
    entry.title = title.strip() or None
    entry.body = body.strip()
    entry.session_id = parsed_session
    entry.linked_reveal_id = parsed_reveal
    entry.updated_at = utc_now()
    db.add(entry)
    db.commit()
    return RedirectResponse(f"/player/campaigns/{campaign_id}/journal", status_code=303)


@router.post("/player/campaigns/{campaign_id}/journal/{entry_id}/delete")
def delete_player_journal_entry(
    request: Request,
    campaign_id: int,
    entry_id: int,
    db: Session = Depends(get_session),
):
    _membership_or_404(db, request, campaign_id)
    entry = db.get(PlayerJournalEntry, entry_id)
    if (
        not entry
        or entry.campaign_id != campaign_id
        or entry.author_user_id != request.state.current_user.id
    ):
        raise HTTPException(status_code=404, detail="Journal entry not found.")
    db.delete(entry)
    db.commit()
    return RedirectResponse(f"/player/campaigns/{campaign_id}/journal", status_code=303)


@router.get("/campaigns/{campaign_id}/player-journal", response_class=HTMLResponse)
def gm_player_journal(request: Request, campaign_id: int, db: Session = Depends(get_session)):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    ctx = mc_context(db, campaign=campaign, request=request, layout="dashboard", include_campaigns=True)
    ctx.update({
        "request": request,
        "campaign": campaign,
        "journal_entries": load_gm_journal(db, campaign_id),
        "active_nav": "player_journal",
    })
    return templates.TemplateResponse("gm_player_journal.html", ctx)


@router.post("/campaigns/{campaign_id}/player-journal/{entry_id}/respond")
def gm_respond_to_player_journal(
    request: Request,
    campaign_id: int,
    entry_id: int,
    gm_response: str = Form(""),
    resolved: Optional[str] = Form(None),
    db: Session = Depends(get_session),
):
    entry = db.get(PlayerJournalEntry, entry_id)
    if not entry or entry.campaign_id != campaign_id or entry.visibility == "private":
        raise HTTPException(status_code=404, detail="Journal entry not found.")
    entry.gm_response = gm_response.strip() or None
    entry.is_resolved = bool(resolved)
    entry.updated_at = utc_now()
    db.add(entry)
    db.commit()
    return RedirectResponse(f"/campaigns/{campaign_id}/player-journal", status_code=303)
