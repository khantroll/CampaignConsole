"""Convert characters between NPC and PC records, preserving session and location links."""

from __future__ import annotations

from typing import Optional, Tuple

from sqlmodel import Session, select

from app.models import (
    Faction,
    Location,
    NPC,
    NPCFactionLink,
    NPCLocationLink,
    NPCPlotThreadLink,
    PCLocationLink,
    PCFactionLink,
    PCPlotThreadLink,
    PlayerCharacterNote,
    SessionNPCLink,
    SessionPartyMemberLink,
)
from app.services.entity_deletion import delete_npc_cascade, delete_pc_cascade


def _join_notes(*parts: Optional[str]) -> Optional[str]:
    lines = [part.strip() for part in parts if part and str(part).strip()]
    return "\n\n".join(lines) if lines else None


def _migrate_session_links_npc_to_pc(db: Session, npc_id: int, pc_id: int) -> None:
    for link in db.exec(select(SessionNPCLink).where(SessionNPCLink.npc_id == npc_id)).all():
        exists = db.exec(
            select(SessionPartyMemberLink).where(
                SessionPartyMemberLink.session_id == link.session_id,
                SessionPartyMemberLink.pc_note_id == pc_id,
            )
        ).first()
        if not exists:
            db.add(SessionPartyMemberLink(session_id=link.session_id, pc_note_id=pc_id))


def _migrate_session_links_pc_to_npc(db: Session, pc_id: int, npc_id: int) -> None:
    for link in db.exec(select(SessionPartyMemberLink).where(SessionPartyMemberLink.pc_note_id == pc_id)).all():
        exists = db.exec(
            select(SessionNPCLink).where(
                SessionNPCLink.session_id == link.session_id,
                SessionNPCLink.npc_id == npc_id,
            )
        ).first()
        if not exists:
            db.add(SessionNPCLink(session_id=link.session_id, npc_id=npc_id))


def _migrate_location_links_npc_to_pc(db: Session, npc_id: int, pc_id: int) -> None:
    for link in db.exec(select(NPCLocationLink).where(NPCLocationLink.npc_id == npc_id)).all():
        exists = db.exec(
            select(PCLocationLink).where(
                PCLocationLink.pc_note_id == pc_id,
                PCLocationLink.location_id == link.location_id,
            )
        ).first()
        if not exists:
            db.add(PCLocationLink(pc_note_id=pc_id, location_id=link.location_id))


def _migrate_location_links_pc_to_npc(db: Session, pc_id: int, npc_id: int) -> None:
    for link in db.exec(select(PCLocationLink).where(PCLocationLink.pc_note_id == pc_id)).all():
        exists = db.exec(
            select(NPCLocationLink).where(
                NPCLocationLink.npc_id == npc_id,
                NPCLocationLink.location_id == link.location_id,
            )
        ).first()
        if not exists:
            db.add(NPCLocationLink(npc_id=npc_id, location_id=link.location_id))


def _migrate_faction_links_npc_to_pc(db: Session, npc_id: int, pc_id: int) -> None:
    for link in db.exec(select(NPCFactionLink).where(NPCFactionLink.npc_id == npc_id)).all():
        exists = db.exec(
            select(PCFactionLink).where(
                PCFactionLink.pc_note_id == pc_id,
                PCFactionLink.faction_id == link.faction_id,
            )
        ).first()
        if not exists:
            db.add(PCFactionLink(pc_note_id=pc_id, faction_id=link.faction_id))


def _migrate_faction_links_pc_to_npc(db: Session, pc_id: int, npc_id: int) -> None:
    for link in db.exec(select(PCFactionLink).where(PCFactionLink.pc_note_id == pc_id)).all():
        exists = db.exec(
            select(NPCFactionLink).where(
                NPCFactionLink.npc_id == npc_id,
                NPCFactionLink.faction_id == link.faction_id,
            )
        ).first()
        if not exists:
            db.add(NPCFactionLink(npc_id=npc_id, faction_id=link.faction_id))


def _migrate_thread_links_npc_to_pc(db: Session, npc_id: int, pc_id: int) -> None:
    for link in db.exec(select(NPCPlotThreadLink).where(NPCPlotThreadLink.npc_id == npc_id)).all():
        exists = db.exec(
            select(PCPlotThreadLink).where(
                PCPlotThreadLink.pc_note_id == pc_id,
                PCPlotThreadLink.plot_thread_id == link.plot_thread_id,
            )
        ).first()
        if not exists:
            db.add(PCPlotThreadLink(pc_note_id=pc_id, plot_thread_id=link.plot_thread_id))


def _migrate_thread_links_pc_to_npc(db: Session, pc_id: int, npc_id: int) -> None:
    for link in db.exec(select(PCPlotThreadLink).where(PCPlotThreadLink.pc_note_id == pc_id)).all():
        exists = db.exec(
            select(NPCPlotThreadLink).where(
                NPCPlotThreadLink.npc_id == npc_id,
                NPCPlotThreadLink.plot_thread_id == link.plot_thread_id,
            )
        ).first()
        if not exists:
            db.add(NPCPlotThreadLink(npc_id=npc_id, plot_thread_id=link.plot_thread_id))


def convert_npc_to_pc(db: Session, npc: NPC) -> Tuple[PlayerCharacterNote, Optional[str]]:
    if not npc.id:
        raise ValueError("NPC must be persisted before conversion.")

    notes = _join_notes(
        npc.relationship_to_party and f"Relationship to party: {npc.relationship_to_party}",
        npc.goals and f"Goals: {npc.goals}",
        npc.secrets and f"Secrets: {npc.secrets}",
        npc.current_status and f"Status: {npc.current_status}",
        npc.current_location and f"Current location: {npc.current_location}",
        npc.alive_or_dead and f"Alive or dead: {npc.alive_or_dead}",
    )

    pc = PlayerCharacterNote(
        campaign_id=npc.campaign_id,
        character_name=npc.name,
        character_archetype=npc.role,
        description=npc.description,
        key_ties_history=notes,
    )
    db.add(pc)
    db.flush()

    _migrate_session_links_npc_to_pc(db, npc.id, pc.id)
    _migrate_location_links_npc_to_pc(db, npc.id, pc.id)
    _migrate_faction_links_npc_to_pc(db, npc.id, pc.id)
    _migrate_thread_links_npc_to_pc(db, npc.id, pc.id)

    delete_npc_cascade(db, npc)
    db.add(pc)
    db.flush()

    return pc, None


def convert_pc_to_npc(db: Session, pc: PlayerCharacterNote) -> Tuple[NPC, None]:
    if not pc.id:
        raise ValueError("PC must be persisted before conversion.")

    npc = NPC(
        campaign_id=pc.campaign_id,
        name=pc.character_name,
        role=pc.character_archetype or "Party Member",
        description=pc.description,
        goals=pc.key_ties_history,
        relationship_to_party=pc.campaign_role_plot_notes or "Party member",
        secrets=_join_notes(
            pc.signature_gear and f"Signature gear: {pc.signature_gear}",
            pc.notes and f"Additional notes: {pc.notes}",
        ),
    )
    db.add(npc)
    db.flush()

    _migrate_session_links_pc_to_npc(db, pc.id, npc.id)
    _migrate_location_links_pc_to_npc(db, pc.id, npc.id)
    _migrate_faction_links_pc_to_npc(db, pc.id, npc.id)
    _migrate_thread_links_pc_to_npc(db, pc.id, npc.id)

    delete_pc_cascade(db, pc)
    db.add(npc)
    db.flush()
    return npc, None
