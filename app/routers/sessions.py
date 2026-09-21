import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from app.database import get_session
from app.deps import get_campaign_or_none, get_entity_or_none, optional_new_faction_form, related_options, templates
from app.models import (
    Campaign,
    Creature,
    Faction,
    Item,
    Location,
    NPC,
    PlayerCharacterNote,
    PlotThread,
    SessionCreatureLink,
    SessionFactionLink,
    SessionItemLink,
    SessionLocationLink,
    SessionModel,
    SessionNPCLink,
    SessionPlotThreadLink,
)
from app.services.entity_links import (
    load_campaign_entities_by_ids,
    load_factions_for_link,
    related_ids_from_links,
    replace_many_to_many_links,
)
from app.services.campaign_ui import htmx_or_redirect, render_sessions_section
from app.services.provider_router import gemini_is_disabled, generate, provider_available as llm_available
from app.llm import get_active_provider_or_none, get_configured_model
from app.utils.time import utc_now
from app.services.entity_deletion import delete_session_cascade
from app.services.ai_workflow import run_future_prep_generation, session_has_analysis
from app.services.analysis import (
    apply_local_session_analysis_fallback,
    apply_parsed_ai_output,
    build_ai_parse_message,
    build_analyze_session_prompt,
    clear_session_ai_fields,
    extract_entities,
    load_ai_run_metadata,
    prep_overwrite_requires_confirmation,
    save_ai_run_metadata,
)
from app.services.entity_session_presence import refresh_session_link_metadata
from app.services.mission_control_ui import confirm_delete_context, entity_form_context, redirect_after_session_edit, session_workflow_url, with_mc

router = APIRouter()
logger = logging.getLogger(__name__)


def _session_detail_context(
    request: Request,
    db: Session,
    campaign: Campaign,
    session_model: SessionModel,
    *,
    analysis_result=None,
    analysis_warning=None,
    prep_draft=None,
    prep_warning=None,
    prep_message=None,
    prep_result=None,
    prep_overwrite_confirmation=None,
    workflow_message=None,
    hub_message: Optional[str] = None,
):
    ctx = {
            "request": request,
            "campaign": campaign,
            "session": session_model,
            "hub_message": hub_message,
            "analysis_result": analysis_result,
            "analysis_warning": analysis_warning,
            "ai_run_metadata": load_ai_run_metadata(session_model),
            "prep_draft": prep_draft,
            "prep_warning": prep_warning,
            "prep_message": prep_message,
            "prep_result": prep_result,
            "prep_overwrite_confirmation": prep_overwrite_confirmation,
            "workflow_message": workflow_message,
            "has_analysis": session_has_analysis(session_model),
        }
    prep_source = prep_draft or session_model.next_session_prep
    if prep_source:
        from app.services.narrative_blocks import parse_ai_narrative_suggestions

        suggestions = parse_ai_narrative_suggestions(prep_source)
        if any(suggestions.values()):
            ctx["narrative_suggestions"] = suggestions
    return with_mc(
        db,
        ctx,
        request=request,
        campaign=campaign,
        session=session_model,
        active_nav="sessions",
        layout="dashboard",
    )


def _run_session_analysis(
    db: Session,
    campaign: Campaign,
    session_model: SessionModel,
    notes: str,
    session_id: int,
) -> tuple:
    analysis_warning = None
    analysis_result = None
    if llm_available():
        try:
            analysis_text = generate(
                build_analyze_session_prompt(campaign, session_model.title, session_model.date or "", notes),
                max_tokens=3200,
                task_name="sessions/analyze",
            )
            analysis_result = apply_parsed_ai_output(
                session_model,
                analysis_text,
                update_fields={"player_recap", "gm_recap", "analysis"},
                task_name="sessions/analyze",
                session_id=session_id,
            )
            provider = get_active_provider_or_none()
            model = get_configured_model(provider) if provider else None
            save_ai_run_metadata(
                session_model,
                analysis_result,
                provider=provider,
                model=model,
                task_name="sessions/analyze",
                saved_to_session_id=session_id,
            )
            analysis_warning = build_ai_parse_message(analysis_result, context="analyze")
        except Exception as exc:
            logger.exception("AI analysis failed for session %s in campaign %s", session_id, campaign.id)
            analysis_warning = f"AI analysis failed: {exc}"
    elif gemini_is_disabled():
        analysis_warning = "Gemini is disabled (GEMINI_DISABLED=true); fallback analysis was generated locally."
    else:
        analysis_warning = "LLM provider not configured; fallback analysis was generated locally."

    if analysis_result is None:
        npcs = db.exec(select(NPC).where(NPC.campaign_id == campaign.id)).all()
        locations = db.exec(select(Location).where(Location.campaign_id == campaign.id)).all()
        factions = db.exec(select(Faction).where(Faction.campaign_id == campaign.id)).all()
        items = db.exec(select(Item).where(Item.campaign_id == campaign.id)).all()
        threads = db.exec(select(PlotThread).where(PlotThread.campaign_id == campaign.id)).all()
        pc_notes = db.exec(
            select(PlayerCharacterNote).where(PlayerCharacterNote.campaign_id == campaign.id)
        ).all()
        entities = extract_entities(notes, npcs, locations, factions, items, threads, pc_notes)
        apply_local_session_analysis_fallback(session_model, notes, entities, threads)

    return analysis_result, analysis_warning


@router.get("/campaigns/{campaign_id}/sessions/{session_id}/edit", response_class=HTMLResponse)
def edit_session(request: Request, campaign_id: int, session_id: int, db: Session = Depends(get_session)):
    campaign = get_campaign_or_none(db, campaign_id)
    session_model = get_entity_or_none(db, SessionModel, campaign_id, session_id)
    if not campaign or not session_model:
        return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)
    npcs = db.exec(select(NPC).where(NPC.campaign_id == campaign_id)).all()
    locations = db.exec(select(Location).where(Location.campaign_id == campaign_id)).all()
    factions = db.exec(select(Faction).where(Faction.campaign_id == campaign_id)).all()
    items = db.exec(select(Item).where(Item.campaign_id == campaign_id)).all()
    creatures = db.exec(select(Creature).where(Creature.campaign_id == campaign_id)).all()
    threads = db.exec(select(PlotThread).where(PlotThread.campaign_id == campaign_id)).all()
    return templates.TemplateResponse(
        "entity_form.html",
        entity_form_context(
            db,
            request,
            campaign,
            {
            "title": "Edit Session",
            "action": f"/campaigns/{campaign_id}/sessions/{session_id}/edit",
            "entity": session_model,
            "fields": [
                {"name": "title", "label": "Title", "type": "text", "required": True},
                {"name": "date", "label": "Date", "type": "text"},
                {"name": "notes", "label": "Notes", "type": "textarea", "rows": 4},
                {"name": "player_recap", "label": "Player Recap (shareable)", "type": "textarea", "rows": 3},
                {"name": "recap", "label": "GM Recap (private)", "type": "textarea", "rows": 3},
                {"name": "analysis", "label": "Analysis (private)", "type": "textarea", "rows": 3},
                {"name": "next_session_prep", "label": "Next Session Prep (private)", "type": "textarea", "rows": 3},
            ],
            "select_fields": [
                {
                    "name": "selected_npcs",
                    "label": "Appearing NPCs",
                    "options": related_options(
                        npcs,
                        related_ids_from_links(db, SessionNPCLink, "session_id", session_model.id, "npc_id"),
                    ),
                },
                {
                    "name": "selected_locations",
                    "label": "Appearing Locations",
                    "options": related_options(
                        locations,
                        related_ids_from_links(db, SessionLocationLink, "session_id", session_model.id, "location_id"),
                    ),
                },
                {
                    "name": "selected_factions",
                    "label": "Appearing Factions",
                    "options": related_options(
                        factions,
                        related_ids_from_links(db, SessionFactionLink, "session_id", session_model.id, "faction_id"),
                    ),
                },
                {
                    "name": "selected_items",
                    "label": "Appearing Items",
                    "options": related_options(
                        items,
                        related_ids_from_links(db, SessionItemLink, "session_id", session_model.id, "item_id"),
                    ),
                },
                {
                    "name": "selected_creatures",
                    "label": "Appearing Creatures",
                    "options": related_options(
                        creatures,
                        related_ids_from_links(db, SessionCreatureLink, "session_id", session_model.id, "creature_id"),
                    ),
                },
                {
                    "name": "selected_plot_threads",
                    "label": "Appearing Plot Threads",
                    "options": related_options(
                        threads,
                        related_ids_from_links(db, SessionPlotThreadLink, "session_id", session_model.id, "plot_thread_id"),
                    ),
                },
            ],
            "submit_label": "Save Session",
            },
            session=session_model,
            active_nav="sessions",
            cancel_default=session_workflow_url(campaign_id, session_id),
        ),
    )


@router.post("/campaigns/{campaign_id}/sessions/{session_id}/edit")
def update_session(
    request: Request,
    campaign_id: int,
    session_id: int,
    title: str = Form(...),
    date: str = Form(""),
    notes: str = Form(""),
    player_recap: str = Form(""),
    recap: str = Form(""),
    analysis: str = Form(""),
    next_session_prep: str = Form(""),
    selected_npcs: Optional[List[str]] = Form(None),
    selected_locations: Optional[List[str]] = Form(None),
    selected_factions: Optional[List[str]] = Form(None),
    selected_items: Optional[List[str]] = Form(None),
    selected_creatures: Optional[List[str]] = Form(None),
    selected_plot_threads: Optional[List[str]] = Form(None),
    return_to: Optional[str] = Form(None),
    new_faction: dict = Depends(optional_new_faction_form),
    db: Session = Depends(get_session),
):
    session_model = get_entity_or_none(db, SessionModel, campaign_id, session_id)
    if not session_model:
        return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)
    session_model.title = title
    session_model.date = date
    session_model.notes = notes
    session_model.player_recap = player_recap
    session_model.recap = recap
    session_model.analysis = analysis
    session_model.next_session_prep = next_session_prep
    session_model.next_session_prep_manually_edited = True
    replace_many_to_many_links(
        db,
        session_model.id,
        SessionNPCLink,
        "session_id",
        "npc_id",
        load_campaign_entities_by_ids(db, NPC, campaign_id, selected_npcs),
    )
    replace_many_to_many_links(
        db,
        session_model.id,
        SessionLocationLink,
        "session_id",
        "location_id",
        load_campaign_entities_by_ids(db, Location, campaign_id, selected_locations),
    )
    replace_many_to_many_links(
        db,
        session_model.id,
        SessionFactionLink,
        "session_id",
        "faction_id",
        load_factions_for_link(
            db,
            campaign_id,
            selected_factions,
            new_faction_name=new_faction["name"],
            new_faction_type=new_faction["type"],
            new_faction_type_custom=new_faction["type_custom"],
        ),
    )
    replace_many_to_many_links(
        db,
        session_model.id,
        SessionItemLink,
        "session_id",
        "item_id",
        load_campaign_entities_by_ids(db, Item, campaign_id, selected_items),
    )
    replace_many_to_many_links(
        db,
        session_model.id,
        SessionCreatureLink,
        "session_id",
        "creature_id",
        load_campaign_entities_by_ids(db, Creature, campaign_id, selected_creatures),
    )
    replace_many_to_many_links(
        db,
        session_model.id,
        SessionPlotThreadLink,
        "session_id",
        "plot_thread_id",
        load_campaign_entities_by_ids(db, PlotThread, campaign_id, selected_plot_threads),
    )
    db.add(session_model)
    db.commit()
    refresh_session_link_metadata(db, campaign_id, session_id)
    db.commit()
    return RedirectResponse(
        url=redirect_after_session_edit(campaign_id, session_id, return_to),
        status_code=303,
    )


@router.get("/campaigns/{campaign_id}/sessions/{session_id}/delete", response_class=HTMLResponse)
def delete_session_confirm(request: Request, campaign_id: int, session_id: int, db: Session = Depends(get_session)):
    campaign = get_campaign_or_none(db, campaign_id)
    session_model = get_entity_or_none(db, SessionModel, campaign_id, session_id)
    if not campaign or not session_model:
        return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)
    return templates.TemplateResponse(
        "confirm_delete.html",
        confirm_delete_context(
            db,
            request,
            campaign,
            {
            "title": "Delete Session",
            "message": f"Are you sure you want to delete '{session_model.title}'? This cannot be undone.",
            "action": f"/campaigns/{campaign_id}/sessions/{session_id}/delete",
            },
        ),
    )


@router.post("/campaigns/{campaign_id}/sessions/{session_id}/delete")
def delete_session(campaign_id: int, session_id: int, db: Session = Depends(get_session)):
    session_model = get_entity_or_none(db, SessionModel, campaign_id, session_id)
    if session_model:
        delete_session_cascade(db, session_model)
        db.commit()
    return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)


@router.post("/campaigns/{campaign_id}/sessions")
def create_session(
    request: Request,
    campaign_id: int,
    title: str = Form(...),
    date: str = Form(""),
    notes: str = Form(""),
    session: Session = Depends(get_session),
):
    session_model = SessionModel(campaign_id=campaign_id, title=title, date=date, notes=notes)
    session.add(session_model)
    session.commit()
    return htmx_or_redirect(
        request,
        f"/campaigns/{campaign_id}",
        render_sessions_section(request, campaign_id, session),
    )


@router.get("/campaigns/{campaign_id}/sessions/{session_id}", response_class=HTMLResponse)
def session_detail(
    request: Request,
    campaign_id: int,
    session_id: int,
    hub_message: Optional[str] = Query(None),
    db: Session = Depends(get_session),
):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        return RedirectResponse(url="/", status_code=303)

    session_model = db.get(SessionModel, session_id)
    if not session_model or session_model.campaign_id != campaign_id:
        return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)

    hub_text = None
    if hub_message == "created":
        hub_text = (
            "Session created from ingest. Run analysis here in Session Workflow, "
            "or open Workspace for live prep."
        )
    elif hub_message == "updated":
        hub_text = (
            "Session updated from ingest. Notes and session entity links were replaced. "
            "Run analysis here if needed, or open Workspace for live prep."
        )

    return templates.TemplateResponse(
        "session_detail.html",
        _session_detail_context(request, db, campaign, session_model, hub_message=hub_text),
    )


@router.get("/campaigns/{campaign_id}/sessions/{session_id}/player", response_class=HTMLResponse)
def session_player_view(request: Request, campaign_id: int, session_id: int, db: Session = Depends(get_session)):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        return RedirectResponse(url="/", status_code=303)

    session_model = db.get(SessionModel, session_id)
    if not session_model or session_model.campaign_id != campaign_id:
        return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)

    return templates.TemplateResponse(
        "session_player.html",
        with_mc(
            db,
            {"request": request, "campaign": campaign, "session": session_model},
            request=request,
            campaign=campaign,
            session=session_model,
            active_nav="sessions",
            layout="dashboard",
        ),
    )


@router.post("/campaigns/{campaign_id}/sessions/{session_id}/notes")
def update_session_notes(
    request: Request,
    campaign_id: int,
    session_id: int,
    notes: str = Form(""),
    db: Session = Depends(get_session),
):
    session_model = db.get(SessionModel, session_id)
    if not session_model or session_model.campaign_id != campaign_id:
        return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)

    session_model.notes = notes
    db.add(session_model)
    db.commit()
    return RedirectResponse(url=f"/campaigns/{campaign_id}/sessions/{session_id}", status_code=303)


@router.post("/campaigns/{campaign_id}/sessions/{session_id}/prep")
def save_session_prep(
    campaign_id: int,
    session_id: int,
    next_session_prep: str = Form(""),
    db: Session = Depends(get_session),
):
    session_model = db.get(SessionModel, session_id)
    if not session_model or session_model.campaign_id != campaign_id:
        return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)

    session_model.next_session_prep = next_session_prep
    session_model.next_session_prep_manually_edited = True
    session_model.updated_at = utc_now()
    db.add(session_model)
    db.commit()
    return RedirectResponse(url=f"/campaigns/{campaign_id}/sessions/{session_id}", status_code=303)


@router.post("/campaigns/{campaign_id}/sessions/{session_id}/ai-drafts", response_class=HTMLResponse)
def save_session_ai_drafts(
    request: Request,
    campaign_id: int,
    session_id: int,
    player_recap: str = Form(""),
    recap: str = Form(""),
    analysis: str = Form(""),
    next_session_prep: str = Form(""),
    db: Session = Depends(get_session),
):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        return RedirectResponse(url="/", status_code=303)

    session_model = db.get(SessionModel, session_id)
    if not session_model or session_model.campaign_id != campaign_id:
        return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)

    session_model.player_recap = player_recap or None
    session_model.recap = recap or None
    session_model.analysis = analysis or None
    session_model.next_session_prep = next_session_prep or None
    session_model.next_session_prep_manually_edited = True
    session_model.updated_at = utc_now()
    db.add(session_model)
    db.commit()
    db.refresh(session_model)

    return templates.TemplateResponse(
        "session_detail.html",
        _session_detail_context(
            request,
            db,
            campaign,
            session_model,
            workflow_message="AI drafts saved.",
        ),
    )


@router.post("/campaigns/{campaign_id}/sessions/{session_id}/save-and-analyze", response_class=HTMLResponse)
def save_and_analyze_session(
    request: Request,
    campaign_id: int,
    session_id: int,
    notes: str = Form(""),
    db: Session = Depends(get_session),
):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        return RedirectResponse(url="/", status_code=303)

    session_model = db.get(SessionModel, session_id)
    if not session_model or session_model.campaign_id != campaign_id:
        return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)

    session_model.notes = notes
    db.add(session_model)
    db.commit()

    analysis_result, analysis_warning = _run_session_analysis(
        db, campaign, session_model, notes, session_id
    )
    session_model.updated_at = utc_now()
    db.add(session_model)
    db.commit()
    db.refresh(session_model)

    if analysis_result and analysis_result.get("fields_extracted"):
        workflow_message = "Notes saved and AI recaps/analysis updated."
    else:
        workflow_message = "Notes saved."

    return templates.TemplateResponse(
        "session_detail.html",
        _session_detail_context(
            request,
            db,
            campaign,
            session_model,
            analysis_result=analysis_result,
            analysis_warning=analysis_warning,
            workflow_message=workflow_message,
        ),
    )


@router.post("/campaigns/{campaign_id}/sessions/{session_id}/generate-prep", response_class=HTMLResponse)
def generate_session_prep_from_session(
    request: Request,
    campaign_id: int,
    session_id: int,
    notes: str = Form(""),
    confirm_overwrite: Optional[str] = Form(None),
    db: Session = Depends(get_session),
):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        return RedirectResponse(url="/", status_code=303)

    session_model = db.get(SessionModel, session_id)
    if not session_model or session_model.campaign_id != campaign_id:
        return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)

    session_model.notes = notes
    db.add(session_model)
    db.commit()

    prep_warning = None
    if not session_has_analysis(session_model):
        prep_warning = "No analysis exists yet; generating prep from notes and campaign context."

    context_notes = (session_model.notes or "").strip()
    if not context_notes:
        return templates.TemplateResponse(
            "session_detail.html",
            _session_detail_context(
                request,
                db,
                campaign,
                session_model,
                prep_message="Add session notes before generating prep.",
            ),
        )

    if prep_overwrite_requires_confirmation(session_model) and confirm_overwrite != "1":
        return templates.TemplateResponse(
            "session_detail.html",
            _session_detail_context(
                request,
                db,
                campaign,
                session_model,
                prep_overwrite_confirmation={
                    "existing_prep_preview": (session_model.next_session_prep or "")[:500],
                },
                prep_warning=prep_warning,
            ),
        )

    if not llm_available():
        message = "LLM provider not configured; cannot generate prep."
        if gemini_is_disabled():
            message = "Gemini is disabled (GEMINI_DISABLED=true); cannot generate prep."
        return templates.TemplateResponse(
            "session_detail.html",
            _session_detail_context(
                request,
                db,
                campaign,
                session_model,
                prep_message=message,
                prep_warning=prep_warning,
            ),
        )

    prep_message, prep_result, prep_draft = run_future_prep_generation(
        db,
        campaign_id,
        session_model,
        context_notes,
        save_to_session=False,
        task_name="sessions/generate-prep",
    )
    session_model.updated_at = utc_now()
    db.commit()
    db.refresh(session_model)

    return templates.TemplateResponse(
        "session_detail.html",
        _session_detail_context(
            request,
            db,
            campaign,
            session_model,
            prep_draft=prep_draft,
            prep_warning=prep_warning,
            prep_message=prep_message,
            prep_result=prep_result,
        ),
    )


@router.post("/campaigns/{campaign_id}/sessions/{session_id}/clear-ai-fields")
def clear_session_ai_fields_route(campaign_id: int, session_id: int, db: Session = Depends(get_session)):
    session_model = db.get(SessionModel, session_id)
    if not session_model or session_model.campaign_id != campaign_id:
        return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)

    clear_session_ai_fields(session_model)
    session_model.updated_at = utc_now()
    db.add(session_model)
    db.commit()
    return RedirectResponse(url=f"/campaigns/{campaign_id}/sessions/{session_id}", status_code=303)


@router.post("/campaigns/{campaign_id}/sessions/{session_id}/narrative-suggestions")
def apply_narrative_suggestions(
    campaign_id: int,
    session_id: int,
    approved_scenes: Optional[List[str]] = Form(None),
    approved_encounters: Optional[List[str]] = Form(None),
    approved_objectives: Optional[List[str]] = Form(None),
    db: Session = Depends(get_session),
):
    from app.services.narrative_blocks import create_encounter, create_objective, create_scene

    campaign = db.get(Campaign, campaign_id)
    session_model = db.get(SessionModel, session_id)
    if not campaign or not session_model or session_model.campaign_id != campaign_id:
        return RedirectResponse(url="/", status_code=303)

    for title in approved_scenes or []:
        if title.strip():
            create_scene(db, campaign_id, session_id=session_id, title=title.strip())
    for row in approved_encounters or []:
        if "|" in row:
            title, enc_type = row.split("|", 1)
            create_encounter(
                db,
                campaign_id,
                session_id=session_id,
                title=title.strip(),
                encounter_type=enc_type.strip() or "other",
            )
    for row in approved_objectives or []:
        if "|" in row:
            title, priority = row.split("|", 1)
            create_objective(
                db,
                campaign_id,
                session_id=session_id,
                title=title.strip(),
                priority=priority.strip() or "normal",
            )
    db.commit()
    return RedirectResponse(
        url=f"/campaigns/{campaign_id}/workspace?session_id={session_id}&mode=prep",
        status_code=303,
    )


@router.post("/campaigns/{campaign_id}/sessions/{session_id}/analyze", response_class=HTMLResponse)
def analyze_session_notes(request: Request, campaign_id: int, session_id: int, db: Session = Depends(get_session)):
    """Backward-compatible alias: analyzes using notes already saved on the session."""
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        return RedirectResponse(url="/", status_code=303)

    session_model = db.get(SessionModel, session_id)
    if not session_model or session_model.campaign_id != campaign_id:
        return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)

    notes = session_model.notes or ""
    analysis_result, analysis_warning = _run_session_analysis(
        db, campaign, session_model, notes, session_id
    )
    session_model.updated_at = utc_now()
    db.add(session_model)
    db.commit()
    db.refresh(session_model)

    return templates.TemplateResponse(
        "session_detail.html",
        _session_detail_context(
            request,
            db,
            campaign,
            session_model,
            analysis_result=analysis_result,
            analysis_warning=analysis_warning,
        ),
    )
