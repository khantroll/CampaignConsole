import io

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse, RedirectResponse, StreamingResponse
from sqlmodel import Session

from app import database
from app.database import get_session
from app.models import Campaign, SessionModel
from app.services.backup import (
    campaign_backup_filename,
    export_campaign_json_bytes,
    export_campaign_sqlite_bytes,
)
from app.services.export import create_obsidian_export, render_briefing_markdown, render_campaign_markdown, render_session_markdown
from app.services.campaign_intelligence import load_campaign_briefing_data
from app.services.location_links import load_related_locations
from app.services.plot_thread_links import load_related_plot_threads
from app.services.lore_index import load_campaign_entities


def _location_related_names_map(db: Session, campaign_id: int, locations) -> dict:
    return {
        location.id: [related.name for related in load_related_locations(db, campaign_id, location.id)]
        for location in locations
        if location.id
    }


def _thread_related_names_map(db: Session, campaign_id: int, threads) -> dict:
    return {
        thread.id: [related.title for related in load_related_plot_threads(db, campaign_id, thread.id)]
        for thread in threads
        if thread.id
    }

router = APIRouter()


def _sorted_campaign_entities(db: Session, campaign_id: int):
    _, entities = load_campaign_entities(db, campaign_id)
    sessions = sorted(entities["sessions"], key=lambda session: session.id or 0)
    return (
        sessions,
        entities["npcs"],
        entities["locations"],
        entities["factions"],
        entities["items"],
        entities["threads"],
        entities["pc_notes"],
    )


@router.get("/campaigns/{campaign_id}/export/markdown", response_class=PlainTextResponse)
def export_campaign_markdown(
    campaign_id: int,
    scope: str = "gm",
    db: Session = Depends(get_session),
):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        return PlainTextResponse("Campaign not found.", status_code=404)

    sessions, npcs, locations, factions, items, threads, pc_notes = _sorted_campaign_entities(db, campaign_id)
    markdown = render_campaign_markdown(
        campaign,
        sessions,
        npcs,
        locations,
        factions,
        items,
        threads,
        pc_notes,
        location_related_names=_location_related_names_map(db, campaign_id, locations),
        thread_related_names=_thread_related_names_map(db, campaign_id, threads),
        include_gm_secrets=scope.strip().lower() != "player",
    )
    return PlainTextResponse(markdown, media_type="text/markdown")


@router.get("/campaigns/{campaign_id}/briefing/export/markdown", response_class=PlainTextResponse)
def export_briefing_markdown(campaign_id: int, db: Session = Depends(get_session)):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        return PlainTextResponse("Campaign not found.", status_code=404)

    briefing = load_campaign_briefing_data(db, campaign_id)
    markdown = render_briefing_markdown(campaign, briefing)
    return PlainTextResponse(markdown, media_type="text/markdown")


@router.get("/campaigns/{campaign_id}/backup/json")
def download_campaign_json(campaign_id: int, db: Session = Depends(get_session)):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        return RedirectResponse(url="/", status_code=303)

    payload = export_campaign_json_bytes(db, campaign_id)
    filename = campaign_backup_filename(campaign, "json")
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/campaigns/{campaign_id}/backup/db")
def download_campaign_database(campaign_id: int, db: Session = Depends(get_session)):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        return RedirectResponse(url="/", status_code=303)

    try:
        sqlite_bytes = export_campaign_sqlite_bytes(database.DB_FILE, campaign_id)
    except ValueError:
        return RedirectResponse(url="/", status_code=303)

    filename = campaign_backup_filename(campaign, "db")
    return StreamingResponse(
        io.BytesIO(sqlite_bytes),
        media_type="application/x-sqlite3",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/campaigns/{campaign_id}/backup/markdown")
def download_markdown_zip(campaign_id: int, db: Session = Depends(get_session)):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        return RedirectResponse(url="/", status_code=303)

    sessions, npcs, locations, factions, items, threads, pc_notes = _sorted_campaign_entities(db, campaign_id)
    zip_bytes = create_obsidian_export(
        campaign,
        sessions,
        npcs,
        locations,
        factions,
        items,
        threads,
        pc_notes,
        location_related_names=_location_related_names_map(db, campaign_id, locations),
        thread_related_names=_thread_related_names_map(db, campaign_id, threads),
    )
    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=campaign_{campaign_id}_obsidian.zip"},
    )


@router.get("/campaigns/{campaign_id}/sessions/{session_id}/export/markdown", response_class=PlainTextResponse)
def export_session_markdown(
    campaign_id: int,
    session_id: int,
    scope: str = "gm",
    db: Session = Depends(get_session),
):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        return PlainTextResponse("Campaign not found.", status_code=404)

    session_model = db.get(SessionModel, session_id)
    if not session_model or session_model.campaign_id != campaign_id:
        return PlainTextResponse("Session not found.", status_code=404)

    from app.services.narrative_blocks import load_session_narrative_blocks

    blocks = load_session_narrative_blocks(db, campaign_id, session_id)
    _, npcs, locations, factions, items, threads, _ = _sorted_campaign_entities(db, campaign_id)
    references = (
        [npc.name for npc in npcs]
        + [location.name for location in locations]
        + [faction.name for faction in factions]
        + [item.name for item in items]
        + [thread.title for thread in threads]
    )
    markdown = render_session_markdown(
        campaign,
        session_model,
        references,
        scenes=blocks["scenes"],
        encounters=blocks["encounters"],
        objectives=blocks["objectives"],
        include_gm_notes=scope.strip().lower() != "player",
    )
    return PlainTextResponse(markdown, media_type="text/markdown")
