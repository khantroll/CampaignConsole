"""Shared helpers for campaign detail HTMX partial responses."""

from typing import Any, Dict, List, Tuple

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from app.deps import templates
from app.services.entity_health import ENTITY_TYPE_BADGES, CampaignEntityHealth, sort_entities
from app.services.location_classification import filter_locations_by_type, location_type_label
from app.services.faction_classification import faction_type_label
from app.services.item_classification import build_item_type_options, item_type_label
from app.services.creature_classification import creature_type_label
from app.models import (
    Creature,
    Faction,
    Item,
    Location,
    NPC,
    PlayerCharacterNote,
    PlotThread,
    SessionModel,
)

ENTITY_SECTIONS: Dict[str, Dict[str, Any]] = {
    "npcs": {
        "title": "NPCs",
        "model": NPC,
        "fields": [("name", "Name"), ("role", "Role"), ("description", "Description")],
        "add_label": "Add NPC",
    },
    "locations": {
        "title": "Locations",
        "model": Location,
        "fields": [
            ("name", "Name"),
            ("location_type", "Type"),
            ("description", "Description"),
            ("notes", "Notes"),
        ],
        "add_label": "Add Location",
    },
    "factions": {
        "title": "Factions",
        "model": Faction,
        "fields": [
            ("name", "Name"),
            ("faction_type", "Type"),
            ("summary", "Description"),
            ("plot_notes", "Plot Notes"),
        ],
        "add_label": "Add Faction",
    },
    "items": {
        "title": "Items",
        "model": Item,
        "fields": [
            ("name", "Name"),
            ("item_type", "Type"),
            ("description", "Description"),
            ("origin", "Origin"),
            ("plot_notes", "Plot Notes"),
        ],
        "add_label": "Add Item",
    },
    "creatures": {
        "title": "Creatures",
        "model": Creature,
        "fields": [
            ("name", "Name"),
            ("classification", "Classification"),
            ("habitat", "Habitat"),
            ("threat_level", "Threat Level"),
            ("physical_description", "Physical Description"),
            ("special_traits", "Special Traits & Abilities"),
            ("campaign_context_tactics", "Campaign Context & Tactics"),
            ("notes", "Additional Notes"),
        ],
        "add_label": "Add Creature",
    },
    "threads": {
        "title": "Plot Threads",
        "model": PlotThread,
        "fields": [
            ("title", "Title"),
            ("thread_type", "Thread Type"),
            ("status", "Status"),
            ("details", "Description"),
            ("plot_significance_notes", "Plot Significance / Notes"),
        ],
        "add_label": "Add Plot Thread",
    },
    "pcs": {
        "title": "PC Notes",
        "model": PlayerCharacterNote,
        "fields": [
            ("character_name", "Character"),
            ("character_archetype", "Archetype"),
            ("description", "Description"),
            ("signature_gear", "Signature Gear"),
            ("key_ties_history", "Key Ties & History"),
            ("campaign_role_plot_notes", "Campaign Role & Plot Notes"),
            ("notes", "Additional Notes"),
        ],
        "add_label": "Add PC Note",
    },
}


def is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def htmx_or_redirect(request: Request, redirect_url: str, partial: HTMLResponse):
    if is_htmx(request):
        return partial
    return RedirectResponse(url=redirect_url, status_code=303)


def render_sessions_section(request: Request, campaign_id: int, db: Session) -> HTMLResponse:
    sessions = db.exec(
        select(SessionModel).where(SessionModel.campaign_id == campaign_id).order_by(SessionModel.id)
    ).all()
    return templates.TemplateResponse(
        "partials/campaign_sessions_section.html",
        {
            "request": request,
            "campaign_id": campaign_id,
            "sessions": sessions,
        },
    )


def render_entity_section(request: Request, campaign_id: int, db: Session, section_key: str) -> HTMLResponse:
    config = ENTITY_SECTIONS[section_key]
    items = db.exec(
        select(config["model"]).where(config["model"].campaign_id == campaign_id)
    ).all()
    if section_key == "locations":
        items = filter_locations_by_type(items, "major_sub")
    health_service = CampaignEntityHealth(db, campaign_id)
    health_map = health_service.health_map(section_key, items)
    items = sort_entities(section_key, items, health_map, "name")
    from app.services.entity_session_presence import hydrate_last_seen_for_display

    hydrate_last_seen_for_display(db, campaign_id, section_key, items)
    sessions = db.exec(
        select(SessionModel).where(SessionModel.campaign_id == campaign_id).order_by(SessionModel.id)
    ).all()
    return templates.TemplateResponse(
        "partials/campaign_entity_section.html",
        {
            "request": request,
            "campaign_id": campaign_id,
            "section_key": section_key,
            "section_title": config["title"],
            "items": items,
            "action": section_key,
            "fields": config["fields"],
            "add_label": config["add_label"],
            "form_name": f"add-{section_key}",
            "location_filter": "major_sub",
            "location_type_label": location_type_label,
            "faction_type_label": faction_type_label,
            "item_type_label": item_type_label,
            "item_type_options": build_item_type_options(db, campaign_id),
            "creature_type_label": creature_type_label,
            "health_map": health_map,
            "entity_sort": "name",
            "entity_type_badges": ENTITY_TYPE_BADGES,
            "session_lookup": {s.id: s for s in sessions if s.id},
        },
    )


def entity_item_detail(item: Any) -> str:
    return (
        getattr(item, "description", None)
        or getattr(item, "summary", None)
        or getattr(item, "details", None)
        or getattr(item, "notes", None)
        or "No details yet"
    )


def entity_item_title(item: Any) -> str:
    return getattr(item, "name", None) or getattr(item, "title", "") or ""


def entity_item_subtitle(item: Any) -> str:
    return getattr(item, "role", None) or getattr(item, "status", None) or ""
