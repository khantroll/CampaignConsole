import re
from difflib import SequenceMatcher
from typing import Any, List, Optional, Tuple

STOPWORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "to",
    "of",
    "in",
    "on",
    "for",
    "about",
    "investigate",
    "investigating",
    "investigation",
}


def normalize_text(text: str) -> str:
    lowered = (text or "").lower().replace("'s", "")
    cleaned = re.sub(r"[^a-z0-9\s]+", " ", lowered)
    return re.sub(r"\s+", " ", cleaned).strip()


def token_set(text: str) -> set[str]:
    return {token for token in normalize_text(text).split() if token and token not in STOPWORDS}


def text_similarity(left: str, right: str) -> float:
    left_norm = normalize_text(left)
    right_norm = normalize_text(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0

    sequence_score = SequenceMatcher(None, left_norm, right_norm).ratio()
    left_tokens = token_set(left_norm)
    right_tokens = token_set(right_norm)
    if not left_tokens or not right_tokens:
        return sequence_score

    overlap = len(left_tokens & right_tokens)
    union = len(left_tokens | right_tokens)
    token_score = overlap / union if union else 0.0

    substring_bonus = 0.0
    if len(left_norm) >= 4 and left_norm in right_norm:
        substring_bonus = 0.15
    elif len(right_norm) >= 4 and right_norm in left_norm:
        substring_bonus = 0.15

    return min(1.0, max(sequence_score, token_score, token_score + substring_bonus))


def entity_match_text(obj: Any, label_attr: str, extra_attrs: Tuple[str, ...] = ()) -> str:
    parts = [str(getattr(obj, label_attr, "") or "")]
    for attr in extra_attrs:
        parts.append(str(getattr(obj, attr, "") or ""))
    return " ".join(part.strip() for part in parts if part and part.strip())


def find_best_match(
    candidate: str,
    existing_objects: List[Any],
    label_attr: str,
    extra_attrs: Tuple[str, ...] = (),
    *,
    exact_first: bool = True,
) -> Tuple[Optional[Any], float]:
    candidate_name = candidate.strip()
    if not candidate_name:
        return None, 0.0

    if exact_first:
        for obj in existing_objects:
            label = getattr(obj, label_attr, "")
            if label and label.strip().lower() == candidate_name.lower():
                return obj, 1.0

    best_obj = None
    best_score = 0.0
    for obj in existing_objects:
        label_score = text_similarity(candidate_name, str(getattr(obj, label_attr, "") or ""))
        full_score = text_similarity(candidate_name, entity_match_text(obj, label_attr, extra_attrs))
        score = max(label_score, full_score)
        if score > best_score:
            best_score = score
            best_obj = obj
    return best_obj, best_score
