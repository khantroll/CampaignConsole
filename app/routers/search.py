from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from app.database import get_session
from app.deps import templates
from app.models import Campaign
from app.services.embeddings import embeddings_available, get_active_embedding_provider
from app.services.lore_index import (
    collect_lore_documents,
    compute_campaign_fingerprint,
    get_index_status,
    get_lore_index_warning,
    load_campaign_entities,
    rag_answer_campaign,
    rebuild_lore_index,
    semantic_search_campaign,
)
from app.services.mission_control_ui import with_mc
from app.services.search import search_campaign_text

router = APIRouter()


def _load_search_context(db: Session, campaign_id: int):
    campaign, entities = load_campaign_entities(db, campaign_id)
    documents = collect_lore_documents(campaign, **entities)
    fingerprint = compute_campaign_fingerprint(documents)
    return campaign, entities, fingerprint


def _search_context(
    db: Session,
    request: Request,
    campaign,
    *,
    query: str = "",
    mode: str = "keyword",
    results=None,
    semantic_results=None,
    rag_answer=None,
    rag_sources=None,
    index_status=None,
    search_warning=None,
) -> Dict[str, Any]:
    if results is None:
        results = {}
    if semantic_results is None:
        semantic_results = []
    if rag_sources is None:
        rag_sources = []
    return with_mc(
        db,
        {
            "request": request,
            "campaign": campaign,
            "query": query,
            "mode": mode,
            "results": results,
            "semantic_results": semantic_results,
            "rag_answer": rag_answer,
            "rag_sources": rag_sources,
            "index_status": index_status,
            "search_warning": search_warning,
            "embeddings_available": embeddings_available(),
            "embedding_provider": get_active_embedding_provider(),
        },
        campaign=campaign,
        active_nav="search",
        layout="dashboard",
        request=request,
    )


@router.get("/campaigns/{campaign_id}/search", response_class=HTMLResponse)
def campaign_search(request: Request, campaign_id: int, db: Session = Depends(get_session)):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        return RedirectResponse(url="/", status_code=303)

    _, _, fingerprint = _load_search_context(db, campaign_id)
    index_status = get_index_status(db, campaign_id, fingerprint)

    return templates.TemplateResponse(
        "search.html",
        _search_context(db, request, campaign, index_status=index_status),
    )


@router.post("/campaigns/{campaign_id}/search/reindex")
def campaign_search_reindex(campaign_id: int, db: Session = Depends(get_session)):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        return RedirectResponse(url="/", status_code=303)
    rebuild_lore_index(db, campaign_id, force=True)
    return RedirectResponse(url=f"/campaigns/{campaign_id}/search", status_code=303)


@router.post("/campaigns/{campaign_id}/search", response_class=HTMLResponse)
def campaign_search_results(
    request: Request,
    campaign_id: int,
    query: str = Form(...),
    mode: str = Form("keyword"),
    db: Session = Depends(get_session),
):
    campaign_ctx, entities, fingerprint = _load_search_context(db, campaign_id)
    if not campaign_ctx:
        return RedirectResponse(url="/", status_code=303)

    index_status = get_index_status(db, campaign_id, fingerprint)
    normalized_mode = mode if mode in {"keyword", "semantic", "ask"} else "keyword"

    results = {}
    semantic_results = []
    rag_answer = None
    rag_sources = []
    search_warning = None

    if normalized_mode == "keyword":
        results = {
            "Sessions": search_campaign_text(
                query, entities["sessions"], ["title", "date", "notes", "player_recap", "recap", "analysis"]
            ),
            "NPCs": search_campaign_text(query, entities["npcs"], ["name", "role", "description"]),
            "Locations": search_campaign_text(query, entities["locations"], ["name", "description", "notes"]),
            "Factions": search_campaign_text(
                query, entities["factions"], ["name", "summary", "plot_notes", "faction_type"]
            ),
            "Items": search_campaign_text(
                query, entities["items"], ["name", "description", "origin", "plot_notes", "item_type"]
            ),
            "Creatures": search_campaign_text(
                query, entities["creatures"], [
                    "name",
                    "classification",
                    "habitat",
                    "threat_level",
                    "physical_description",
                    "special_traits",
                    "campaign_context_tactics",
                    "description",
                    "notes",
                    "creature_type",
                ]
            ),
            "Plot Threads": search_campaign_text(query, entities["threads"], ["title", "status", "details"]),
            "PC Notes": search_campaign_text(
                query,
                entities["pc_notes"],
                [
                    "character_name",
                    "character_archetype",
                    "description",
                    "signature_gear",
                    "key_ties_history",
                    "campaign_role_plot_notes",
                    "notes",
                ],
            ),
        }
    elif normalized_mode == "semantic":
        search_warning = get_lore_index_warning(db, campaign_id, fingerprint)
        if not search_warning:
            semantic_results = semantic_search_campaign(db, campaign_id, query)
    else:
        search_warning = get_lore_index_warning(db, campaign_id, fingerprint)
        if not search_warning:
            rag_result = rag_answer_campaign(db, campaign_id, query)
            rag_answer = rag_result["answer"]
            rag_sources = rag_result["sources"]

    return templates.TemplateResponse(
        "search.html",
        _search_context(
            db,
            request,
            campaign_ctx,
            query=query,
            mode=normalized_mode,
            results=results,
            semantic_results=semantic_results,
            rag_answer=rag_answer,
            rag_sources=rag_sources,
            index_status=index_status,
            search_warning=search_warning,
        ),
    )
