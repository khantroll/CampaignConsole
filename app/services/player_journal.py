"""Player Journal and campaign-memory read models."""

from typing import Dict, List, Optional

from sqlmodel import Session, select

from app.models import (
    CampaignMembership,
    PlayerCharacterNote,
    PlayerJournalEntry,
    PlayerReveal,
    PlotThread,
    SessionModel,
    User,
)
from app.services.player_console import load_player_reveals


ENTRY_TYPES = {
    "note": "Note",
    "theory": "Theory",
    "question": "Question",
    "goal": "Goal",
    "journal": "Journal Entry",
}
VISIBILITIES = {
    "private": "Private",
    "gm": "GM",
    "party": "Party",
}


def visible_reveal_map(db: Session, membership: CampaignMembership) -> Dict[int, Dict]:
    return {
        row["reveal_id"]: row
        for row in load_player_reveals(db, membership)
        if row.get("reveal_id") is not None
    }


def published_sessions(db: Session, campaign_id: int) -> List[SessionModel]:
    return [
        row
        for row in db.exec(
            select(SessionModel)
            .where(SessionModel.campaign_id == campaign_id)
            .order_by(SessionModel.id.desc())
        ).all()
        if (row.player_recap or "").strip()
    ]


def validate_session_link(db: Session, campaign_id: int, session_id: Optional[int]) -> bool:
    if session_id is None:
        return True
    row = db.get(SessionModel, session_id)
    return bool(
        row
        and row.campaign_id == campaign_id
        and (row.player_recap or "").strip()
    )


def validate_reveal_link(
    db: Session,
    membership: CampaignMembership,
    reveal_id: Optional[int],
) -> bool:
    if reveal_id is None:
        return True
    return reveal_id in visible_reveal_map(db, membership)


def load_player_journal(
    db: Session,
    membership: CampaignMembership,
    viewer_user_id: int,
) -> List[Dict]:
    entries = db.exec(
        select(PlayerJournalEntry)
        .where(PlayerJournalEntry.campaign_id == membership.campaign_id)
        .order_by(PlayerJournalEntry.created_at.desc(), PlayerJournalEntry.id.desc())
    ).all()
    reveal_map = visible_reveal_map(db, membership)
    rows: List[Dict] = []
    for entry in entries:
        is_author = entry.author_user_id == viewer_user_id
        if not is_author and entry.visibility != "party":
            continue
        linked_reveal = reveal_map.get(entry.linked_reveal_id) if entry.linked_reveal_id else None
        session = db.get(SessionModel, entry.session_id) if entry.session_id else None
        if session and (
            session.campaign_id != membership.campaign_id
            or not (session.player_recap or "").strip()
        ):
            session = None
        rows.append({
            "entry": entry,
            "type_label": ENTRY_TYPES.get(entry.entry_type, entry.entry_type.title()),
            "visibility_label": VISIBILITIES.get(entry.visibility, entry.visibility.title()),
            "linked_reveal": linked_reveal,
            "session": session,
            "is_author": is_author,
        })
    return rows


def load_gm_journal(db: Session, campaign_id: int) -> List[Dict]:
    entries = db.exec(
        select(PlayerJournalEntry)
        .where(
            PlayerJournalEntry.campaign_id == campaign_id,
            PlayerJournalEntry.visibility != "private",
        )
        .order_by(PlayerJournalEntry.is_resolved, PlayerJournalEntry.created_at.desc())
    ).all()
    rows: List[Dict] = []
    for entry in entries:
        reveal = db.get(PlayerReveal, entry.linked_reveal_id) if entry.linked_reveal_id else None
        session = db.get(SessionModel, entry.session_id) if entry.session_id else None
        rows.append({
            "entry": entry,
            "type_label": ENTRY_TYPES.get(entry.entry_type, entry.entry_type.title()),
            "visibility_label": VISIBILITIES.get(entry.visibility, entry.visibility.title()),
            "reveal": reveal if reveal and reveal.campaign_id == campaign_id else None,
            "session": session if session and session.campaign_id == campaign_id else None,
        })
    return rows


def load_party(db: Session, campaign_id: int) -> List[Dict]:
    memberships = db.exec(
        select(CampaignMembership).where(
            CampaignMembership.campaign_id == campaign_id,
            CampaignMembership.role == "player",
        )
    ).all()
    rows: List[Dict] = []
    for membership in memberships:
        user = db.get(User, membership.user_id)
        pc = db.get(PlayerCharacterNote, membership.player_character_id) if membership.player_character_id else None
        rows.append({
            "display_name": user.display_name if user else "Former player",
            "character_name": pc.character_name if pc else None,
            "character_archetype": pc.character_archetype if pc else None,
            "portrait_path": pc.portrait_path if pc else None,
        })
    return rows


def load_active_leads(db: Session, membership: CampaignMembership) -> List[Dict]:
    leads: List[Dict] = []
    for reveal in load_player_reveals(db, membership, entity_kind="plot_thread"):
        thread = db.get(PlotThread, reveal["entity_id"])
        if not thread or thread.campaign_id != membership.campaign_id:
            continue
        # The reveal is the player-safe projection. Do not expose raw PlotThread fields here.
        leads.append(dict(reveal))
    return leads
