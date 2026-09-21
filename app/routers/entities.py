from typing import List, Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from app.database import get_session
from app.deps import get_campaign_or_none, get_entity_or_none, optional_new_faction_form, related_options, templates
from app.models import (
    Creature,
    CreatureFactionLink,
    CreatureLocationLink,
    CreaturePlotThreadLink,
    Faction,
    FactionPlotThreadLink,
    Item,
    ItemFactionLink,
    ItemLocationLink,
    ItemNPCLink,
    ItemPlotThreadLink,
    Location,
    LocationFactionLink,
    LocationPlotThreadLink,
    LocationRelatedLocationLink,
    NPC,
    NPCFactionLink,
    NPCLocationLink,
    NPCPlotThreadLink,
    PCLocationLink,
    PCFactionLink,
    PCPlotThreadLink,
    PlayerCharacterNote,
    PlotThread,
    PlotThreadRelatedPlotThreadLink,
)
from app.services.entity_links import (
    load_campaign_entities_by_ids,
    load_factions_for_link,
    related_ids_from_links,
    replace_many_to_many_links,
)
from app.services.entity_deletion import (
    delete_creature_cascade,
    delete_faction_cascade,
    delete_item_cascade,
    delete_location_cascade,
    delete_npc_cascade,
    delete_plot_thread_cascade,
)
from app.services.campaign_ui import (
    htmx_or_redirect,
    render_entity_section,
)
from app.services.location_classification import LOCATION_TYPE_CHOICES, LOCATION_TYPE_MAJOR, normalize_location_type
from app.services.faction_classification import (
    FACTION_TYPE_CHOICES,
    FACTION_TYPE_OTHER,
    faction_type_form_values,
    resolve_faction_type,
)
from app.services.creature_classification import (
    resolve_creature_type,
)
from app.services.item_classification import (
    ITEM_TYPE_OTHER,
    build_item_type_options,
    item_owner_options,
    item_type_form_values,
    parse_item_owner,
    resolve_item_type,
)
from app.services.mission_control_ui import confirm_delete_context, entity_form_context, redirect_after_entity_save, resolve_entity_edit_session_id
from app.services.entity_form_fields import (
    creature_profile_fields,
    faction_profile_fields,
    item_profile_fields,
    location_entity_select_field,
    location_profile_fields,
    npc_profile_fields,
    plot_thread_profile_fields,
)
from app.services.entity_field_choices import (
    HABITAT_LABELS,
    PLOT_THREAD_TYPE_LABELS,
    THREAT_LEVEL_LABELS,
    resolve_preset_or_custom,
    resolve_primary_location_text,
)
from app.services.world_state import (
    apply_mystery_fields,
    apply_world_status_fields,
)

router = APIRouter()


def _entity_save_redirect(campaign_id: int, return_to: Optional[str] = None) -> RedirectResponse:
    return RedirectResponse(url=redirect_after_entity_save(campaign_id, return_to), status_code=303)


@router.get("/campaigns/{campaign_id}/npcs/{npc_id}/edit", response_class=HTMLResponse)
def edit_npc(request: Request, campaign_id: int, npc_id: int, db: Session = Depends(get_session)):
    campaign = get_campaign_or_none(db, campaign_id)
    npc = get_entity_or_none(db, NPC, campaign_id, npc_id)
    if not campaign or not npc:
        return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)

    factions = db.exec(select(Faction).where(Faction.campaign_id == campaign_id)).all()
    locations = db.exec(select(Location).where(Location.campaign_id == campaign_id)).all()
    threads = db.exec(select(PlotThread).where(PlotThread.campaign_id == campaign_id)).all()
    flash_message = request.query_params.get("message")

    return templates.TemplateResponse(
        "entity_form.html",
        entity_form_context(
            db,
            request,
            campaign,
            {
            "title": "Edit NPC",
            "message": flash_message,
            "action": f"/campaigns/{campaign_id}/npcs/{npc_id}/edit",
            "entity": npc,
            "fields": npc_profile_fields(npc, locations),
            "select_fields": [
                {
                    "name": "selected_factions",
                    "label": "Related Factions",
                    "options": related_options(
                        factions,
                        related_ids_from_links(db, NPCFactionLink, "npc_id", npc.id, "faction_id"),
                    ),
                },
                {
                    "name": "selected_locations",
                    "label": "Related Locations",
                    "options": related_options(
                        locations,
                        related_ids_from_links(db, NPCLocationLink, "npc_id", npc.id, "location_id"),
                    ),
                },
                {
                    "name": "selected_plot_threads",
                    "label": "Related Plot Threads",
                    "options": related_options(
                        threads,
                        related_ids_from_links(db, NPCPlotThreadLink, "npc_id", npc.id, "plot_thread_id"),
                    ),
                },
            ],
            "submit_label": "Save NPC",
            "convert_action": {
                "url": f"/campaigns/{campaign_id}/npcs/{npc_id}/convert-to-pc",
                "label": "Convert to PC",
                "confirm": f"Convert {npc.name} to a party member (PC)? Session and location links will be preserved.",
            },
            },
            entity_section_key="npcs",
        ),
    )


@router.post("/campaigns/{campaign_id}/npcs/{npc_id}/edit")
def update_npc(
    request: Request,
    campaign_id: int,
    npc_id: int,
    name: str = Form(...),
    role: str = Form(""),
    description: str = Form(""),
    world_status: str = Form("unknown"),
    state_notes: str = Form(""),
    current_location_id: str = Form(""),
    current_location_custom: str = Form(""),
    relationship_to_party: str = Form(""),
    goals: str = Form(""),
    secrets: str = Form(""),
    selected_factions: Optional[List[str]] = Form(None),
    selected_locations: Optional[List[str]] = Form(None),
    selected_plot_threads: Optional[List[str]] = Form(None),
    return_to: Optional[str] = Form(None),
    new_faction: dict = Depends(optional_new_faction_form),
    db: Session = Depends(get_session),
):
    npc = get_entity_or_none(db, NPC, campaign_id, npc_id)
    if not npc:
        return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)
    locations = db.exec(select(Location).where(Location.campaign_id == campaign_id)).all()
    npc.name = name
    npc.role = role
    npc.description = description
    apply_world_status_fields(npc, "npcs", world_status, state_notes)
    npc.current_location = resolve_primary_location_text(locations, current_location_id, current_location_custom)
    npc.relationship_to_party = relationship_to_party
    npc.goals = goals
    npc.secrets = secrets
    relationship_session_id = resolve_entity_edit_session_id(db, request, campaign_id, return_to)
    replace_many_to_many_links(
        db,
        npc.id,
        NPCFactionLink,
        "npc_id",
        "faction_id",
        load_factions_for_link(
            db,
            campaign_id,
            selected_factions,
            new_faction_name=new_faction["name"],
            new_faction_type=new_faction["type"],
            new_faction_type_custom=new_faction["type_custom"],
        ),
        campaign_id=campaign_id,
        owner_kind="npcs",
        related_kind="factions",
        session_id=relationship_session_id,
    )
    replace_many_to_many_links(
        db,
        npc.id,
        NPCLocationLink,
        "npc_id",
        "location_id",
        load_campaign_entities_by_ids(db, Location, campaign_id, selected_locations),
        campaign_id=campaign_id,
        owner_kind="npcs",
        related_kind="locations",
        session_id=relationship_session_id,
    )
    replace_many_to_many_links(
        db,
        npc.id,
        NPCPlotThreadLink,
        "npc_id",
        "plot_thread_id",
        load_campaign_entities_by_ids(db, PlotThread, campaign_id, selected_plot_threads),
        campaign_id=campaign_id,
        owner_kind="npcs",
        related_kind="threads",
        session_id=relationship_session_id,
    )
    db.add(npc)
    db.commit()
    return _entity_save_redirect(campaign_id, return_to)


@router.post("/campaigns/{campaign_id}/npcs/{npc_id}/convert-to-pc")
def convert_npc_to_pc_route(
    request: Request,
    campaign_id: int,
    npc_id: int,
    return_to: Optional[str] = Form(None),
    db: Session = Depends(get_session),
):
    from urllib.parse import quote

    from app.services.character_conversion import convert_npc_to_pc

    npc = get_entity_or_none(db, NPC, campaign_id, npc_id)
    if not npc:
        return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)

    pc, warning = convert_npc_to_pc(db, npc)
    db.commit()

    url = f"/campaigns/{campaign_id}/pcs/{pc.id}/edit"
    params = []
    if return_to:
        params.append(f"return_to={quote(return_to, safe='')}")
    if warning:
        params.append(f"message={quote(warning)}")
    if params:
        url = f"{url}?{'&'.join(params)}"
    return RedirectResponse(url=url, status_code=303)


@router.get("/campaigns/{campaign_id}/npcs/{npc_id}/delete", response_class=HTMLResponse)
def delete_npc_confirm(request: Request, campaign_id: int, npc_id: int, db: Session = Depends(get_session)):
    campaign = get_campaign_or_none(db, campaign_id)
    npc = get_entity_or_none(db, NPC, campaign_id, npc_id)
    if not npc or not campaign:
        return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)
    return templates.TemplateResponse(
        "confirm_delete.html",
        confirm_delete_context(
            db,
            request,
            campaign,
            {
            "title": "Delete NPC",
            "message": f"Are you sure you want to delete '{npc.name}'? This cannot be undone.",
            "action": f"/campaigns/{campaign_id}/npcs/{npc_id}/delete",
            },
        ),
    )


@router.post("/campaigns/{campaign_id}/npcs/{npc_id}/delete")
def delete_npc(campaign_id: int, npc_id: int, db: Session = Depends(get_session)):
    npc = get_entity_or_none(db, NPC, campaign_id, npc_id)
    if npc:
        delete_npc_cascade(db, npc)
        db.commit()
    return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)


@router.get("/campaigns/{campaign_id}/locations/{location_id}/edit", response_class=HTMLResponse)
def edit_location(request: Request, campaign_id: int, location_id: int, db: Session = Depends(get_session)):
    campaign = get_campaign_or_none(db, campaign_id)
    location = get_entity_or_none(db, Location, campaign_id, location_id)
    if not campaign or not location:
        return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)
    factions = db.exec(select(Faction).where(Faction.campaign_id == campaign_id)).all()
    threads = db.exec(select(PlotThread).where(PlotThread.campaign_id == campaign_id)).all()
    npcs = db.exec(select(NPC).where(NPC.campaign_id == campaign_id)).all()
    creatures = db.exec(select(Creature).where(Creature.campaign_id == campaign_id)).all()
    all_locations = db.exec(select(Location).where(Location.campaign_id == campaign_id)).all()
    from app.services.location_links import load_related_location_options

    related_location_options = load_related_location_options(db, campaign_id, location.id)
    related_location_empty_hint = None
    if not related_location_options:
        if len(all_locations) <= 1:
            related_location_empty_hint = (
                "Add at least one more location on the Lore Board before you can link related places."
            )
        else:
            related_location_empty_hint = "No other locations available to link."

    return templates.TemplateResponse(
        "entity_form.html",
        entity_form_context(
            db,
            request,
            campaign,
            {
            "title": "Edit Location",
            "action": f"/campaigns/{campaign_id}/locations/{location_id}/edit",
            "entity": location,
            "fields": [
                {"name": "name", "label": "Name", "type": "text", "required": True},
                {
                    "name": "location_type",
                    "label": "Location Type",
                    "type": "select",
                    "options": [{"value": value, "label": label} for value, label in LOCATION_TYPE_CHOICES],
                },
                {"name": "description", "label": "Description", "type": "textarea", "rows": 3},
                {"name": "notes", "label": "Notes", "type": "textarea", "rows": 4},
            ] + location_profile_fields(location),
            "select_fields": [
                {
                    "name": "selected_related_locations",
                    "label": "Related Locations",
                    "options": related_location_options,
                    "empty_hint": related_location_empty_hint,
                },
                {
                    "name": "selected_npcs",
                    "label": "Key NPCs",
                    "options": related_options(
                        npcs,
                        related_ids_from_links(db, NPCLocationLink, "location_id", location.id, "npc_id"),
                    ),
                },
                {
                    "name": "selected_creatures",
                    "label": "Key Creatures",
                    "options": related_options(
                        creatures,
                        related_ids_from_links(db, CreatureLocationLink, "location_id", location.id, "creature_id"),
                    ),
                },
                {
                    "name": "selected_factions",
                    "label": "Related Factions",
                    "options": related_options(
                        factions,
                        related_ids_from_links(db, LocationFactionLink, "location_id", location.id, "faction_id"),
                    ),
                },
                {
                    "name": "selected_plot_threads",
                    "label": "Related Plot Threads",
                    "options": related_options(
                        threads,
                        related_ids_from_links(db, LocationPlotThreadLink, "location_id", location.id, "plot_thread_id"),
                    ),
                },
            ],
            "submit_label": "Save Location",
            },
            entity_section_key="locations",
        ),
    )


@router.post("/campaigns/{campaign_id}/locations/{location_id}/edit")
def update_location(
    request: Request,
    campaign_id: int,
    location_id: int,
    name: str = Form(...),
    description: str = Form(""),
    notes: str = Form(""),
    location_type: str = Form(LOCATION_TYPE_MAJOR),
    world_status: str = Form("unknown"),
    state_notes: str = Form(""),
    selected_related_locations: Optional[List[str]] = Form(None),
    selected_npcs: Optional[List[str]] = Form(None),
    selected_creatures: Optional[List[str]] = Form(None),
    selected_factions: Optional[List[str]] = Form(None),
    selected_plot_threads: Optional[List[str]] = Form(None),
    return_to: Optional[str] = Form(None),
    new_faction: dict = Depends(optional_new_faction_form),
    db: Session = Depends(get_session),
):
    location = get_entity_or_none(db, Location, campaign_id, location_id)
    if not location:
        return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)
    location.name = name
    location.description = description
    location.notes = notes.strip() or None
    location.location_type = normalize_location_type(location_type) or LOCATION_TYPE_MAJOR
    apply_world_status_fields(location, "locations", world_status, state_notes)
    relationship_session_id = resolve_entity_edit_session_id(db, request, campaign_id, return_to)
    from app.services.location_links import replace_location_related_links

    replace_location_related_links(
        db,
        campaign_id,
        location.id,
        load_campaign_entities_by_ids(db, Location, campaign_id, selected_related_locations),
        session_id=relationship_session_id,
    )
    replace_many_to_many_links(
        db,
        location.id,
        NPCLocationLink,
        "location_id",
        "npc_id",
        load_campaign_entities_by_ids(db, NPC, campaign_id, selected_npcs),
        campaign_id=campaign_id,
        owner_kind="locations",
        related_kind="npcs",
        session_id=relationship_session_id,
    )
    replace_many_to_many_links(
        db,
        location.id,
        CreatureLocationLink,
        "location_id",
        "creature_id",
        load_campaign_entities_by_ids(db, Creature, campaign_id, selected_creatures),
        campaign_id=campaign_id,
        owner_kind="locations",
        related_kind="creatures",
        session_id=relationship_session_id,
    )
    replace_many_to_many_links(
        db,
        location.id,
        LocationFactionLink,
        "location_id",
        "faction_id",
        load_factions_for_link(
            db,
            campaign_id,
            selected_factions,
            new_faction_name=new_faction["name"],
            new_faction_type=new_faction["type"],
            new_faction_type_custom=new_faction["type_custom"],
        ),
        campaign_id=campaign_id,
        owner_kind="locations",
        related_kind="factions",
        session_id=relationship_session_id,
    )
    replace_many_to_many_links(
        db,
        location.id,
        LocationPlotThreadLink,
        "location_id",
        "plot_thread_id",
        load_campaign_entities_by_ids(db, PlotThread, campaign_id, selected_plot_threads),
        campaign_id=campaign_id,
        owner_kind="locations",
        related_kind="threads",
        session_id=relationship_session_id,
    )
    db.add(location)
    db.commit()
    return _entity_save_redirect(campaign_id, return_to)


@router.get("/campaigns/{campaign_id}/locations/{location_id}/delete", response_class=HTMLResponse)
def delete_location_confirm(request: Request, campaign_id: int, location_id: int, db: Session = Depends(get_session)):
    campaign = get_campaign_or_none(db, campaign_id)
    location = get_entity_or_none(db, Location, campaign_id, location_id)
    if not campaign or not location:
        return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)
    return templates.TemplateResponse(
        "confirm_delete.html",
        confirm_delete_context(
            db,
            request,
            campaign,
            {
            "title": "Delete Location",
            "message": f"Are you sure you want to delete '{location.name}'? This cannot be undone.",
            "action": f"/campaigns/{campaign_id}/locations/{location_id}/delete",
            },
        ),
    )


@router.post("/campaigns/{campaign_id}/locations/{location_id}/delete")
def delete_location(campaign_id: int, location_id: int, db: Session = Depends(get_session)):
    location = get_entity_or_none(db, Location, campaign_id, location_id)
    if location:
        delete_location_cascade(db, location)
        db.commit()
    return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)


@router.get("/campaigns/{campaign_id}/factions/{faction_id}/edit", response_class=HTMLResponse)
def edit_faction(request: Request, campaign_id: int, faction_id: int, db: Session = Depends(get_session)):
    campaign = get_campaign_or_none(db, campaign_id)
    faction = get_entity_or_none(db, Faction, campaign_id, faction_id)
    if not campaign or not faction:
        return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)
    npcs = db.exec(select(NPC).where(NPC.campaign_id == campaign_id)).all()
    pcs = db.exec(select(PlayerCharacterNote).where(PlayerCharacterNote.campaign_id == campaign_id)).all()
    locations = db.exec(select(Location).where(Location.campaign_id == campaign_id)).all()
    creatures = db.exec(select(Creature).where(Creature.campaign_id == campaign_id)).all()
    threads = db.exec(select(PlotThread).where(PlotThread.campaign_id == campaign_id)).all()
    faction_type_select, faction_type_custom = faction_type_form_values(faction.faction_type)
    faction_type_options = [{"value": "", "label": "— Unspecified —", "selected": not faction_type_select}]
    for value, label in FACTION_TYPE_CHOICES:
        faction_type_options.append(
            {"value": value, "label": label, "selected": value == faction_type_select}
        )
    faction_fields = [
        {"name": "name", "label": "Name", "type": "text", "required": True},
        {
            "name": "faction_type",
            "label": "Faction Type",
            "type": "select",
            "options": faction_type_options,
            "reveals": "faction_type_custom",
        },
        {
            "name": "faction_type_custom",
            "label": "Custom Faction Type",
            "type": "text",
            "value": faction_type_custom,
            "reveal_target": "faction_type_custom",
        },
        {"name": "summary", "label": "Description", "type": "textarea", "rows": 3},
        location_entity_select_field("hq_location_id", "HQ / Base of Operations", locations, faction.hq_location_id),
        {"name": "plot_notes", "label": "Plot Significance / Notes", "type": "textarea", "rows": 4},
    ] + faction_profile_fields(faction)
    return templates.TemplateResponse(
        "entity_form.html",
        entity_form_context(
            db,
            request,
            campaign,
            {
            "title": "Edit Faction",
            "action": f"/campaigns/{campaign_id}/factions/{faction_id}/edit",
            "entity": faction,
            "fields": faction_fields,
            "select_fields": [
                {
                    "name": "selected_npcs",
                    "label": "Key Figures",
                    "options": related_options(
                        npcs,
                        related_ids_from_links(db, NPCFactionLink, "faction_id", faction.id, "npc_id"),
                    ),
                },
                {
                    "name": "selected_pcs",
                    "label": "Related Party Members",
                    "options": related_options(
                        pcs,
                        related_ids_from_links(db, PCFactionLink, "faction_id", faction.id, "pc_note_id"),
                    ),
                },
                {
                    "name": "selected_creatures",
                    "label": "Related Creatures",
                    "options": related_options(
                        creatures,
                        related_ids_from_links(db, CreatureFactionLink, "faction_id", faction.id, "creature_id"),
                    ),
                },
                {
                    "name": "selected_locations",
                    "label": "Related Locations",
                    "options": related_options(
                        locations,
                        related_ids_from_links(db, LocationFactionLink, "faction_id", faction.id, "location_id"),
                    ),
                },
                {
                    "name": "selected_plot_threads",
                    "label": "Related Plot Threads",
                    "options": related_options(
                        threads,
                        related_ids_from_links(db, FactionPlotThreadLink, "faction_id", faction.id, "plot_thread_id"),
                    ),
                },
            ],
            "submit_label": "Save Faction",
            },
            entity_section_key="factions",
        ),
    )


@router.post("/campaigns/{campaign_id}/factions/{faction_id}/edit")
def update_faction(
    request: Request,
    campaign_id: int,
    faction_id: int,
    name: str = Form(...),
    faction_type: str = Form(""),
    faction_type_custom: str = Form(""),
    summary: str = Form(""),
    hq_location_id: str = Form(""),
    plot_notes: str = Form(""),
    world_status: str = Form("unknown"),
    state_notes: str = Form(""),
    selected_npcs: Optional[List[str]] = Form(None),
    selected_pcs: Optional[List[str]] = Form(None),
    selected_creatures: Optional[List[str]] = Form(None),
    selected_locations: Optional[List[str]] = Form(None),
    selected_plot_threads: Optional[List[str]] = Form(None),
    return_to: Optional[str] = Form(None),
    db: Session = Depends(get_session),
):
    faction = get_entity_or_none(db, Faction, campaign_id, faction_id)
    if not faction:
        return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)
    faction.name = name
    faction.faction_type = resolve_faction_type(faction_type, faction_type_custom)
    faction.summary = summary
    faction.plot_notes = plot_notes.strip() or None
    parsed_hq = hq_location_id.strip()
    faction.hq_location_id = int(parsed_hq) if parsed_hq.isdigit() else None
    apply_world_status_fields(faction, "factions", world_status, state_notes)
    relationship_session_id = resolve_entity_edit_session_id(db, request, campaign_id, return_to)
    replace_many_to_many_links(
        db,
        faction.id,
        NPCFactionLink,
        "faction_id",
        "npc_id",
        load_campaign_entities_by_ids(db, NPC, campaign_id, selected_npcs),
        campaign_id=campaign_id,
        owner_kind="factions",
        related_kind="npcs",
        session_id=relationship_session_id,
    )
    replace_many_to_many_links(
        db,
        faction.id,
        PCFactionLink,
        "faction_id",
        "pc_note_id",
        load_campaign_entities_by_ids(db, PlayerCharacterNote, campaign_id, selected_pcs),
        campaign_id=campaign_id,
        owner_kind="factions",
        related_kind="pcs",
        session_id=relationship_session_id,
    )
    replace_many_to_many_links(
        db,
        faction.id,
        CreatureFactionLink,
        "faction_id",
        "creature_id",
        load_campaign_entities_by_ids(db, Creature, campaign_id, selected_creatures),
        campaign_id=campaign_id,
        owner_kind="factions",
        related_kind="creatures",
        session_id=relationship_session_id,
    )
    replace_many_to_many_links(
        db,
        faction.id,
        LocationFactionLink,
        "faction_id",
        "location_id",
        load_campaign_entities_by_ids(db, Location, campaign_id, selected_locations),
        campaign_id=campaign_id,
        owner_kind="factions",
        related_kind="locations",
        session_id=relationship_session_id,
    )
    replace_many_to_many_links(
        db,
        faction.id,
        FactionPlotThreadLink,
        "faction_id",
        "plot_thread_id",
        load_campaign_entities_by_ids(db, PlotThread, campaign_id, selected_plot_threads),
        campaign_id=campaign_id,
        owner_kind="factions",
        related_kind="threads",
        session_id=relationship_session_id,
    )
    db.add(faction)
    db.commit()
    return _entity_save_redirect(campaign_id, return_to)


@router.get("/campaigns/{campaign_id}/factions/{faction_id}/delete", response_class=HTMLResponse)
def delete_faction_confirm(request: Request, campaign_id: int, faction_id: int, db: Session = Depends(get_session)):
    campaign = get_campaign_or_none(db, campaign_id)
    faction = get_entity_or_none(db, Faction, campaign_id, faction_id)
    if not campaign or not faction:
        return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)
    return templates.TemplateResponse(
        "confirm_delete.html",
        confirm_delete_context(
            db,
            request,
            campaign,
            {
            "title": "Delete Faction",
            "message": f"Are you sure you want to delete '{faction.name}'? This cannot be undone.",
            "action": f"/campaigns/{campaign_id}/factions/{faction_id}/delete",
            },
        ),
    )


@router.post("/campaigns/{campaign_id}/factions/{faction_id}/delete")
def delete_faction(campaign_id: int, faction_id: int, db: Session = Depends(get_session)):
    faction = get_entity_or_none(db, Faction, campaign_id, faction_id)
    if faction:
        delete_faction_cascade(db, faction)
        db.commit()
    return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)


@router.get("/campaigns/{campaign_id}/items/{item_id}/edit", response_class=HTMLResponse)
def edit_item(request: Request, campaign_id: int, item_id: int, db: Session = Depends(get_session)):
    campaign = get_campaign_or_none(db, campaign_id)
    item = get_entity_or_none(db, Item, campaign_id, item_id)
    if not campaign or not item:
        return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)
    npcs = db.exec(select(NPC).where(NPC.campaign_id == campaign_id)).all()
    pcs = db.exec(select(PlayerCharacterNote).where(PlayerCharacterNote.campaign_id == campaign_id)).all()
    factions = db.exec(select(Faction).where(Faction.campaign_id == campaign_id)).all()
    locations = db.exec(select(Location).where(Location.campaign_id == campaign_id)).all()
    threads = db.exec(select(PlotThread).where(PlotThread.campaign_id == campaign_id)).all()
    item_type_select, item_type_custom = item_type_form_values(item.item_type)
    item_type_options = build_item_type_options(db, campaign_id, item.item_type)
    return templates.TemplateResponse(
        "entity_form.html",
        entity_form_context(
            db,
            request,
            campaign,
            {
            "title": "Edit Item",
            "action": f"/campaigns/{campaign_id}/items/{item_id}/edit",
            "entity": item,
            "fields": [
                {"name": "name", "label": "Name", "type": "text", "required": True},
                {
                    "name": "item_type",
                    "label": "Item Type",
                    "type": "select",
                    "options": item_type_options,
                    "reveals": "item_type_custom",
                },
                {
                    "name": "item_type_custom",
                    "label": "Custom Item Type",
                    "type": "text",
                    "value": item_type_custom,
                    "reveal_target": "item_type_custom",
                    "initially_visible": item_type_select == ITEM_TYPE_OTHER,
                },
                {"name": "description", "label": "Description", "type": "textarea", "rows": 3},
                {
                    "name": "current_owner",
                    "label": "Current Owner / Carrier",
                    "type": "select",
                    "options": item_owner_options(npcs, pcs, item),
                },
                {"name": "origin", "label": "Origin / Where Found", "type": "textarea", "rows": 2},
                {"name": "plot_notes", "label": "Plot Significance / Notes", "type": "textarea", "rows": 4},
            ] + item_profile_fields(item),
            "select_fields": [
                {
                    "name": "selected_factions",
                    "label": "Related Factions",
                    "options": related_options(
                        factions,
                        related_ids_from_links(db, ItemFactionLink, "item_id", item.id, "faction_id"),
                    ),
                },
                {
                    "name": "selected_locations",
                    "label": "Related Locations",
                    "options": related_options(
                        locations,
                        related_ids_from_links(db, ItemLocationLink, "item_id", item.id, "location_id"),
                    ),
                },
                {
                    "name": "selected_plot_threads",
                    "label": "Related Plot Threads",
                    "options": related_options(
                        threads,
                        related_ids_from_links(db, ItemPlotThreadLink, "item_id", item.id, "plot_thread_id"),
                    ),
                },
            ],
            "submit_label": "Save Item",
            },
            entity_section_key="items",
        ),
    )


@router.post("/campaigns/{campaign_id}/items/{item_id}/edit")
def update_item(
    request: Request,
    campaign_id: int,
    item_id: int,
    name: str = Form(...),
    item_type: str = Form(""),
    item_type_custom: str = Form(""),
    description: str = Form(""),
    current_owner: str = Form(""),
    origin: str = Form(""),
    plot_notes: str = Form(""),
    world_status: str = Form("unknown"),
    state_notes: str = Form(""),
    selected_factions: Optional[List[str]] = Form(None),
    selected_locations: Optional[List[str]] = Form(None),
    selected_plot_threads: Optional[List[str]] = Form(None),
    return_to: Optional[str] = Form(None),
    new_faction: dict = Depends(optional_new_faction_form),
    db: Session = Depends(get_session),
):
    item = get_entity_or_none(db, Item, campaign_id, item_id)
    if not item:
        return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)
    item.name = name
    item.item_type = resolve_item_type(item_type, item_type_custom)
    item.description = description
    item.origin = origin.strip() or None
    item.plot_notes = plot_notes.strip() or None
    owner_npc_id, owner_pc_id = parse_item_owner(current_owner)
    item.owner_npc_id = owner_npc_id
    item.owner_pc_id = owner_pc_id
    apply_world_status_fields(item, "items", world_status, state_notes)
    relationship_session_id = resolve_entity_edit_session_id(db, request, campaign_id, return_to)
    replace_many_to_many_links(
        db,
        item.id,
        ItemFactionLink,
        "item_id",
        "faction_id",
        load_factions_for_link(
            db,
            campaign_id,
            selected_factions,
            new_faction_name=new_faction["name"],
            new_faction_type=new_faction["type"],
            new_faction_type_custom=new_faction["type_custom"],
        ),
        campaign_id=campaign_id,
        owner_kind="items",
        related_kind="factions",
        session_id=relationship_session_id,
    )
    replace_many_to_many_links(
        db,
        item.id,
        ItemLocationLink,
        "item_id",
        "location_id",
        load_campaign_entities_by_ids(db, Location, campaign_id, selected_locations),
        campaign_id=campaign_id,
        owner_kind="items",
        related_kind="locations",
        session_id=relationship_session_id,
    )
    replace_many_to_many_links(
        db,
        item.id,
        ItemPlotThreadLink,
        "item_id",
        "plot_thread_id",
        load_campaign_entities_by_ids(db, PlotThread, campaign_id, selected_plot_threads),
        campaign_id=campaign_id,
        owner_kind="items",
        related_kind="threads",
        session_id=relationship_session_id,
    )
    db.add(item)
    db.commit()
    return _entity_save_redirect(campaign_id, return_to)


@router.get("/campaigns/{campaign_id}/items/{item_id}/delete", response_class=HTMLResponse)
def delete_item_confirm(request: Request, campaign_id: int, item_id: int, db: Session = Depends(get_session)):
    campaign = get_campaign_or_none(db, campaign_id)
    item = get_entity_or_none(db, Item, campaign_id, item_id)
    if not campaign or not item:
        return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)
    return templates.TemplateResponse(
        "confirm_delete.html",
        confirm_delete_context(
            db,
            request,
            campaign,
            {
            "title": "Delete Item",
            "message": f"Are you sure you want to delete '{item.name}'? This cannot be undone.",
            "action": f"/campaigns/{campaign_id}/items/{item_id}/delete",
            },
        ),
    )


@router.post("/campaigns/{campaign_id}/items/{item_id}/delete")
def delete_item(campaign_id: int, item_id: int, db: Session = Depends(get_session)):
    item = get_entity_or_none(db, Item, campaign_id, item_id)
    if item:
        delete_item_cascade(db, item)
        db.commit()
    return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)


@router.get("/campaigns/{campaign_id}/creatures/{creature_id}/edit", response_class=HTMLResponse)
def edit_creature(request: Request, campaign_id: int, creature_id: int, db: Session = Depends(get_session)):
    campaign = get_campaign_or_none(db, campaign_id)
    creature = get_entity_or_none(db, Creature, campaign_id, creature_id)
    if not campaign or not creature:
        return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)
    factions = db.exec(select(Faction).where(Faction.campaign_id == campaign_id)).all()
    locations = db.exec(select(Location).where(Location.campaign_id == campaign_id)).all()
    threads = db.exec(select(PlotThread).where(PlotThread.campaign_id == campaign_id)).all()
    return templates.TemplateResponse(
        "entity_form.html",
        entity_form_context(
            db,
            request,
            campaign,
            {
            "title": "Edit Creature",
            "action": f"/campaigns/{campaign_id}/creatures/{creature_id}/edit",
            "entity": creature,
            "fields": creature_profile_fields(creature),
            "select_fields": [
                {
                    "name": "selected_factions",
                    "label": "Related Factions",
                    "options": related_options(
                        factions,
                        related_ids_from_links(db, CreatureFactionLink, "creature_id", creature.id, "faction_id"),
                    ),
                },
                {
                    "name": "selected_locations",
                    "label": "Related Locations",
                    "options": related_options(
                        locations,
                        related_ids_from_links(db, CreatureLocationLink, "creature_id", creature.id, "location_id"),
                    ),
                },
                {
                    "name": "selected_plot_threads",
                    "label": "Related Plot Threads",
                    "options": related_options(
                        threads,
                        related_ids_from_links(db, CreaturePlotThreadLink, "creature_id", creature.id, "plot_thread_id"),
                    ),
                },
            ],
            "submit_label": "Save Creature",
            },
            entity_section_key="creatures",
        ),
    )


@router.post("/campaigns/{campaign_id}/creatures/{creature_id}/edit")
def update_creature(
    request: Request,
    campaign_id: int,
    creature_id: int,
    name: str = Form(...),
    creature_type: str = Form(""),
    creature_type_custom: str = Form(""),
    classification: str = Form(""),
    habitat: str = Form(""),
    habitat_custom: str = Form(""),
    threat_level: str = Form(""),
    threat_level_custom: str = Form(""),
    physical_description: str = Form(""),
    special_traits: str = Form(""),
    campaign_context_tactics: str = Form(""),
    notes: str = Form(""),
    world_status: str = Form("unknown"),
    state_notes: str = Form(""),
    selected_factions: Optional[List[str]] = Form(None),
    selected_locations: Optional[List[str]] = Form(None),
    selected_plot_threads: Optional[List[str]] = Form(None),
    return_to: Optional[str] = Form(None),
    new_faction: dict = Depends(optional_new_faction_form),
    db: Session = Depends(get_session),
):
    creature = get_entity_or_none(db, Creature, campaign_id, creature_id)
    if not creature:
        return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)
    creature.name = name
    creature.creature_type = resolve_creature_type(creature_type, creature_type_custom)
    creature.classification = classification.strip() or None
    creature.habitat = resolve_preset_or_custom(habitat, habitat_custom, HABITAT_LABELS)
    creature.threat_level = resolve_preset_or_custom(threat_level, threat_level_custom, THREAT_LEVEL_LABELS)
    creature.physical_description = physical_description.strip() or None
    creature.special_traits = special_traits.strip() or None
    creature.campaign_context_tactics = campaign_context_tactics.strip() or None
    creature.notes = notes.strip() or None
    apply_world_status_fields(creature, "creatures", world_status, state_notes)
    relationship_session_id = resolve_entity_edit_session_id(db, request, campaign_id, return_to)
    replace_many_to_many_links(
        db,
        creature.id,
        CreatureFactionLink,
        "creature_id",
        "faction_id",
        load_factions_for_link(
            db,
            campaign_id,
            selected_factions,
            new_faction_name=new_faction["name"],
            new_faction_type=new_faction["type"],
            new_faction_type_custom=new_faction["type_custom"],
        ),
        campaign_id=campaign_id,
        owner_kind="creatures",
        related_kind="factions",
        session_id=relationship_session_id,
    )
    replace_many_to_many_links(
        db,
        creature.id,
        CreatureLocationLink,
        "creature_id",
        "location_id",
        load_campaign_entities_by_ids(db, Location, campaign_id, selected_locations),
        campaign_id=campaign_id,
        owner_kind="creatures",
        related_kind="locations",
        session_id=relationship_session_id,
    )
    replace_many_to_many_links(
        db,
        creature.id,
        CreaturePlotThreadLink,
        "creature_id",
        "plot_thread_id",
        load_campaign_entities_by_ids(db, PlotThread, campaign_id, selected_plot_threads),
        campaign_id=campaign_id,
        owner_kind="creatures",
        related_kind="threads",
        session_id=relationship_session_id,
    )
    db.add(creature)
    db.commit()
    return _entity_save_redirect(campaign_id, return_to)


@router.get("/campaigns/{campaign_id}/creatures/{creature_id}/delete", response_class=HTMLResponse)
def delete_creature_confirm(request: Request, campaign_id: int, creature_id: int, db: Session = Depends(get_session)):
    campaign = get_campaign_or_none(db, campaign_id)
    creature = get_entity_or_none(db, Creature, campaign_id, creature_id)
    if not campaign or not creature:
        return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)
    return templates.TemplateResponse(
        "confirm_delete.html",
        confirm_delete_context(
            db,
            request,
            campaign,
            {
            "title": "Delete Creature",
            "message": f"Are you sure you want to delete '{creature.name}'? This cannot be undone.",
            "action": f"/campaigns/{campaign_id}/creatures/{creature_id}/delete",
            },
        ),
    )


@router.post("/campaigns/{campaign_id}/creatures/{creature_id}/delete")
def delete_creature(campaign_id: int, creature_id: int, db: Session = Depends(get_session)):
    creature = get_entity_or_none(db, Creature, campaign_id, creature_id)
    if creature:
        delete_creature_cascade(db, creature)
        db.commit()
    return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)


@router.get("/campaigns/{campaign_id}/threads/{thread_id}/edit", response_class=HTMLResponse)
def edit_plot_thread(request: Request, campaign_id: int, thread_id: int, db: Session = Depends(get_session)):
    campaign = get_campaign_or_none(db, campaign_id)
    thread = get_entity_or_none(db, PlotThread, campaign_id, thread_id)
    if not campaign or not thread:
        return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)
    npcs = db.exec(select(NPC).where(NPC.campaign_id == campaign_id)).all()
    pcs = db.exec(select(PlayerCharacterNote).where(PlayerCharacterNote.campaign_id == campaign_id)).all()
    locations = db.exec(select(Location).where(Location.campaign_id == campaign_id)).all()
    factions = db.exec(select(Faction).where(Faction.campaign_id == campaign_id)).all()
    creatures = db.exec(select(Creature).where(Creature.campaign_id == campaign_id)).all()
    all_threads = db.exec(select(PlotThread).where(PlotThread.campaign_id == campaign_id)).all()
    from app.services.plot_thread_links import load_related_plot_thread_options

    related_thread_options = load_related_plot_thread_options(db, campaign_id, thread.id)
    related_thread_empty_hint = None
    if not related_thread_options:
        if len(all_threads) <= 1:
            related_thread_empty_hint = (
                "Add at least one more plot thread on the Lore Board before you can link related threads."
            )
        else:
            related_thread_empty_hint = "No other plot threads available to link."
    return templates.TemplateResponse(
        "entity_form.html",
        entity_form_context(
            db,
            request,
            campaign,
            {
            "title": "Edit Plot Thread",
            "action": f"/campaigns/{campaign_id}/threads/{thread_id}/edit",
            "entity": thread,
            "fields": plot_thread_profile_fields(thread),
            "select_fields": [
                {
                    "name": "selected_npcs",
                    "label": "Key Actors (NPCs)",
                    "options": related_options(
                        npcs,
                        related_ids_from_links(db, NPCPlotThreadLink, "plot_thread_id", thread.id, "npc_id"),
                    ),
                },
                {
                    "name": "selected_pcs",
                    "label": "Key Actors (Party Members)",
                    "options": related_options(
                        pcs,
                        related_ids_from_links(db, PCPlotThreadLink, "plot_thread_id", thread.id, "pc_note_id"),
                    ),
                },
                {
                    "name": "selected_locations",
                    "label": "Key Locations",
                    "options": related_options(
                        locations,
                        related_ids_from_links(db, LocationPlotThreadLink, "plot_thread_id", thread.id, "location_id"),
                    ),
                },
                {
                    "name": "selected_factions",
                    "label": "Related Factions",
                    "options": related_options(
                        factions,
                        related_ids_from_links(db, FactionPlotThreadLink, "plot_thread_id", thread.id, "faction_id"),
                    ),
                },
                {
                    "name": "selected_creatures",
                    "label": "Related Creatures",
                    "options": related_options(
                        creatures,
                        related_ids_from_links(db, CreaturePlotThreadLink, "plot_thread_id", thread.id, "creature_id"),
                    ),
                },
                {
                    "name": "selected_related_plot_threads",
                    "label": "Related Plot Threads",
                    "options": related_thread_options,
                    "empty_hint": related_thread_empty_hint,
                },
            ],
            "submit_label": "Save Plot Thread",
            },
            entity_section_key="threads",
        ),
    )


@router.post("/campaigns/{campaign_id}/threads/{thread_id}/edit")
def update_plot_thread(
    request: Request,
    campaign_id: int,
    thread_id: int,
    title: str = Form(...),
    status: str = Form("unknown"),
    state_notes: str = Form(""),
    thread_type: str = Form(""),
    thread_type_custom: str = Form(""),
    mystery_status: str = Form("unknown"),
    details: str = Form(""),
    open_clues: str = Form(""),
    revealed_clues: str = Form(""),
    secret_notes: str = Form(""),
    plot_significance_notes: str = Form(""),
    resolution_notes: str = Form(""),
    selected_npcs: Optional[List[str]] = Form(None),
    selected_pcs: Optional[List[str]] = Form(None),
    selected_locations: Optional[List[str]] = Form(None),
    selected_factions: Optional[List[str]] = Form(None),
    selected_creatures: Optional[List[str]] = Form(None),
    selected_related_plot_threads: Optional[List[str]] = Form(None),
    return_to: Optional[str] = Form(None),
    db: Session = Depends(get_session),
):
    thread = get_entity_or_none(db, PlotThread, campaign_id, thread_id)
    if not thread:
        return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)
    thread.title = title
    apply_world_status_fields(thread, "threads", status, state_notes)
    thread.thread_type = resolve_preset_or_custom(thread_type, thread_type_custom, PLOT_THREAD_TYPE_LABELS)
    apply_mystery_fields(thread, mystery_status, open_clues, revealed_clues, secret_notes)
    thread.details = details.strip() or None
    thread.plot_significance_notes = plot_significance_notes.strip() or None
    thread.resolution_notes = resolution_notes.strip() or None
    relationship_session_id = resolve_entity_edit_session_id(db, request, campaign_id, return_to)
    replace_many_to_many_links(
        db,
        thread.id,
        NPCPlotThreadLink,
        "plot_thread_id",
        "npc_id",
        load_campaign_entities_by_ids(db, NPC, campaign_id, selected_npcs),
        campaign_id=campaign_id,
        owner_kind="threads",
        related_kind="npcs",
        session_id=relationship_session_id,
    )
    replace_many_to_many_links(
        db,
        thread.id,
        PCPlotThreadLink,
        "plot_thread_id",
        "pc_note_id",
        load_campaign_entities_by_ids(db, PlayerCharacterNote, campaign_id, selected_pcs),
        campaign_id=campaign_id,
        owner_kind="threads",
        related_kind="pcs",
        session_id=relationship_session_id,
    )
    replace_many_to_many_links(
        db,
        thread.id,
        LocationPlotThreadLink,
        "plot_thread_id",
        "location_id",
        load_campaign_entities_by_ids(db, Location, campaign_id, selected_locations),
        campaign_id=campaign_id,
        owner_kind="threads",
        related_kind="locations",
        session_id=relationship_session_id,
    )
    replace_many_to_many_links(
        db,
        thread.id,
        FactionPlotThreadLink,
        "plot_thread_id",
        "faction_id",
        load_campaign_entities_by_ids(db, Faction, campaign_id, selected_factions),
        campaign_id=campaign_id,
        owner_kind="threads",
        related_kind="factions",
        session_id=relationship_session_id,
    )
    replace_many_to_many_links(
        db,
        thread.id,
        CreaturePlotThreadLink,
        "plot_thread_id",
        "creature_id",
        load_campaign_entities_by_ids(db, Creature, campaign_id, selected_creatures),
        campaign_id=campaign_id,
        owner_kind="threads",
        related_kind="creatures",
        session_id=relationship_session_id,
    )
    from app.services.plot_thread_links import replace_plot_thread_related_links

    replace_plot_thread_related_links(
        db,
        campaign_id,
        thread.id,
        load_campaign_entities_by_ids(db, PlotThread, campaign_id, selected_related_plot_threads),
        session_id=relationship_session_id,
    )
    db.add(thread)
    db.commit()
    return _entity_save_redirect(campaign_id, return_to)


@router.get("/campaigns/{campaign_id}/threads/{thread_id}/delete", response_class=HTMLResponse)
def delete_plot_thread_confirm(request: Request, campaign_id: int, thread_id: int, db: Session = Depends(get_session)):
    campaign = get_campaign_or_none(db, campaign_id)
    thread = get_entity_or_none(db, PlotThread, campaign_id, thread_id)
    if not campaign or not thread:
        return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)
    return templates.TemplateResponse(
        "confirm_delete.html",
        confirm_delete_context(
            db,
            request,
            campaign,
            {
            "title": "Delete Plot Thread",
            "message": f"Are you sure you want to delete '{thread.title}'? This cannot be undone.",
            "action": f"/campaigns/{campaign_id}/threads/{thread_id}/delete",
            },
        ),
    )


@router.post("/campaigns/{campaign_id}/threads/{thread_id}/delete")
def delete_plot_thread(campaign_id: int, thread_id: int, db: Session = Depends(get_session)):
    thread = get_entity_or_none(db, PlotThread, campaign_id, thread_id)
    if thread:
        delete_plot_thread_cascade(db, thread)
        db.commit()
    return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)


@router.post("/campaigns/{campaign_id}/npcs")
def create_npc(
    request: Request,
    campaign_id: int,
    name: str = Form(...),
    role: str = Form(""),
    description: str = Form(""),
    session: Session = Depends(get_session),
):
    npc = NPC(campaign_id=campaign_id, name=name, role=role, description=description)
    session.add(npc)
    session.commit()
    return htmx_or_redirect(
        request,
        f"/campaigns/{campaign_id}",
        render_entity_section(request, campaign_id, session, "npcs"),
    )


@router.post("/campaigns/{campaign_id}/locations")
def create_location(
    request: Request,
    campaign_id: int,
    name: str = Form(...),
    description: str = Form(""),
    notes: str = Form(""),
    location_type: str = Form(LOCATION_TYPE_MAJOR),
    session: Session = Depends(get_session),
):
    location = Location(
        campaign_id=campaign_id,
        name=name,
        description=description,
        notes=notes.strip() or None,
        location_type=normalize_location_type(location_type) or LOCATION_TYPE_MAJOR,
    )
    session.add(location)
    session.commit()
    return htmx_or_redirect(
        request,
        f"/campaigns/{campaign_id}",
        render_entity_section(request, campaign_id, session, "locations"),
    )


@router.post("/campaigns/{campaign_id}/factions")
def create_faction(
    request: Request,
    campaign_id: int,
    name: str = Form(...),
    faction_type: str = Form(""),
    faction_type_custom: str = Form(""),
    summary: str = Form(""),
    plot_notes: str = Form(""),
    session: Session = Depends(get_session),
):
    faction = Faction(
        campaign_id=campaign_id,
        name=name,
        faction_type=resolve_faction_type(faction_type, faction_type_custom),
        summary=summary,
        plot_notes=plot_notes.strip() or None,
    )
    session.add(faction)
    session.commit()
    return htmx_or_redirect(
        request,
        f"/campaigns/{campaign_id}",
        render_entity_section(request, campaign_id, session, "factions"),
    )


@router.post("/campaigns/{campaign_id}/items")
def create_item(
    request: Request,
    campaign_id: int,
    name: str = Form(...),
    item_type: str = Form(""),
    item_type_custom: str = Form(""),
    description: str = Form(""),
    origin: str = Form(""),
    plot_notes: str = Form(""),
    session: Session = Depends(get_session),
):
    item = Item(
        campaign_id=campaign_id,
        name=name,
        item_type=resolve_item_type(item_type, item_type_custom),
        description=description,
        origin=origin.strip() or None,
        plot_notes=plot_notes.strip() or None,
    )
    session.add(item)
    session.commit()
    return htmx_or_redirect(
        request,
        f"/campaigns/{campaign_id}",
        render_entity_section(request, campaign_id, session, "items"),
    )


@router.post("/campaigns/{campaign_id}/creatures")
def create_creature(
    request: Request,
    campaign_id: int,
    name: str = Form(...),
    creature_type: str = Form(""),
    creature_type_custom: str = Form(""),
    classification: str = Form(""),
    habitat: str = Form(""),
    threat_level: str = Form(""),
    physical_description: str = Form(""),
    special_traits: str = Form(""),
    campaign_context_tactics: str = Form(""),
    notes: str = Form(""),
    session: Session = Depends(get_session),
):
    creature = Creature(
        campaign_id=campaign_id,
        name=name,
        creature_type=resolve_creature_type(creature_type, creature_type_custom),
        classification=classification.strip() or None,
        habitat=habitat.strip() or None,
        threat_level=threat_level.strip() or None,
        physical_description=physical_description.strip() or None,
        special_traits=special_traits.strip() or None,
        campaign_context_tactics=campaign_context_tactics.strip() or None,
        notes=notes.strip() or None,
    )
    session.add(creature)
    session.commit()
    return htmx_or_redirect(
        request,
        f"/campaigns/{campaign_id}",
        render_entity_section(request, campaign_id, session, "creatures"),
    )


@router.post("/campaigns/{campaign_id}/threads")
def create_plot_thread(
    request: Request,
    campaign_id: int,
    title: str = Form(...),
    thread_type: str = Form(""),
    status: str = Form(""),
    details: str = Form(""),
    plot_significance_notes: str = Form(""),
    session: Session = Depends(get_session),
):
    thread = PlotThread(
        campaign_id=campaign_id,
        title=title,
        thread_type=thread_type.strip() or None,
        status=status.strip() or None,
        details=details.strip() or None,
        plot_significance_notes=plot_significance_notes.strip() or None,
    )
    session.add(thread)
    session.commit()
    return htmx_or_redirect(
        request,
        f"/campaigns/{campaign_id}",
        render_entity_section(request, campaign_id, session, "threads"),
    )


@router.post("/campaigns/{campaign_id}/pcs")
def create_pc_note(
    request: Request,
    campaign_id: int,
    character_name: str = Form(...),
    character_archetype: str = Form(""),
    description: str = Form(""),
    signature_gear: str = Form(""),
    key_ties_history: str = Form(""),
    campaign_role_plot_notes: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_session),
):
    pc_note = PlayerCharacterNote(
        campaign_id=campaign_id,
        character_name=character_name,
        character_archetype=character_archetype.strip() or None,
        description=description.strip() or None,
        signature_gear=signature_gear.strip() or None,
        key_ties_history=key_ties_history.strip() or None,
        campaign_role_plot_notes=campaign_role_plot_notes.strip() or None,
        notes=notes.strip() or None,
    )
    db.add(pc_note)
    db.commit()
    return htmx_or_redirect(
        request,
        f"/campaigns/{campaign_id}",
        render_entity_section(request, campaign_id, db, "pcs"),
    )


@router.get("/campaigns/{campaign_id}/pcs/{pc_id}/edit", response_class=HTMLResponse)
def edit_pc(request: Request, campaign_id: int, pc_id: int, db: Session = Depends(get_session)):
    campaign = get_campaign_or_none(db, campaign_id)
    pc = get_entity_or_none(db, PlayerCharacterNote, campaign_id, pc_id)
    if not campaign or not pc:
        return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)

    locations = db.exec(select(Location).where(Location.campaign_id == campaign_id)).all()
    factions = db.exec(select(Faction).where(Faction.campaign_id == campaign_id)).all()
    threads = db.exec(select(PlotThread).where(PlotThread.campaign_id == campaign_id)).all()
    flash_message = request.query_params.get("message")

    return templates.TemplateResponse(
        "entity_form.html",
        entity_form_context(
            db,
            request,
            campaign,
            {
                "title": "Edit Party Member",
                "action": f"/campaigns/{campaign_id}/pcs/{pc_id}/edit",
                "entity": pc,
                "message": flash_message,
                "fields": [
                    {"name": "character_name", "label": "Character Name", "type": "text", "required": True},
                    {"name": "character_archetype", "label": "Character Archetype", "type": "text"},
                    {"name": "description", "label": "Description", "type": "textarea", "rows": 4},
                    {"name": "signature_gear", "label": "Signature Gear", "type": "textarea", "rows": 2},
                    {"name": "key_ties_history", "label": "Key Ties & History", "type": "textarea", "rows": 4},
                    {"name": "campaign_role_plot_notes", "label": "Campaign Role & Plot Notes", "type": "textarea", "rows": 4},
                    {"name": "notes", "label": "Additional Notes", "type": "textarea", "rows": 3},
                ],
                "select_fields": [
                    {
                        "name": "selected_factions",
                        "label": "Related Factions",
                        "options": related_options(
                            factions,
                            related_ids_from_links(db, PCFactionLink, "pc_note_id", pc.id, "faction_id"),
                        ),
                    },
                    {
                        "name": "selected_locations",
                        "label": "Related Locations",
                        "options": related_options(
                            locations,
                            related_ids_from_links(db, PCLocationLink, "pc_note_id", pc.id, "location_id"),
                        ),
                    },
                    {
                        "name": "selected_plot_threads",
                        "label": "Related Plot Threads",
                        "options": related_options(
                            threads,
                            related_ids_from_links(db, PCPlotThreadLink, "pc_note_id", pc.id, "plot_thread_id"),
                        ),
                    },
                ],
                "submit_label": "Save PC",
                "convert_action": {
                    "url": f"/campaigns/{campaign_id}/pcs/{pc_id}/convert-to-npc",
                    "label": "Convert to NPC",
                    "confirm": f"Convert {pc.character_name} to an NPC? Session and location links will be preserved.",
                },
            },
            entity_section_key="pcs",
            active_nav="pcs",
        ),
    )


@router.post("/campaigns/{campaign_id}/pcs/{pc_id}/edit")
def update_pc(
    request: Request,
    campaign_id: int,
    pc_id: int,
    character_name: str = Form(...),
    character_archetype: str = Form(""),
    description: str = Form(""),
    signature_gear: str = Form(""),
    key_ties_history: str = Form(""),
    campaign_role_plot_notes: str = Form(""),
    notes: str = Form(""),
    selected_factions: Optional[List[str]] = Form(None),
    selected_locations: Optional[List[str]] = Form(None),
    selected_plot_threads: Optional[List[str]] = Form(None),
    return_to: Optional[str] = Form(None),
    new_faction: dict = Depends(optional_new_faction_form),
    db: Session = Depends(get_session),
):
    pc = get_entity_or_none(db, PlayerCharacterNote, campaign_id, pc_id)
    if not pc:
        return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)
    pc.character_name = character_name
    pc.character_archetype = character_archetype.strip() or None
    pc.description = description.strip() or None
    pc.signature_gear = signature_gear.strip() or None
    pc.key_ties_history = key_ties_history.strip() or None
    pc.campaign_role_plot_notes = campaign_role_plot_notes.strip() or None
    pc.notes = notes.strip() or None
    relationship_session_id = resolve_entity_edit_session_id(db, request, campaign_id, return_to)
    replace_many_to_many_links(
        db,
        pc.id,
        PCFactionLink,
        "pc_note_id",
        "faction_id",
        load_factions_for_link(
            db,
            campaign_id,
            selected_factions,
            new_faction_name=new_faction["name"],
            new_faction_type=new_faction["type"],
            new_faction_type_custom=new_faction["type_custom"],
        ),
        campaign_id=campaign_id,
        owner_kind="pcs",
        related_kind="factions",
        session_id=relationship_session_id,
    )
    replace_many_to_many_links(
        db,
        pc.id,
        PCLocationLink,
        "pc_note_id",
        "location_id",
        load_campaign_entities_by_ids(db, Location, campaign_id, selected_locations),
        campaign_id=campaign_id,
        owner_kind="pcs",
        related_kind="locations",
        session_id=relationship_session_id,
    )
    replace_many_to_many_links(
        db,
        pc.id,
        PCPlotThreadLink,
        "pc_note_id",
        "plot_thread_id",
        load_campaign_entities_by_ids(db, PlotThread, campaign_id, selected_plot_threads),
        campaign_id=campaign_id,
        owner_kind="pcs",
        related_kind="threads",
        session_id=relationship_session_id,
    )
    db.add(pc)
    db.commit()
    return _entity_save_redirect(campaign_id, return_to)


@router.post("/campaigns/{campaign_id}/pcs/{pc_id}/convert-to-npc")
def convert_pc_to_npc_route(
    request: Request,
    campaign_id: int,
    pc_id: int,
    return_to: Optional[str] = Form(None),
    db: Session = Depends(get_session),
):
    from urllib.parse import quote

    from app.services.character_conversion import convert_pc_to_npc

    pc = get_entity_or_none(db, PlayerCharacterNote, campaign_id, pc_id)
    if not pc:
        return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)

    npc, _warning = convert_pc_to_npc(db, pc)
    db.commit()

    url = f"/campaigns/{campaign_id}/npcs/{npc.id}/edit"
    params = []
    if return_to:
        params.append(f"return_to={quote(return_to, safe='')}")
    params.append(f"message={quote('Converted to NPC.')}")
    if params:
        url = f"{url}?{'&'.join(params)}"
    return RedirectResponse(url=url, status_code=303)
