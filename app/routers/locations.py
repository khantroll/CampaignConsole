from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from app.database import get_session
from app.deps import templates
from app.models import Campaign, Location
from app.services.location_admin import bulk_delete_locations, merge_locations, update_location_types
from app.services.location_classification import (
    LOCATION_TYPE_CHOICES,
    LOCATION_TYPE_MAJOR,
    LOCATION_TYPE_SCENE,
    filter_locations_by_type,
    location_type_label,
    normalize_location_type,
)
from app.services.mission_control_ui import with_mc

router = APIRouter()


def _load_campaign_locations(db: Session, campaign_id: int, filter_key: str = "all") -> List[Location]:
    locations = db.exec(
        select(Location).where(Location.campaign_id == campaign_id).order_by(Location.name)
    ).all()
    return filter_locations_by_type(locations, filter_key)


def _location_admin_context(
    db: Session,
    request: Request,
    campaign: Campaign,
    *,
    locations: List[Location],
    filter: str,
    message: Optional[str] = None,
) -> Dict[str, Any]:
    return with_mc(
        db,
        {
            "request": request,
            "campaign": campaign,
            "locations": locations,
            "filter": filter,
            "location_type_choices": LOCATION_TYPE_CHOICES,
            "location_type_label": location_type_label,
            "message": message,
        },
        campaign=campaign,
        active_nav="location_admin",
        layout="dashboard",
        request=request,
    )


@router.post("/campaigns/{campaign_id}/locations/admin/create")
def location_admin_create(
    campaign_id: int,
    name: str = Form(...),
    description: str = Form(""),
    location_type: str = Form(LOCATION_TYPE_MAJOR),
    filter: str = Form("all"),
    db: Session = Depends(get_session),
):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        return RedirectResponse(url="/", status_code=303)

    location = Location(
        campaign_id=campaign_id,
        name=name.strip(),
        description=description.strip() or None,
        location_type=normalize_location_type(location_type) or LOCATION_TYPE_MAJOR,
    )
    db.add(location)
    db.commit()
    return RedirectResponse(
        url=f"/campaigns/{campaign_id}/locations/admin?filter={filter}&message=Location+added",
        status_code=303,
    )


@router.get("/campaigns/{campaign_id}/locations/admin", response_class=HTMLResponse)
def location_admin(
    request: Request,
    campaign_id: int,
    filter: str = "major_sub",
    message: Optional[str] = None,
    db: Session = Depends(get_session),
):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        return RedirectResponse(url="/", status_code=303)

    locations = _load_campaign_locations(db, campaign_id, filter)
    return templates.TemplateResponse(
        "location_admin.html",
        _location_admin_context(db, request, campaign, locations=locations, filter=filter, message=message),
    )


@router.post("/campaigns/{campaign_id}/locations/admin/reclassify", response_class=HTMLResponse)
async def location_admin_reclassify(
    request: Request,
    campaign_id: int,
    filter: str = Form("major_sub"),
    db: Session = Depends(get_session),
):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        return RedirectResponse(url="/", status_code=303)

    form = await request.form()
    updates = {}
    for key, value in form.items():
        if key.startswith("location_type_") and value:
            try:
                location_id = int(key.split("_", 2)[2])
            except (ValueError, IndexError):
                continue
            updates[location_id] = str(value)
    changed = update_location_types(db, campaign_id, updates)
    db.commit()
    message = f"Updated {changed} location type(s)."
    locations = _load_campaign_locations(db, campaign_id, filter)
    return templates.TemplateResponse(
        "location_admin.html",
        _location_admin_context(db, request, campaign, locations=locations, filter=filter, message=message),
    )


@router.post("/campaigns/{campaign_id}/locations/admin/merge", response_class=HTMLResponse)
def location_admin_merge(
    request: Request,
    campaign_id: int,
    canonical_id: int = Form(...),
    merge_ids: Optional[List[str]] = Form(None),
    filter: str = Form("major_sub"),
    db: Session = Depends(get_session),
):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        return RedirectResponse(url="/", status_code=303)

    duplicate_ids = [int(value) for value in (merge_ids or []) if value]
    merged = merge_locations(db, campaign_id, canonical_id, duplicate_ids)
    db.commit()
    if merged:
        message = f"Merged {len(duplicate_ids)} location(s) into '{merged.name}'."
    else:
        message = "Merge failed — check the canonical location and selected duplicates."
    locations = _load_campaign_locations(db, campaign_id, filter)
    return templates.TemplateResponse(
        "location_admin.html",
        _location_admin_context(db, request, campaign, locations=locations, filter=filter, message=message),
    )


@router.post("/campaigns/{campaign_id}/locations/admin/delete", response_class=HTMLResponse)
def location_admin_delete(
    request: Request,
    campaign_id: int,
    delete_ids: Optional[List[str]] = Form(None),
    filter: str = Form("major_sub"),
    db: Session = Depends(get_session),
):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        return RedirectResponse(url="/", status_code=303)

    location_ids = [int(value) for value in (delete_ids or []) if value]
    deleted = bulk_delete_locations(db, campaign_id, location_ids)
    db.commit()
    message = f"Deleted {deleted} location(s)."
    locations = _load_campaign_locations(db, campaign_id, filter)
    return templates.TemplateResponse(
        "location_admin.html",
        _location_admin_context(db, request, campaign, locations=locations, filter=filter, message=message),
    )


@router.post("/campaigns/{campaign_id}/locations/admin/delete-scene-features", response_class=HTMLResponse)
def location_admin_delete_scene_features(
    request: Request,
    campaign_id: int,
    filter: str = Form("scene_feature"),
    db: Session = Depends(get_session),
):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        return RedirectResponse(url="/", status_code=303)

    scene_locations = _load_campaign_locations(db, campaign_id, LOCATION_TYPE_SCENE)
    deleted = bulk_delete_locations(db, campaign_id, [loc.id for loc in scene_locations])
    db.commit()
    message = f"Deleted {deleted} scene feature location(s)."
    locations = _load_campaign_locations(db, campaign_id, filter)
    return templates.TemplateResponse(
        "location_admin.html",
        _location_admin_context(db, request, campaign, locations=locations, filter=filter, message=message),
    )
