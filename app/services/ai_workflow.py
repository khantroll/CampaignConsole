import logging
from typing import Any, Dict, Optional, Tuple

from sqlmodel import Session, select

from app.llm import generate, get_active_provider_or_none, get_configured_model
from app.models import Campaign, Faction, Location, NPC, PlotThread, SessionModel
from app.services.analysis import (
    apply_parsed_ai_output,
    build_ai_parse_message,
    build_campaign_future_prep_prompt,
    parser_display_name,
    parse_ai_analysis,
    save_ai_run_metadata,
)

logger = logging.getLogger(__name__)


def load_future_prep_context(db: Session, campaign_id: int):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        return None, [], [], [], [], [], []
    sessions = db.exec(
        select(SessionModel).where(SessionModel.campaign_id == campaign_id).order_by(SessionModel.id)
    ).all()
    npcs = db.exec(select(NPC).where(NPC.campaign_id == campaign_id)).all()
    locations = db.exec(select(Location).where(Location.campaign_id == campaign_id)).all()
    factions = db.exec(select(Faction).where(Faction.campaign_id == campaign_id)).all()
    threads = db.exec(select(PlotThread).where(PlotThread.campaign_id == campaign_id)).all()
    return campaign, sessions, npcs, locations, factions, threads


def session_has_analysis(session_model: SessionModel) -> bool:
    return bool(
        (session_model.player_recap or "").strip()
        or (session_model.recap or "").strip()
        or (session_model.analysis or "").strip()
    )


def run_future_prep_generation(
    db: Session,
    campaign_id: int,
    session_model: SessionModel,
    notes: str,
    *,
    save_to_session: bool,
    task_name: str = "ai/review",
    save_raw_on_failure: bool = False,
) -> Tuple[Optional[str], Dict[str, Any], str]:
    """Generate future prep. Returns (message, result_dict, prep_text)."""
    context = load_future_prep_context(db, campaign_id)
    if context[0] is None:
        return "Campaign not found.", {"fields_extracted": False, "updated_fields": []}, ""

    campaign, sessions, npcs, locations, factions, threads = context
    prompt = build_campaign_future_prep_prompt(
        campaign,
        sessions,
        npcs,
        locations,
        factions,
        threads,
        session_model.title,
        session_model.date or "",
        notes,
    )
    try:
        output = generate(prompt, max_tokens=2400, task_name=task_name)
    except Exception as exc:
        logger.exception("Future prep generation failed for session %s", session_model.id)
        return str(exc), {"fields_extracted": False, "updated_fields": []}, ""

    if save_to_session:
        result = apply_parsed_ai_output(
            session_model,
            output,
            update_fields={"next_session_prep"},
            task_name=task_name,
            session_id=session_model.id,
            save_raw_on_failure=save_raw_on_failure,
        )
        prep_text = session_model.next_session_prep or ""
    else:
        parsed, parse_error, parse_format, parse_diagnostics = parse_ai_analysis(output)
        prep_text = (parsed or {}).get("next_session_prep", "") if parsed else ""
        result = {
            "json_parsed": bool(prep_text),
            "fields_extracted": bool(prep_text),
            "parse_error": parse_error,
            "parse_format": parse_format,
            "parser_used": parser_display_name(parse_format),
            "updated_fields": ["next_session_prep"] if prep_text else [],
            "missing_requested_fields": [] if prep_text else ["next_session_prep"],
            "prep_detected_in_raw": bool(prep_text),
            "raw_saved_to": None,
            "raw_output": output if not prep_text else None,
            **parse_diagnostics,
        }

    provider = get_active_provider_or_none()
    model = get_configured_model(provider) if provider else None
    save_ai_run_metadata(
        session_model,
        result,
        provider=provider,
        model=model,
        task_name=task_name,
        saved_to_session_id=session_model.id,
    )
    db.add(session_model)

    message = build_ai_parse_message(result, context="review")
    if not message and prep_text:
        if save_to_session:
            message = f"Future prep saved to {session_model.title}."
        else:
            message = "Prep draft generated. Review and save when ready."

    return message, result, prep_text
