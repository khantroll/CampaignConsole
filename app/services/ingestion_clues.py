"""Ingestion review helpers for plot-thread clue assignment."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlmodel import Session

from app.models import PlotThread
from app.services.text_similarity import find_best_match, normalize_text
from app.services.world_state import append_unique_lines

REVEALED_HINTS = (
    "learned",
    "discovered",
    "found out",
    "revealed",
    "party knows",
    "told them",
    "realized",
    "uncovered",
)

CLUE_MATCH_THRESHOLD = 0.35


def classify_clue_kind(clue_text: str) -> str:
    lower = (clue_text or "").lower()
    if any(hint in lower for hint in REVEALED_HINTS):
        return "revealed"
    return "open"


def _clue_action_options(
    clue_text: str,
    suggested_kind: str,
    matched_thread: Optional[PlotThread],
    confidence: float,
) -> List[Dict[str, Any]]:
    options: List[Dict[str, Any]] = [
        {"value": "skip", "label": "Skip (do not add to plot thread)", "selected": False},
    ]
    if matched_thread and matched_thread.id:
        pct = f"{confidence * 100:.0f}%"
        open_value = f"open:existing:{matched_thread.id}"
        revealed_value = f"revealed:existing:{matched_thread.id}"
        options.append(
            {
                "value": open_value,
                "label": f"Add as open clue → {matched_thread.title} ({pct} match)",
                "selected": suggested_kind == "open",
            }
        )
        options.append(
            {
                "value": revealed_value,
                "label": f"Add as revealed clue → {matched_thread.title} ({pct} match)",
                "selected": suggested_kind == "revealed" and confidence >= CLUE_MATCH_THRESHOLD,
            }
        )
    title_guess = _title_guess_from_clue(clue_text)
    options.append(
        {
            "value": f"open:create:{title_guess}",
            "label": f"Create plot thread “{title_guess}” and add as open clue",
            "selected": not matched_thread and suggested_kind == "open",
        }
    )
    options.append(
        {
            "value": f"revealed:create:{title_guess}",
            "label": f"Create plot thread “{title_guess}” and add as revealed clue",
            "selected": not matched_thread and suggested_kind == "revealed",
        }
    )
    if not any(opt["selected"] for opt in options):
        options[0]["selected"] = True
    return options


def _title_guess_from_clue(clue_text: str) -> str:
    text = (clue_text or "").strip()
    if not text:
        return "New Mystery"
    if len(text) <= 48:
        return text.rstrip(".")
    return text[:45].rstrip() + "…"


def build_clue_review_rows(
    clues: Sequence[str],
    existing_threads: Sequence[PlotThread],
    *,
    extracted_thread_titles: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    unassigned: List[Dict[str, Any]] = []

    title_pool = list(extracted_thread_titles or [])
    for thread in existing_threads:
        if thread.title and thread.title not in title_pool:
            title_pool.append(thread.title)

    for index, clue in enumerate(clues):
        clue_text = (clue or "").strip()
        if not clue_text:
            continue
        suggested_kind = classify_clue_kind(clue_text)
        matched_thread, confidence = find_best_match(
            clue_text,
            list(existing_threads),
            "title",
            ("details", "open_clues", "revealed_clues"),
        )
        if confidence < CLUE_MATCH_THRESHOLD:
            for title in title_pool:
                thread_stub = PlotThread(title=title)
                alt_match, alt_conf = find_best_match(
                    clue_text,
                    [thread_stub],
                    "title",
                    ("details",),
                )
                if alt_conf > confidence:
                    matched_thread, confidence = alt_match, alt_conf

        options = _clue_action_options(clue_text, suggested_kind, matched_thread, confidence)
        row = {
            "index": index,
            "text": clue_text,
            "suggested_kind": suggested_kind,
            "suggested_kind_label": "Revealed" if suggested_kind == "revealed" else "Open",
            "matched_thread": matched_thread,
            "confidence": confidence,
            "options": options,
        }
        rows.append(row)
        if confidence < CLUE_MATCH_THRESHOLD:
            unassigned.append(row)

    return {"clue_rows": rows, "unassigned_clues": unassigned}


def parse_clue_action(action: str) -> Optional[Tuple[str, str, Optional[int], Optional[str]]]:
    """Return (kind, mode, thread_id, create_title) where mode is existing|create."""
    parts = (action or "").split(":")
    if not parts or parts[0] == "skip":
        return None
    kind = parts[0]
    if kind not in {"open", "revealed"} or len(parts) < 3:
        return None
    mode = parts[1]
    if mode == "existing" and parts[2].isdigit():
        return kind, mode, int(parts[2]), None
    if mode == "create":
        title = ":".join(parts[2:]).strip()
        return kind, mode, None, title or "New Mystery"
    return None


def decode_clue_action(encoded: str) -> Optional[Tuple[int, str]]:
    if not encoded or "|" not in encoded:
        return None
    index_text, action = encoded.split("|", 1)
    if not index_text.isdigit():
        return None
    return int(index_text), action


def apply_clue_ingest_actions(
    db: Session,
    campaign_id: int,
    clue_texts: Sequence[str],
    actions: Sequence[str],
) -> None:
    thread_cache: Dict[int, PlotThread] = {}

    for encoded in actions:
        decoded = decode_clue_action(encoded)
        if not decoded:
            continue
        clue_index, action = decoded
        parsed = parse_clue_action(action)
        if not parsed:
            continue
        kind, mode, thread_id, create_title = parsed
        if clue_index < 0 or clue_index >= len(clue_texts):
            continue
        clue_text = (clue_texts[clue_index] or "").strip()
        if not clue_text:
            continue

        thread: Optional[PlotThread] = None
        if mode == "existing" and thread_id:
            thread = thread_cache.get(thread_id)
            if thread is None:
                thread = db.get(PlotThread, thread_id)
                if thread and thread.campaign_id == campaign_id:
                    thread_cache[thread_id] = thread
                else:
                    thread = None
        elif mode == "create" and create_title:
            thread = select_plot_thread_by_title(db, campaign_id, create_title)
            if not thread:
                thread = PlotThread(campaign_id=campaign_id, title=create_title, status="active")
                db.add(thread)
                db.flush()
                thread_cache[thread.id] = thread

        if not thread:
            continue

        if kind == "open":
            thread.open_clues = append_unique_lines(thread.open_clues, [clue_text])
            if not thread.mystery_status or thread.mystery_status == "unknown":
                thread.mystery_status = "unrevealed"
        else:
            thread.revealed_clues = append_unique_lines(thread.revealed_clues, [clue_text])
            if thread.mystery_status in {None, "unknown", "unrevealed"}:
                thread.mystery_status = "partially_revealed"
        db.add(thread)


def select_plot_thread_by_title(db: Session, campaign_id: int, title: str) -> Optional[PlotThread]:
    from sqlmodel import select

    target = normalize_text(title)
    threads = db.exec(select(PlotThread).where(PlotThread.campaign_id == campaign_id)).all()
    for thread in threads:
        if normalize_text(thread.title) == target:
            return thread
    return None


def encode_clue_action(index: int, action: str) -> str:
    return f"{index}|{action}"


def parse_ingest_clues_json(raw: str) -> List[str]:
    if not raw or not raw.strip():
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(item).strip() for item in data if str(item).strip()]
    except json.JSONDecodeError:
        pass
    return [line.strip() for line in raw.splitlines() if line.strip()]
