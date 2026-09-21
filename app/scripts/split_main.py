"""One-shot helper to split app/main.py into services and routers."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
main_path = ROOT / "app" / "main.py"
text = main_path.read_text(encoding="utf-8")

export_start = text.index("def wrap_link")
export_end = text.index("def build_ingestion_prompt")
export_header = "import io\nimport re\nimport zipfile\nfrom typing import List\n\n"
(ROOT / "app/services/export.py").write_text(
    export_header + text[export_start:export_end], encoding="utf-8"
)

ingest_start = text.index("def build_ingestion_prompt")
ingest_end = text.index("def search_campaign_text")
ingest_header = """import base64
import json
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.llm import llm_complete

"""
ingest_extra = '''

def create_entity_if_missing(db: Session, campaign_id: int, model, name_field, value, extra=None):
    exists = db.exec(
        select(model).where(model.campaign_id == campaign_id, getattr(model, name_field) == value)
    ).first()
    if not exists:
        params = {"campaign_id": campaign_id, name_field: value}
        if extra:
            params.update(extra)
        obj = model(**params)
        db.add(obj)
        db.flush()
        return obj
    return exists


def parse_entity_links(db: Session, campaign_id: int, selections: Optional[List[str]], model, name_field):
    linked = []
    seen = set()
    for selection in selections or []:
        if not selection:
            continue
        if selection.startswith("existing:"):
            try:
                entity_id = int(selection.split(":", 1)[1])
            except ValueError:
                continue
            entity = db.get(model, entity_id)
            if entity and entity.id not in seen:
                linked.append(entity)
                seen.add(entity.id)
        elif selection.startswith("new:"):
            label = selection.split(":", 1)[1].strip()
            if not label:
                continue
            entity = create_entity_if_missing(db, campaign_id, model, name_field, label)
            if entity and entity.id not in seen:
                linked.append(entity)
                seen.add(entity.id)
    return linked
'''
(ROOT / "app/services/ingestion.py").write_text(
    ingest_header + text[ingest_start:ingest_end] + ingest_extra, encoding="utf-8"
)

routes_start = text.index("@app.get(\"/\", response_class=HTMLResponse)")
routes_body = text[routes_start:]
routes_body = re.sub(
    r"def _load_by_ids.*?(?=@app\.get)",
    "",
    routes_body,
    flags=re.S,
)
routes_body = re.sub(
    r"def _related_options.*?(?=@app\.get)",
    "",
    routes_body,
    flags=re.S,
)
routes_body = routes_body.replace("@app.", "@router.")
routes_body = routes_body.replace("_load_by_ids", "load_by_ids").replace(
    "_related_options", "related_options"
)

header = """from datetime import datetime
import io
from typing import List, Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from sqlmodel import Session, select

from app.database import DB_FILE, get_session
from app.deps import get_campaign_or_none, get_entity_or_none, load_by_ids, related_options, templates
from app.llm import llm_complete, llm_available
from app.models import Campaign, Faction, Item, Location, NPC, PlayerCharacterNote, PlotThread, SessionModel
from app.services.analysis import (
    build_ai_review_prompt,
    extract_entities,
    generate_session_prep,
    summarize_notes,
)
from app.services.export import create_obsidian_export, render_campaign_markdown, render_session_markdown
from app.services.ingestion import (
    build_candidate_link_options,
    deserialize_candidate_data,
    extract_candidates_from_notes,
    parse_entity_links,
    serialize_candidate_data,
)
from app.services.search import search_campaign_text

router = APIRouter()

"""
(ROOT / "app/routers").mkdir(parents=True, exist_ok=True)
(ROOT / "app/routers/__init__.py").write_text("", encoding="utf-8")
(ROOT / "app/routers/routes.py").write_text(header + routes_body, encoding="utf-8")
print("generated export.py, ingestion.py, routers/routes.py")
