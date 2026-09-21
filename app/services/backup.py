import json
import os
import sqlite3
import tempfile
from app.utils.time import utc_now
from pathlib import Path
from typing import Any, Dict, List, Type

from sqlmodel import Session, SQLModel, select

from app.models import (
    Campaign,
    CampaignLoreIndex,
    Creature,
    CreatureFactionLink,
    CreatureLocationLink,
    CreaturePlotThreadLink,
    Faction,
    FactionPlotThreadLink,
    Item,
    ItemFactionLink,
    ItemLocationLink,
    ItemNPCLink,
    ItemPlotThreadLink,
    Location,
    LocationFactionLink,
    LocationPlotThreadLink,
    LocationRelatedLocationLink,
    LoreChunk,
    NPC,
    NPCFactionLink,
    NPCLocationLink,
    NPCPlotThreadLink,
    PCLocationLink,
    PCFactionLink,
    PCPlotThreadLink,
    PlayerCharacterNote,
    PlotThread,
    PlotThreadRelatedPlotThreadLink,
    SessionCreatureLink,
    SessionFactionLink,
    SessionItemLink,
    SessionLocationLink,
    SessionModel,
    SessionNPCLink,
    SessionPartyMemberLink,
    SessionPlotThreadLink,
)
from app.services.export import safe_filename

BACKUP_VERSION = 1

CAMPAIGN_SCOPED_TABLES = (
    "sessionmodel",
    "npc",
    "location",
    "faction",
    "item",
    "creature",
    "plotthread",
    "playercharacternote",
    "lorechunk",
)

LINK_TABLE_FILTERS = {
    "sessionnpclink": (
        "session_id IN (SELECT id FROM sessionmodel WHERE campaign_id = ?) "
        "AND npc_id IN (SELECT id FROM npc WHERE campaign_id = ?)"
    ),
    "sessionlocationlink": (
        "session_id IN (SELECT id FROM sessionmodel WHERE campaign_id = ?) "
        "AND location_id IN (SELECT id FROM location WHERE campaign_id = ?)"
    ),
    "sessionfactionlink": (
        "session_id IN (SELECT id FROM sessionmodel WHERE campaign_id = ?) "
        "AND faction_id IN (SELECT id FROM faction WHERE campaign_id = ?)"
    ),
    "sessionitemlink": (
        "session_id IN (SELECT id FROM sessionmodel WHERE campaign_id = ?) "
        "AND item_id IN (SELECT id FROM item WHERE campaign_id = ?)"
    ),
    "sessioncreaturelink": (
        "session_id IN (SELECT id FROM sessionmodel WHERE campaign_id = ?) "
        "AND creature_id IN (SELECT id FROM creature WHERE campaign_id = ?)"
    ),
    "sessionplotthreadlink": (
        "session_id IN (SELECT id FROM sessionmodel WHERE campaign_id = ?) "
        "AND plot_thread_id IN (SELECT id FROM plotthread WHERE campaign_id = ?)"
    ),
    "sessionpartymemberlink": (
        "session_id IN (SELECT id FROM sessionmodel WHERE campaign_id = ?) "
        "AND pc_note_id IN (SELECT id FROM playercharacternote WHERE campaign_id = ?)"
    ),
    "npcfactionlink": (
        "npc_id IN (SELECT id FROM npc WHERE campaign_id = ?) "
        "AND faction_id IN (SELECT id FROM faction WHERE campaign_id = ?)"
    ),
    "npclocationlink": (
        "npc_id IN (SELECT id FROM npc WHERE campaign_id = ?) "
        "AND location_id IN (SELECT id FROM location WHERE campaign_id = ?)"
    ),
    "pclocationlink": (
        "pc_note_id IN (SELECT id FROM playercharacternote WHERE campaign_id = ?) "
        "AND location_id IN (SELECT id FROM location WHERE campaign_id = ?)"
    ),
    "pcfactionlink": (
        "pc_note_id IN (SELECT id FROM playercharacternote WHERE campaign_id = ?) "
        "AND faction_id IN (SELECT id FROM faction WHERE campaign_id = ?)"
    ),
    "pcplotthreadlink": (
        "pc_note_id IN (SELECT id FROM playercharacternote WHERE campaign_id = ?) "
        "AND plot_thread_id IN (SELECT id FROM plotthread WHERE campaign_id = ?)"
    ),
    "npcplotthreadlink": (
        "npc_id IN (SELECT id FROM npc WHERE campaign_id = ?) "
        "AND plot_thread_id IN (SELECT id FROM plotthread WHERE campaign_id = ?)"
    ),
    "locationfactionlink": (
        "location_id IN (SELECT id FROM location WHERE campaign_id = ?) "
        "AND faction_id IN (SELECT id FROM faction WHERE campaign_id = ?)"
    ),
    "factionplotthreadlink": (
        "faction_id IN (SELECT id FROM faction WHERE campaign_id = ?) "
        "AND plot_thread_id IN (SELECT id FROM plotthread WHERE campaign_id = ?)"
    ),
    "locationplotthreadlink": (
        "location_id IN (SELECT id FROM location WHERE campaign_id = ?) "
        "AND plot_thread_id IN (SELECT id FROM plotthread WHERE campaign_id = ?)"
    ),
    "locationrelatedlocationlink": (
        "location_id IN (SELECT id FROM location WHERE campaign_id = ?) "
        "AND related_location_id IN (SELECT id FROM location WHERE campaign_id = ?)"
    ),
    "plotthreadrelatedplotthreadlink": (
        "plot_thread_id IN (SELECT id FROM plotthread WHERE campaign_id = ?) "
        "AND related_plot_thread_id IN (SELECT id FROM plotthread WHERE campaign_id = ?)"
    ),
    "itemnpclink": (
        "item_id IN (SELECT id FROM item WHERE campaign_id = ?) "
        "AND npc_id IN (SELECT id FROM npc WHERE campaign_id = ?)"
    ),
    "itemfactionlink": (
        "item_id IN (SELECT id FROM item WHERE campaign_id = ?) "
        "AND faction_id IN (SELECT id FROM faction WHERE campaign_id = ?)"
    ),
    "itemlocationlink": (
        "item_id IN (SELECT id FROM item WHERE campaign_id = ?) "
        "AND location_id IN (SELECT id FROM location WHERE campaign_id = ?)"
    ),
    "itemplotthreadlink": (
        "item_id IN (SELECT id FROM item WHERE campaign_id = ?) "
        "AND plot_thread_id IN (SELECT id FROM plotthread WHERE campaign_id = ?)"
    ),
    "creaturefactionlink": (
        "creature_id IN (SELECT id FROM creature WHERE campaign_id = ?) "
        "AND faction_id IN (SELECT id FROM faction WHERE campaign_id = ?)"
    ),
    "creaturelocationlink": (
        "creature_id IN (SELECT id FROM creature WHERE campaign_id = ?) "
        "AND location_id IN (SELECT id FROM location WHERE campaign_id = ?)"
    ),
    "creatureplotthreadlink": (
        "creature_id IN (SELECT id FROM creature WHERE campaign_id = ?) "
        "AND plot_thread_id IN (SELECT id FROM plotthread WHERE campaign_id = ?)"
    ),
}

def _dump_model(obj: SQLModel) -> Dict[str, Any]:
    return obj.model_dump(mode="json")


def _ids_or_sentinel(values: List[int]) -> List[int]:
    return values or [-1]


def _load_campaign_links(
    db: Session,
    link_model: Type[SQLModel],
    left_field: str,
    right_field: str,
    left_ids: List[int],
    right_ids: List[int],
) -> List[Dict[str, Any]]:
    rows = db.exec(
        select(link_model).where(
            getattr(link_model, left_field).in_(_ids_or_sentinel(left_ids)),
            getattr(link_model, right_field).in_(_ids_or_sentinel(right_ids)),
        )
    ).all()
    return [_dump_model(row) for row in rows]


def export_campaign_json(db: Session, campaign_id: int) -> Dict[str, Any]:
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise ValueError("Campaign not found.")

    sessions = db.exec(select(SessionModel).where(SessionModel.campaign_id == campaign_id)).all()
    npcs = db.exec(select(NPC).where(NPC.campaign_id == campaign_id)).all()
    locations = db.exec(select(Location).where(Location.campaign_id == campaign_id)).all()
    factions = db.exec(select(Faction).where(Faction.campaign_id == campaign_id)).all()
    items = db.exec(select(Item).where(Item.campaign_id == campaign_id)).all()
    creatures = db.exec(select(Creature).where(Creature.campaign_id == campaign_id)).all()
    threads = db.exec(select(PlotThread).where(PlotThread.campaign_id == campaign_id)).all()
    pc_notes = db.exec(select(PlayerCharacterNote).where(PlayerCharacterNote.campaign_id == campaign_id)).all()
    lore_chunks = db.exec(select(LoreChunk).where(LoreChunk.campaign_id == campaign_id)).all()
    lore_index = db.get(CampaignLoreIndex, campaign_id)

    session_ids = [row.id for row in sessions if row.id is not None]
    npc_ids = [row.id for row in npcs if row.id is not None]
    location_ids = [row.id for row in locations if row.id is not None]
    faction_ids = [row.id for row in factions if row.id is not None]
    item_ids = [row.id for row in items if row.id is not None]
    creature_ids = [row.id for row in creatures if row.id is not None]
    thread_ids = [row.id for row in threads if row.id is not None]

    pc_ids = [row.id for row in pc_notes if row.id is not None]

    links = {
        "session_npc": _load_campaign_links(db, SessionNPCLink, "session_id", "npc_id", session_ids, npc_ids),
        "session_location": _load_campaign_links(db, SessionLocationLink, "session_id", "location_id", session_ids, location_ids),
        "session_faction": _load_campaign_links(db, SessionFactionLink, "session_id", "faction_id", session_ids, faction_ids),
        "session_item": _load_campaign_links(db, SessionItemLink, "session_id", "item_id", session_ids, item_ids),
        "session_creature": _load_campaign_links(
            db, SessionCreatureLink, "session_id", "creature_id", session_ids, creature_ids
        ),
        "session_plot_thread": _load_campaign_links(db, SessionPlotThreadLink, "session_id", "plot_thread_id", session_ids, thread_ids),
        "npc_faction": _load_campaign_links(db, NPCFactionLink, "npc_id", "faction_id", npc_ids, faction_ids),
        "npc_location": _load_campaign_links(db, NPCLocationLink, "npc_id", "location_id", npc_ids, location_ids),
        "npc_plot_thread": _load_campaign_links(db, NPCPlotThreadLink, "npc_id", "plot_thread_id", npc_ids, thread_ids),
        "location_faction": _load_campaign_links(db, LocationFactionLink, "location_id", "faction_id", location_ids, faction_ids),
        "faction_thread": _load_campaign_links(
            db, FactionPlotThreadLink, "faction_id", "plot_thread_id", faction_ids, thread_ids
        ),
        "location_plot_thread": _load_campaign_links(db, LocationPlotThreadLink, "location_id", "plot_thread_id", location_ids, thread_ids),
        "location_related": _load_campaign_links(
            db, LocationRelatedLocationLink, "location_id", "related_location_id", location_ids, location_ids
        ),
        "thread_related": _load_campaign_links(
            db,
            PlotThreadRelatedPlotThreadLink,
            "plot_thread_id",
            "related_plot_thread_id",
            thread_ids,
            thread_ids,
        ),
        "item_npc": _load_campaign_links(db, ItemNPCLink, "item_id", "npc_id", item_ids, npc_ids),
        "item_faction": _load_campaign_links(db, ItemFactionLink, "item_id", "faction_id", item_ids, faction_ids),
        "item_location": _load_campaign_links(db, ItemLocationLink, "item_id", "location_id", item_ids, location_ids),
        "item_plot_thread": _load_campaign_links(db, ItemPlotThreadLink, "item_id", "plot_thread_id", item_ids, thread_ids),
        "creature_faction": _load_campaign_links(
            db, CreatureFactionLink, "creature_id", "faction_id", creature_ids, faction_ids
        ),
        "creature_location": _load_campaign_links(
            db, CreatureLocationLink, "creature_id", "location_id", creature_ids, location_ids
        ),
        "creature_plot_thread": _load_campaign_links(
            db, CreaturePlotThreadLink, "creature_id", "plot_thread_id", creature_ids, thread_ids
        ),
        "session_party": _load_campaign_links(
            db, SessionPartyMemberLink, "session_id", "pc_note_id", session_ids, pc_ids
        ),
        "pc_location": _load_campaign_links(db, PCLocationLink, "pc_note_id", "location_id", pc_ids, location_ids),
        "pc_faction": _load_campaign_links(db, PCFactionLink, "pc_note_id", "faction_id", pc_ids, faction_ids),
        "pc_plot_thread": _load_campaign_links(db, PCPlotThreadLink, "pc_note_id", "plot_thread_id", pc_ids, thread_ids),
    }

    return {
        "version": BACKUP_VERSION,
        "exported_at": utc_now().isoformat().replace("+00:00", "Z"),
        "campaign": _dump_model(campaign),
        "sessions": [_dump_model(row) for row in sessions],
        "npcs": [_dump_model(row) for row in npcs],
        "locations": [_dump_model(row) for row in locations],
        "factions": [_dump_model(row) for row in factions],
        "items": [_dump_model(row) for row in items],
        "creatures": [_dump_model(row) for row in creatures],
        "plot_threads": [_dump_model(row) for row in threads],
        "player_notes": [_dump_model(row) for row in pc_notes],
        "lore_chunks": [_dump_model(row) for row in lore_chunks],
        "lore_index": _dump_model(lore_index) if lore_index else None,
        "links": links,
    }


def export_campaign_json_bytes(db: Session, campaign_id: int) -> bytes:
    payload = export_campaign_json(db, campaign_id)
    return json.dumps(payload, indent=2).encode("utf-8")


def _copy_schema(source: sqlite3.Connection, dest: sqlite3.Connection) -> None:
    for (sql,) in source.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall():
        if sql:
            dest.execute(sql)


def _copy_rows(
    source: sqlite3.Connection,
    dest: sqlite3.Connection,
    table: str,
    where_clause: str,
    params: tuple,
) -> None:
    columns = [row[1] for row in source.execute(f"PRAGMA table_info({table})").fetchall()]
    if not columns:
        return
    column_list = ", ".join(columns)
    placeholders = ", ".join(["?"] * len(columns))
    rows = source.execute(f"SELECT {column_list} FROM {table} WHERE {where_clause}", params).fetchall()
    if not rows:
        return
    dest.executemany(f"INSERT INTO {table} ({column_list}) VALUES ({placeholders})", rows)


def export_campaign_sqlite_bytes(db_file: Path, campaign_id: int) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        dest_path = tmp.name

    source = sqlite3.connect(db_file)
    try:
        campaign_exists = source.execute("SELECT 1 FROM campaign WHERE id = ?", (campaign_id,)).fetchone()
        if not campaign_exists:
            raise ValueError("Campaign not found.")

        dest = sqlite3.connect(dest_path)
        try:
            _copy_schema(source, dest)
            _copy_rows(source, dest, "campaign", "id = ?", (campaign_id,))
            for table in CAMPAIGN_SCOPED_TABLES:
                _copy_rows(source, dest, table, "campaign_id = ?", (campaign_id,))
            _copy_rows(source, dest, "campaignloreindex", "campaign_id = ?", (campaign_id,))
            for table, where_clause in LINK_TABLE_FILTERS.items():
                _copy_rows(source, dest, table, where_clause, (campaign_id, campaign_id))
            dest.commit()
        finally:
            dest.close()
        return Path(dest_path).read_bytes()
    finally:
        source.close()
        os.unlink(dest_path)


def campaign_backup_filename(campaign: Campaign, extension: str) -> str:
    slug = safe_filename(campaign.name) or f"campaign_{campaign.id}"
    return f"{slug}_backup.{extension}"
