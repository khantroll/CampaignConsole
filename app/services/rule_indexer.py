"""Index rules markdown from Systems/ profiles into an in-memory cache."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Set

from app.services.text_similarity import STOPWORDS, normalize_text, token_set

H2_HEADER_PATTERN = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)

DEFAULT_SYSTEMS_ROOT = Path(__file__).resolve().parents[2] / "Systems"

SYSTEM_PROFILE_ALIASES: Dict[str, str] = {
    "5e": "DND5E",
    "dnd5": "DND5E",
    "dnd5e": "DND5E",
    "dd5e": "DND5E",
    "dnd35": "DND3.5",
    "dnd3.5": "DND3.5",
    "dd35": "DND3.5",
    "3.5": "DND3.5",
    "ose": "OSE",
    "oldschool": "OSE",
    "oldschoolessentials": "OSE",
    "pathfinder1e": "Pathfinder-1E",
    "pf1": "Pathfinder-1E",
    "pf1e": "Pathfinder-1E",
    "pathfinder2e": "Pathfinder-2E",
    "pf2": "Pathfinder-2E",
    "pf2e": "Pathfinder-2E",
}


def _compact_system_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _read_markdown_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _split_markdown_by_h2(content: str) -> Dict[str, str]:
    """Split markdown into sections keyed by level-2 header title."""
    matches = list(H2_HEADER_PATTERN.finditer(content))
    if not matches:
        return {}

    sections: Dict[str, str] = {}
    for index, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        sections[title] = content[start:end].strip()
    return sections


class RuleIndexerService:
    """Scan Systems/<profile>/*.md and cache each ## section for lookup."""

    def __init__(self, systems_root: Optional[Path] = None) -> None:
        self.systems_root = systems_root or DEFAULT_SYSTEMS_ROOT
        self.rules_cache: Dict[str, Dict[str, str]] = {}

    def load(self) -> None:
        """Scan Systems/ and populate the in-memory rules cache."""
        self.rules_cache.clear()
        self._build_cache()

    def _normalize_rule_name(self, rule_name: str) -> str:
        return normalize_text(rule_name)

    def _build_cache(self) -> None:
        if not self.systems_root.is_dir():
            return

        for system_dir in sorted(self.systems_root.iterdir()):
            if not system_dir.is_dir():
                continue

            system_id = system_dir.name
            system_rules: Dict[str, str] = {}

            for md_path in sorted(system_dir.rglob("*.md")):
                try:
                    content = _read_markdown_file(md_path)
                except OSError:
                    continue

                for header_title, snippet in _split_markdown_by_h2(content).items():
                    key = self._normalize_rule_name(header_title)
                    if key:
                        system_rules[key] = snippet

            if system_rules:
                self.rules_cache[system_id] = system_rules

    def lookup_rule(self, system_id: str, rule_name: str) -> Optional[str]:
        system_rules = self.rules_cache.get(system_id)
        if not system_rules:
            return None
        return system_rules.get(self._normalize_rule_name(rule_name))

    def resolve_system_id(self, profile: Optional[str]) -> Optional[str]:
        """Map a campaign rules profile label to a Systems/ directory id."""
        if not profile or not str(profile).strip():
            return None

        label = str(profile).strip()
        available: Set[str] = set(self.rules_cache.keys())
        if not available:
            return None

        if label in available:
            return label

        label_lower = label.lower()
        for system_id in available:
            if system_id.lower() == label_lower:
                return system_id

        compact = _compact_system_label(label)
        if not compact:
            return None

        aliased = SYSTEM_PROFILE_ALIASES.get(compact)
        if aliased and aliased in available:
            return aliased

        by_compact = {_compact_system_label(system_id): system_id for system_id in available}
        return by_compact.get(compact)

    def _rule_key_matches_text(self, rule_key: str, normalized_text: str, text_tokens: Set[str]) -> bool:
        if not rule_key:
            return False

        tokens = [token for token in rule_key.split() if token]
        if len(tokens) == 1:
            return tokens[0] in text_tokens

        if rule_key in normalized_text:
            return True

        rule_tokens = {token for token in tokens if token not in STOPWORDS}
        return bool(rule_tokens) and rule_tokens.issubset(text_tokens)

    def lookup_rules_in_text(self, profile: Optional[str], text: str) -> List[str]:
        """Return markdown snippets whose rule names appear in the input text."""
        system_id = self.resolve_system_id(profile)
        if not system_id:
            return []

        system_rules = self.rules_cache.get(system_id)
        if not system_rules:
            return []

        normalized_text = normalize_text(text)
        if not normalized_text:
            return []

        text_tokens = token_set(text)
        matches: List[str] = []
        seen_snippets: Set[str] = set()

        for rule_key, snippet in system_rules.items():
            if not self._rule_key_matches_text(rule_key, normalized_text, text_tokens):
                continue
            if snippet in seen_snippets:
                continue
            seen_snippets.add(snippet)
            matches.append(snippet)

        return matches


# Set during app startup (see app.main.lifespan).
rule_indexer: Optional[RuleIndexerService] = None
