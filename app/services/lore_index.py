import hashlib
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from sqlmodel import Session, delete, select

from app.services.provider_router import generate, provider_available as llm_available
from app.models import (
    Campaign,
    CampaignLoreIndex,
    Creature,
    Faction,
    Item,
    Location,
    LoreChunk,
    NPC,
    PlayerCharacterNote,
    PlotThread,
    SessionModel,
)
from app.services.embeddings import (
    cosine_similarity,
    deserialize_embedding,
    embed_text,
    embed_texts,
    get_active_embedding_provider,
    serialize_embedding,
)
from app.utils.time import utc_now

CHUNK_SIZE = 900
CHUNK_OVERLAP = 120
TOP_K_DEFAULT = 8


@dataclass
class LoreDocument:
    source_type: str
    source_id: int
    title: str
    content: str
    url: str


def _join_fields(values: List[Optional[str]]) -> str:
    return "\n".join(value.strip() for value in values if value and value.strip())


def _split_chunks(text: str) -> List[str]:
    cleaned = text.strip()
    if not cleaned:
        return []
    if len(cleaned) <= CHUNK_SIZE:
        return [cleaned]

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", cleaned) if part.strip()]
    chunks: List[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= CHUNK_SIZE:
            current = candidate
            continue
        if current:
            chunks.append(current)
        if len(paragraph) <= CHUNK_SIZE:
            current = paragraph
            continue
        start = 0
        while start < len(paragraph):
            end = min(start + CHUNK_SIZE, len(paragraph))
            chunks.append(paragraph[start:end].strip())
            if end >= len(paragraph):
                break
            start = max(end - CHUNK_OVERLAP, start + 1)
        current = ""
    if current:
        chunks.append(current)
    return chunks


def collect_lore_documents(
    campaign: Campaign,
    sessions: List[SessionModel],
    npcs: List[NPC],
    locations: List[Location],
    factions: List[Faction],
    items: List[Item],
    creatures: List[Creature],
    threads: List[PlotThread],
    pc_notes: List[PlayerCharacterNote],
) -> List[LoreDocument]:
    campaign_id = campaign.id
    documents: List[LoreDocument] = []

    campaign_text = _join_fields([campaign.name, campaign.system, campaign.description])
    if campaign_text:
        documents.append(
            LoreDocument(
                source_type="campaign",
                source_id=campaign_id,
                title=campaign.name,
                content=campaign_text,
                url=f"/campaigns/{campaign_id}",
            )
        )

    for session in sessions:
        body = _join_fields(
            [session.title, session.date, session.player_recap, session.notes, session.recap, session.analysis, session.next_session_prep]
        )
        if body:
            documents.append(
                LoreDocument(
                    source_type="session",
                    source_id=session.id,
                    title=session.title,
                    content=body,
                    url=f"/campaigns/{campaign_id}/sessions/{session.id}",
                )
            )

    for npc in npcs:
        body = _join_fields(
            [
                npc.name,
                npc.role,
                npc.description,
                npc.current_status,
                npc.current_location,
                npc.relationship_to_party,
                npc.goals,
                npc.secrets,
                npc.alive_or_dead,
            ]
        )
        if body:
            documents.append(
                LoreDocument(
                    source_type="npc",
                    source_id=npc.id,
                    title=npc.name,
                    content=body,
                    url=f"/campaigns/{campaign_id}/npcs/{npc.id}/edit",
                )
            )

    for location in locations:
        body = _join_fields([location.name, location.description, location.notes])
        if body:
            documents.append(
                LoreDocument(
                    source_type="location",
                    source_id=location.id,
                    title=location.name,
                    content=body,
                    url=f"/campaigns/{campaign_id}/locations/{location.id}/edit",
                )
            )

    for faction in factions:
        body = _join_fields([faction.name, faction.faction_type, faction.summary, faction.plot_notes])
        if body:
            documents.append(
                LoreDocument(
                    source_type="faction",
                    source_id=faction.id,
                    title=faction.name,
                    content=body,
                    url=f"/campaigns/{campaign_id}/factions/{faction.id}/edit",
                )
            )

    for item in items:
        body = _join_fields([item.name, item.item_type, item.description, item.origin, item.plot_notes])
        if body:
            documents.append(
                LoreDocument(
                    source_type="item",
                    source_id=item.id,
                    title=item.name,
                    content=body,
                    url=f"/campaigns/{campaign_id}/items/{item.id}/edit",
                )
            )

    for creature in creatures:
        body = _join_fields([
            creature.name,
            creature.creature_type,
            creature.classification,
            creature.habitat,
            creature.threat_level,
            creature.physical_description,
            creature.special_traits,
            creature.campaign_context_tactics,
            creature.description,
            creature.notes,
        ])
        if body:
            documents.append(
                LoreDocument(
                    source_type="creature",
                    source_id=creature.id,
                    title=creature.name,
                    content=body,
                    url=f"/campaigns/{campaign_id}/creatures/{creature.id}/edit",
                )
            )

    for thread in threads:
        body = _join_fields([
            thread.title,
            thread.status,
            thread.thread_type,
            thread.details,
            thread.plot_significance_notes,
            thread.importance,
            thread.resolution_notes,
        ])
        if body:
            documents.append(
                LoreDocument(
                    source_type="plot_thread",
                    source_id=thread.id,
                    title=thread.title,
                    content=body,
                    url=f"/campaigns/{campaign_id}/threads/{thread.id}/edit",
                )
            )

    for note in pc_notes:
        body = _join_fields(
            [
                note.character_name,
                note.character_archetype,
                note.description,
                note.signature_gear,
                note.key_ties_history,
                note.campaign_role_plot_notes,
                note.notes,
            ]
        )
        if body:
            documents.append(
                LoreDocument(
                    source_type="pc_note",
                    source_id=note.id,
                    title=note.character_name,
                    content=body,
                    url=f"/campaigns/{campaign_id}/pcs/{note.id}/edit",
                )
            )

    return documents


def compute_campaign_fingerprint(documents: List[LoreDocument]) -> str:
    digest = hashlib.sha256()
    for document in sorted(documents, key=lambda doc: (doc.source_type, doc.source_id, doc.title)):
        digest.update(document.source_type.encode("utf-8"))
        digest.update(str(document.source_id).encode("utf-8"))
        digest.update(document.title.encode("utf-8"))
        digest.update(document.content.encode("utf-8"))
    return digest.hexdigest()


def load_campaign_entities(db: Session, campaign_id: int) -> Tuple[Campaign, Dict[str, Any]]:
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise ValueError("Campaign not found.")
    entities = {
        "sessions": db.exec(select(SessionModel).where(SessionModel.campaign_id == campaign_id)).all(),
        "npcs": db.exec(select(NPC).where(NPC.campaign_id == campaign_id)).all(),
        "locations": db.exec(select(Location).where(Location.campaign_id == campaign_id)).all(),
        "factions": db.exec(select(Faction).where(Faction.campaign_id == campaign_id)).all(),
        "items": db.exec(select(Item).where(Item.campaign_id == campaign_id)).all(),
        "creatures": db.exec(select(Creature).where(Creature.campaign_id == campaign_id)).all(),
        "threads": db.exec(select(PlotThread).where(PlotThread.campaign_id == campaign_id)).all(),
        "pc_notes": db.exec(select(PlayerCharacterNote).where(PlayerCharacterNote.campaign_id == campaign_id)).all(),
    }
    return campaign, entities


def get_index_status(db: Session, campaign_id: int, fingerprint: str) -> Dict[str, Any]:
    meta = db.get(CampaignLoreIndex, campaign_id)
    if not meta:
        return {"indexed": False, "stale": True, "chunk_count": 0, "embedding_provider": None}
    return {
        "indexed": True,
        "stale": meta.content_fingerprint != fingerprint,
        "chunk_count": meta.chunk_count,
        "embedding_provider": meta.embedding_provider,
        "indexed_at": meta.indexed_at,
    }


def get_lore_index_warning(db: Session, campaign_id: int, fingerprint: str) -> Optional[str]:
    status = get_index_status(db, campaign_id, fingerprint)
    if not status["indexed"] or status["stale"] or status["chunk_count"] == 0:
        return "Search index is missing or stale. Click Rebuild Index."
    return None


def rebuild_lore_index(db: Session, campaign_id: int, force: bool = False) -> Dict[str, Any]:
    campaign, entities = load_campaign_entities(db, campaign_id)
    documents = collect_lore_documents(campaign, **entities)
    fingerprint = compute_campaign_fingerprint(documents)
    meta = db.get(CampaignLoreIndex, campaign_id)
    if meta and not force and meta.content_fingerprint == fingerprint:
        return {
            "rebuilt": False,
            "chunk_count": meta.chunk_count,
            "embedding_provider": meta.embedding_provider,
            "content_fingerprint": fingerprint,
        }

    provider = get_active_embedding_provider()
    chunk_records: List[Tuple[LoreDocument, int, str, str]] = []
    for document in documents:
        for chunk_index, chunk_text in enumerate(_split_chunks(document.content)):
            chunk_hash = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()
            chunk_records.append((document, chunk_index, chunk_text, chunk_hash))

    texts = [chunk_text for _, _, chunk_text, _ in chunk_records]
    embeddings = embed_texts(texts, provider=provider, task_name="search/reindex") if texts else []

    db.exec(delete(LoreChunk).where(LoreChunk.campaign_id == campaign_id))
    for (document, chunk_index, chunk_text, chunk_hash), embedding in zip(chunk_records, embeddings):
        db.add(
            LoreChunk(
                campaign_id=campaign_id,
                source_type=document.source_type,
                source_id=document.source_id,
                chunk_index=chunk_index,
                title=document.title,
                content=chunk_text,
                content_hash=chunk_hash,
                embedding=serialize_embedding(embedding),
            )
        )

    if meta:
        meta.content_fingerprint = fingerprint
        meta.chunk_count = len(chunk_records)
        meta.embedding_provider = provider
        meta.indexed_at = utc_now()
        db.add(meta)
    else:
        db.add(
            CampaignLoreIndex(
                campaign_id=campaign_id,
                content_fingerprint=fingerprint,
                chunk_count=len(chunk_records),
                embedding_provider=provider,
            )
        )

    db.commit()
    return {
        "rebuilt": True,
        "chunk_count": len(chunk_records),
        "embedding_provider": provider,
        "content_fingerprint": fingerprint,
    }


def ensure_lore_index(db: Session, campaign_id: int) -> Dict[str, Any]:
    """Returns index metadata without rebuilding. Use rebuild_lore_index explicitly."""
    campaign, entities = load_campaign_entities(db, campaign_id)
    documents = collect_lore_documents(campaign, **entities)
    fingerprint = compute_campaign_fingerprint(documents)
    meta = db.get(CampaignLoreIndex, campaign_id)
    if not meta:
        return {
            "rebuilt": False,
            "chunk_count": 0,
            "embedding_provider": None,
            "content_fingerprint": fingerprint,
            "ready": False,
        }
    return {
        "rebuilt": False,
        "chunk_count": meta.chunk_count,
        "embedding_provider": meta.embedding_provider,
        "content_fingerprint": fingerprint,
        "ready": meta.content_fingerprint == fingerprint and meta.chunk_count > 0,
    }


def semantic_search_campaign(
    db: Session,
    campaign_id: int,
    query: str,
    top_k: int = TOP_K_DEFAULT,
) -> List[Dict[str, Any]]:
    query_vector = embed_text(query, task_name="search/semantic")
    chunks = db.exec(select(LoreChunk).where(LoreChunk.campaign_id == campaign_id)).all()
    scored = []
    for chunk in chunks:
        score = cosine_similarity(query_vector, deserialize_embedding(chunk.embedding))
        scored.append((score, chunk))
    scored.sort(key=lambda item: item[0], reverse=True)

    results = []
    for score, chunk in scored[:top_k]:
        if score <= 0:
            continue
        snippet = chunk.content[:220] + ("..." if len(chunk.content) > 220 else "")
        results.append(
            {
                "title": chunk.title,
                "subtitle": f"{chunk.source_type.replace('_', ' ').title()} · chunk {chunk.chunk_index + 1}",
                "snippet": snippet,
                "score": round(score, 3),
                "source_type": chunk.source_type,
                "source_id": chunk.source_id,
                "url": build_entity_url(campaign_id, chunk.source_type, chunk.source_id),
            }
        )
    return results


def build_entity_url(campaign_id: int, source_type: str, source_id: int) -> str:
    routes = {
        "campaign": f"/campaigns/{campaign_id}",
        "session": f"/campaigns/{campaign_id}/sessions/{source_id}",
        "npc": f"/campaigns/{campaign_id}/npcs/{source_id}/edit",
        "location": f"/campaigns/{campaign_id}/locations/{source_id}/edit",
        "faction": f"/campaigns/{campaign_id}/factions/{source_id}/edit",
        "item": f"/campaigns/{campaign_id}/items/{source_id}/edit",
        "creature": f"/campaigns/{campaign_id}/creatures/{source_id}/edit",
        "plot_thread": f"/campaigns/{campaign_id}/threads/{source_id}/edit",
        "pc_note": f"/campaigns/{campaign_id}/pcs/{source_id}/edit",
    }
    return routes.get(source_type, f"/campaigns/{campaign_id}")


def rag_answer_campaign(db: Session, campaign_id: int, query: str, top_k: int = TOP_K_DEFAULT) -> Dict[str, Any]:
    campaign, _ = load_campaign_entities(db, campaign_id)
    matches = semantic_search_campaign(db, campaign_id, query, top_k=top_k)
    if not matches:
        return {
            "answer": "No indexed campaign lore matched that question. Try rebuilding the search index or adding more notes.",
            "sources": [],
            "used_llm": False,
        }

    context_blocks = []
    sources = []
    for index, match in enumerate(matches, start=1):
        context_blocks.append(f"[{index}] {match['title']} ({match['subtitle']})\n{match['snippet']}")
        sources.append(
            {
                **match,
                "url": build_entity_url(campaign_id, match["source_type"], match["source_id"]),
            }
        )

    if not llm_available():
        answer = (
            "Retrieved the most relevant lore snippets, but no LLM provider is configured for a synthesized answer.\n\n"
            + "\n\n".join(context_blocks)
        )
        return {"answer": answer, "sources": sources, "used_llm": False}

    prompt = (
        f"You are a tabletop campaign lore assistant for the campaign '{campaign.name}'.\n"
        "Answer the user's question using only the retrieved lore context below.\n"
        "If the context is insufficient, say what is missing instead of inventing facts.\n"
        "Cite source numbers like [1] when referencing specific lore.\n\n"
        f"Question:\n{query}\n\n"
        "Retrieved lore:\n"
        f"{chr(10).join(context_blocks)}\n\n"
        "Answer in clear markdown."
    )
    try:
        answer = generate(
            prompt,
            max_tokens=1200,
            task_name="search/rag",
        )
        return {"answer": answer, "sources": sources, "used_llm": True}
    except Exception as exc:
        prefix = f"LLM request failed ({exc}); showing retrieved lore snippets only.\n\n"
        return {"answer": prefix + "\n\n".join(context_blocks), "sources": sources, "used_llm": False}
