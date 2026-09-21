from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from app.database import get_session
from app.deps import templates
from app.models import Campaign, Creature, Faction, Item, Location, NPC, PlayerCharacterNote, PlotThread, SessionModel
from app.services.ingestion import (
    EMPTY_CANDIDATES,
    PLOT_THREAD_MATCH_ATTRS,
    apply_approved_entity_relationships,
    apply_ingest_session_content,
    build_candidate_link_options,
    build_entity_relationship_options,
    build_location_link_options,
    build_matched_npc_link_options,
    build_matched_pc_link_options,
    build_review_debug_rows,
    build_unclassified_character_options,
    candidates_for_review,
    extract_candidates_from_notes,
    get_known_party_names,
    prepare_review_candidates,
    split_party_and_npc_selections,
    split_unclassified_character_selections,
)
from app.services.ingestion_clues import apply_clue_ingest_actions, build_clue_review_rows, parse_ingest_clues_json
from app.services.mission_control_ui import with_mc
from app.services.entity_session_presence import refresh_session_link_metadata
from app.services.provider_router import gemini_is_disabled, provider_available as llm_available
from app.services.session_matching import find_matching_session

router = APIRouter()


def _ingest_context(
    db: Session,
    request: Request,
    campaign: Campaign,
    *,
    message: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    return with_mc(
        db,
        {"request": request, "campaign": campaign, "message": message, **extra},
        request=request,
        campaign=campaign,
        active_nav="ingest",
        layout="dashboard",
    )


@router.get("/campaigns/{campaign_id}/ingest", response_class=HTMLResponse)
def ingest_form(request: Request, campaign_id: int, db: Session = Depends(get_session)):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        "ingest.html",
        _ingest_context(db, request, campaign),
    )


@router.post("/campaigns/{campaign_id}/ingest", response_class=HTMLResponse)
def ingest_review(
    request: Request,
    campaign_id: int,
    session_title: str = Form(""),
    session_date: str = Form(""),
    raw_notes: str = Form(""),
    db: Session = Depends(get_session),
):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        return RedirectResponse(url="/", status_code=303)
    if not raw_notes.strip():
        return templates.TemplateResponse(
            "ingest.html",
            _ingest_context(db, request, campaign, message="Please paste raw session notes."),
        )

    message = None
    if gemini_is_disabled():
        message = (
            "Gemini is disabled (GEMINI_DISABLED=true). Candidate extraction is unavailable; "
            "you can still create a session from the raw notes."
        )
        normalized = dict(EMPTY_CANDIDATES)
    elif not llm_available():
        message = (
            "LLM provider not configured. Candidate extraction is unavailable; "
            "you can still create a session from the raw notes."
        )
        normalized = dict(EMPTY_CANDIDATES)
    else:
        try:
            normalized, parse_warning = extract_candidates_from_notes(campaign, raw_notes)
            if parse_warning:
                message = (
                    "Candidate extraction was partially parsed from AI output. "
                    "Review the results below and edit links as needed. "
                    f"Parse note: {parse_warning}"
                )
        except Exception as exc:
            message = (
                f"Candidate extraction failed, but you can still create a session from the raw notes. "
                f"Error: {exc}"
            )
            normalized = dict(EMPTY_CANDIDATES)

    existing_pcs = db.exec(select(PlayerCharacterNote).where(PlayerCharacterNote.campaign_id == campaign_id)).all()
    existing_npcs = db.exec(select(NPC).where(NPC.campaign_id == campaign_id)).all()
    review_data = prepare_review_candidates(normalized, existing_pcs, existing_npcs)
    review_candidates = candidates_for_review(review_data)

    existing_locations = db.exec(select(Location).where(Location.campaign_id == campaign_id)).all()
    existing_factions = db.exec(select(Faction).where(Faction.campaign_id == campaign_id)).all()
    existing_items = db.exec(select(Item).where(Item.campaign_id == campaign_id)).all()
    existing_creatures = db.exec(select(Creature).where(Creature.campaign_id == campaign_id)).all()
    existing_threads = db.exec(select(PlotThread).where(PlotThread.campaign_id == campaign_id)).all()

    party_links = build_matched_pc_link_options(review_candidates.get("PartyMembers", []), existing_pcs)
    npc_links = build_matched_npc_link_options(review_candidates.get("NPCs", []), existing_npcs)
    unclassified_links = build_unclassified_character_options(
        review_candidates.get("UnclassifiedCharacters", [])
    )

    candidate_links = {
        "PartyMembers": party_links,
        "NPCs": npc_links,
        "UnclassifiedCharacters": unclassified_links,
        "Locations": build_location_link_options(
            review_candidates.get("Locations", []), existing_locations
        ),
        "Factions": build_candidate_link_options(
            review_candidates.get("Factions", []), existing_factions, "name", bucket="faction"
        ),
        "Items": build_candidate_link_options(
            review_candidates.get("Items", []), existing_items, "name", bucket="item"
        ),
        "Creatures": build_candidate_link_options(
            review_candidates.get("Creatures", []), existing_creatures, "name", bucket="creature"
        ),
        "PlotThreads": build_candidate_link_options(
            review_candidates.get("PlotThreads", []),
            existing_threads,
            "title",
            bucket="thread",
            similarity_extra_attrs=PLOT_THREAD_MATCH_ATTRS,
        ),
        "SecretsClues": review_candidates.get("SecretsClues", []),
        "UnresolvedHooks": review_candidates.get("UnresolvedHooks", []),
    }
    relationship_options = build_entity_relationship_options(review_data.get("EntityRelationships", []))
    debug_rows = build_review_debug_rows(
        party_links,
        npc_links,
        unclassified_links,
        candidate_links["Locations"],
        candidate_links["Factions"],
        candidate_links["Items"],
        candidate_links["Creatures"],
        candidate_links["PlotThreads"],
    )

    clue_review = build_clue_review_rows(
        review_candidates.get("SecretsClues", []),
        existing_threads,
        extracted_thread_titles=review_candidates.get("PlotThreads", []),
    )

    matched_session = find_matching_session(db, campaign_id, session_title, session_date)

    return templates.TemplateResponse(
        "ingest_review.html",
        _ingest_context(
            db,
            request,
            campaign,
            message=message,
            session_title=session_title,
            session_date=session_date,
            raw_notes=raw_notes,
            candidates=review_candidates,
            candidate_links=candidate_links,
            relationship_options=relationship_options,
            debug_rows=debug_rows,
            known_party_names=get_known_party_names(db, campaign_id),
            matched_session=matched_session,
            clue_review=clue_review,
        ),
    )


@router.post("/campaigns/{campaign_id}/ingest/save")
def ingest_save(
    request: Request,
    campaign_id: int,
    session_title: str = Form("Untitled Session"),
    session_date: str = Form(""),
    raw_notes: str = Form(""),
    selected_party_links: Optional[List[str]] = Form(None),
    selected_npc_links: Optional[List[str]] = Form(None),
    selected_unclassified_links: Optional[List[str]] = Form(None),
    selected_location_links: Optional[List[str]] = Form(None),
    selected_faction_links: Optional[List[str]] = Form(None),
    selected_item_links: Optional[List[str]] = Form(None),
    selected_creature_links: Optional[List[str]] = Form(None),
    selected_thread_links: Optional[List[str]] = Form(None),
    selected_secretsclues: Optional[List[str]] = Form(None),
    selected_unresolvedhooks: Optional[List[str]] = Form(None),
    selected_entity_relationships: Optional[List[str]] = Form(None),
    selected_npc_relationships: Optional[List[str]] = Form(None),
    selected_clue_actions: Optional[List[str]] = Form(None),
    ingest_clues_json: str = Form(""),
    ingest_save_mode: str = Form("create_new"),
    matched_session_id: str = Form(""),
    db: Session = Depends(get_session),
):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        return RedirectResponse(url="/", status_code=303)

    prep_parts = []
    if selected_secretsclues:
        prep_parts.append(
            "Secrets/Clues Revealed:\n" + "\n".join(f"- {item.strip()}" for item in selected_secretsclues if item.strip())
        )
    if selected_unresolvedhooks:
        prep_parts.append(
            "Unresolved Hooks:\n" + "\n".join(f"- {item.strip()}" for item in selected_unresolvedhooks if item.strip())
        )

    party_only, _ = split_party_and_npc_selections(selected_party_links)
    party_from_unclassified, npc_from_unclassified = split_unclassified_character_selections(
        selected_unclassified_links
    )
    party_selections = party_only + party_from_unclassified
    combined_npc_links = list(selected_npc_links or []) + npc_from_unclassified
    clue_texts = parse_ingest_clues_json(ingest_clues_json)

    target_session = None
    if ingest_save_mode == "update_existing" and matched_session_id.isdigit():
        candidate = db.get(SessionModel, int(matched_session_id))
        if (
            candidate
            and candidate.campaign_id == campaign_id
            and find_matching_session(db, campaign_id, session_title, session_date) == candidate
        ):
            target_session = candidate

    if target_session:
        apply_ingest_session_content(
            db,
            campaign_id,
            target_session,
            raw_notes=raw_notes,
            prep_parts=prep_parts,
            party_selections=party_selections,
            npc_selections=combined_npc_links,
            location_selections=selected_location_links,
            faction_selections=selected_faction_links,
            item_selections=selected_item_links,
            creature_selections=selected_creature_links,
            thread_selections=selected_thread_links,
        )
        approved_relationships = list(selected_entity_relationships or [])
        if selected_npc_relationships:
            approved_relationships.extend(selected_npc_relationships)
        apply_approved_entity_relationships(
            db, campaign_id, approved_relationships, session_id=target_session.id
        )
        if selected_clue_actions and clue_texts:
            apply_clue_ingest_actions(db, campaign_id, clue_texts, selected_clue_actions)
        db.commit()
        db.refresh(target_session)
        refresh_session_link_metadata(db, campaign_id, target_session.id)
        db.commit()
        return RedirectResponse(
            url=f"/campaigns/{campaign_id}/sessions/{target_session.id}?hub_message=updated",
            status_code=303,
        )

    new_session = SessionModel(
        campaign_id=campaign_id,
        title=session_title or "Untitled Session",
        date=session_date,
        notes=raw_notes,
        next_session_prep="\n\n".join(prep_parts) if prep_parts else None,
    )
    db.add(new_session)
    db.flush()

    apply_ingest_session_content(
        db,
        campaign_id,
        new_session,
        raw_notes=raw_notes,
        prep_parts=prep_parts,
        party_selections=party_selections,
        npc_selections=combined_npc_links,
        location_selections=selected_location_links,
        faction_selections=selected_faction_links,
        item_selections=selected_item_links,
        creature_selections=selected_creature_links,
        thread_selections=selected_thread_links,
    )

    approved_relationships = list(selected_entity_relationships or [])
    if selected_npc_relationships:
        approved_relationships.extend(selected_npc_relationships)
    apply_approved_entity_relationships(db, campaign_id, approved_relationships, session_id=new_session.id)

    if selected_clue_actions and clue_texts:
        apply_clue_ingest_actions(db, campaign_id, clue_texts, selected_clue_actions)

    db.commit()
    db.refresh(new_session)
    refresh_session_link_metadata(db, campaign_id, new_session.id)
    db.commit()

    return RedirectResponse(
        url=f"/campaigns/{campaign_id}/sessions/{new_session.id}?hub_message=created",
        status_code=303,
    )
