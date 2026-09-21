from pathlib import Path
from typing import List

from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select

DB_FILE = Path(__file__).resolve().parent.parent / "campaign_console.db"
SQLITE_URL = f"sqlite:///{DB_FILE}"

engine = create_engine(SQLITE_URL, echo=False, connect_args={"check_same_thread": False})

COLUMN_DEFINITIONS = {
    "campaign": [
        "created_at TEXT NOT NULL DEFAULT (datetime('now'))",
        "updated_at TEXT NOT NULL DEFAULT (datetime('now'))",
        "briefing_narrative TEXT",
        "briefing_narrative_generated_at TEXT",
        "briefing_narrative_provider TEXT",
        "briefing_narrative_model TEXT",
    ],
    "sessionmodel": [
        "player_recap TEXT",
        "analysis TEXT",
        "analysis_raw TEXT",
        "next_session_prep_manually_edited INTEGER NOT NULL DEFAULT 0",
        "workspace_notes TEXT",
        "active_scene_id INTEGER",
        "ai_last_run_metadata TEXT",
        "created_at TEXT NOT NULL DEFAULT (datetime('now'))",
        "updated_at TEXT NOT NULL DEFAULT (datetime('now'))",
    ],
    "npc": [
        "current_status TEXT",
        "last_seen_session_id INTEGER",
        "current_location TEXT",
        "relationship_to_party TEXT",
        "goals TEXT",
        "secrets TEXT",
        "alive_or_dead TEXT",
        "world_status TEXT DEFAULT 'unknown'",
        "state_notes TEXT",
        "created_at TEXT NOT NULL DEFAULT (datetime('now'))",
        "updated_at TEXT NOT NULL DEFAULT (datetime('now'))",
    ],
    "location": [
        "location_type TEXT DEFAULT 'major'",
        "notes TEXT",
        "world_status TEXT DEFAULT 'unknown'",
        "state_notes TEXT",
        "last_seen_session_id INTEGER",
        "created_at TEXT NOT NULL DEFAULT (datetime('now'))",
        "updated_at TEXT NOT NULL DEFAULT (datetime('now'))",
    ],
    "faction": [
        "faction_type TEXT",
        "plot_notes TEXT",
        "hq_location_id INTEGER",
        "world_status TEXT DEFAULT 'unknown'",
        "state_notes TEXT",
        "last_seen_session_id INTEGER",
        "created_at TEXT NOT NULL DEFAULT (datetime('now'))",
        "updated_at TEXT NOT NULL DEFAULT (datetime('now'))",
    ],
    "item": [
        "item_type TEXT",
        "origin TEXT",
        "plot_notes TEXT",
        "owner_npc_id INTEGER",
        "owner_pc_id INTEGER",
        "world_status TEXT DEFAULT 'unknown'",
        "state_notes TEXT",
        "last_seen_session_id INTEGER",
        "created_at TEXT NOT NULL DEFAULT (datetime('now'))",
        "updated_at TEXT NOT NULL DEFAULT (datetime('now'))",
    ],
    "creature": [
        "creature_type TEXT",
        "classification TEXT",
        "habitat TEXT",
        "threat_level TEXT",
        "physical_description TEXT",
        "special_traits TEXT",
        "campaign_context_tactics TEXT",
        "notes TEXT",
        "world_status TEXT DEFAULT 'unknown'",
        "state_notes TEXT",
        "last_seen_session_id INTEGER",
        "created_at TEXT NOT NULL DEFAULT (datetime('now'))",
        "updated_at TEXT NOT NULL DEFAULT (datetime('now'))",
    ],
    "plotthread": [
        "thread_type TEXT",
        "plot_significance_notes TEXT",
        "importance TEXT",
        "related_npcs TEXT",
        "related_locations TEXT",
        "last_touched_session_id INTEGER",
        "resolution_notes TEXT",
        "state_notes TEXT",
        "open_clues TEXT",
        "revealed_clues TEXT",
        "secret_notes TEXT",
        "mystery_status TEXT DEFAULT 'unknown'",
        "created_at TEXT NOT NULL DEFAULT (datetime('now'))",
        "updated_at TEXT NOT NULL DEFAULT (datetime('now'))",
    ],
    "playercharacternote": [
        "character_archetype TEXT",
        "description TEXT",
        "signature_gear TEXT",
        "key_ties_history TEXT",
        "campaign_role_plot_notes TEXT",
        "created_at TEXT NOT NULL DEFAULT (datetime('now'))",
        "updated_at TEXT NOT NULL DEFAULT (datetime('now'))",
    ],
}


def get_table_columns(table_name: str) -> List[str]:
    with engine.connect() as conn:
        result = conn.execute(text(f"PRAGMA table_info('{table_name}')"))
        return [row[1] for row in result.fetchall()]


def ensure_missing_columns() -> None:
    with engine.connect() as conn:
        for table_name, definitions in COLUMN_DEFINITIONS.items():
            existing_columns = set(get_table_columns(table_name))
            for definition in definitions:
                column_name = definition.split()[0]
                if column_name not in existing_columns:
                    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {definition}"))


def backfill_world_status_defaults() -> None:
    """Map legacy status fields into world_status where possible; do not overwrite set values."""
    from app.models import NPC, PlotThread
    from app.services.world_state import (
        WORLD_STATUS_UNKNOWN,
        backfill_npc_world_status,
        normalize_world_status,
        PLOT_THREAD_STATUS_LABELS,
    )

    with Session(engine) as db:
        for npc in db.exec(select(NPC)).all():
            if not npc.world_status or npc.world_status == WORLD_STATUS_UNKNOWN:
                npc.world_status = backfill_npc_world_status(npc.current_status, npc.alive_or_dead)
                db.add(npc)
        for thread in db.exec(select(PlotThread)).all():
            if thread.status:
                thread.status = normalize_world_status(thread.status, PLOT_THREAD_STATUS_LABELS)
                db.add(thread)
        db.commit()


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)
    ensure_missing_columns()
    backfill_world_status_defaults()

def get_session():
    with Session(engine) as session:
        yield session
