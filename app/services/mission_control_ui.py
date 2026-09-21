"""Mission Control template context helpers."""

from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, quote, urlencode

from fastapi import Request
from sqlmodel import Session, select

from app.models import Campaign, SessionModel
from app.services.entity_health import CampaignEntityHealth, health_tooltip

WORKSPACE_MODES = ("prep", "run", "review")


def load_all_campaigns(db: Session) -> List[Campaign]:
    return db.exec(select(Campaign).order_by(Campaign.name)).all()


def load_campaign_sessions(db: Session, campaign_id: int) -> List[SessionModel]:
    return db.exec(
        select(SessionModel)
        .where(SessionModel.campaign_id == campaign_id)
        .order_by(SessionModel.id.desc())
    ).all()


def session_cookie_name(campaign_id: int) -> str:
    return f"mc_session_{campaign_id}"


def mode_cookie_name(campaign_id: int) -> str:
    return f"mc_mode_{campaign_id}"


def read_persisted_session_id(request: Optional[Request], campaign_id: int) -> Optional[int]:
    if not request:
        return None
    raw = request.cookies.get(session_cookie_name(campaign_id))
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def read_persisted_mode(request: Optional[Request], campaign_id: int, default: str = "prep") -> str:
    if not request:
        return default
    mode = request.cookies.get(mode_cookie_name(campaign_id), default)
    return mode if mode in WORKSPACE_MODES else default


def resolve_persisted_session(
    db: Session,
    request: Optional[Request],
    campaign_id: int,
    explicit: Optional[SessionModel] = None,
) -> Optional[SessionModel]:
    if explicit is not None:
        return explicit
    session_id = read_persisted_session_id(request, campaign_id)
    if not session_id:
        return None
    session_model = db.get(SessionModel, session_id)
    if not session_model or session_model.campaign_id != campaign_id:
        return None
    return session_model


def safe_return_to(value: Optional[str]) -> Optional[str]:
    if not value or not str(value).strip():
        return None
    path = str(value).strip()
    if not path.startswith("/") or path.startswith("//"):
        return None
    if "://" in path:
        return None
    return path


def session_id_from_return_to(return_to: Optional[str], campaign_id: int) -> Optional[int]:
    """Extract session id from a workspace or session-workflow return_to path."""
    safe = safe_return_to(return_to)
    if not safe:
        return None
    path, _, query = safe.partition("?")
    params = parse_qs(query)
    session_values = params.get("session_id") or []
    if session_values and str(session_values[0]).isdigit():
        return int(session_values[0])
    prefix = f"/campaigns/{campaign_id}/sessions/"
    if path.startswith(prefix):
        rest = path[len(prefix) :].split("/", 1)[0]
        if rest.isdigit():
            return int(rest)
    return None


def resolve_entity_edit_session_id(
    db: Session,
    request: Optional[Request],
    campaign_id: int,
    return_to: Optional[str] = None,
) -> Optional[int]:
    """Session context for relationship history on manual entity edits."""
    from_return_to = session_id_from_return_to(return_to, campaign_id)
    if from_return_to is not None:
        session_model = db.get(SessionModel, from_return_to)
        if session_model and session_model.campaign_id == campaign_id:
            return from_return_to
    session_model = resolve_persisted_session(db, request, campaign_id)
    if session_model and session_model.id:
        return session_model.id
    return None


def resolve_workspace_session(
    db: Session,
    request: Optional[Request],
    campaign_id: int,
    session_id: Optional[int] = None,
) -> Optional[SessionModel]:
    if session_id is not None:
        session_model = db.get(SessionModel, session_id)
        if session_model and session_model.campaign_id == campaign_id:
            return session_model
    if request:
        persisted_id = read_persisted_session_id(request, campaign_id)
        if persisted_id:
            session_model = db.get(SessionModel, persisted_id)
            if session_model and session_model.campaign_id == campaign_id:
                return session_model
    return db.exec(
        select(SessionModel)
        .where(SessionModel.campaign_id == campaign_id)
        .order_by(SessionModel.id.desc())
    ).first()


def resolve_workspace_mode(
    request: Optional[Request],
    campaign_id: int,
    mode: Optional[str] = None,
    *,
    default: str = "prep",
) -> str:
    if mode in WORKSPACE_MODES:
        return mode
    return read_persisted_mode(request, campaign_id, default)


def workspace_needs_canonical_redirect(
    request: Request,
    session_model: Optional[SessionModel],
    resolved_mode: str,
) -> bool:
    if not session_model:
        return False
    q_session = request.query_params.get("session_id")
    q_mode = request.query_params.get("mode")
    if q_session != str(session_model.id):
        return True
    if q_mode not in WORKSPACE_MODES:
        return True
    return False


def workspace_url(
    campaign_id: int,
    *,
    session_id: Optional[int] = None,
    mode: str = "prep",
) -> str:
    params: Dict[str, str] = {}
    if session_id:
        params["session_id"] = str(session_id)
    if mode in WORKSPACE_MODES:
        params["mode"] = mode
    base = f"/campaigns/{campaign_id}/workspace"
    if not params:
        return base
    return f"{base}?{urlencode(params)}"


def session_workflow_url(campaign_id: int, session_id: Optional[int] = None) -> str:
    if session_id:
        return f"/campaigns/{campaign_id}/sessions/{session_id}"
    return f"/campaigns/{campaign_id}#sessions-section"


def lore_board_url(campaign_id: int) -> str:
    return f"/campaigns/{campaign_id}"


def append_return_to(url: str, return_to: Optional[str]) -> str:
    safe = safe_return_to(return_to)
    if not safe:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}return_to={quote(safe, safe='')}"


def redirect_after_entity_save(campaign_id: int, return_to: Optional[str] = None) -> str:
    return safe_return_to(return_to) or lore_board_url(campaign_id)


def redirect_after_session_edit(campaign_id: int, session_id: int, return_to: Optional[str] = None) -> str:
    return safe_return_to(return_to) or session_workflow_url(campaign_id, session_id)


def mc_context(
    db: Session,
    *,
    campaign: Optional[Campaign] = None,
    session: Optional[SessionModel] = None,
    active_nav: Optional[str] = None,
    layout: str = "dashboard",
    mode: str = "prep",
    include_campaigns: bool = True,
    request: Optional[Request] = None,
    **extra: Any,
) -> Dict[str, Any]:
    resolved_session = session
    workspace_mode = mode
    if campaign and request:
        resolved_session = resolve_persisted_session(db, request, campaign.id, session)
        if active_nav != "workspace":
            workspace_mode = read_persisted_mode(request, campaign.id, mode)

    ctx: Dict[str, Any] = {
        "campaign": campaign,
        "session": resolved_session,
        "active_nav": active_nav,
        "layout": layout,
        "mode": mode if active_nav == "workspace" else workspace_mode,
        "workspace_mode": workspace_mode,
    }
    if include_campaigns:
        ctx["campaigns"] = load_all_campaigns(db)
    if campaign:
        ctx["sessions"] = load_campaign_sessions(db, campaign.id)
        ctx["workspace_href"] = workspace_url(
            campaign.id,
            session_id=resolved_session.id if resolved_session else None,
            mode=ctx["workspace_mode"],
        )
        ctx["session_workflow_href"] = session_workflow_url(
            campaign.id,
            resolved_session.id if resolved_session else None,
        )
        ctx["lore_board_href"] = lore_board_url(campaign.id)
    ctx.update(extra)
    return ctx


def mc_settings_context(db: Session, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Mission Control shell for global settings pages (no campaign sidebar)."""
    return with_mc(db, ctx, active_nav="settings", layout="minimal")


def with_mc(
    db: Session,
    ctx: Dict[str, Any],
    *,
    campaign: Optional[Campaign] = None,
    session: Optional[SessionModel] = None,
    active_nav: Optional[str] = None,
    layout: str = "dashboard",
    request: Optional[Request] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """Merge Mission Control shell context into an existing template context."""
    req = request or ctx.get("request")
    merged = mc_context(
        db,
        campaign=campaign,
        session=session,
        active_nav=active_nav,
        layout=layout,
        request=req,
        **extra,
    )
    return {**merged, **ctx}


def entity_form_context(
    db: Session,
    request: Request,
    campaign: Campaign,
    ctx: Dict[str, Any],
    *,
    active_nav: Optional[str] = None,
    session: Optional[SessionModel] = None,
    cancel_default: Optional[str] = None,
    entity_section_key: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    return_to = safe_return_to(request.query_params.get("return_to"))
    form_ctx = {
        **ctx,
        "request": request,
        "return_to": return_to,
        "cancel_url": return_to or cancel_default or lore_board_url(campaign.id),
    }
    entity = ctx.get("entity")
    if entity_section_key and entity and getattr(entity, "id", None):
        from app.services.entity_history_panel import RELATED_KIND_LABELS, build_entity_history_panel

        form_ctx["entity_history_panel"] = build_entity_history_panel(
            db, campaign.id, entity_section_key, entity.id, entity
        )
        form_ctx["related_kind_labels"] = RELATED_KIND_LABELS
        # Legacy alias used by a few tests/templates
        form_ctx["entity_history"] = {
            "sessions": form_ctx["entity_history_panel"]["sessions"],
            "first": form_ctx["entity_history_panel"]["first_seen"],
            "last": form_ctx["entity_history_panel"]["last_seen"],
            "session_count": form_ctx["entity_history_panel"]["session_count"],
        }
        form_ctx["session_presence"] = form_ctx["entity_history"]
        from app.services.relationship_history import get_entity_relationship_history

        form_ctx["relationship_history"] = get_entity_relationship_history(
            db, campaign.id, entity_section_key, entity.id
        )
        from app.services.coappearance import get_entity_coappearance_timeline

        form_ctx["coappearance"] = get_entity_coappearance_timeline(
            db, campaign.id, entity_section_key, entity.id
        )
        health_service = CampaignEntityHealth(db, campaign.id)
        form_ctx["entity_health"] = health_service.score_entity(entity_section_key, entity)
        form_ctx["entity_health_tooltip"] = health_tooltip(form_ctx["entity_health"])
        if entity_section_key in {"npcs", "locations", "threads"}:
            from app.services.narrative_blocks import find_blocks_for_entity

            form_ctx["entity_narrative_blocks"] = find_blocks_for_entity(
                db, campaign.id, entity_section_key, entity.id
            )
    return with_mc(
        db,
        form_ctx,
        request=request,
        campaign=campaign,
        session=session,
        active_nav=active_nav,
        layout="dashboard",
        **extra,
    )


def confirm_delete_context(
    db: Session,
    request: Request,
    campaign: Campaign,
    ctx: Dict[str, Any],
) -> Dict[str, Any]:
    return_to = safe_return_to(request.query_params.get("return_to"))
    form_ctx = {
        **ctx,
        "request": request,
        "return_to": return_to,
        "cancel_url": return_to or lore_board_url(campaign.id),
    }
    return with_mc(db, form_ctx, request=request, campaign=campaign, layout="dashboard")
