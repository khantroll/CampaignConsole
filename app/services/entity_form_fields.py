"""Builders for shared entity edit form field configs."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.services.entity_field_choices import (
    LOCATION_CUSTOM,
    PLOT_THREAD_TYPE_CHOICES,
    PLOT_THREAD_TYPE_LABELS,
    PRESET_THREAD_TYPE_KEYS,
    THREAT_LEVEL_CHOICES,
    THREAT_LEVEL_LABELS,
    HABITAT_CHOICES,
    HABITAT_LABELS,
    PRESET_HABITAT_KEYS,
    PRESET_THREAT_KEYS,
    match_location_id_by_name,
    preset_form_values,
)
from app.services.world_state import (
    CREATURE_STATUS_CHOICES,
    CREATURE_STATUS_LABELS,
    FACTION_STATUS_CHOICES,
    FACTION_STATUS_LABELS,
    ITEM_STATUS_CHOICES,
    ITEM_STATUS_LABELS,
    LOCATION_STATUS_CHOICES,
    LOCATION_STATUS_LABELS,
    MYSTERY_STATUS_CHOICES,
    MYSTERY_STATUS_LABELS,
    NPC_WORLD_STATUS_CHOICES,
    NPC_WORLD_STATUS_LABELS,
    PLOT_THREAD_WORLD_STATUS_CHOICES,
    PLOT_THREAD_STATUS_LABELS,
    PRESET_CREATURE_STATUS_KEYS,
    PRESET_FACTION_STATUS_KEYS,
    PRESET_ITEM_STATUS_KEYS,
    PRESET_LOCATION_STATUS_KEYS,
    PRESET_MYSTERY_STATUS_KEYS,
    PRESET_NPC_WORLD_STATUS_KEYS,
    PRESET_THREAD_WORLD_STATUS_KEYS,
    entity_world_status,
    normalize_world_status,
)


def _preset_select_options(
    choices: Sequence[Tuple[str, str]],
    selected_key: str,
    *,
    include_unspecified: bool = True,
) -> List[Dict[str, Any]]:
    options: List[Dict[str, Any]] = []
    if include_unspecified:
        options.append({"value": "", "label": "— Unspecified —", "selected": not selected_key})
    for value, label in choices:
        options.append({"value": value, "label": label, "selected": value == selected_key})
    return options


def _world_status_select(name: str, label: str, choices, labels, preset_keys, stored: Optional[str]) -> Dict[str, Any]:
    selected = normalize_world_status(stored, labels)
    return {
        "name": name,
        "label": label,
        "type": "select",
        "options": _preset_select_options(choices, selected, include_unspecified=False),
    }


def _state_notes_field(stored: Optional[str]) -> Dict[str, Any]:
    return {
        "name": "state_notes",
        "label": "State Notes",
        "type": "textarea",
        "rows": 2,
        "value": stored or "",
    }


def world_status_form_fields(entity, entity_kind: str) -> List[Dict[str, Any]]:
    if entity_kind == "threads":
        status_name = "status"
        status_label = "Status"
        choices = PLOT_THREAD_WORLD_STATUS_CHOICES
        labels = PLOT_THREAD_STATUS_LABELS
        preset_keys = PRESET_THREAD_WORLD_STATUS_KEYS
        stored = entity.status
    else:
        status_name = "world_status"
        status_label = "World Status"
        mapping = {
            "factions": (FACTION_STATUS_CHOICES, FACTION_STATUS_LABELS, PRESET_FACTION_STATUS_KEYS),
            "locations": (LOCATION_STATUS_CHOICES, LOCATION_STATUS_LABELS, PRESET_LOCATION_STATUS_KEYS),
            "items": (ITEM_STATUS_CHOICES, ITEM_STATUS_LABELS, PRESET_ITEM_STATUS_KEYS),
            "npcs": (NPC_WORLD_STATUS_CHOICES, NPC_WORLD_STATUS_LABELS, PRESET_NPC_WORLD_STATUS_KEYS),
            "creatures": (CREATURE_STATUS_CHOICES, CREATURE_STATUS_LABELS, PRESET_CREATURE_STATUS_KEYS),
        }
        choices, labels, preset_keys = mapping[entity_kind]
        stored = entity.world_status
    return [
        _world_status_select(status_name, status_label, choices, labels, preset_keys, stored),
        _state_notes_field(getattr(entity, "state_notes", None)),
    ]


def primary_location_field(locations, stored_text: Optional[str]) -> List[Dict[str, Any]]:
    selected_id, custom_value = match_location_id_by_name(locations, stored_text)
    options: List[Dict[str, Any]] = [{"value": "", "label": "— Unspecified —", "selected": not selected_id}]
    for location in locations:
        options.append(
            {
                "value": str(location.id),
                "label": location.name,
                "selected": selected_id == str(location.id),
            }
        )
    options.append(
        {
            "value": LOCATION_CUSTOM,
            "label": "Custom location (not in list)…",
            "selected": selected_id == LOCATION_CUSTOM,
        }
    )
    return [
        {
            "name": "current_location_id",
            "label": "Current Location",
            "type": "select",
            "options": options,
            "reveals": "current_location_custom",
            "reveals_value": LOCATION_CUSTOM,
        },
        {
            "name": "current_location_custom",
            "label": "Custom Current Location",
            "type": "text",
            "value": custom_value,
            "reveal_target": "current_location_custom",
            "initially_visible": selected_id == LOCATION_CUSTOM,
        },
    ]


def location_entity_select_field(name: str, label: str, locations, selected_id: Optional[int]) -> Dict[str, Any]:
    options: List[Dict[str, Any]] = [{"value": "", "label": "— None —", "selected": not selected_id}]
    for location in locations:
        is_selected = selected_id is not None and location.id == selected_id
        options.append({"value": str(location.id), "label": location.name, "selected": is_selected})
    return {"name": name, "label": label, "type": "select", "options": options}


def npc_profile_fields(npc, locations) -> List[Dict[str, Any]]:
    fields: List[Dict[str, Any]] = [
        {"name": "name", "label": "Name", "type": "text", "required": True},
        {"name": "role", "label": "Role", "type": "text"},
        {"name": "description", "label": "Description", "type": "textarea", "rows": 3},
    ]
    fields.extend(world_status_form_fields(npc, "npcs"))
    fields.extend(primary_location_field(locations, npc.current_location))
    fields.extend(
        [
            {"name": "relationship_to_party", "label": "Relationship to Party", "type": "text"},
            {"name": "goals", "label": "Goals", "type": "textarea", "rows": 3},
            {"name": "secrets", "label": "Secrets", "type": "textarea", "rows": 3},
        ]
    )
    return fields


def faction_profile_fields(faction) -> List[Dict[str, Any]]:
    return world_status_form_fields(faction, "factions")


def location_profile_fields(location) -> List[Dict[str, Any]]:
    return world_status_form_fields(location, "locations")


def item_profile_fields(item) -> List[Dict[str, Any]]:
    return world_status_form_fields(item, "items")


def creature_profile_fields(creature) -> List[Dict[str, Any]]:
    from app.services.creature_classification import CREATURE_TYPE_CHOICES, creature_type_form_values

    creature_type_select, creature_type_custom = creature_type_form_values(creature.creature_type)
    creature_type_options = [{"value": "", "label": "— Unspecified —", "selected": not creature_type_select}]
    for value, label in CREATURE_TYPE_CHOICES:
        creature_type_options.append({"value": value, "label": label, "selected": value == creature_type_select})

    habitat_select, habitat_custom = preset_form_values(creature.habitat, HABITAT_LABELS, PRESET_HABITAT_KEYS)
    threat_select, threat_custom = preset_form_values(creature.threat_level, THREAT_LEVEL_LABELS, PRESET_THREAT_KEYS)

    fields: List[Dict[str, Any]] = [
        {"name": "name", "label": "Name", "type": "text", "required": True},
        {
            "name": "creature_type",
            "label": "Creature Type",
            "type": "select",
            "options": creature_type_options,
            "reveals": "creature_type_custom",
        },
        {
            "name": "creature_type_custom",
            "label": "Custom Creature Type",
            "type": "text",
            "value": creature_type_custom,
            "reveal_target": "creature_type_custom",
        },
        {"name": "classification", "label": "Classification", "type": "text"},
    ]
    from app.services.entity_field_choices import preset_select_field

    fields.extend(preset_select_field("habitat", "Habitat", HABITAT_CHOICES, habitat_select, "habitat_custom", habitat_custom))
    fields.extend(preset_select_field("threat_level", "Threat Level", THREAT_LEVEL_CHOICES, threat_select, "threat_level_custom", threat_custom))
    fields.extend(world_status_form_fields(creature, "creatures"))
    fields.extend(
        [
            {"name": "physical_description", "label": "Physical Description", "type": "textarea", "rows": 5},
            {"name": "special_traits", "label": "Special Traits & Abilities", "type": "textarea", "rows": 5},
            {"name": "campaign_context_tactics", "label": "Campaign Context & Tactics", "type": "textarea", "rows": 5},
            {"name": "notes", "label": "Additional Notes", "type": "textarea", "rows": 3},
        ]
    )
    return fields


def plot_thread_profile_fields(thread) -> List[Dict[str, Any]]:
    type_select, type_custom = preset_form_values(thread.thread_type, PLOT_THREAD_TYPE_LABELS, PRESET_THREAD_TYPE_KEYS)
    mystery_select = normalize_world_status(thread.mystery_status, MYSTERY_STATUS_LABELS)
    from app.services.entity_field_choices import preset_select_field

    fields: List[Dict[str, Any]] = [
        {"name": "title", "label": "Title", "type": "text", "required": True},
    ]
    fields.extend(world_status_form_fields(thread, "threads"))
    fields.extend(preset_select_field("thread_type", "Thread Type", PLOT_THREAD_TYPE_CHOICES, type_select, "thread_type_custom", type_custom))
    fields.append(
        {
            "name": "mystery_status",
            "label": "Mystery Status",
            "type": "select",
            "options": _preset_select_options(MYSTERY_STATUS_CHOICES, mystery_select, include_unspecified=False),
        }
    )
    fields.extend(
        [
            {"name": "details", "label": "Description", "type": "textarea", "rows": 5},
            {"name": "open_clues", "label": "Open Clues (one per line)", "type": "textarea", "rows": 4, "value": thread.open_clues or ""},
            {"name": "revealed_clues", "label": "Revealed Clues (one per line)", "type": "textarea", "rows": 4, "value": thread.revealed_clues or ""},
            {"name": "secret_notes", "label": "Secret Notes (GM only)", "type": "textarea", "rows": 4, "value": thread.secret_notes or ""},
            {"name": "plot_significance_notes", "label": "Plot Significance / Notes", "type": "textarea", "rows": 5},
            {"name": "resolution_notes", "label": "Resolution Notes", "type": "textarea", "rows": 3},
        ]
    )
    return fields
