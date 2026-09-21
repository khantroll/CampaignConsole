from typing import Optional

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from app.database import get_session
from app.deps import get_campaign_or_none, sort_sessions_chronologically, templates
from app.models import Campaign, SessionModel
from app.services.campaign_deletion import delete_campaign_cascade
from app.services.campaign_dashboard import build_campaign_dashboard_summary
from app.services.campaign_intelligence import load_campaign_briefing_data
from app.services.entity_health import prepare_entity_lists
from app.services.location_classification import LOCATION_TYPE_CHOICES, location_type_label
from app.services.faction_classification import FACTION_TYPE_CHOICES, faction_type_label
from app.services.item_classification import build_item_type_options, item_type_label
from app.services.creature_classification import CREATURE_TYPE_CHOICES, creature_type_label
from app.services.mission_control_ui import mc_context, with_mc, workspace_url

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def home(request: Request, session: Session = Depends(get_session)):
    ctx = mc_context(session, layout="minimal", include_campaigns=True)
    ctx["request"] = request
    return templates.TemplateResponse("campaigns.html", ctx)


@router.post("/campaigns")
def create_campaign(
    request: Request,
    name: str = Form(...),
    system: str = Form(""),
    description: str = Form(""),
    session: Session = Depends(get_session),
):
    campaign = Campaign(name=name, system=system, description=description)
    session.add(campaign)
    session.commit()
    session.refresh(campaign)
    return RedirectResponse(url=workspace_url(campaign.id), status_code=303)


@router.get("/campaigns/{campaign_id}", response_class=HTMLResponse)
def campaign_detail(
    request: Request,
    campaign_id: int,
    location_filter: str = Query("major_sub"),
    entity_sort: str = Query("name"),
    session: Session = Depends(get_session),
):
    campaign = session.get(Campaign, campaign_id)
    if not campaign:
        return RedirectResponse(url="/", status_code=303)

    campaign = session.exec(select(Campaign).where(Campaign.id == campaign_id)).one()
    sessions = session.exec(
        select(SessionModel).where(SessionModel.campaign_id == campaign_id).order_by(SessionModel.id)
    ).all()

    _health_service, entity_context = prepare_entity_lists(
        session,
        campaign_id,
        location_filter=location_filter,
        entity_sort=entity_sort,
    )

    entity_lists = {
        "npcs": entity_context["npcs"],
        "locations": entity_context["locations"],
        "factions": entity_context["factions"],
        "items": entity_context["items"],
        "creatures": entity_context["creatures"],
        "threads": entity_context["threads"],
        "pcs": entity_context["pc_notes"],
    }
    dashboard_summary = build_campaign_dashboard_summary(
        session,
        campaign_id,
        request=request,
        health_maps=entity_context["health_maps"],
        entity_lists=entity_lists,
    )

    return templates.TemplateResponse(
        "campaign_detail.html",
        with_mc(
            session,
            {
                "request": request,
                "campaign": campaign,
                "sessions": sessions,
                "npcs": entity_context["npcs"],
                "locations": entity_context["locations"],
                "location_filter": location_filter,
                "location_type_label": location_type_label,
                "location_type_choices": LOCATION_TYPE_CHOICES,
                "faction_type_label": faction_type_label,
                "faction_type_choices": FACTION_TYPE_CHOICES,
                "item_type_label": item_type_label,
                "item_type_options": build_item_type_options(session, campaign_id),
                "creature_type_label": creature_type_label,
                "factions": entity_context["factions"],
                "items": entity_context["items"],
                "creatures": entity_context["creatures"],
                "threads": entity_context["threads"],
                "pc_notes": entity_context["pc_notes"],
                "health_maps": entity_context["health_maps"],
                "entity_sort": entity_sort,
                "completeness_overview": entity_context["completeness_overview"],
                "entity_type_badges": entity_context["entity_type_badges"],
                "dashboard_summary": dashboard_summary,
                "session_lookup": {s.id: s for s in sessions if s.id},
            },
            request=request,
            campaign=campaign,
            active_nav="dashboard",
            layout="dashboard",
        ),
    )


@router.get("/campaigns/{campaign_id}/briefing", response_class=HTMLResponse)
def campaign_briefing(
    request: Request,
    campaign_id: int,
    message: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    campaign = get_campaign_or_none(session, campaign_id)
    if not campaign:
        return RedirectResponse(url="/", status_code=303)

    briefing = load_campaign_briefing_data(session, campaign_id, request=request)
    dashboard_summary = briefing.get("dashboard_summary")

    return templates.TemplateResponse(
        "campaign_briefing.html",
        with_mc(
            session,
            {
                "request": request,
                "campaign": campaign,
                "briefing": briefing,
                "dashboard_summary": dashboard_summary,
                "message": message,
            },
            request=request,
            campaign=campaign,
            active_nav="dashboard",
            layout="dashboard",
        ),
    )


@router.post("/campaigns/{campaign_id}/briefing/generate-narrative")
def campaign_briefing_generate_narrative(
    request: Request,
    campaign_id: int,
    session: Session = Depends(get_session),
):
    from app.services.briefing_narrative import generate_ai_briefing_narrative, save_ai_briefing_narrative

    campaign = get_campaign_or_none(session, campaign_id)
    if not campaign:
        return RedirectResponse(url="/", status_code=303)

    briefing = load_campaign_briefing_data(session, campaign_id, request=request)
    text, error = generate_ai_briefing_narrative(campaign, briefing)
    if error:
        from urllib.parse import quote

        return RedirectResponse(
            url=f"/campaigns/{campaign_id}/briefing?message={quote(error)}",
            status_code=303,
        )

    save_ai_briefing_narrative(session, campaign, text)
    session.commit()
    return RedirectResponse(url=f"/campaigns/{campaign_id}/briefing?message=ai_narrative_saved", status_code=303)


@router.get("/campaigns/{campaign_id}/briefing/print", response_class=HTMLResponse)
def campaign_briefing_print(
    request: Request,
    campaign_id: int,
    session: Session = Depends(get_session),
):
    campaign = get_campaign_or_none(session, campaign_id)
    if not campaign:
        return RedirectResponse(url="/", status_code=303)

    briefing = load_campaign_briefing_data(session, campaign_id, request=request)
    from app.utils.time import utc_now

    return templates.TemplateResponse(
        "campaign_briefing_print.html",
        {
            "request": request,
            "campaign": campaign,
            "briefing": briefing,
            "generated_at": utc_now().strftime("%Y-%m-%d %H:%M UTC"),
        },
    )


@router.get("/campaigns/{campaign_id}/timeline", response_class=HTMLResponse)
def campaign_timeline(request: Request, campaign_id: int, db: Session = Depends(get_session)):
    campaign = get_campaign_or_none(db, campaign_id)
    if not campaign:
        return RedirectResponse(url="/", status_code=303)

    sessions = sort_sessions_chronologically(
        db.exec(select(SessionModel).where(SessionModel.campaign_id == campaign_id)).all()
    )

    return templates.TemplateResponse(
        "timeline.html",
        with_mc(
            db,
            {"request": request, "campaign": campaign, "sessions": sessions},
            request=request,
            campaign=campaign,
            active_nav="timeline",
            layout="dashboard",
        ),
    )


@router.get("/campaigns/{campaign_id}/delete", response_class=HTMLResponse)
def delete_campaign_confirm(request: Request, campaign_id: int, session: Session = Depends(get_session)):
    campaign = session.get(Campaign, campaign_id)
    if not campaign:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        "confirm_delete.html",
        with_mc(
            session,
            {
                "request": request,
                "title": "Delete Campaign",
                "message": (
                    f"Are you sure you want to delete '{campaign.name}' and all sessions, entities, "
                    "and lore index data? This cannot be undone."
                ),
                "action": f"/campaigns/{campaign_id}/delete",
                "cancel_url": f"/campaigns/{campaign_id}",
            },
            request=request,
            campaign=campaign,
            active_nav="dashboard",
            layout="dashboard",
        ),
    )


@router.post("/campaigns/{campaign_id}/delete")
def delete_campaign(campaign_id: int, session: Session = Depends(get_session)):
    try:
        delete_campaign_cascade(session, campaign_id)
    except ValueError:
        pass
    return RedirectResponse(url="/", status_code=303)
