from datetime import date, datetime
from typing import Any, Dict, List, Optional

import markdown as markdown_lib
from fastapi import Form
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from sqlmodel import Session, select

from app.services.analysis import looks_like_ai_blob, looks_like_invalid_prep
from app.models import Campaign
from app.services.entity_links import load_campaign_entities_by_ids, parse_form_id_list
from app.services.faction_classification import FACTION_TYPE_CHOICES
from app.services.narrative_blocks import (
    ENCOUNTER_TYPE_BADGE,
    OBJECTIVE_PRIORITY_BADGE,
    OBJECTIVE_STATUS_BADGE,
    OBJECTIVE_TYPE_BADGE,
    SCENE_STATUS_BADGE,
)
from app.services.world_state import (
    mystery_status_badge_class,
    mystery_status_label,
    world_status_badge_class,
    world_status_label,
)
from app.services.mission_control_ui import (
    append_return_to,
    lore_board_url,
    session_workflow_url,
    workspace_url,
)

templates = Jinja2Templates(directory="app/templates")
templates.env.globals["getattr"] = getattr
templates.env.globals["workspace_url"] = workspace_url
templates.env.globals["session_workflow_url"] = session_workflow_url
templates.env.globals["lore_board_url"] = lore_board_url
templates.env.globals["append_return_to"] = append_return_to
templates.env.globals["faction_type_choices"] = FACTION_TYPE_CHOICES
templates.env.globals["world_status_label"] = world_status_label
templates.env.globals["world_status_badge_class"] = world_status_badge_class
templates.env.globals["mystery_status_label"] = mystery_status_label
templates.env.globals["mystery_status_badge_class"] = mystery_status_badge_class
templates.env.globals["scene_status_badges"] = SCENE_STATUS_BADGE
templates.env.globals["encounter_type_badges"] = ENCOUNTER_TYPE_BADGE
templates.env.globals["objective_type_badges"] = OBJECTIVE_TYPE_BADGE
templates.env.globals["objective_priority_badges"] = OBJECTIVE_PRIORITY_BADGE
templates.env.globals["objective_status_badges"] = OBJECTIVE_STATUS_BADGE


def optional_new_faction_form(
    new_faction_name: str = Form(""),
    new_faction_type: str = Form(""),
    new_faction_type_custom: str = Form(""),
) -> Dict[str, str]:
    return {
        "name": new_faction_name,
        "type": new_faction_type,
        "type_custom": new_faction_type_custom,
    }


def render_markdown(text: str) -> Markup:
    if not text:
        return Markup("")
    html = markdown_lib.markdown(
        text,
        extensions=["extra", "nl2br", "sane_lists", "tables"],
    )
    return Markup(html)


def preview_text(text: Optional[str], limit: int = 500) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


templates.env.filters["markdown"] = render_markdown
templates.env.filters["preview_text"] = preview_text
templates.env.filters["looks_like_ai_blob"] = looks_like_ai_blob
templates.env.filters["looks_like_invalid_prep"] = looks_like_invalid_prep

_SESSION_DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%B %d %Y",
    "%b %d %Y",
)


def parse_session_date(value: Optional[str]) -> Optional[date]:
    if not value or not value.strip():
        return None
    text = value.strip()
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass
    for fmt in _SESSION_DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def sort_sessions_chronologically(sessions: List[Any]) -> List[Any]:
    def sort_key(session: Any) -> tuple:
        parsed = parse_session_date(getattr(session, "date", None))
        return (parsed is None, parsed or date.min, getattr(session, "id", 0) or 0)

    return sorted(sessions, key=sort_key)


def get_campaign_or_none(db: Session, campaign_id: int):
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        return None
    return campaign


def get_entity_or_none(db: Session, model, campaign_id: int, entity_id: int):
    entity = db.get(model, entity_id)
    if not entity or getattr(entity, "campaign_id", None) != campaign_id:
        return None
    return entity


def load_by_ids(db: Session, model, ids: Optional[List[str]], campaign_id: Optional[int] = None):
    """Load entities by form IDs; prefer load_campaign_entities_by_ids when campaign_id is known."""
    parsed = parse_form_id_list(ids)
    if not parsed:
        return []
    query = select(model).where(model.id.in_(parsed))
    if campaign_id is not None and hasattr(model, "campaign_id"):
        query = query.where(model.campaign_id == campaign_id)
    return db.exec(query).all()


def related_options(objects, current_ids):
    return [
        {
            "value": str(obj.id),
            "label": getattr(obj, "name", None) or getattr(obj, "character_name", None) or getattr(obj, "title", ""),
            "selected": obj.id in current_ids,
        }
        for obj in objects
    ]
