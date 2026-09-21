"""World-state status enums, badge styling, and clue line helpers (Phase 2)."""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from app.services.text_similarity import normalize_text

WORLD_STATUS_UNKNOWN = "unknown"

FACTION_STATUS_LABELS: Dict[str, str] = {
    "hostile": "Hostile",
    "friendly": "Friendly",
    "neutral": "Neutral",
    "fractured": "Fractured",
    WORLD_STATUS_UNKNOWN: "Unknown",
}

LOCATION_STATUS_LABELS: Dict[str, str] = {
    "unexplored": "Unexplored",
    "explored": "Explored",
    "cleared": "Cleared",
    "destroyed": "Destroyed",
    WORLD_STATUS_UNKNOWN: "Unknown",
}

PLOT_THREAD_STATUS_LABELS: Dict[str, str] = {
    "active": "Active",
    "dormant": "Dormant",
    "resolved": "Resolved",
    "stalled": "Stalled",
    WORLD_STATUS_UNKNOWN: "Unknown",
}

ITEM_STATUS_LABELS: Dict[str, str] = {
    WORLD_STATUS_UNKNOWN: "Unknown",
    "discovered": "Discovered",
    "claimed": "Claimed",
    "lost": "Lost",
    "destroyed": "Destroyed",
}

NPC_WORLD_STATUS_LABELS: Dict[str, str] = {
    WORLD_STATUS_UNKNOWN: "Unknown",
    "active": "Active",
    "allied": "Allied",
    "hostile": "Hostile",
    "missing": "Missing",
    "dead": "Dead",
}

CREATURE_STATUS_LABELS: Dict[str, str] = {
    WORLD_STATUS_UNKNOWN: "Unknown",
    "active": "Active",
    "defeated": "Defeated",
    "recurring": "Recurring",
    "extinct": "Extinct",
}

MYSTERY_STATUS_LABELS: Dict[str, str] = {
    WORLD_STATUS_UNKNOWN: "Unknown",
    "unrevealed": "Unrevealed",
    "partially_revealed": "Partially Revealed",
    "revealed": "Revealed",
    "resolved": "Resolved",
}

ENTITY_STATUS_LABELS: Dict[str, Dict[str, str]] = {
    "factions": FACTION_STATUS_LABELS,
    "locations": LOCATION_STATUS_LABELS,
    "threads": PLOT_THREAD_STATUS_LABELS,
    "items": ITEM_STATUS_LABELS,
    "npcs": NPC_WORLD_STATUS_LABELS,
    "creatures": CREATURE_STATUS_LABELS,
}

# Plot threads use `status` column; other entities use `world_status`.
PLOT_THREAD_STATUS_FIELD = "status"
WORLD_STATUS_FIELD = "world_status"

STATUS_BADGE_CLASS: Dict[str, str] = {
    "hostile": "danger",
    "dead": "danger",
    "destroyed": "danger",
    "defeated": "danger",
    "extinct": "danger",
    "active": "info",
    "recurring": "info",
    "friendly": "success",
    "allied": "success",
    "cleared": "success",
    "resolved": "success",
    "explored": "success",
    "claimed": "success",
    "revealed": "success",
    "discovered": "success",
    "dormant": "warning",
    "stalled": "warning",
    "fractured": "warning",
    "missing": "warning",
    "lost": "warning",
    "partially_revealed": "warning",
    "unrevealed": "warning",
    "neutral": "secondary",
    "unexplored": "secondary",
    WORLD_STATUS_UNKNOWN: "secondary",
}

FACTION_STATUS_CHOICES: Tuple[Tuple[str, str], ...] = tuple(FACTION_STATUS_LABELS.items())
LOCATION_STATUS_CHOICES: Tuple[Tuple[str, str], ...] = tuple(LOCATION_STATUS_LABELS.items())
PLOT_THREAD_WORLD_STATUS_CHOICES: Tuple[Tuple[str, str], ...] = tuple(PLOT_THREAD_STATUS_LABELS.items())
ITEM_STATUS_CHOICES: Tuple[Tuple[str, str], ...] = tuple(ITEM_STATUS_LABELS.items())
NPC_WORLD_STATUS_CHOICES: Tuple[Tuple[str, str], ...] = tuple(NPC_WORLD_STATUS_LABELS.items())
CREATURE_STATUS_CHOICES: Tuple[Tuple[str, str], ...] = tuple(CREATURE_STATUS_LABELS.items())
MYSTERY_STATUS_CHOICES: Tuple[Tuple[str, str], ...] = tuple(MYSTERY_STATUS_LABELS.items())

PRESET_FACTION_STATUS_KEYS = frozenset(FACTION_STATUS_LABELS)
PRESET_LOCATION_STATUS_KEYS = frozenset(LOCATION_STATUS_LABELS)
PRESET_THREAD_WORLD_STATUS_KEYS = frozenset(PLOT_THREAD_STATUS_LABELS)
PRESET_ITEM_STATUS_KEYS = frozenset(ITEM_STATUS_LABELS)
PRESET_NPC_WORLD_STATUS_KEYS = frozenset(NPC_WORLD_STATUS_LABELS)
PRESET_CREATURE_STATUS_KEYS = frozenset(CREATURE_STATUS_LABELS)
PRESET_MYSTERY_STATUS_KEYS = frozenset(MYSTERY_STATUS_LABELS)

_STATUS_ALIASES: Dict[str, str] = {
    "failed": "stalled",
    "open": "active",
    "in_progress": "active",
    "ongoing": "active",
    "alive": "active",
}


def normalize_world_status(value: Optional[str], labels: Dict[str, str]) -> str:
    if not value or not str(value).strip():
        return WORLD_STATUS_UNKNOWN
    key = str(value).strip().lower().replace(" ", "_")
    key = _STATUS_ALIASES.get(key, key)
    if key in labels:
        return key
    for label_key, label in labels.items():
        if normalize_text(label) == normalize_text(value):
            return label_key
    return WORLD_STATUS_UNKNOWN


def world_status_label(value: Optional[str], entity_kind: str) -> str:
    labels = ENTITY_STATUS_LABELS.get(entity_kind, {})
    if entity_kind == "threads":
        key = normalize_world_status(value, PLOT_THREAD_STATUS_LABELS)
    else:
        key = normalize_world_status(value, labels)
    return labels.get(key, (value or "Unknown").replace("_", " ").title())


def world_status_badge_class(value: Optional[str], entity_kind: str = "") -> str:
    if entity_kind == "threads":
        key = normalize_world_status(value, PLOT_THREAD_STATUS_LABELS)
    elif entity_kind in ENTITY_STATUS_LABELS:
        key = normalize_world_status(value, ENTITY_STATUS_LABELS[entity_kind])
    else:
        key = normalize_world_status(value, {})
    return STATUS_BADGE_CLASS.get(key, "secondary")


def mystery_status_label(value: Optional[str]) -> str:
    key = normalize_world_status(value, MYSTERY_STATUS_LABELS)
    return MYSTERY_STATUS_LABELS.get(key, "Unknown")


def mystery_status_badge_class(value: Optional[str]) -> str:
    key = normalize_world_status(value, MYSTERY_STATUS_LABELS)
    return STATUS_BADGE_CLASS.get(key, "secondary")


def entity_world_status(entity, entity_kind: str) -> str:
    if entity_kind == "threads":
        return normalize_world_status(getattr(entity, "status", None), PLOT_THREAD_STATUS_LABELS)
    return normalize_world_status(getattr(entity, "world_status", None), ENTITY_STATUS_LABELS.get(entity_kind, {}))


def lines_to_clue_list(text: Optional[str]) -> List[str]:
    if not text:
        return []
    return [line.strip() for line in str(text).splitlines() if line.strip()]


def clue_list_to_lines(clues: Sequence[str]) -> Optional[str]:
    cleaned = [c.strip() for c in clues if c and str(c).strip()]
    if not cleaned:
        return None
    return "\n".join(cleaned)


def append_unique_lines(existing: Optional[str], new_lines: Sequence[str]) -> str:
    current = lines_to_clue_list(existing)
    seen = {normalize_text(line) for line in current}
    for line in new_lines:
        normalized = normalize_text(line)
        if normalized and normalized not in seen:
            current.append(line.strip())
            seen.add(normalized)
    return clue_list_to_lines(current) or ""


def count_open_clues(thread) -> int:
    return len(lines_to_clue_list(getattr(thread, "open_clues", None)))


def count_revealed_clues(thread) -> int:
    return len(lines_to_clue_list(getattr(thread, "revealed_clues", None)))


def is_mystery_open(thread) -> bool:
    mystery = normalize_world_status(getattr(thread, "mystery_status", None), MYSTERY_STATUS_LABELS)
    return mystery not in {"resolved", WORLD_STATUS_UNKNOWN}


def apply_world_status_fields(
    entity,
    entity_kind: str,
    status_value: Optional[str],
    state_notes: Optional[str] = None,
) -> None:
    if entity_kind == "threads":
        entity.status = normalize_world_status(status_value, PLOT_THREAD_STATUS_LABELS)
    else:
        labels = ENTITY_STATUS_LABELS.get(entity_kind, {})
        entity.world_status = normalize_world_status(status_value, labels)
    if state_notes is not None:
        entity.state_notes = state_notes.strip() or None


def apply_mystery_fields(thread, mystery_status: Optional[str], open_clues: Optional[str], revealed_clues: Optional[str], secret_notes: Optional[str]) -> None:
    thread.mystery_status = normalize_world_status(mystery_status, MYSTERY_STATUS_LABELS)
    thread.open_clues = clue_list_to_lines(lines_to_clue_list(open_clues)) if open_clues is not None else thread.open_clues
    thread.revealed_clues = clue_list_to_lines(lines_to_clue_list(revealed_clues)) if revealed_clues is not None else thread.revealed_clues
    thread.secret_notes = secret_notes.strip() or None if secret_notes is not None else thread.secret_notes


def backfill_npc_world_status(current_status: Optional[str], alive_or_dead: Optional[str]) -> str:
    alive = normalize_text(alive_or_dead or "")
    if alive in {"dead", "deceased"}:
        return "dead"
    status = normalize_text(current_status or "")
    mapping = {
        "active": "active",
        "missing": "missing",
        "imprisoned": "missing",
        "hidden": "active",
        "retired": "active",
    }
    for token, world in mapping.items():
        if token in status:
            return world
    return WORLD_STATUS_UNKNOWN
