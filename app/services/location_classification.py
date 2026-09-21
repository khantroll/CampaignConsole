"""Heuristic location typing for ingestion and admin."""

import re
from typing import Any, Dict, List, Optional, Tuple

LOCATION_TYPE_MAJOR = "major"
LOCATION_TYPE_SUB = "sub"
LOCATION_TYPE_SCENE = "scene_feature"

LOCATION_TYPE_LABELS = {
    LOCATION_TYPE_MAJOR: "Major Location",
    LOCATION_TYPE_SUB: "Sub-Location",
    LOCATION_TYPE_SCENE: "Scene Feature",
}

LOCATION_TYPE_CHOICES = (
    (LOCATION_TYPE_MAJOR, LOCATION_TYPE_LABELS[LOCATION_TYPE_MAJOR]),
    (LOCATION_TYPE_SUB, LOCATION_TYPE_LABELS[LOCATION_TYPE_SUB]),
    (LOCATION_TYPE_SCENE, LOCATION_TYPE_LABELS[LOCATION_TYPE_SCENE]),
)

GENERIC_SCENE_NOUNS = (
    "dead-end",
    "dead end",
    "passage",
    "corridor",
    "hallway",
    "chest",
    "room",
    "pool",
    "pit",
    "drop-off",
    "drop off",
    "alcove",
    "niche",
    "doorway",
    "archway",
    "staircase",
    "stairs",
    "landing",
    "ledge",
    "tunnel",
    "cavern",
)

GENERIC_MODIFIERS = (
    "side",
    "hidden",
    "secret",
    "narrow",
    "wide",
    "shallow",
    "deep",
    "small",
    "large",
    "empty",
    "dark",
    "dim",
    "locked",
    "broken",
    "collapsed",
)

ARTICLE_PREFIX = re.compile(r"^(a|an|the)\s+", re.IGNORECASE)
POSSESSIVE_PATTERN = re.compile(r"\w+'s\s", re.IGNORECASE)
TITLE_CASE_WORD = re.compile(r"^[A-Z][a-zA-Z''-]+$")


def location_type_label(location_type: Optional[str]) -> str:
    if not location_type:
        return LOCATION_TYPE_LABELS[LOCATION_TYPE_MAJOR]
    return LOCATION_TYPE_LABELS.get(location_type, location_type.replace("_", " ").title())


def normalize_location_type(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    mapping = {
        "major": LOCATION_TYPE_MAJOR,
        "major_location": LOCATION_TYPE_MAJOR,
        "city": LOCATION_TYPE_MAJOR,
        "region": LOCATION_TYPE_MAJOR,
        "district": LOCATION_TYPE_MAJOR,
        "settlement": LOCATION_TYPE_MAJOR,
        "sub": LOCATION_TYPE_SUB,
        "sub_location": LOCATION_TYPE_SUB,
        "sublocation": LOCATION_TYPE_SUB,
        "building": LOCATION_TYPE_SUB,
        "structure": LOCATION_TYPE_SUB,
        "scene": LOCATION_TYPE_SCENE,
        "scene_feature": LOCATION_TYPE_SCENE,
        "temporary": LOCATION_TYPE_SCENE,
        "feature": LOCATION_TYPE_SCENE,
    }
    return mapping.get(text)


def _strip_article(text: str) -> str:
    return ARTICLE_PREFIX.sub("", text.strip())


def _contains_generic_noun(text: str) -> bool:
    lowered = text.lower().strip()
    for noun in GENERIC_SCENE_NOUNS:
        if re.search(rf"\b{re.escape(noun)}\b", lowered):
            return True
    return False


def is_generic_scene_feature(name: str) -> bool:
    """True for temporary scene features like 'a chest' or 'side passage'."""
    text = name.strip()
    if not text:
        return True

    lowered = text.lower()
    core = _strip_article(lowered)
    if not _contains_generic_noun(core):
        return False

    if is_explicitly_named(text):
        return False

    if ARTICLE_PREFIX.match(lowered):
        return True

    words = core.split()
    if len(words) == 1:
        return True

    if words[0] in GENERIC_MODIFIERS:
        return True

    if " of " in core and _contains_generic_noun(core):
        return True

    return _contains_generic_noun(lowered) and not is_explicitly_named(text)


def is_explicitly_named(name: str) -> bool:
    text = name.strip()
    if not text:
        return False

    if POSSESSIVE_PATTERN.search(text):
        return True

    words = [word for word in re.split(r"\s+", text) if word]
    significant = [
        word
        for word in words
        if word.lower() not in {"a", "an", "the", "of", "in", "at", "to", "and"}
    ]
    capitalized = [word for word in significant if TITLE_CASE_WORD.match(word)]
    if len(capitalized) >= 2:
        return True

    if len(significant) == 1 and TITLE_CASE_WORD.match(significant[0]):
        return not is_generic_scene_feature(text)

    return False


def _heuristic_classify(name: str) -> Tuple[str, float, str]:
    if is_generic_scene_feature(name):
        return LOCATION_TYPE_SCENE, 0.9, "generic scene feature"

    if POSSESSIVE_PATTERN.search(name) or re.search(r"\b(home|house|shop|tavern|inn|temple|tower|keep|hall|manor|estate)\b", name, re.I):
        return LOCATION_TYPE_SUB, 0.75, "named structure or possessive place"

    words = [word for word in re.split(r"\s+", name.strip()) if word]
    if len(words) == 1 and TITLE_CASE_WORD.match(words[0]):
        return LOCATION_TYPE_MAJOR, 0.7, "single proper-noun place"

    if len(words) >= 2 and is_explicitly_named(name):
        return LOCATION_TYPE_SUB, 0.65, "multi-word named place"

    return LOCATION_TYPE_MAJOR, 0.5, "default major location"


def classify_location(
    name: str,
    *,
    llm_type: Optional[str] = None,
    llm_confidence: Optional[float] = None,
) -> Dict[str, Any]:
    cleaned = name.strip()
    normalized_type = normalize_location_type(llm_type)
    if normalized_type:
        location_type = normalized_type
        confidence = llm_confidence if llm_confidence is not None else 0.85
        reason = "llm classification"
    else:
        location_type, confidence, reason = _heuristic_classify(cleaned)

    if location_type == LOCATION_TYPE_SCENE and is_explicitly_named(cleaned):
        location_type = LOCATION_TYPE_SUB
        confidence = max(confidence, 0.8)
        reason = "explicit name overrides generic noun"

    should_create = location_type != LOCATION_TYPE_SCENE
    return {
        "name": cleaned,
        "location_type": location_type,
        "confidence": round(confidence, 2),
        "should_create": should_create,
        "reason": reason,
    }


def filter_locations_by_type(
    locations: List[Any],
    filter_key: str,
) -> List[Any]:
    if filter_key in ("", "all"):
        return list(locations)
    if filter_key == "major":
        return [loc for loc in locations if (loc.location_type or LOCATION_TYPE_MAJOR) == LOCATION_TYPE_MAJOR]
    if filter_key == "sub":
        return [loc for loc in locations if loc.location_type == LOCATION_TYPE_SUB]
    if filter_key == "scene_feature":
        return [loc for loc in locations if loc.location_type == LOCATION_TYPE_SCENE]
    if filter_key == "major_sub":
        return [
            loc
            for loc in locations
            if (loc.location_type or LOCATION_TYPE_MAJOR) in {LOCATION_TYPE_MAJOR, LOCATION_TYPE_SUB}
        ]
    return list(locations)
