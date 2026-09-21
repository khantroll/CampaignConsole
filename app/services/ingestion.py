import json
import logging
from typing import Any, Dict, List, Optional, Tuple
from sqlmodel import Session, select

from app.models import (
    Creature,
    CreatureFactionLink,
    CreatureLocationLink,
    CreaturePlotThreadLink,
    Faction,
    Item,
    ItemLocationLink,
    ItemNPCLink,
    ItemPlotThreadLink,
    Location,
    LocationPlotThreadLink,
    NPC,
    NPCFactionLink,
    NPCLocationLink,
    NPCPlotThreadLink,
    PCFactionLink,
    PlayerCharacterNote,
    PlotThread,
    SessionModel,
    SessionPartyMemberLink,
)
from app.services.location_classification import (
    LOCATION_TYPE_SCENE,
    classify_location,
    location_type_label,
    normalize_location_type,
)
from app.services.llm_json import parse_llm_json_lenient
from app.services.provider_router import generate, provider_available as llm_available
from app.services.text_similarity import find_best_match, normalize_text

logger = logging.getLogger(__name__)

INGESTION_JSON_KEYS = (
    "Characters",
    "Creatures",
    "Locations",
    "Factions",
    "Items",
    "PlotThreads",
    "SecretsClues",
    "UnresolvedHooks",
    "EntityRelationships",
    "NPCRelationships",
)
EMPTY_CANDIDATES = {
    "extracted_characters": [],
    "extracted_creatures": [],
    "extracted_locations": [],
    "extracted_factions": [],
    "extracted_items": [],
    "extracted_threads": [],
    "SecretsClues": [],
    "UnresolvedHooks": [],
    "EntityRelationships": [],
}

SIMILARITY_USE_EXISTING_THRESHOLD = 0.48
HIGH_RELATIONSHIP_CONFIDENCE = 0.9

PLOT_THREAD_MATCH_ATTRS = ("details", "related_npcs", "related_locations", "status")


def build_ingestion_prompt(campaign, notes: str) -> str:
    return (
        f"You are an assistant helping a tabletop game master extract structured campaign elements from raw session notes. "
        f"The campaign is {campaign.name}. "
        f"Provide JSON only with these keys:\n"
        f"- Characters: named intelligent people mentioned in these notes (individuals with personal names or titles, "
        f"e.g. Baron Kestrel, Captain Serana). Do not classify them as PCs or NPCs. "
        f"Do not put monsters, beasts, wildlife, or unnamed enemies here.\n"
        f"- Creatures: species or type names for monsters, beasts, hostile creatures, wildlife, and unnamed enemies "
        f"(e.g. Goblin, Dragon, Dire Wolf, Skeleton, Black-skinned Reptilian). Use a singular type label, not "
        f"individual personal names. Do not put named intelligent individuals here. Prefer Creatures over Items for "
        f"living hostile entities.\n"
        f"- Locations: places mentioned in these notes. Return objects with name, type, and confidence. "
        f"type must be one of: major (cities, regions, districts), sub (buildings, homes, named structures), "
        f"scene_feature (temporary features such as a chest, side passage, shallow pool, dead-end, or generic room). "
        f"Do not list generic scene features unless they are explicitly named places.\n"
        f"- Factions, Items, PlotThreads: names/titles mentioned in these notes only. "
        f"Do not put monsters, beasts, wildlife, or unnamed enemies in Items.\n"
        f"- SecretsClues: short clue or secret strings from these notes, separate from plot thread titles. "
        f"Include discoveries the party made (revealed clues) and unanswered mysteries (open clues).\n"
        f"- UnresolvedHooks: short strings from these notes\n"
        f"- EntityRelationships: list of objects with keys from_type, from, to_type, to, and optional confidence "
        f"(high, medium, or low). Supported types: npc, location, faction, item, creature, thread. "
        f"Include a relationship only when the notes clearly connect those entities. "
        f"Supported pairs include npc->faction, npc->location, npc->thread, item->npc, item->location, "
        f"item->thread, creature->location, creature->thread, and location->thread. "
        f"Do not relate every extracted entity to every other entity.\n"
        f"If a category is empty, return an empty list. "
        f"Raw notes:\n{notes}"
    )


def _entry_name(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("name", "Name", "NAME", "title", "Title", "TITLE", "character", "Character"):
            candidate = value.get(key)
            if candidate:
                return str(candidate).strip()
        return ""
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, dict):
                    return _entry_name(parsed)
            except json.JSONDecodeError:
                pass
        return stripped
    return str(value or "").strip()


def _bucket(data: Dict[str, Any], *keys: str) -> List[str]:
    for key in keys:
        values = data.get(key)
        if isinstance(values, list):
            return [_entry_name(value) for value in values if _entry_name(value)]
    return []


def _confidence_to_score(value: Any) -> float:
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    text = str(value or "").strip().lower()
    if text == "high":
        return 0.95
    if text == "medium":
        return 0.65
    if text == "low":
        return 0.35
    return 0.5


def _normalize_relationship_row(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    from_type = str(row.get("from_type") or row.get("source_type") or "").strip().lower()
    to_type = str(row.get("to_type") or row.get("target_type") or "").strip().lower()
    from_name = str(row.get("from") or row.get("source") or row.get("from_name") or "").strip()
    to_name = str(row.get("to") or row.get("target") or row.get("to_name") or "").strip()
    if not from_name or not to_name:
        return None

    if from_type in {"plot_thread", "plotthread"}:
        from_type = "thread"
    if to_type in {"plot_thread", "plotthread"}:
        to_type = "thread"

    rel_key = f"{from_type}_{to_type}"
    allowed = {
        "npc_faction",
        "npc_location",
        "npc_thread",
        "item_npc",
        "item_location",
        "item_thread",
        "creature_location",
        "creature_thread",
        "location_thread",
    }
    if rel_key not in allowed:
        return None

    confidence = _confidence_to_score(row.get("confidence"))
    return {
        "rel_type": rel_key,
        "from_name": from_name,
        "to_name": to_name,
        "confidence": confidence,
        "source": "llm",
    }


def _parse_entity_relationships(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    relationships: List[Dict[str, Any]] = []
    seen = set()

    raw_rows = data.get("EntityRelationships") or data.get("entity_relationships") or []
    if isinstance(raw_rows, list):
        for row in raw_rows:
            if not isinstance(row, dict):
                continue
            normalized = _normalize_relationship_row(row)
            if normalized:
                key = (normalized["rel_type"], normalized["from_name"].lower(), normalized["to_name"].lower())
                if key not in seen:
                    seen.add(key)
                    relationships.append(normalized)

    legacy_rows = data.get("NPCRelationships") or data.get("npc_relationships") or []
    if isinstance(legacy_rows, list):
        for row in legacy_rows:
            if not isinstance(row, dict):
                continue
            npc_name = str(row.get("npc") or row.get("NPC") or "").strip()
            if not npc_name:
                continue
            for rel_type, rel_key in (
                ("faction", "faction"),
                ("location", "location"),
                ("thread", "plot_thread"),
            ):
                target = str(row.get(rel_key) or row.get(rel_type.title()) or "").strip()
                if not target:
                    continue
                rel_key_name = f"npc_{rel_type}"
                key = (rel_key_name, npc_name.lower(), target.lower())
                if key in seen:
                    continue
                seen.add(key)
                relationships.append(
                    {
                        "rel_type": rel_key_name,
                        "from_name": npc_name,
                        "to_name": target,
                        "confidence": 0.95,
                        "source": "llm_legacy",
                    }
                )
    return relationships


def _dedupe_names(names: List[str]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for name in names:
        key = name.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(name.strip())
    return ordered


def _collect_character_names(data: Dict[str, Any]) -> List[str]:
    names: List[str] = []
    names.extend(_bucket(data, "Characters", "characters", "extracted_characters"))
    names.extend(_bucket(data, "NPCs", "extracted_npcs"))
    names.extend(_bucket(data, "PartyMembers", "Party", "extracted_party_members"))
    return _dedupe_names(names)


def _find_exact_pc(name: str, existing_pcs: List[PlayerCharacterNote]) -> Optional[PlayerCharacterNote]:
    target = normalize_text(name)
    if not target:
        return None
    for pc in existing_pcs:
        if normalize_text(pc.character_name) == target:
            return pc
    return None


def _find_exact_npc(name: str, existing_npcs: List[NPC]) -> Optional[NPC]:
    target = normalize_text(name)
    if not target:
        return None
    for npc in existing_npcs:
        if normalize_text(npc.name) == target:
            return npc
    return None


def classify_characters(
    character_names: List[str],
    existing_pcs: List[PlayerCharacterNote],
    existing_npcs: List[NPC],
) -> Tuple[List[str], List[str], List[str]]:
    party_members: List[str] = []
    matched_npcs: List[str] = []
    unclassified: List[str] = []

    for name in _dedupe_names(character_names):
        if _find_exact_pc(name, existing_pcs):
            party_members.append(name)
        elif _find_exact_npc(name, existing_npcs):
            matched_npcs.append(name)
        else:
            unclassified.append(name)

    return party_members, matched_npcs, unclassified


def _location_entry_name(entry: Any) -> str:
    if isinstance(entry, dict):
        return str(entry.get("name") or "").strip()
    return str(entry or "").strip()


def _parse_locations_bucket(data: Dict[str, Any], *keys: str) -> List[Dict[str, Any]]:
    for key in keys:
        values = data.get(key)
        if not isinstance(values, list):
            continue
        classified: List[Dict[str, Any]] = []
        seen = set()
        for value in values:
            if isinstance(value, dict):
                name = str(value.get("name") or value.get("Name") or "").strip()
                llm_type = value.get("type") or value.get("location_type")
                confidence = _confidence_to_score(value.get("confidence"))
            else:
                name = str(value or "").strip()
                llm_type = None
                confidence = None
            if not name:
                continue
            key_name = name.lower()
            if key_name in seen:
                continue
            seen.add(key_name)
            classified.append(
                classify_location(name, llm_type=llm_type, llm_confidence=confidence)
            )
        return classified
    return []


def normalize_extraction(data: Dict[str, Any]) -> Dict[str, Any]:
    creatures = _bucket(data, "Creatures", "creatures", "extracted_creatures")
    items = _bucket(data, "Items", "extracted_items")
    creature_keys = {normalize_text(name) for name in creatures}
    filtered_items = [item for item in items if normalize_text(item) not in creature_keys]
    return {
        "extracted_characters": _collect_character_names(data),
        "extracted_creatures": creatures,
        "extracted_locations": _parse_locations_bucket(data, "Locations", "extracted_locations"),
        "extracted_factions": _bucket(data, "Factions", "extracted_factions"),
        "extracted_items": filtered_items,
        "extracted_threads": _bucket(data, "PlotThreads", "extracted_threads"),
        "SecretsClues": _bucket(data, "SecretsClues"),
        "UnresolvedHooks": _bucket(data, "UnresolvedHooks"),
        "EntityRelationships": _parse_entity_relationships(data),
    }


def prepare_review_candidates(
    normalized: Dict[str, Any],
    existing_pcs: List[PlayerCharacterNote],
    existing_npcs: List[NPC],
) -> Dict[str, Any]:
    party_members, matched_npcs, unclassified = classify_characters(
        normalized.get("extracted_characters", []),
        existing_pcs,
        existing_npcs,
    )
    review = dict(normalized)
    review["extracted_party_members"] = party_members
    review["extracted_npcs"] = matched_npcs
    review["unclassified_characters"] = unclassified
    review["EntityRelationships"] = enrich_relationship_suggestions(review)
    return review


def candidates_for_review(normalized: Dict[str, Any]) -> Dict[str, List[str]]:
    return {
        "PartyMembers": normalized.get("extracted_party_members", []),
        "NPCs": normalized.get("extracted_npcs", []),
        "UnclassifiedCharacters": normalized.get("unclassified_characters", []),
        "Locations": normalized.get("extracted_locations", []),
        "Factions": normalized.get("extracted_factions", []),
        "Creatures": normalized.get("extracted_creatures", []),
        "Items": normalized.get("extracted_items", []),
        "PlotThreads": normalized.get("extracted_threads", []),
        "SecretsClues": normalized.get("SecretsClues", []),
        "UnresolvedHooks": normalized.get("UnresolvedHooks", []),
    }


def extract_candidates_from_notes(campaign, notes: str) -> Tuple[Dict[str, Any], Optional[str]]:
    if not llm_available():
        raise RuntimeError("LLM provider not configured.")
    raw = generate(
        build_ingestion_prompt(campaign, notes),
        max_tokens=2400,
        task_name="ingest/extract",
    )
    data, parse_warning = parse_llm_json_lenient(raw, fallback_keys=list(INGESTION_JSON_KEYS))
    if parse_warning:
        logger.warning("Ingestion JSON partial parse: %s", parse_warning)
    return normalize_extraction(data), parse_warning

def _default_action(selected_value: str) -> str:
    if selected_value == "skip":
        return "skip"
    if selected_value.startswith("existing:"):
        return "use existing"
    if selected_value.startswith("new:"):
        return "create"
    if selected_value.startswith("party:new:"):
        return "create pc"
    if selected_value.startswith("npc:new:"):
        return "create npc"
    return selected_value


def build_candidate_link_options(
    candidates: List[str],
    existing_objects: List[Any],
    label_attr: str = "name",
    *,
    bucket: str = "entity",
    similarity_extra_attrs: Tuple[str, ...] = (),
    similarity_threshold: float = SIMILARITY_USE_EXISTING_THRESHOLD,
) -> List[Dict[str, Any]]:
    options_by_candidate = []
    for candidate in candidates:
        candidate_name = candidate.strip()
        if not candidate_name:
            continue

        matched_existing, confidence = find_best_match(
            candidate_name,
            existing_objects,
            label_attr,
            similarity_extra_attrs,
        )

        options = [
            {
                "value": "skip",
                "label": "Skip (do not link to this session)",
                "selected": False,
            }
        ]

        use_existing = matched_existing is not None and confidence >= similarity_threshold
        if matched_existing:
            label = getattr(matched_existing, label_attr, candidate_name)
            confidence_pct = f"{confidence * 100:.0f}%"
            options.append(
                {
                    "value": f"existing:{matched_existing.id}",
                    "label": f"Use existing: {label} ({confidence_pct} match)",
                    "selected": use_existing,
                }
            )

        options.append(
            {
                "value": f"new:{candidate_name}",
                "label": f"Create new: {candidate_name}",
                "selected": not use_existing,
            }
        )

        selected_value = next((option["value"] for option in options if option["selected"]), "skip")
        options_by_candidate.append(
            {
                "candidate": candidate_name,
                "bucket": bucket,
                "options": options,
                "debug": {
                    "bucket": bucket,
                    "action": _default_action(selected_value),
                    "matched_record": getattr(matched_existing, label_attr, None) if matched_existing else None,
                    "confidence": round(confidence, 2) if matched_existing else None,
                },
            }
        )
    return options_by_candidate


def build_location_link_options(
    classified_locations: List[Dict[str, Any]],
    existing_objects: List[Any],
    *,
    similarity_threshold: float = SIMILARITY_USE_EXISTING_THRESHOLD,
) -> List[Dict[str, Any]]:
    options_by_candidate = []
    for entry in classified_locations:
        candidate_name = _location_entry_name(entry)
        if not candidate_name:
            continue

        location_type = entry.get("location_type") or normalize_location_type(entry.get("type")) or "major"
        extraction_confidence = entry.get("confidence")
        should_create = entry.get("should_create", location_type != LOCATION_TYPE_SCENE)
        type_label = location_type_label(location_type)

        matched_existing, match_confidence = find_best_match(
            candidate_name,
            existing_objects,
            "name",
        )

        options = [
            {
                "value": "skip",
                "label": "Skip (do not link to this session)",
                "selected": not should_create,
            }
        ]

        use_existing = matched_existing is not None and match_confidence >= similarity_threshold
        if matched_existing:
            label = getattr(matched_existing, "name", candidate_name)
            confidence_pct = f"{match_confidence * 100:.0f}%"
            options.append(
                {
                    "value": f"existing:{matched_existing.id}",
                    "label": f"Use existing: {label} ({confidence_pct} match)",
                    "selected": use_existing and should_create,
                }
            )

        if location_type == LOCATION_TYPE_SCENE:
            options.append(
                {
                    "value": f"new:{candidate_name}|{location_type}",
                    "label": f"Create anyway: {candidate_name} ({type_label})",
                    "selected": False,
                }
            )
        else:
            options.append(
                {
                    "value": f"new:{candidate_name}|{location_type}",
                    "label": f"Create new: {candidate_name} ({type_label})",
                    "selected": should_create and not use_existing,
                }
            )

        selected_value = next((option["value"] for option in options if option["selected"]), "skip")
        options_by_candidate.append(
            {
                "candidate": candidate_name,
                "bucket": "location",
                "location_type": location_type,
                "location_type_label": type_label,
                "extraction_confidence": extraction_confidence,
                "options": options,
                "debug": {
                    "bucket": "location",
                    "action": _default_action(selected_value),
                    "matched_record": getattr(matched_existing, "name", None) if matched_existing else None,
                    "confidence": round(match_confidence, 2) if matched_existing else extraction_confidence,
                    "location_type": type_label,
                },
            }
        )
    return options_by_candidate


def build_matched_pc_link_options(
    candidates: List[str],
    existing_pcs: List[PlayerCharacterNote],
) -> List[Dict[str, Any]]:
    options_by_candidate = []
    for candidate in candidates:
        candidate_name = candidate.strip()
        if not candidate_name:
            continue

        matched_pc = _find_exact_pc(candidate_name, existing_pcs)
        options = [
            {"value": "skip", "label": "Skip", "selected": False},
        ]
        if matched_pc:
            options.append(
                {
                    "value": f"party:existing:{matched_pc.id}",
                    "label": f"Use existing PC: {matched_pc.character_name}",
                    "selected": True,
                }
            )

        selected_value = next((option["value"] for option in options if option["selected"]), "skip")
        options_by_candidate.append(
            {
                "candidate": candidate_name,
                "bucket": "party",
                "options": options,
                "debug": {
                    "bucket": "party",
                    "action": _default_action(selected_value),
                    "matched_record": matched_pc.character_name if matched_pc else None,
                    "confidence": 1.0 if matched_pc else None,
                },
            }
        )
    return options_by_candidate


def build_matched_npc_link_options(
    candidates: List[str],
    existing_npcs: List[NPC],
) -> List[Dict[str, Any]]:
    options_by_candidate = []
    for candidate in candidates:
        candidate_name = candidate.strip()
        if not candidate_name:
            continue

        matched_npc = _find_exact_npc(candidate_name, existing_npcs)
        options = [
            {"value": "skip", "label": "Skip (do not link to this session)", "selected": False},
        ]
        if matched_npc:
            options.append(
                {
                    "value": f"existing:{matched_npc.id}",
                    "label": f"Use existing NPC: {matched_npc.name}",
                    "selected": True,
                }
            )

        selected_value = next((option["value"] for option in options if option["selected"]), "skip")
        options_by_candidate.append(
            {
                "candidate": candidate_name,
                "bucket": "npc",
                "options": options,
                "debug": {
                    "bucket": "npc",
                    "action": _default_action(selected_value),
                    "matched_record": matched_npc.name if matched_npc else None,
                    "confidence": 1.0 if matched_npc else None,
                },
            }
        )
    return options_by_candidate


def build_unclassified_character_options(
    candidates: List[str],
) -> List[Dict[str, Any]]:
    options_by_candidate = []
    for candidate in candidates:
        candidate_name = candidate.strip()
        if not candidate_name:
            continue

        options = [
            {"value": "skip", "label": "Skip", "selected": False},
            {
                "value": f"npc:new:{candidate_name}",
                "label": f"Create NPC: {candidate_name}",
                "selected": True,
            },
            {
                "value": f"party:new:{candidate_name}",
                "label": f"Create PC: {candidate_name}",
                "selected": False,
            },
        ]

        selected_value = next((option["value"] for option in options if option["selected"]), "skip")
        options_by_candidate.append(
            {
                "candidate": candidate_name,
                "bucket": "unclassified",
                "options": options,
                "debug": {
                    "bucket": "unclassified",
                    "action": _default_action(selected_value),
                    "matched_record": None,
                    "confidence": None,
                },
            }
        )
    return options_by_candidate


def enrich_relationship_suggestions(normalized: Dict[str, Any]) -> List[Dict[str, Any]]:
    suggestions = list(normalized.get("EntityRelationships", []))
    seen = {(row["rel_type"], row["from_name"].lower(), row["to_name"].lower()) for row in suggestions}
    character_names = _dedupe_names(
        normalized.get("extracted_npcs", [])
        + normalized.get("extracted_party_members", [])
        + normalized.get("unclassified_characters", [])
    )

    def add_suggestion(rel_type: str, from_name: str, to_name: str, confidence: float, source: str) -> None:
        key = (rel_type, from_name.lower(), to_name.lower())
        if key in seen:
            return
        seen.add(key)
        suggestions.append(
            {
                "rel_type": rel_type,
                "from_name": from_name,
                "to_name": to_name,
                "confidence": confidence,
                "source": source,
            }
        )

    for npc in character_names:
        for thread in normalized.get("extracted_threads", []):
            if normalize_text(npc) in normalize_text(thread):
                add_suggestion("npc_thread", npc, thread, 0.62, "heuristic")

    for creature in normalized.get("extracted_creatures", []):
        for location in normalized.get("extracted_locations", []):
            location_name = _location_entry_name(location)
            if not location_name:
                continue
            if normalize_text(creature) in normalize_text(location_name) or normalize_text(location_name) in normalize_text(creature):
                add_suggestion("creature_location", creature, location_name, 0.62, "heuristic")
        for thread in normalized.get("extracted_threads", []):
            if normalize_text(creature) in normalize_text(thread):
                add_suggestion("creature_thread", creature, thread, 0.6, "heuristic")

    for item in normalized.get("extracted_items", []):
        for npc in character_names:
            if normalize_text(item) in normalize_text(npc) or normalize_text(npc) in normalize_text(item):
                add_suggestion("item_npc", item, npc, 0.6, "heuristic")
        for location in normalized.get("extracted_locations", []):
            location_name = _location_entry_name(location)
            if not location_name:
                continue
            if normalize_text(location_name) in normalize_text(item) or normalize_text(item) in normalize_text(location_name):
                add_suggestion("item_location", item, location_name, 0.6, "heuristic")
        for thread in normalized.get("extracted_threads", []):
            if normalize_text(item) in normalize_text(thread):
                add_suggestion("item_thread", item, thread, 0.6, "heuristic")

    for location in normalized.get("extracted_locations", []):
        location_name = _location_entry_name(location)
        if not location_name:
            continue
        for thread in normalized.get("extracted_threads", []):
            if normalize_text(location_name) in normalize_text(thread):
                add_suggestion("location_thread", location_name, thread, 0.6, "heuristic")

    return suggestions


def build_entity_relationship_options(
    relationships: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    labels = {
        "npc_faction": ("NPC", "faction"),
        "npc_location": ("NPC", "location"),
        "npc_thread": ("NPC", "plot thread"),
        "item_npc": ("Item", "NPC"),
        "item_location": ("Item", "location"),
        "item_thread": ("Item", "plot thread"),
        "creature_location": ("Creature", "location"),
        "creature_thread": ("Creature", "plot thread"),
        "location_thread": ("Location", "plot thread"),
    }
    options: List[Dict[str, Any]] = []
    seen = set()
    for row in relationships:
        rel_type = row.get("rel_type", "").strip()
        from_name = row.get("from_name", "").strip()
        to_name = row.get("to_name", "").strip()
        if not rel_type or not from_name or not to_name:
            continue
        value = f"{rel_type}|{from_name}|{to_name}"
        if value in seen:
            continue
        seen.add(value)
        _, right_label = labels.get(rel_type, ("Entity", "entity"))
        confidence = float(row.get("confidence", 0.5))
        options.append(
            {
                "value": value,
                "label": f"{from_name} → {right_label}: {to_name}",
                "checked": confidence >= HIGH_RELATIONSHIP_CONFIDENCE,
                "confidence": round(confidence, 2),
                "rel_type": rel_type,
                "source": row.get("source", "llm"),
            }
        )
    return options


def build_npc_relationship_options(relationships: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    npc_only = [row for row in relationships if str(row.get("rel_type", "")).startswith("npc_")]
    return build_entity_relationship_options(npc_only)


def build_review_debug_rows(*candidate_groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for group in candidate_groups:
        for candidate in group:
            debug = candidate.get("debug", {})
            rows.append(
                {
                    "candidate": candidate.get("candidate"),
                    "bucket": debug.get("bucket") or candidate.get("bucket"),
                    "action": debug.get("action"),
                    "matched_record": debug.get("matched_record"),
                    "confidence": debug.get("confidence"),
                }
            )
    return rows


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


def create_pc_if_missing(db: Session, campaign_id: int, character_name: str) -> PlayerCharacterNote:
    existing = db.exec(
        select(PlayerCharacterNote).where(
            PlayerCharacterNote.campaign_id == campaign_id,
            PlayerCharacterNote.character_name == character_name,
        )
    ).first()
    if existing:
        return existing
    pc = PlayerCharacterNote(campaign_id=campaign_id, character_name=character_name)
    db.add(pc)
    db.flush()
    return pc


def parse_entity_links(db: Session, campaign_id: int, selections: Optional[List[str]], model, name_field):
    linked = []
    seen = set()
    for selection in selections or []:
        if not selection or selection == "skip":
            continue
        if selection.startswith("existing:"):
            try:
                entity_id = int(selection.split(":", 1)[1])
            except ValueError:
                continue
            entity = db.get(model, entity_id)
            if entity and entity.campaign_id == campaign_id and entity.id not in seen:
                linked.append(entity)
                seen.add(entity.id)
        elif selection.startswith("new:"):
            rest = selection.split(":", 1)[1].strip()
            if not rest:
                continue
            label = rest
            extra = None
            if "|" in rest:
                label, location_type = rest.rsplit("|", 1)
                label = label.strip()
                if model is Location:
                    extra = {"location_type": normalize_location_type(location_type) or location_type}
            elif model is Location:
                extra = {"location_type": classify_location(label)["location_type"]}
            entity = create_entity_if_missing(db, campaign_id, model, name_field, label, extra=extra)
            if entity and entity.id not in seen:
                linked.append(entity)
                seen.add(entity.id)
    return linked


def split_unclassified_character_selections(
    selections: Optional[List[str]],
) -> Tuple[List[str], List[str]]:
    party_links: List[str] = []
    npc_links: List[str] = []
    for selection in selections or []:
        if not selection or selection == "skip":
            continue
        if selection.startswith("party:new:"):
            party_links.append(selection)
        elif selection.startswith("npc:new:"):
            npc_links.append(f"new:{selection.split(':', 2)[2]}")
    return party_links, npc_links


def split_party_and_npc_selections(
    party_selections: Optional[List[str]],
) -> Tuple[List[str], List[str]]:
    party_links: List[str] = []
    for selection in party_selections or []:
        if not selection or selection == "skip":
            continue
        if selection.startswith("party:"):
            party_links.append(selection)
    return party_links, []


def resolve_party_members_from_selections(
    db: Session,
    campaign_id: int,
    selections: Optional[List[str]],
) -> List[PlayerCharacterNote]:
    linked: List[PlayerCharacterNote] = []
    seen: set[int] = set()
    for selection in selections or []:
        if selection.startswith("party:existing:"):
            try:
                pc_id = int(selection.split(":", 2)[2])
            except ValueError:
                continue
            pc = db.get(PlayerCharacterNote, pc_id)
            if pc and pc.campaign_id == campaign_id and pc.id not in seen:
                linked.append(pc)
                seen.add(pc.id)
        elif selection.startswith("party:new:"):
            name = selection.split(":", 2)[2].strip()
            if not name:
                continue
            pc = create_pc_if_missing(db, campaign_id, name)
            if pc.id not in seen:
                linked.append(pc)
                seen.add(pc.id)
    return linked


def apply_party_member_links(
    db: Session,
    campaign_id: int,
    session_id: int,
    selections: Optional[List[str]],
) -> None:
    for pc in resolve_party_members_from_selections(db, campaign_id, selections):
        db.add(SessionPartyMemberLink(session_id=session_id, pc_note_id=pc.id))


def apply_ingest_session_content(
    db: Session,
    campaign_id: int,
    session: SessionModel,
    *,
    raw_notes: str,
    prep_parts: List[str],
    party_selections: Optional[List[str]],
    npc_selections: Optional[List[str]],
    location_selections: Optional[List[str]],
    faction_selections: Optional[List[str]],
    item_selections: Optional[List[str]],
    creature_selections: Optional[List[str]],
    thread_selections: Optional[List[str]],
) -> None:
    session.notes = raw_notes
    if prep_parts:
        session.next_session_prep = "\n\n".join(prep_parts)

    session.party_members = resolve_party_members_from_selections(db, campaign_id, party_selections)
    session_npcs = parse_entity_links(db, campaign_id, npc_selections, NPC, "name")
    session_locations = parse_entity_links(db, campaign_id, location_selections, Location, "name")
    session_factions = parse_entity_links(db, campaign_id, faction_selections, Faction, "name")
    session_items = parse_entity_links(db, campaign_id, item_selections, Item, "name")
    session_creatures = parse_entity_links(db, campaign_id, creature_selections, Creature, "name")
    session_threads = parse_entity_links(db, campaign_id, thread_selections, PlotThread, "title")

    session.npcs = session_npcs
    session.locations = session_locations
    session.factions = session_factions
    session.items = session_items
    session.creatures = session_creatures
    session.plot_threads = session_threads
    db.add(session)

    update_npc_last_seen_sessions(db, session_npcs, session.id)
    update_creature_last_seen_sessions(db, session_creatures, session.id)


def _find_by_name(db: Session, campaign_id: int, model, name_field: str, name: str):
    target = name.strip()
    if not target:
        return None
    for obj in db.exec(select(model).where(model.campaign_id == campaign_id)).all():
        label = getattr(obj, name_field, "")
        if label and label.strip().lower() == target.lower():
            return obj
    return None


def _append_link(db: Session, link_model, left_field: str, left_id: int, right_field: str, right_id: int) -> bool:
    existing = db.exec(
        select(link_model).where(
            getattr(link_model, left_field) == left_id,
            getattr(link_model, right_field) == right_id,
        )
    ).first()
    if not existing:
        db.add(link_model(**{left_field: left_id, right_field: right_id}))
        return True
    return False


def apply_approved_entity_relationships(
    db: Session,
    campaign_id: int,
    selections: Optional[List[str]],
    *,
    session_id: Optional[int] = None,
) -> None:
    handlers = {
        "npc_faction": (NPC, "name", Faction, "name", NPCFactionLink, "npc_id", "faction_id"),
        "pc_faction": (PlayerCharacterNote, "character_name", Faction, "name", PCFactionLink, "pc_note_id", "faction_id"),
        "npc_location": (NPC, "name", Location, "name", NPCLocationLink, "npc_id", "location_id"),
        "npc_thread": (NPC, "name", PlotThread, "title", NPCPlotThreadLink, "npc_id", "plot_thread_id"),
        "item_npc": (Item, "name", NPC, "name", ItemNPCLink, "item_id", "npc_id"),
        "item_location": (Item, "name", Location, "name", ItemLocationLink, "item_id", "location_id"),
        "item_thread": (Item, "name", PlotThread, "title", ItemPlotThreadLink, "item_id", "plot_thread_id"),
        "creature_location": (Creature, "name", Location, "name", CreatureLocationLink, "creature_id", "location_id"),
        "creature_thread": (Creature, "name", PlotThread, "title", CreaturePlotThreadLink, "creature_id", "plot_thread_id"),
        "location_thread": (
            Location,
            "name",
            PlotThread,
            "title",
            LocationPlotThreadLink,
            "location_id",
            "plot_thread_id",
        ),
    }

    for selection in selections or []:
        if not selection:
            continue
        try:
            rel_type, from_name, to_name = selection.split("|", 2)
        except ValueError:
            continue

        legacy_map = {
            "faction": "npc_faction",
            "location": "npc_location",
            "thread": "npc_thread",
            "plot_thread": "npc_thread",
        }
        rel_type = legacy_map.get(rel_type, rel_type)

        handler = handlers.get(rel_type)
        if not handler:
            continue

        left_model, left_field, right_model, right_field, link_model, link_left, link_right = handler
        left = _find_by_name(db, campaign_id, left_model, left_field, from_name)
        right = _find_by_name(db, campaign_id, right_model, right_field, to_name)
        if left and right:
            created = _append_link(db, link_model, link_left, left.id, link_right, right.id)
            if created:
                from app.services.relationship_history import (
                    RELATIONSHIP_TYPE_KINDS,
                    log_relationship_event,
                )

                kinds = RELATIONSHIP_TYPE_KINDS.get(rel_type)
                if kinds:
                    owner_kind, related_kind = kinds
                    log_relationship_event(
                        db,
                        campaign_id,
                        owner_kind,
                        left.id,
                        related_kind,
                        right.id,
                        "linked",
                        session_id=session_id,
                    )


def apply_approved_npc_relationships(
    db: Session,
    campaign_id: int,
    selections: Optional[List[str]],
) -> None:
    apply_approved_entity_relationships(db, campaign_id, selections)


def update_npc_last_seen_sessions(db: Session, npcs, session_id: int) -> None:
    for npc in npcs:
        npc.last_seen_session_id = session_id
        db.add(npc)


def update_creature_last_seen_sessions(db: Session, creatures, session_id: int) -> None:
    for creature in creatures:
        creature.last_seen_session_id = session_id
        db.add(creature)


def get_known_party_names(db: Session, campaign_id: int) -> List[str]:
    pcs = db.exec(select(PlayerCharacterNote).where(PlayerCharacterNote.campaign_id == campaign_id)).all()
    return [pc.character_name for pc in pcs if pc.character_name.strip()]
