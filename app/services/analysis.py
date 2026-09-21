import json
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from app.services.llm_json import (
    extract_balanced_brace_object,
    extract_json_value_for_key,
    parse_llm_json,
    parse_llm_json_lenient,
    parse_python_literal_dict,
    strip_markdown_fences,
)
from app.utils.time import utc_now

logger = logging.getLogger(__name__)

SECTION_HEADER_MAP = {
    "PLAYER RECAP": "player_recap",
    "GM RECAP": "gm_recap",
    "ANALYSIS": "analysis",
    "NEXT SESSION PREP": "next_session_prep",
    "NEXT_SESSION_PREP": "next_session_prep",
    "NPC UPDATES": "npc_updates",
    "PLOT THREAD UPDATES": "plot_thread_updates",
}

MARKDOWN_HEADING_MAP = {
    "player recap": "player_recap",
    "player-facing recap": "player_recap",
    "player facing recap": "player_recap",
    "gm recap": "gm_recap",
    "private gm recap": "gm_recap",
    "private recap": "gm_recap",
    "analysis": "analysis",
    "next session prep": "next_session_prep",
    "next_session_prep": "next_session_prep",
    "npc updates": "npc_updates",
    "plot thread updates": "plot_thread_updates",
}

CANONICAL_FIELD_KEYS = {
    "player_recap",
    "gm_recap",
    "analysis",
    "next_session_prep",
    "npc_updates",
    "plot_thread_updates",
}

PREP_SECTION_ORDER = (
    "Opening Scene",
    "Likely Player Actions",
    "NPC Agendas",
    "Faction Moves",
    "Encounter Options",
    "Clues to Reveal",
    "Complications",
    "Cliffhanger Options",
    "GM Notes",
)

SECTION_MARKER_PATTERN = re.compile(r"^===\s*.+?\s*===$", re.MULTILINE | re.IGNORECASE)
SECTION_HEADER_PATTERN = re.compile(r"^===\s*(.+?)\s*===$", re.MULTILINE | re.IGNORECASE)
MARKDOWN_HEADING_PATTERN = re.compile(r"^#{1,3}\s+(.+?)\s*$", re.MULTILINE)
LABELED_SECTION_PATTERN = re.compile(
    r"^(Player Recap|GM Recap|Analysis|NPC Updates|Plot Thread Updates|Next Session Prep)\s*:?\s*$",
    re.MULTILINE | re.IGNORECASE,
)

ANALYSIS_JSON_KEYS = (
    "PLAYER RECAP",
    "Player Recap",
    "player_recap",
    "GM RECAP",
    "GM Recap",
    "gm_recap",
    "ANALYSIS",
    "Analysis",
    "analysis",
    "NPC UPDATES",
    "Npc Updates",
    "npc_updates",
    "PLOT THREAD UPDATES",
    "Plot Thread Updates",
    "plot_thread_updates",
    "NEXT SESSION PREP",
    "NEXT_SESSION_PREP",
    "next_session_prep",
)


def _looks_like_invalid_prep_content(value: str) -> bool:
    cleaned = (value or "").strip()
    if not cleaned:
        return True
    if len(cleaned) <= 2 and cleaned[0] in "{[})":
        return True
    if re.fullmatch(r"[\{\}\[\]\s,]+", cleaned):
        return True
    if cleaned.startswith(("{", "[")) and not cleaned.endswith(("}", "]")):
        return True
    if cleaned.startswith(("{", "[")):
        for loader in (json.loads, parse_python_literal_dict):
            try:
                loader(cleaned)
                return True
            except (json.JSONDecodeError, ValueError, SyntaxError, TypeError):
                continue
        return True
    return False


def _looks_like_prep_blob(value: str, raw: str) -> bool:
    cleaned = (value or "").strip()
    if not cleaned:
        return False
    source = (raw or "").strip()
    if source and cleaned == source:
        return True
    lowered = cleaned.lower()
    if cleaned.startswith("{") and cleaned.endswith("}") and (
        '"player_recap"' in lowered or '"gm_recap"' in lowered or '"analysis"' in lowered
    ):
        return True
    response_markers = 0
    for match in SECTION_HEADER_PATTERN.finditer(cleaned):
        field = _canonical_field_key(match.group(1).strip())
        if field in {"player_recap", "gm_recap", "analysis", "npc_updates", "plot_thread_updates"}:
            response_markers += 1
    return response_markers >= 2


def _looks_like_unparsed_blob(value: str, raw: str) -> bool:
    cleaned = (value or "").strip()
    if not cleaned:
        return False
    source = (raw or "").strip()
    if source and cleaned == source:
        return True
    if source and len(source) > 100 and len(cleaned) > len(source) and source in cleaned:
        return True
    marker_hits = sum(1 for match in SECTION_MARKER_PATTERN.finditer(cleaned))
    if marker_hits >= 2:
        return True
    if cleaned.startswith("{") and cleaned.endswith("}"):
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            try:
                parsed = parse_python_literal_dict(cleaned)
            except (ValueError, SyntaxError, TypeError):
                return False
        if isinstance(parsed, dict):
            canonical_hits = sum(1 for key in parsed if _canonical_field_key(str(key)))
            if canonical_hits >= 2:
                return True
            return False
    return False


def _clean_field_value(value: str, raw: str, field: Optional[str] = None) -> str:
    text = _normalize_section_content(value)
    if not text:
        return ""
    if text.startswith(("{", "[")):
        markdown = _field_value_to_markdown(text, field or "")
        if markdown:
            text = markdown
    if field == "next_session_prep":
        if _looks_like_prep_blob(text, raw):
            return ""
        if _looks_like_invalid_prep_content(text):
            return ""
        return text
    if _looks_like_unparsed_blob(text, raw):
        return ""
    return text


def _sanitize_parsed_fields(parsed: Dict[str, str], raw: str) -> Dict[str, str]:
    sanitized: Dict[str, str] = {}
    for field, value in parsed.items():
        cleaned = _clean_field_value(value, raw, field=field)
        if cleaned:
            sanitized[field] = cleaned
    return sanitized


def _normalize_prep_key(key: str) -> str:
    return key.strip().lower().replace("_", " ").replace("-", " ")


def _format_next_session_prep(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") or text.startswith("["):
            for loader in (json.loads, parse_python_literal_dict):
                try:
                    return _format_next_session_prep(loader(text))
                except (json.JSONDecodeError, ValueError, SyntaxError, TypeError):
                    continue
            return ""
        return _normalize_section_content(value)
    if isinstance(value, dict):
        parts: List[str] = []
        used_keys: Set[str] = set()
        lookup = {_normalize_prep_key(str(key)): (str(key), val) for key, val in value.items()}
        for section in PREP_SECTION_ORDER:
            match = lookup.get(_normalize_prep_key(section))
            if not match:
                continue
            original_key, section_value = match
            used_keys.add(original_key)
            text = (
                _value_to_text(section_value)
                if isinstance(section_value, (dict, list))
                else str(section_value).strip()
            )
            if text and text.lower() not in {"(none)", "none", "n/a"}:
                parts.append(f"{section}:\n{text}")
        for key, section_value in value.items():
            if key in used_keys:
                continue
            text = (
                _value_to_text(section_value)
                if isinstance(section_value, (dict, list))
                else str(section_value).strip()
            )
            if not text or text.lower() in {"(none)", "none", "n/a"}:
                continue
            title = str(key).replace("_", " ").strip().title()
            parts.append(f"{title}:\n{text}")
        return "\n\n".join(parts).strip()
    return _value_to_text(value)


def _prep_detected_in_raw(raw: str) -> bool:
    if not raw or not raw.strip():
        return False
    lowered = raw.lower()
    if any(token in lowered for token in ("next_session_prep", "next session prep")):
        return True
    if SECTION_HEADER_PATTERN.search(raw):
        for match in SECTION_HEADER_PATTERN.finditer(raw):
            if _canonical_field_key(match.group(1).strip()) == "next_session_prep":
                return True
    if MARKDOWN_HEADING_PATTERN.search(raw):
        for match in MARKDOWN_HEADING_PATTERN.finditer(raw):
            heading = match.group(1).strip().lower()
            if heading in MARKDOWN_HEADING_MAP and MARKDOWN_HEADING_MAP[heading] == "next_session_prep":
                return True
            if _canonical_field_key(match.group(1).strip()) == "next_session_prep":
                return True
    return False


def _prep_detected_in_parsed(parsed: Optional[Dict[str, str]]) -> bool:
    if not parsed:
        return False
    return bool((parsed.get("next_session_prep") or "").strip())


def summarize_notes(notes: str) -> str:
    if not notes:
        return ""

    normalized = notes.strip().replace("\r\n", "\n")
    lines = [line.strip() for line in normalized.split("\n") if line.strip()]
    if not lines:
        return ""
    if len(lines) <= 3:
        return " ".join(lines)
    return " ".join(lines[:3])


def extract_entities(notes: str, npcs, locations, factions, items, threads, pc_notes) -> Dict[str, List[str]]:
    text = notes.lower()

    def scan(entries, attrs):
        found = []
        for entry in entries:
            for attr in attrs:
                value = getattr(entry, attr, None)
                if not value:
                    continue
                lowered = value.lower()
                if re.search(rf"\b{re.escape(lowered)}\b", text):
                    found.append(value)
                    break
        return found

    return {
        "NPCs": scan(npcs, ["name"]),
        "Locations": scan(locations, ["name"]),
        "Factions": scan(factions, ["name"]),
        "Items": scan(items, ["name"]),
        "Plot Threads": scan(threads, ["title"]),
        "PC Notes": scan(
            pc_notes,
            [
                "character_name",
                "character_archetype",
                "description",
                "signature_gear",
                "key_ties_history",
                "campaign_role_plot_notes",
                "notes",
            ],
        ),
    }


def generate_session_prep(notes: str, entities: Dict[str, List[str]], threads) -> Dict[str, str]:
    prep = {
        "recap": summarize_notes(notes) or "Review the latest session notes and update the party's status.",
        "likely_scenes": "Outline a few scenes based on the last session's events.",
        "secrets_clues": "Consider what clues the party discovered and what secrets remain.",
        "encounters": "Prepare one or two encounters that build on recent conflict or tensions.",
        "npc_reminders": "Keep next session NPC motivations and changes in mind.",
        "sideways_options": "Prepare a couple of alternate directions if the party deviates.",
        "unresolved_hooks": "Follow up on unresolved plot threads and promises.",
    }

    named_npcs = entities.get("NPCs", [])
    if named_npcs:
        prep["npc_reminders"] = "Focus on: " + ", ".join(named_npcs)

    if entities.get("Plot Threads"):
        prep["unresolved_hooks"] = "Unresolved hooks: " + ", ".join(entities.get("Plot Threads"))
    elif threads:
        prep["unresolved_hooks"] = "Review active plot threads for your campaign."

    if entities.get("Locations"):
        prep["likely_scenes"] = "Likely scenes include locations such as " + ", ".join(entities.get("Locations"))

    if entities.get("Items") or entities.get("PC Notes"):
        clues = []
        if entities.get("Items"):
            clues.append("items: " + ", ".join(entities.get("Items")))
        if entities.get("PC Notes"):
            clues.append("PC story hooks: " + ", ".join(entities.get("PC Notes")))
        prep["secrets_clues"] = "Watch for " + ", ".join(clues)

    if notes:
        summary = summarize_notes(notes)
        prep["encounters"] = "Based on the recent events, one encounter could involve " + (
            summary if len(summary) < 120 else summary[:120] + "..."
        )

    prep_text = "\n\n".join(f"**{key.replace('_', ' ').title()}:** {value}" for key, value in prep.items())
    prep["next_session_prep"] = prep_text
    return prep


def _normalize_section_content(content: str) -> str:
    text = (content or "").strip()
    if text.lower() in {"(none)", "none", "n/a"}:
        return ""
    return text


def _canonical_field_key(key: str) -> Optional[str]:
    if not key:
        return None
    stripped = key.strip()
    header_key = re.sub(r"[\s_-]+", " ", stripped).upper()
    if header_key in SECTION_HEADER_MAP:
        return SECTION_HEADER_MAP[header_key]

    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", stripped)
    normalized = spaced.strip().lower().replace("_", " ").replace("-", " ")
    normalized = re.sub(r"\s+", " ", normalized)
    if normalized in MARKDOWN_HEADING_MAP:
        return MARKDOWN_HEADING_MAP[normalized]

    snake = normalized.replace(" ", "_")
    if snake in CANONICAL_FIELD_KEYS:
        return snake
    return None


def _coerce_structured_value(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") or text.startswith("["):
            for loader in (json.loads, parse_python_literal_dict):
                try:
                    loaded = loader(text)
                    return _coerce_structured_value(loaded)
                except (json.JSONDecodeError, ValueError, SyntaxError, TypeError):
                    continue
    return value


def _field_value_to_markdown(value: Any, field: str) -> str:
    coerced = _coerce_structured_value(value)
    if field == "next_session_prep":
        return _format_next_session_prep(coerced)
    return _value_to_text(coerced)


def _first_mapping_text(mapping: Dict[str, Any], *candidates: str) -> str:
    for candidate in candidates:
        for key, value in mapping.items():
            if candidate in key and value is not None:
                text = str(value).strip()
                if text and text.lower() not in {"(none)", "none", "n/a"}:
                    return text
    return ""


def _format_structured_item(item: Dict[str, Any]) -> str:
    normalized = {str(key).strip().lower(): value for key, value in item.items()}
    title = _first_mapping_text(normalized, "thread", "title", "name", "npc")
    status = _first_mapping_text(normalized, "status")
    notes = _first_mapping_text(
        normalized,
        "notes",
        "note",
        "update",
        "updates",
        "details",
        "description",
        "change",
        "summary",
    )
    if title:
        line = title
        if status:
            line += f" ({status})"
        if notes:
            line += f": {notes}"
        return line

    parts: List[str] = []
    for key, value in item.items():
        text = _value_to_text(value) if isinstance(value, (dict, list)) else str(value).strip()
        if not text or text.lower() in {"(none)", "none", "n/a"}:
            continue
        label = str(key).replace("_", " ").strip().title()
        parts.append(f"{label}: {text}" if len(item) > 1 else text)
    return "; ".join(parts)


def _value_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        items: List[str] = []
        for item in value:
            if isinstance(item, dict):
                text = _format_structured_item(item)
            elif isinstance(item, (dict, list)):
                text = _value_to_text(item)
            else:
                text = str(item).strip()
            if text and text.lower() not in {"(none)", "none", "n/a"}:
                items.append(text)
        return "\n".join(f"- {item}" for item in items) if items else ""
    if isinstance(value, dict):
        parts: List[str] = []
        for nested_key, nested_value in value.items():
            text = _value_to_text(nested_value)
            if not text:
                continue
            title = str(nested_key).replace("_", " ").title()
            parts.append(f"{title}:\n{text}")
        return "\n\n".join(parts).strip()
    text = str(value).strip()
    if text.lower() in {"(none)", "none", "n/a"}:
        return ""
    return text


def _normalize_parsed_fields(data: Dict[str, Any]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for key, value in data.items():
        field = _canonical_field_key(str(key))
        if not field:
            continue
        text = _field_value_to_markdown(value, field)
        if text:
            result[field] = text
    return result


def _finalize_parsed_dict(raw_dict: Dict[str, Any], raw: str) -> Dict[str, str]:
    normalized = _normalize_parsed_fields(raw_dict)
    logger.info("_finalize_parsed_dict normalized.keys()=%s", list(normalized.keys()))
    sanitized = _sanitize_parsed_fields(normalized, raw)
    logger.info("_finalize_parsed_dict sanitized.keys()=%s", list(sanitized.keys()))
    if sanitized:
        return sanitized
    if normalized:
        recovered = {
            field: text
            for field, text in normalized.items()
            if _normalize_section_content(text)
        }
        if recovered:
            logger.info("_finalize_parsed_dict recovered.keys()=%s", list(recovered.keys()))
            return recovered
    prep_text = normalized.get("next_session_prep", "")
    if prep_text:
        cleaned_prep = _clean_field_value(prep_text, raw, field="next_session_prep")
        if cleaned_prep:
            return {"next_session_prep": cleaned_prep}
    return sanitized


def _extract_json_value_for_key(raw: str, key: str) -> Any:
    pattern = re.compile(
        rf'["\']?{re.escape(key)}["\']?\s*:\s*',
        re.IGNORECASE,
    )
    match = pattern.search(raw)
    if not match:
        return None
    snippet = raw[match.end() :].lstrip()
    if not snippet:
        return None
    if snippet[0] in "{[":
        extracted = extract_balanced_brace_object(snippet)
        if extracted:
            for loader in (json.loads, parse_python_literal_dict):
                try:
                    return loader(extracted)
                except (json.JSONDecodeError, ValueError, SyntaxError, TypeError):
                    continue
        return None
    if snippet[0] == '"':
        try:
            value, _ = json.JSONDecoder().raw_decode(snippet)
            return value
        except json.JSONDecodeError:
            pass
    line = snippet.split("\n", 1)[0].strip().rstrip(",")
    if len(line) >= 2 and line[0] == '"' and line[-1] == '"':
        return line[1:-1]
    return line or None


PREP_JSON_KEYS = ("NEXT_SESSION_PREP", "Next Session Prep", "next_session_prep", "NEXT SESSION PREP")


def _extract_prep_only(raw: str) -> Optional[Dict[str, str]]:
    for key in PREP_JSON_KEYS:
        value = _extract_json_value_for_key(raw, key)
        if value is None:
            continue
        text = _format_next_session_prep(value)
        cleaned = _clean_field_value(text, raw, field="next_session_prep")
        if cleaned:
            return {"next_session_prep": cleaned}

    sections = _parse_section_headers(raw)
    if sections and sections.get("next_session_prep"):
        cleaned = _clean_field_value(sections["next_session_prep"], raw, field="next_session_prep")
        if cleaned:
            return {"next_session_prep": cleaned}

    markdown = _parse_markdown_headings(raw)
    if markdown and markdown.get("next_session_prep"):
        cleaned = _clean_field_value(markdown["next_session_prep"], raw, field="next_session_prep")
        if cleaned:
            return {"next_session_prep": cleaned}
    return None


def _parse_labeled_sections(raw: str) -> Optional[Dict[str, str]]:
    normalized = raw.replace("\r\n", "\n").strip()
    matches = list(LABELED_SECTION_PATTERN.finditer(normalized))
    if not matches:
        return None

    sections: Dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
        content = _normalize_section_content(normalized[start:end])
        key = _canonical_field_key(match.group(1).strip())
        if not key:
            continue
        sections[key] = content
    return sections if sections else None


def _extract_structured_fields_only(raw: str, keys: Tuple[str, ...]) -> Optional[Dict[str, str]]:
    partial_data: Dict[str, Any] = {}
    seen_fields: Set[str] = set()
    for key in keys:
        field = _canonical_field_key(key)
        if not field or field in seen_fields:
            continue
        value = extract_json_value_for_key(raw, key)
        if value is not None:
            partial_data[field] = value
            seen_fields.add(field)
    if not partial_data:
        return None
    normalized = _normalize_parsed_fields({field: value for field, value in partial_data.items()})
    sanitized = _sanitize_parsed_fields(normalized, raw)
    if sanitized:
        return sanitized
    if normalized:
        return {
            field: text
            for field, text in normalized.items()
            if _normalize_section_content(text)
        }
    return None


def _parse_section_headers(raw: str) -> Optional[Dict[str, str]]:
    normalized = strip_markdown_fences(raw.replace("\r\n", "\n")).strip()
    matches = list(SECTION_HEADER_PATTERN.finditer(normalized))
    if not matches:
        return None

    sections: Dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
        content = _normalize_section_content(normalized[start:end])
        key = _canonical_field_key(match.group(1).strip())
        if not key:
            continue
        sections[key] = content
    return sections if sections else None


def _parse_markdown_headings(raw: str) -> Optional[Dict[str, str]]:
    normalized = raw.replace("\r\n", "\n").strip()
    matches = list(MARKDOWN_HEADING_PATTERN.finditer(normalized))
    if not matches:
        return None

    sections: Dict[str, str] = {}
    for index, match in enumerate(matches):
        heading = match.group(1).strip().lower()
        field = MARKDOWN_HEADING_MAP.get(heading)
        if not field:
            field = _canonical_field_key(heading)
        if not field:
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
        content = _normalize_section_content(normalized[start:end])
        sections[field] = content
    return sections if sections else None


def _empty_parse_diagnostics() -> Dict[str, Any]:
    return {
        "raw_keys": [],
        "normalized_keys": [],
        "finalized_keys": [],
    }


def parse_ai_analysis(
    raw: str,
) -> Tuple[Optional[Dict[str, str]], Optional[str], Optional[str], Dict[str, Any]]:
    diagnostics = _empty_parse_diagnostics()
    if not raw or not raw.strip():
        return None, "Empty LLM response", None, diagnostics

    errors: List[str] = []

    try:
        raw_dict, json_warning = parse_llm_json_lenient(raw, fallback_keys=list(ANALYSIS_JSON_KEYS))
        diagnostics["raw_keys"] = [str(key) for key in raw_dict.keys()]
        logger.info("parse_ai_analysis raw_dict.keys()=%s", diagnostics["raw_keys"])
        if json_warning:
            logger.warning("parse_ai_analysis partial JSON: %s", json_warning)
        normalized = _normalize_parsed_fields(raw_dict)
        diagnostics["normalized_keys"] = list(normalized.keys())
        logger.info("parse_ai_analysis normalized.keys()=%s", diagnostics["normalized_keys"])
        finalized = _finalize_parsed_dict(raw_dict, raw)
        diagnostics["finalized_keys"] = list(finalized.keys()) if finalized else []
        logger.info("parse_ai_analysis finalized.keys()=%s", diagnostics["finalized_keys"])
        if finalized:
            return finalized, None, "json", diagnostics
        prep_only = _extract_prep_only(raw)
        if prep_only:
            diagnostics["finalized_keys"] = list(prep_only.keys())
            return prep_only, None, "json", diagnostics
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        errors.append(f"json: {exc}")

    try:
        raw_dict = parse_python_literal_dict(raw)
        diagnostics["raw_keys"] = [str(key) for key in raw_dict.keys()]
        logger.info("parse_ai_analysis python_dict.keys()=%s", diagnostics["raw_keys"])
        normalized = _normalize_parsed_fields(raw_dict)
        diagnostics["normalized_keys"] = list(normalized.keys())
        logger.info("parse_ai_analysis normalized.keys()=%s", diagnostics["normalized_keys"])
        finalized = _finalize_parsed_dict(raw_dict, raw)
        diagnostics["finalized_keys"] = list(finalized.keys()) if finalized else []
        if finalized:
            return finalized, None, "python_dict", diagnostics
    except (ValueError, SyntaxError, TypeError) as exc:
        errors.append(f"python_dict: {exc}")

    sections = _parse_section_headers(raw)
    if sections is not None:
        normalized = _sanitize_parsed_fields(sections, raw)
        if normalized:
            diagnostics["normalized_keys"] = list(normalized.keys())
            diagnostics["finalized_keys"] = list(normalized.keys())
            return normalized, None, "sections", diagnostics
    errors.append("sections: no section headers found")

    labeled_sections = _parse_labeled_sections(raw)
    if labeled_sections is not None:
        normalized = _sanitize_parsed_fields(labeled_sections, raw)
        if normalized:
            diagnostics["normalized_keys"] = list(normalized.keys())
            diagnostics["finalized_keys"] = list(normalized.keys())
            return normalized, None, "sections", diagnostics
    errors.append("labeled sections: no labeled headers found")

    markdown_sections = _parse_markdown_headings(raw)
    if markdown_sections is not None:
        normalized = _sanitize_parsed_fields(markdown_sections, raw)
        if normalized:
            diagnostics["normalized_keys"] = list(normalized.keys())
            diagnostics["finalized_keys"] = list(normalized.keys())
            return normalized, None, "markdown", diagnostics

    errors.append("markdown: no markdown headings found")

    prep_only = _extract_prep_only(raw)
    if prep_only:
        diagnostics["finalized_keys"] = list(prep_only.keys())
        return prep_only, None, "json", diagnostics

    structured = _extract_structured_fields_only(raw, ANALYSIS_JSON_KEYS)
    if structured:
        diagnostics["normalized_keys"] = list(structured.keys())
        diagnostics["finalized_keys"] = list(structured.keys())
        return structured, None, "json", diagnostics

    return None, "; ".join(errors), None, diagnostics


def parse_ai_analysis_sections(raw: str) -> Tuple[Optional[Dict[str, str]], Optional[str]]:
    parsed, error, _format, _diagnostics = parse_ai_analysis(raw)
    return parsed, error


# Backward-compatible alias for callers/tests.
parse_ai_analysis_json = parse_ai_analysis_sections


def compose_analysis_display(sections: Dict[str, str]) -> str:
    parts: List[str] = []
    if sections.get("analysis"):
        parts.append(sections["analysis"])
    if sections.get("npc_updates"):
        parts.append(f"NPC Updates:\n{sections['npc_updates']}")
    if sections.get("plot_thread_updates"):
        parts.append(f"Plot Thread Updates:\n{sections['plot_thread_updates']}")
    return "\n\n".join(parts).strip()


def _prep_section_format() -> str:
    return (
        "Structure the NEXT_SESSION_PREP section with these headings and actionable content:\n\n"
        "Opening Scene:\n"
        "Where the session starts and what the players encounter immediately.\n\n"
        "Likely Player Actions:\n"
        "What the party is likely to do next based on last session outcomes.\n\n"
        "NPC Agendas:\n"
        "What key NPCs want and will push toward this session.\n\n"
        "Faction Moves:\n"
        "Off-screen and on-screen moves by factions.\n\n"
        "Encounter Options:\n"
        "2-3 concrete encounters or scenes the GM can run.\n\n"
        "Clues to Reveal:\n"
        "Specific clues or information the GM can drop in.\n\n"
        "Complications:\n"
        "Twists, timers, or pressures if the party stalls or succeeds easily.\n\n"
        "Cliffhanger Options:\n"
        "Strong end-of-session hooks.\n\n"
        "GM Notes:\n"
        "Practical reminders, pacing notes, or table management tips."
    )


def _prep_generation_rules() -> str:
    return (
        "Next session prep rules:\n"
        "- Write actionable GM run material, not a recap.\n"
        "- Do not repeat the session notes verbatim.\n"
        "- Do not summarize the previous session except brief context when needed.\n"
        "- Focus on what to run next: scenes, NPC moves, hooks, and complications."
    )


def _future_prep_only_output_format() -> str:
    return (
        "Return plain text using exactly these section headers, in this order:\n\n"
        "=== PLAYER RECAP ===\n(none)\n\n"
        "=== GM RECAP ===\n(none)\n\n"
        "=== ANALYSIS ===\n(none)\n\n"
        "=== NEXT_SESSION_PREP ===\n"
        "<actionable prep here>\n\n"
        "=== NPC UPDATES ===\n(none)\n\n"
        "=== PLOT THREAD UPDATES ===\n(none)\n\n"
        "Put prep content directly below === NEXT_SESSION_PREP ===. Use bullet points where helpful. "
        "Use section headers only. Do NOT return JSON."
    )


def _section_output_format() -> str:
    return (
        "Return plain text using exactly these section headers, in this order:\n\n"
        "=== PLAYER RECAP ===\n"
        "...\n\n"
        "=== GM RECAP ===\n"
        "...\n\n"
        "=== ANALYSIS ===\n"
        "...\n\n"
        "=== NEXT_SESSION_PREP ===\n"
        "...\n\n"
        "=== NPC UPDATES ===\n"
        "...\n\n"
        "=== PLOT THREAD UPDATES ===\n"
        "...\n\n"
        "Put content directly below each header. Use bullet points where helpful. "
        "Section headers are preferred, but JSON or markdown headings are also accepted.\n"
        "Use exactly the === HEADER === format shown above — do not omit the equals signs."
    )


def _synthesis_rules() -> str:
    return (
        "Important rules:\n"
        "- Do not repeat the session notes verbatim.\n"
        "- Summarize and synthesize.\n"
        "- Player recap should be spoiler-safe for players.\n"
        "- GM recap may include secrets and hidden context.\n"
        "- Analysis should focus on what happened, player behavior, and GM opportunities.\n"
        "- Next session prep must be actionable run material, not a recap."
    )


def build_analyze_session_prompt(campaign, session_title: str, session_date: str, notes: str) -> str:
    return (
        f"You are an AI game master assistant analyzing one tabletop RPG session.\n\n"
        f"Campaign: {campaign.name}\n"
        f"System: {campaign.system or 'Unknown'}\n"
        f"Description: {campaign.description or 'No description provided.'}\n\n"
        f"Session: {session_title}\n"
        f"Date: {session_date or 'Unknown'}\n\n"
        f"Session Notes:\n{notes}\n\n"
        "Analyze this session only. Populate PLAYER RECAP, GM RECAP, ANALYSIS, "
        "NPC UPDATES, and PLOT THREAD UPDATES. Leave NEXT_SESSION_PREP empty or write (none).\n\n"
        f"{_synthesis_rules()}\n\n"
        f"{_section_output_format()}"
    )


def build_campaign_future_prep_prompt(
    campaign,
    sessions: List[Any],
    npcs: List[Any],
    locations: List[Any],
    factions: List[Any],
    threads: List[Any],
    target_session_title: str,
    target_session_date: str,
    target_session_notes: str,
) -> str:
    recent_sessions = sessions[-5:]
    session_summaries = []
    for session in recent_sessions:
        title = getattr(session, "title", "Untitled")
        date = getattr(session, "date", "") or "Unknown"
        recap = getattr(session, "recap", "") or summarize_notes(getattr(session, "notes", "") or "")
        session_summaries.append(f"- {title} ({date}): {recap or 'No recap yet.'}")

    npc_lines = [f"- {npc.name}: {npc.role or 'NPC'}" for npc in npcs[:20]]
    location_lines = [f"- {loc.name}" for loc in locations[:20]]
    faction_lines = [f"- {fac.name}" for fac in factions[:20]]
    thread_lines = [
        f"- {thread.title} ({thread.status or 'Active'}): {thread.details or ''}".strip()
        for thread in threads[:20]
    ]

    return (
        f"You are an AI game master assistant preparing the next session for a tabletop RPG campaign.\n\n"
        f"Campaign: {campaign.name}\n"
        f"System: {campaign.system or 'Unknown'}\n"
        f"Description: {campaign.description or 'No description provided.'}\n\n"
        f"Recent sessions:\n{chr(10).join(session_summaries) or '- No prior sessions.'}\n\n"
        f"NPCs:\n{chr(10).join(npc_lines) or '- None recorded.'}\n\n"
        f"Locations:\n{chr(10).join(location_lines) or '- None recorded.'}\n\n"
        f"Factions:\n{chr(10).join(faction_lines) or '- None recorded.'}\n\n"
        f"Plot threads:\n{chr(10).join(thread_lines) or '- None recorded.'}\n\n"
        f"Latest session to prep from:\n"
        f"Title: {target_session_title}\n"
        f"Date: {target_session_date or 'Unknown'}\n"
        f"Notes:\n{target_session_notes}\n\n"
        "Generate actionable next-session prep from the campaign context above. "
        "Only populate NEXT_SESSION_PREP. "
        "Leave PLAYER RECAP, GM RECAP, ANALYSIS, NPC UPDATES, and PLOT THREAD UPDATES empty or write (none).\n\n"
        f"{_prep_generation_rules()}\n\n"
        f"{_future_prep_only_output_format()}\n\n"
        f"{_prep_section_format()}"
    )


def looks_like_ai_blob(value: str, raw: str = "") -> bool:
    return _looks_like_unparsed_blob(value, raw)


def looks_like_invalid_prep(value: str) -> bool:
    return _looks_like_invalid_prep_content(value)


def parser_display_name(parse_format: Optional[str]) -> str:
    return {
        "json": "JSON",
        "python_dict": "JSON",
        "sections": "Section",
        "markdown": "Markdown",
    }.get(parse_format or "", "Fallback")


MAIN_AI_FIELDS = ("player_recap", "gm_recap", "analysis", "next_session_prep")

PARSE_MSG_FAILURE = "AI response could not be parsed."
PARSE_MSG_PARTIAL = "AI response partially parsed. Some optional sections were not found."
PARSE_MSG_PREP_MISSING = "No next-session prep section found."


def _requested_fields_for_context(context: str) -> Set[str]:
    if context == "review":
        return {"next_session_prep"}
    return {"player_recap", "gm_recap", "analysis"}


def build_ai_parse_message(
    result: Optional[Dict[str, Any]],
    *,
    context: str = "analyze",
    requested_fields: Optional[Set[str]] = None,
) -> Optional[str]:
    if not result:
        return None

    updated = set(result.get("updated_fields") or [])
    missing = set(result.get("missing_requested_fields") or [])
    requested = requested_fields or _requested_fields_for_context(context)

    if context == "review":
        if "next_session_prep" in updated:
            return None
        if result.get("prep_detected_in_raw"):
            return PARSE_MSG_PREP_MISSING
        return PARSE_MSG_FAILURE

    if not updated:
        return PARSE_MSG_FAILURE

    missing_requested = missing & requested
    if not missing_requested:
        return None

    if updated & requested:
        return PARSE_MSG_PARTIAL

    return PARSE_MSG_FAILURE


def save_ai_run_metadata(
    session_model,
    result: Dict[str, Any],
    *,
    provider: Optional[str],
    model: Optional[str],
    task_name: str,
    saved_to_session_id: Optional[int] = None,
) -> Dict[str, Any]:
    metadata = {
        "task": task_name,
        "provider": provider or "unknown",
        "model": model or "unknown",
        "generated_at": utc_now().isoformat(),
        "parser_used": result.get("parser_used") or "Fallback",
        "saved_to_session_id": saved_to_session_id or getattr(session_model, "id", None),
        "fields_updated": list(result.get("updated_fields") or []),
        "fields_missing": list(result.get("missing_requested_fields") or []),
        "raw_output_saved": bool(result.get("raw_saved_to") == "analysis_raw"),
        "raw_keys": list(result.get("raw_keys") or []),
        "normalized_keys": list(result.get("normalized_keys") or []),
        "finalized_keys": list(result.get("finalized_keys") or []),
    }
    session_model.ai_last_run_metadata = json.dumps(metadata)
    return metadata


def load_ai_run_metadata(session_model) -> Optional[Dict[str, Any]]:
    raw = getattr(session_model, "ai_last_run_metadata", None)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def clear_session_ai_fields(session_model) -> None:
    session_model.player_recap = None
    session_model.recap = None
    session_model.analysis = None
    session_model.analysis_raw = None
    session_model.next_session_prep = None
    session_model.next_session_prep_manually_edited = False
    session_model.ai_last_run_metadata = None


def _log_ai_field_result(
    *,
    task_name: str,
    session_id: Optional[int],
    parser_used: str,
    update_fields: Set[str],
    updated_fields: List[str],
    missing_requested_fields: List[str],
    parsed: bool,
    parse_error: Optional[str] = None,
) -> None:
    field_log = {
        field: (
            "updated"
            if field in updated_fields
            else ("missing" if field in missing_requested_fields else "not_requested")
        )
        for field in ("player_recap", "gm_recap", "analysis", "next_session_prep")
    }
    if parsed:
        logger.info(
            "AI task %s session_id=%s parser=%s updated_fields=%s field_status=%s",
            task_name,
            session_id,
            parser_used,
            updated_fields,
            field_log,
        )
    else:
        logger.warning(
            "AI task %s session_id=%s parser=%s parse_error=%s field_status=%s",
            task_name,
            session_id,
            parser_used,
            parse_error,
            field_log,
        )


def apply_parsed_ai_output(
    session_model,
    raw: str,
    *,
    update_fields: Set[str],
    task_name: str,
    session_id: Optional[int],
    save_raw_on_failure: bool = True,
) -> Dict[str, Any]:
    """Single AI write path for player_recap, gm_recap (recap), analysis, and next_session_prep."""
    parsed, error, parse_format, parse_diagnostics = parse_ai_analysis(raw)
    updated_fields: List[str] = []
    missing_requested_fields: List[str] = []
    prep_detected_in_raw = _prep_detected_in_raw(raw) or _prep_detected_in_parsed(parsed)
    prep_only = update_fields == {"next_session_prep"}

    if parsed is None:
        if save_raw_on_failure:
            session_model.analysis_raw = raw
        _log_ai_field_result(
            task_name=task_name,
            session_id=session_id,
            parser_used="Fallback",
            update_fields=update_fields,
            updated_fields=[],
            missing_requested_fields=list(update_fields),
            parsed=False,
            parse_error=error,
        )
        return {
            "json_parsed": False,
            "fields_extracted": False,
            "parse_error": error,
            "parse_format": None,
            "parser_used": "Fallback",
            "updated_fields": [],
            "missing_requested_fields": list(update_fields),
            "prep_detected_in_raw": prep_detected_in_raw,
            "raw_saved_to": "analysis_raw" if save_raw_on_failure else None,
            "raw_output": raw,
            **parse_diagnostics,
        }

    parser_used = parser_display_name(parse_format)

    if "player_recap" in update_fields:
        value = _clean_field_value(parsed.get("player_recap", ""), raw, field="player_recap")
        if value:
            session_model.player_recap = value
            updated_fields.append("player_recap")
        else:
            missing_requested_fields.append("player_recap")

    if "gm_recap" in update_fields:
        value = _clean_field_value(parsed.get("gm_recap", ""), raw, field="gm_recap")
        if value:
            session_model.recap = value
            updated_fields.append("gm_recap")
        else:
            missing_requested_fields.append("gm_recap")

    if "analysis" in update_fields:
        cleaned_parsed = {
            field: _clean_field_value(parsed.get(field, ""), raw, field=field)
            for field in ("analysis", "npc_updates", "plot_thread_updates")
        }
        value = compose_analysis_display(cleaned_parsed)
        if value:
            session_model.analysis = value
            updated_fields.append("analysis")
        else:
            missing_requested_fields.append("analysis")

    if "next_session_prep" in update_fields:
        value = _clean_field_value(parsed.get("next_session_prep", ""), raw, field="next_session_prep")
        if value:
            session_model.next_session_prep = value
            session_model.next_session_prep_manually_edited = False
            updated_fields.append("next_session_prep")
        else:
            missing_requested_fields.append("next_session_prep")

    requested_updated = [field for field in updated_fields if field in update_fields]
    fields_extracted = bool(requested_updated)
    if prep_only:
        fields_extracted = "next_session_prep" in updated_fields

    if fields_extracted:
        session_model.analysis_raw = None
        raw_saved_to = None
        raw_output = None
    elif save_raw_on_failure:
        session_model.analysis_raw = raw
        raw_saved_to = "analysis_raw"
        raw_output = raw
    else:
        raw_saved_to = None
        raw_output = raw if not fields_extracted else None

    _log_ai_field_result(
        task_name=task_name,
        session_id=session_id,
        parser_used=parser_used,
        update_fields=update_fields,
        updated_fields=updated_fields,
        missing_requested_fields=missing_requested_fields,
        parsed=bool(parsed),
    )
    return {
        "json_parsed": fields_extracted,
        "fields_extracted": fields_extracted,
        "parse_error": None if fields_extracted else (error or "No requested fields extracted"),
        "parse_format": parse_format,
        "parser_used": parser_used,
        "updated_fields": updated_fields,
        "missing_requested_fields": missing_requested_fields,
        "prep_detected_in_raw": prep_detected_in_raw,
        "raw_saved_to": raw_saved_to,
        "raw_output": raw_output,
        **parse_diagnostics,
    }


def apply_local_session_analysis_fallback(session_model, notes: str, entities: Dict[str, List[str]], threads) -> None:
    prep = generate_session_prep(notes, entities, threads)
    session_model.player_recap = prep.get("recap") or session_model.player_recap
    session_model.recap = summarize_notes(notes) or session_model.recap
    session_model.analysis = (
        "Player Choices:\n"
        f"- {summarize_notes(notes) or 'Review recent player decisions from the notes.'}\n\n"
        "GM Opportunities:\n"
        f"- {prep.get('npc_reminders', 'Watch for NPC follow-ups.')}\n\n"
        "Potential Complications:\n"
        f"- {prep.get('unresolved_hooks', 'Review unresolved hooks before next session.')}"
    )


def prep_overwrite_requires_confirmation(session_model) -> bool:
    return bool(
        getattr(session_model, "next_session_prep_manually_edited", False)
        and (session_model.next_session_prep or "").strip()
    )


def extract_markdown_section(text: str, headings: List[str]) -> str:
    if not text:
        return ""
    normalized = text.replace("\r\n", "\n")
    heading_pattern = "|".join(re.escape(heading) for heading in headings)
    pattern = re.compile(
        rf"^#{{1,3}}\s*({heading_pattern})\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    match = pattern.search(normalized)
    if not match:
        return ""
    start = match.end()
    next_heading = re.search(r"^#{1,3}\s+\S", normalized[start:], re.MULTILINE)
    end = start + next_heading.start() if next_heading else len(normalized)
    return normalized[start:end].strip()


def extract_player_recap(text: str) -> str:
    return extract_markdown_section(
        text,
        ["Player-Facing Recap", "Player Facing Recap", "Player Recap"],
    )
