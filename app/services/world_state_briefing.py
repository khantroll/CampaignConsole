"""Briefing and dashboard builders for Phase 2 world-state."""

from __future__ import annotations

from typing import Any, Dict, List

from app.services.campaign_intelligence import is_active_thread_status
from app.services.world_state import (
    PLOT_THREAD_STATUS_LABELS,
    WORLD_STATUS_UNKNOWN,
    count_open_clues,
    count_revealed_clues,
    is_mystery_open,
    lines_to_clue_list,
    mystery_status_label,
    normalize_world_status,
    MYSTERY_STATUS_LABELS,
    world_status_label,
)


def build_world_state_briefing(threads: List[Any], factions: List[Any], locations: List[Any]) -> Dict[str, Any]:
    open_mysteries: List[Dict[str, Any]] = []
    unrevealed_clues: List[Dict[str, Any]] = []
    recently_revealed: List[Dict[str, Any]] = []
    mystery_attention: List[Dict[str, Any]] = []

    for thread in threads:
        status = normalize_world_status(getattr(thread, "status", None), PLOT_THREAD_STATUS_LABELS)
        mystery = normalize_world_status(getattr(thread, "mystery_status", None), MYSTERY_STATUS_LABELS)
        open_list = lines_to_clue_list(getattr(thread, "open_clues", None))
        revealed_list = lines_to_clue_list(getattr(thread, "revealed_clues", None))

        if open_list and mystery not in {"resolved"}:
            open_mysteries.append(
                {
                    "thread": thread,
                    "status_label": world_status_label(thread.status, "threads"),
                    "mystery_label": mystery_status_label(thread.mystery_status),
                    "open_clues": open_list,
                }
            )

        for clue in open_list:
            unrevealed_clues.append({"thread": thread, "clue": clue})

        for clue in revealed_list:
            recently_revealed.append({"thread": thread, "clue": clue})

        if is_mystery_open(thread) and mystery in {"unrevealed", "partially_revealed"}:
            mystery_attention.append(
                {
                    "thread": thread,
                    "reason": f"Mystery status: {mystery_status_label(thread.mystery_status)}",
                }
            )
        if is_active_thread_status(thread.status) and not open_list and not revealed_list:
            mystery_attention.append({"thread": thread, "reason": "Active thread with no clues recorded"})
        if status == "dormant" and open_list:
            mystery_attention.append({"thread": thread, "reason": "Dormant but still has open clues"})

    return {
        "open_mysteries": open_mysteries,
        "unrevealed_clues": unrevealed_clues,
        "recently_revealed_clues": recently_revealed[:20],
        "mystery_needs_attention": mystery_attention,
        "clue_summary": {
            "open_clue_count": sum(count_open_clues(t) for t in threads),
            "revealed_clue_count": sum(count_revealed_clues(t) for t in threads),
            "unresolved_mystery_count": sum(1 for t in threads if is_mystery_open(t)),
        },
        "faction_states": _rollup_states(factions, "factions"),
        "location_states": _rollup_states(locations, "locations"),
        "thread_states": _rollup_states(threads, "threads"),
    }


def _rollup_states(entities: List[Any], kind: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for entity in entities:
        if kind == "threads":
            key = normalize_world_status(getattr(entity, "status", None), PLOT_THREAD_STATUS_LABELS)
        else:
            from app.services.world_state import ENTITY_STATUS_LABELS

            key = normalize_world_status(getattr(entity, "world_status", None), ENTITY_STATUS_LABELS.get(kind, {}))
        counts[key] = counts.get(key, 0) + 1
    return counts
