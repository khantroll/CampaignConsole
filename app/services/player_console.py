"""Player-safe read models for the Phase 2 Player Console."""

from typing import Dict, List, Optional

from sqlmodel import Session, select

from app.models import (
    Campaign,
    CampaignMembership,
    Creature,
    Faction,
    Item,
    Location,
    NPC,
    PCFactionLink,
    PCLocationLink,
    PCPlotThreadLink,
    PlayerCharacterNote,
    PlayerReveal,
    PlotThread,
    RevealAudience,
    SessionModel,
)


ENTITY_MODELS = {
    "npc": (NPC, "name"),
    "location": (Location, "name"),
    "faction": (Faction, "name"),
    "item": (Item, "name"),
    "creature": (Creature, "name"),
    "plot_thread": (PlotThread, "title"),
}

ENTITY_LABELS = {
    "npc": "NPCs",
    "location": "Locations",
    "faction": "Factions",
    "item": "Items",
    "creature": "Creatures",
    "plot_thread": "Plot Threads / Quests",
}


def load_membership(db: Session, user_id: int, campaign_id: int) -> Optional[CampaignMembership]:
    return db.exec(
        select(CampaignMembership).where(
            CampaignMembership.user_id == user_id,
            CampaignMembership.campaign_id == campaign_id,
        )
    ).first()


def load_player_campaigns(db: Session, user_id: int) -> List[Dict]:
    memberships = db.exec(
        select(CampaignMembership)
        .where(CampaignMembership.user_id == user_id)
        .order_by(CampaignMembership.campaign_id)
    ).all()
    rows: List[Dict] = []
    for membership in memberships:
        campaign = db.get(Campaign, membership.campaign_id)
        if not campaign:
            continue
        rows.append({
            "id": campaign.id,
            "name": campaign.name,
            "system": campaign.system,
            "description": campaign.description,
            "role": membership.role,
        })
    return rows


def load_player_campaign(db: Session, membership: CampaignMembership) -> Optional[Dict]:
    campaign = db.get(Campaign, membership.campaign_id)
    if not campaign:
        return None
    return {
        "id": campaign.id,
        "name": campaign.name,
        "system": campaign.system,
        "description": campaign.description,
        "membership_role": membership.role,
    }


def _audience_map(db: Session, reveal_ids: List[int]) -> Dict[int, set]:
    if not reveal_ids:
        return {}
    rows = db.exec(
        select(RevealAudience).where(RevealAudience.reveal_id.in_(reveal_ids))
    ).all()
    audiences: Dict[int, set] = {}
    for row in rows:
        audiences.setdefault(row.reveal_id, set()).add(row.membership_id)
    return audiences


def _visible_reveal_rows(
    db: Session,
    membership: CampaignMembership,
    *,
    entity_kind: Optional[str] = None,
    revealed_session_id: Optional[int] = None,
) -> List[PlayerReveal]:
    query = select(PlayerReveal).where(
        PlayerReveal.campaign_id == membership.campaign_id,
        PlayerReveal.is_active == True,  # noqa: E712 - SQLModel comparison
    )
    if entity_kind:
        query = query.where(PlayerReveal.entity_kind == entity_kind)
    if revealed_session_id is not None:
        query = query.where(PlayerReveal.revealed_session_id == revealed_session_id)
    reveals = db.exec(query.order_by(PlayerReveal.revealed_at.desc(), PlayerReveal.id.desc())).all()
    audiences = _audience_map(db, [r.id for r in reveals if r.id is not None])
    return [
        reveal
        for reveal in reveals
        if reveal.audience_mode == "campaign"
        or (
            reveal.audience_mode == "selected"
            and membership.id in audiences.get(reveal.id, set())
        )
    ]


def _safe_reveal_projection(db: Session, reveal: PlayerReveal) -> Optional[Dict]:
    model_info = ENTITY_MODELS.get(reveal.entity_kind)
    if not model_info:
        return None
    model, name_field = model_info
    entity = db.get(model, reveal.entity_id)
    if not entity or entity.campaign_id != reveal.campaign_id:
        return None
    return {
        "reveal_id": reveal.id,
        "entity_kind": reveal.entity_kind,
        "entity_id": reveal.entity_id,
        "kind_label": ENTITY_LABELS[reveal.entity_kind],
        "title": reveal.title or getattr(entity, name_field),
        "public_summary": reveal.public_summary,
        "revealed_at": reveal.revealed_at,
        "revealed_session_id": reveal.revealed_session_id,
    }


def load_player_reveals(
    db: Session,
    membership: CampaignMembership,
    *,
    entity_kind: Optional[str] = None,
    revealed_session_id: Optional[int] = None,
    limit: Optional[int] = None,
) -> List[Dict]:
    rows = []
    for reveal in _visible_reveal_rows(
        db,
        membership,
        entity_kind=entity_kind,
        revealed_session_id=revealed_session_id,
    ):
        projection = _safe_reveal_projection(db, reveal)
        if projection:
            rows.append(projection)
            if limit and len(rows) >= limit:
                break
    return rows


def load_player_lore_entry(
    db: Session,
    membership: CampaignMembership,
    entity_kind: str,
    entity_id: int,
) -> Optional[Dict]:
    if entity_kind not in ENTITY_MODELS:
        return None
    for projection in load_player_reveals(db, membership, entity_kind=entity_kind):
        if projection["entity_id"] == entity_id:
            return projection
    return None


def load_player_sessions(db: Session, membership: CampaignMembership) -> List[Dict]:
    # A player recap is the deliberate publication signal for a session.
    sessions = db.exec(
        select(SessionModel)
        .where(
            SessionModel.campaign_id == membership.campaign_id,
            SessionModel.player_recap.is_not(None),
        )
        .order_by(SessionModel.id.desc())
    ).all()
    return [
        {
            "id": row.id,
            "title": row.title,
            "date": row.date,
            "player_recap": row.player_recap,
        }
        for row in sessions
        if (row.player_recap or "").strip()
    ]


def load_player_session(
    db: Session,
    membership: CampaignMembership,
    session_id: int,
) -> Optional[Dict]:
    session_model = db.get(SessionModel, session_id)
    if (
        not session_model
        or session_model.campaign_id != membership.campaign_id
        or not (session_model.player_recap or "").strip()
    ):
        return None
    return {
        "id": session_model.id,
        "title": session_model.title,
        "date": session_model.date,
        "player_recap": session_model.player_recap,
        "reveals": load_player_reveals(
            db, membership, revealed_session_id=session_model.id
        ),
    }


def _visible_related(
    db: Session,
    membership: CampaignMembership,
    entity_kind: str,
    entity_ids: List[int],
) -> List[Dict]:
    allowed = {
        row["entity_id"]: row
        for row in load_player_reveals(db, membership, entity_kind=entity_kind)
    }
    return [allowed[entity_id] for entity_id in entity_ids if entity_id in allowed]


def load_player_character(db: Session, membership: CampaignMembership) -> Optional[Dict]:
    if not membership.player_character_id:
        return None
    pc = db.get(PlayerCharacterNote, membership.player_character_id)
    if not pc or pc.campaign_id != membership.campaign_id:
        return None

    location_ids = db.exec(
        select(PCLocationLink.location_id).where(PCLocationLink.pc_note_id == pc.id)
    ).all()
    faction_ids = db.exec(
        select(PCFactionLink.faction_id).where(PCFactionLink.pc_note_id == pc.id)
    ).all()
    thread_ids = db.exec(
        select(PCPlotThreadLink.plot_thread_id).where(PCPlotThreadLink.pc_note_id == pc.id)
    ).all()

    # Intentionally excludes campaign_role_plot_notes and notes.
    return {
        "id": pc.id,
        "character_name": pc.character_name,
        "character_archetype": pc.character_archetype,
        "description": pc.description,
        "signature_gear": pc.signature_gear,
        "key_ties_history": pc.key_ties_history,
        "locations": _visible_related(db, membership, "location", location_ids),
        "factions": _visible_related(db, membership, "faction", faction_ids),
        "plot_threads": _visible_related(db, membership, "plot_thread", thread_ids),
    }


def load_player_home(db: Session, membership: CampaignMembership) -> Dict:
    sessions = load_player_sessions(db, membership)
    return {
        "campaign": load_player_campaign(db, membership),
        "character": load_player_character(db, membership),
        "latest_session": sessions[0] if sessions else None,
        "recent_sessions": sessions[:5],
        "recent_reveals": load_player_reveals(db, membership, limit=8),
    }
