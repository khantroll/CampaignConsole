from datetime import datetime
from typing import List, Optional

from sqlmodel import Column, DateTime, Field, Relationship, SQLModel

from app.utils.time import utc_now


# Link tables must be defined before entity models that reference them via link_model.
class NPCFactionLink(SQLModel, table=True):
    npc_id: Optional[int] = Field(default=None, foreign_key="npc.id", primary_key=True)
    faction_id: Optional[int] = Field(default=None, foreign_key="faction.id", primary_key=True)


class NPCLocationLink(SQLModel, table=True):
    npc_id: Optional[int] = Field(default=None, foreign_key="npc.id", primary_key=True)
    location_id: Optional[int] = Field(default=None, foreign_key="location.id", primary_key=True)


class NPCPlotThreadLink(SQLModel, table=True):
    npc_id: Optional[int] = Field(default=None, foreign_key="npc.id", primary_key=True)
    plot_thread_id: Optional[int] = Field(default=None, foreign_key="plotthread.id", primary_key=True)


class LocationFactionLink(SQLModel, table=True):
    location_id: Optional[int] = Field(default=None, foreign_key="location.id", primary_key=True)
    faction_id: Optional[int] = Field(default=None, foreign_key="faction.id", primary_key=True)


class FactionPlotThreadLink(SQLModel, table=True):
    faction_id: Optional[int] = Field(default=None, foreign_key="faction.id", primary_key=True)
    plot_thread_id: Optional[int] = Field(default=None, foreign_key="plotthread.id", primary_key=True)


class LocationPlotThreadLink(SQLModel, table=True):
    location_id: Optional[int] = Field(default=None, foreign_key="location.id", primary_key=True)
    plot_thread_id: Optional[int] = Field(default=None, foreign_key="plotthread.id", primary_key=True)


class LocationRelatedLocationLink(SQLModel, table=True):
    location_id: Optional[int] = Field(default=None, foreign_key="location.id", primary_key=True)
    related_location_id: Optional[int] = Field(default=None, foreign_key="location.id", primary_key=True)


class PlotThreadRelatedPlotThreadLink(SQLModel, table=True):
    plot_thread_id: Optional[int] = Field(default=None, foreign_key="plotthread.id", primary_key=True)
    related_plot_thread_id: Optional[int] = Field(default=None, foreign_key="plotthread.id", primary_key=True)


class ItemNPCLink(SQLModel, table=True):
    item_id: Optional[int] = Field(default=None, foreign_key="item.id", primary_key=True)
    npc_id: Optional[int] = Field(default=None, foreign_key="npc.id", primary_key=True)


class ItemFactionLink(SQLModel, table=True):
    item_id: Optional[int] = Field(default=None, foreign_key="item.id", primary_key=True)
    faction_id: Optional[int] = Field(default=None, foreign_key="faction.id", primary_key=True)


class ItemLocationLink(SQLModel, table=True):
    item_id: Optional[int] = Field(default=None, foreign_key="item.id", primary_key=True)
    location_id: Optional[int] = Field(default=None, foreign_key="location.id", primary_key=True)


class ItemPlotThreadLink(SQLModel, table=True):
    item_id: Optional[int] = Field(default=None, foreign_key="item.id", primary_key=True)
    plot_thread_id: Optional[int] = Field(default=None, foreign_key="plotthread.id", primary_key=True)


class SessionNPCLink(SQLModel, table=True):
    session_id: Optional[int] = Field(default=None, foreign_key="sessionmodel.id", primary_key=True)
    npc_id: Optional[int] = Field(default=None, foreign_key="npc.id", primary_key=True)


class SessionLocationLink(SQLModel, table=True):
    session_id: Optional[int] = Field(default=None, foreign_key="sessionmodel.id", primary_key=True)
    location_id: Optional[int] = Field(default=None, foreign_key="location.id", primary_key=True)


class SessionFactionLink(SQLModel, table=True):
    session_id: Optional[int] = Field(default=None, foreign_key="sessionmodel.id", primary_key=True)
    faction_id: Optional[int] = Field(default=None, foreign_key="faction.id", primary_key=True)


class SessionItemLink(SQLModel, table=True):
    session_id: Optional[int] = Field(default=None, foreign_key="sessionmodel.id", primary_key=True)
    item_id: Optional[int] = Field(default=None, foreign_key="item.id", primary_key=True)


class CreatureFactionLink(SQLModel, table=True):
    creature_id: Optional[int] = Field(default=None, foreign_key="creature.id", primary_key=True)
    faction_id: Optional[int] = Field(default=None, foreign_key="faction.id", primary_key=True)


class CreatureLocationLink(SQLModel, table=True):
    creature_id: Optional[int] = Field(default=None, foreign_key="creature.id", primary_key=True)
    location_id: Optional[int] = Field(default=None, foreign_key="location.id", primary_key=True)


class CreaturePlotThreadLink(SQLModel, table=True):
    creature_id: Optional[int] = Field(default=None, foreign_key="creature.id", primary_key=True)
    plot_thread_id: Optional[int] = Field(default=None, foreign_key="plotthread.id", primary_key=True)


class SessionCreatureLink(SQLModel, table=True):
    session_id: Optional[int] = Field(default=None, foreign_key="sessionmodel.id", primary_key=True)
    creature_id: Optional[int] = Field(default=None, foreign_key="creature.id", primary_key=True)


class SessionPlotThreadLink(SQLModel, table=True):
    session_id: Optional[int] = Field(default=None, foreign_key="sessionmodel.id", primary_key=True)
    plot_thread_id: Optional[int] = Field(default=None, foreign_key="plotthread.id", primary_key=True)


class SessionPartyMemberLink(SQLModel, table=True):
    session_id: Optional[int] = Field(default=None, foreign_key="sessionmodel.id", primary_key=True)
    pc_note_id: Optional[int] = Field(default=None, foreign_key="playercharacternote.id", primary_key=True)


class PCLocationLink(SQLModel, table=True):
    pc_note_id: Optional[int] = Field(default=None, foreign_key="playercharacternote.id", primary_key=True)
    location_id: Optional[int] = Field(default=None, foreign_key="location.id", primary_key=True)


class PCFactionLink(SQLModel, table=True):
    pc_note_id: Optional[int] = Field(default=None, foreign_key="playercharacternote.id", primary_key=True)
    faction_id: Optional[int] = Field(default=None, foreign_key="faction.id", primary_key=True)


class PCPlotThreadLink(SQLModel, table=True):
    pc_note_id: Optional[int] = Field(default=None, foreign_key="playercharacternote.id", primary_key=True)
    plot_thread_id: Optional[int] = Field(default=None, foreign_key="plotthread.id", primary_key=True)


# Narrative block link tables (Phase 3)
class SceneNPCLink(SQLModel, table=True):
    scene_id: Optional[int] = Field(default=None, foreign_key="scene.id", primary_key=True)
    npc_id: Optional[int] = Field(default=None, foreign_key="npc.id", primary_key=True)


class ScenePCLink(SQLModel, table=True):
    scene_id: Optional[int] = Field(default=None, foreign_key="scene.id", primary_key=True)
    pc_note_id: Optional[int] = Field(default=None, foreign_key="playercharacternote.id", primary_key=True)


class SceneLocationLink(SQLModel, table=True):
    scene_id: Optional[int] = Field(default=None, foreign_key="scene.id", primary_key=True)
    location_id: Optional[int] = Field(default=None, foreign_key="location.id", primary_key=True)


class SceneFactionLink(SQLModel, table=True):
    scene_id: Optional[int] = Field(default=None, foreign_key="scene.id", primary_key=True)
    faction_id: Optional[int] = Field(default=None, foreign_key="faction.id", primary_key=True)


class SceneItemLink(SQLModel, table=True):
    scene_id: Optional[int] = Field(default=None, foreign_key="scene.id", primary_key=True)
    item_id: Optional[int] = Field(default=None, foreign_key="item.id", primary_key=True)


class ScenePlotThreadLink(SQLModel, table=True):
    scene_id: Optional[int] = Field(default=None, foreign_key="scene.id", primary_key=True)
    plot_thread_id: Optional[int] = Field(default=None, foreign_key="plotthread.id", primary_key=True)


class EncounterNPCLink(SQLModel, table=True):
    encounter_id: Optional[int] = Field(default=None, foreign_key="encounter.id", primary_key=True)
    npc_id: Optional[int] = Field(default=None, foreign_key="npc.id", primary_key=True)


class EncounterPCLink(SQLModel, table=True):
    encounter_id: Optional[int] = Field(default=None, foreign_key="encounter.id", primary_key=True)
    pc_note_id: Optional[int] = Field(default=None, foreign_key="playercharacternote.id", primary_key=True)


class EncounterLocationLink(SQLModel, table=True):
    encounter_id: Optional[int] = Field(default=None, foreign_key="encounter.id", primary_key=True)
    location_id: Optional[int] = Field(default=None, foreign_key="location.id", primary_key=True)


class EncounterFactionLink(SQLModel, table=True):
    encounter_id: Optional[int] = Field(default=None, foreign_key="encounter.id", primary_key=True)
    faction_id: Optional[int] = Field(default=None, foreign_key="faction.id", primary_key=True)


class EncounterItemLink(SQLModel, table=True):
    encounter_id: Optional[int] = Field(default=None, foreign_key="encounter.id", primary_key=True)
    item_id: Optional[int] = Field(default=None, foreign_key="item.id", primary_key=True)


class EncounterPlotThreadLink(SQLModel, table=True):
    encounter_id: Optional[int] = Field(default=None, foreign_key="encounter.id", primary_key=True)
    plot_thread_id: Optional[int] = Field(default=None, foreign_key="plotthread.id", primary_key=True)


class ObjectiveNPCLink(SQLModel, table=True):
    objective_id: Optional[int] = Field(default=None, foreign_key="objective.id", primary_key=True)
    npc_id: Optional[int] = Field(default=None, foreign_key="npc.id", primary_key=True)


class ObjectivePCLink(SQLModel, table=True):
    objective_id: Optional[int] = Field(default=None, foreign_key="objective.id", primary_key=True)
    pc_note_id: Optional[int] = Field(default=None, foreign_key="playercharacternote.id", primary_key=True)


class ObjectiveLocationLink(SQLModel, table=True):
    objective_id: Optional[int] = Field(default=None, foreign_key="objective.id", primary_key=True)
    location_id: Optional[int] = Field(default=None, foreign_key="location.id", primary_key=True)


class ObjectiveFactionLink(SQLModel, table=True):
    objective_id: Optional[int] = Field(default=None, foreign_key="objective.id", primary_key=True)
    faction_id: Optional[int] = Field(default=None, foreign_key="faction.id", primary_key=True)


class ObjectiveItemLink(SQLModel, table=True):
    objective_id: Optional[int] = Field(default=None, foreign_key="objective.id", primary_key=True)
    item_id: Optional[int] = Field(default=None, foreign_key="item.id", primary_key=True)


class ObjectivePlotThreadLink(SQLModel, table=True):
    objective_id: Optional[int] = Field(default=None, foreign_key="objective.id", primary_key=True)
    plot_thread_id: Optional[int] = Field(default=None, foreign_key="plotthread.id", primary_key=True)


class EntityRelationshipEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="campaign.id", index=True)
    source_kind: str
    source_id: int
    target_kind: str
    target_id: int
    action: str
    session_id: Optional[int] = Field(default=None, foreign_key="sessionmodel.id")
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime, default=utc_now, nullable=False),
    )


class Campaign(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    system: Optional[str] = None
    description: Optional[str] = None
    briefing_narrative: Optional[str] = None
    briefing_narrative_generated_at: Optional[datetime] = None
    briefing_narrative_provider: Optional[str] = None
    briefing_narrative_model: Optional[str] = None
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime, default=utc_now, nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False),
    )

    sessions: List["SessionModel"] = Relationship(back_populates="campaign")
    npcs: List["NPC"] = Relationship(back_populates="campaign")
    locations: List["Location"] = Relationship(back_populates="campaign")
    factions: List["Faction"] = Relationship(back_populates="campaign")
    items: List["Item"] = Relationship(back_populates="campaign")
    creatures: List["Creature"] = Relationship(back_populates="campaign")
    plot_threads: List["PlotThread"] = Relationship(back_populates="campaign")
    player_notes: List["PlayerCharacterNote"] = Relationship(back_populates="campaign")


class SessionModel(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="campaign.id")
    title: str
    date: Optional[str] = None
    notes: Optional[str] = None
    recap: Optional[str] = None
    player_recap: Optional[str] = None
    analysis: Optional[str] = None
    analysis_raw: Optional[str] = None
    next_session_prep: Optional[str] = None
    next_session_prep_manually_edited: bool = False
    workspace_notes: Optional[str] = None
    active_scene_id: Optional[int] = Field(default=None, foreign_key="scene.id")
    ai_last_run_metadata: Optional[str] = None
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime, default=utc_now, nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False),
    )

    campaign: Optional[Campaign] = Relationship(back_populates="sessions")
    npcs: List["NPC"] = Relationship(back_populates="sessions", link_model=SessionNPCLink)
    locations: List["Location"] = Relationship(back_populates="sessions", link_model=SessionLocationLink)
    factions: List["Faction"] = Relationship(back_populates="sessions", link_model=SessionFactionLink)
    items: List["Item"] = Relationship(back_populates="sessions", link_model=SessionItemLink)
    creatures: List["Creature"] = Relationship(back_populates="sessions", link_model=SessionCreatureLink)
    plot_threads: List["PlotThread"] = Relationship(back_populates="sessions", link_model=SessionPlotThreadLink)
    party_members: List["PlayerCharacterNote"] = Relationship(
        back_populates="sessions", link_model=SessionPartyMemberLink
    )


class NPC(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="campaign.id")
    name: str
    role: Optional[str] = None
    description: Optional[str] = None
    current_status: Optional[str] = None
    last_seen_session_id: Optional[int] = Field(default=None, foreign_key="sessionmodel.id")
    current_location: Optional[str] = None
    relationship_to_party: Optional[str] = None
    goals: Optional[str] = None
    secrets: Optional[str] = None
    alive_or_dead: Optional[str] = None
    world_status: Optional[str] = Field(default="unknown")
    state_notes: Optional[str] = None
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime, default=utc_now, nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False),
    )

    campaign: Optional[Campaign] = Relationship(back_populates="npcs")
    factions: List["Faction"] = Relationship(back_populates="npcs", link_model=NPCFactionLink)
    locations: List["Location"] = Relationship(back_populates="npcs", link_model=NPCLocationLink)
    plot_threads: List["PlotThread"] = Relationship(back_populates="npcs", link_model=NPCPlotThreadLink)
    items: List["Item"] = Relationship(back_populates="npcs", link_model=ItemNPCLink)
    sessions: List["SessionModel"] = Relationship(back_populates="npcs", link_model=SessionNPCLink)


class Location(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="campaign.id")
    name: str
    description: Optional[str] = None
    notes: Optional[str] = None
    location_type: Optional[str] = Field(default="major")
    world_status: Optional[str] = Field(default="unknown")
    state_notes: Optional[str] = None
    last_seen_session_id: Optional[int] = Field(default=None, foreign_key="sessionmodel.id")
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime, default=utc_now, nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False),
    )

    campaign: Optional[Campaign] = Relationship(back_populates="locations")
    npcs: List["NPC"] = Relationship(back_populates="locations", link_model=NPCLocationLink)
    factions: List["Faction"] = Relationship(back_populates="locations", link_model=LocationFactionLink)
    plot_threads: List["PlotThread"] = Relationship(back_populates="locations", link_model=LocationPlotThreadLink)
    items: List["Item"] = Relationship(back_populates="locations", link_model=ItemLocationLink)
    creatures: List["Creature"] = Relationship(back_populates="locations", link_model=CreatureLocationLink)
    sessions: List["SessionModel"] = Relationship(back_populates="locations", link_model=SessionLocationLink)
    pcs: List["PlayerCharacterNote"] = Relationship(back_populates="locations", link_model=PCLocationLink)


class Faction(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="campaign.id")
    name: str
    faction_type: Optional[str] = None
    summary: Optional[str] = None
    plot_notes: Optional[str] = None
    hq_location_id: Optional[int] = Field(default=None, foreign_key="location.id")
    world_status: Optional[str] = Field(default="unknown")
    state_notes: Optional[str] = None
    last_seen_session_id: Optional[int] = Field(default=None, foreign_key="sessionmodel.id")
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime, default=utc_now, nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False),
    )

    campaign: Optional[Campaign] = Relationship(back_populates="factions")
    npcs: List["NPC"] = Relationship(back_populates="factions", link_model=NPCFactionLink)
    pcs: List["PlayerCharacterNote"] = Relationship(back_populates="factions", link_model=PCFactionLink)
    locations: List["Location"] = Relationship(back_populates="factions", link_model=LocationFactionLink)
    plot_threads: List["PlotThread"] = Relationship(back_populates="factions", link_model=FactionPlotThreadLink)
    items: List["Item"] = Relationship(back_populates="factions", link_model=ItemFactionLink)
    creatures: List["Creature"] = Relationship(back_populates="factions", link_model=CreatureFactionLink)
    sessions: List["SessionModel"] = Relationship(back_populates="factions", link_model=SessionFactionLink)


class Item(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="campaign.id")
    name: str
    item_type: Optional[str] = None
    description: Optional[str] = None
    origin: Optional[str] = None
    plot_notes: Optional[str] = None
    owner_npc_id: Optional[int] = Field(default=None, foreign_key="npc.id")
    owner_pc_id: Optional[int] = Field(default=None, foreign_key="playercharacternote.id")
    world_status: Optional[str] = Field(default="unknown")
    state_notes: Optional[str] = None
    last_seen_session_id: Optional[int] = Field(default=None, foreign_key="sessionmodel.id")
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime, default=utc_now, nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False),
    )

    campaign: Optional[Campaign] = Relationship(back_populates="items")
    npcs: List["NPC"] = Relationship(back_populates="items", link_model=ItemNPCLink)
    factions: List["Faction"] = Relationship(back_populates="items", link_model=ItemFactionLink)
    locations: List["Location"] = Relationship(back_populates="items", link_model=ItemLocationLink)
    plot_threads: List["PlotThread"] = Relationship(back_populates="items", link_model=ItemPlotThreadLink)
    sessions: List["SessionModel"] = Relationship(back_populates="items", link_model=SessionItemLink)


class Creature(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="campaign.id")
    name: str
    creature_type: Optional[str] = None
    classification: Optional[str] = None
    habitat: Optional[str] = None
    threat_level: Optional[str] = None
    physical_description: Optional[str] = None
    special_traits: Optional[str] = None
    campaign_context_tactics: Optional[str] = None
    description: Optional[str] = None
    notes: Optional[str] = None
    world_status: Optional[str] = Field(default="unknown")
    state_notes: Optional[str] = None
    last_seen_session_id: Optional[int] = Field(default=None, foreign_key="sessionmodel.id")
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime, default=utc_now, nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False),
    )

    campaign: Optional[Campaign] = Relationship(back_populates="creatures")
    factions: List["Faction"] = Relationship(back_populates="creatures", link_model=CreatureFactionLink)
    locations: List["Location"] = Relationship(back_populates="creatures", link_model=CreatureLocationLink)
    plot_threads: List["PlotThread"] = Relationship(back_populates="creatures", link_model=CreaturePlotThreadLink)
    sessions: List["SessionModel"] = Relationship(back_populates="creatures", link_model=SessionCreatureLink)


class PlotThread(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="campaign.id")
    title: str
    status: Optional[str] = None
    thread_type: Optional[str] = None
    details: Optional[str] = None
    plot_significance_notes: Optional[str] = None
    importance: Optional[str] = None
    related_npcs: Optional[str] = None
    related_locations: Optional[str] = None
    last_touched_session_id: Optional[int] = Field(default=None, foreign_key="sessionmodel.id")
    resolution_notes: Optional[str] = None
    state_notes: Optional[str] = None
    open_clues: Optional[str] = None
    revealed_clues: Optional[str] = None
    secret_notes: Optional[str] = None
    mystery_status: Optional[str] = Field(default="unknown")
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime, default=utc_now, nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False),
    )

    campaign: Optional[Campaign] = Relationship(back_populates="plot_threads")
    npcs: List["NPC"] = Relationship(back_populates="plot_threads", link_model=NPCPlotThreadLink)
    factions: List["Faction"] = Relationship(back_populates="plot_threads", link_model=FactionPlotThreadLink)
    locations: List["Location"] = Relationship(back_populates="plot_threads", link_model=LocationPlotThreadLink)
    items: List["Item"] = Relationship(back_populates="plot_threads", link_model=ItemPlotThreadLink)
    creatures: List["Creature"] = Relationship(back_populates="plot_threads", link_model=CreaturePlotThreadLink)
    pcs: List["PlayerCharacterNote"] = Relationship(back_populates="plot_threads", link_model=PCPlotThreadLink)
    sessions: List["SessionModel"] = Relationship(back_populates="plot_threads", link_model=SessionPlotThreadLink)


class PlayerCharacterNote(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="campaign.id")
    character_name: str
    character_archetype: Optional[str] = None
    description: Optional[str] = None
    signature_gear: Optional[str] = None
    key_ties_history: Optional[str] = None
    campaign_role_plot_notes: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime, default=utc_now, nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False),
    )

    campaign: Optional[Campaign] = Relationship(back_populates="player_notes")
    sessions: List["SessionModel"] = Relationship(
        back_populates="party_members", link_model=SessionPartyMemberLink
    )
    locations: List["Location"] = Relationship(back_populates="pcs", link_model=PCLocationLink)
    factions: List["Faction"] = Relationship(back_populates="pcs", link_model=PCFactionLink)
    plot_threads: List["PlotThread"] = Relationship(back_populates="pcs", link_model=PCPlotThreadLink)


class Scene(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="campaign.id", index=True)
    session_id: Optional[int] = Field(default=None, foreign_key="sessionmodel.id", index=True)
    title: str
    summary: Optional[str] = None
    narrative_goal: Optional[str] = None
    status: str = Field(default="planned")
    location_id: Optional[int] = Field(default=None, foreign_key="location.id")
    notes: Optional[str] = None
    gm_only_notes: Optional[str] = None
    sort_order: int = Field(default=0)
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime, default=utc_now, nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False),
    )

    npcs: List["NPC"] = Relationship(link_model=SceneNPCLink)
    pcs: List["PlayerCharacterNote"] = Relationship(link_model=ScenePCLink)
    locations: List["Location"] = Relationship(link_model=SceneLocationLink)
    factions: List["Faction"] = Relationship(link_model=SceneFactionLink)
    items: List["Item"] = Relationship(link_model=SceneItemLink)
    plot_threads: List["PlotThread"] = Relationship(link_model=ScenePlotThreadLink)


class Encounter(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="campaign.id", index=True)
    session_id: Optional[int] = Field(default=None, foreign_key="sessionmodel.id", index=True)
    scene_id: Optional[int] = Field(default=None, foreign_key="scene.id", index=True)
    title: str
    encounter_type: str = Field(default="other")
    objective: Optional[str] = None
    stakes: Optional[str] = None
    setup: Optional[str] = None
    outcome: Optional[str] = None
    status: str = Field(default="planned")
    notes: Optional[str] = None
    gm_only_notes: Optional[str] = None
    sort_order: int = Field(default=0)
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime, default=utc_now, nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False),
    )

    npcs: List["NPC"] = Relationship(link_model=EncounterNPCLink)
    pcs: List["PlayerCharacterNote"] = Relationship(link_model=EncounterPCLink)
    locations: List["Location"] = Relationship(link_model=EncounterLocationLink)
    factions: List["Faction"] = Relationship(link_model=EncounterFactionLink)
    items: List["Item"] = Relationship(link_model=EncounterItemLink)
    plot_threads: List["PlotThread"] = Relationship(link_model=EncounterPlotThreadLink)


class Objective(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="campaign.id", index=True)
    session_id: Optional[int] = Field(default=None, foreign_key="sessionmodel.id", index=True)
    scene_id: Optional[int] = Field(default=None, foreign_key="scene.id", index=True)
    encounter_id: Optional[int] = Field(default=None, foreign_key="encounter.id", index=True)
    title: str
    description: Optional[str] = None
    objective_type: str = Field(default="other")
    status: str = Field(default="open")
    priority: str = Field(default="normal")
    notes: Optional[str] = None
    gm_only_notes: Optional[str] = None
    sort_order: int = Field(default=0)
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime, default=utc_now, nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False),
    )

    npcs: List["NPC"] = Relationship(link_model=ObjectiveNPCLink)
    pcs: List["PlayerCharacterNote"] = Relationship(link_model=ObjectivePCLink)
    locations: List["Location"] = Relationship(link_model=ObjectiveLocationLink)
    factions: List["Faction"] = Relationship(link_model=ObjectiveFactionLink)
    items: List["Item"] = Relationship(link_model=ObjectiveItemLink)
    plot_threads: List["PlotThread"] = Relationship(link_model=ObjectivePlotThreadLink)


class LoreChunk(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="campaign.id", index=True)
    source_type: str
    source_id: int
    chunk_index: int = 0
    title: str
    content: str
    content_hash: str
    embedding: str
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime, default=utc_now, nullable=False),
    )


class CampaignLoreIndex(SQLModel, table=True):
    campaign_id: int = Field(primary_key=True, foreign_key="campaign.id")
    content_fingerprint: str
    chunk_count: int = 0
    embedding_provider: str
    indexed_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime, default=utc_now, nullable=False),
    )
