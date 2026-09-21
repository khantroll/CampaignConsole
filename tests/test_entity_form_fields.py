import unittest
from types import SimpleNamespace

from app.services.entity_field_choices import (
    LOCATION_CUSTOM,
    match_location_id_by_name,
    preset_form_values,
    resolve_preset_or_custom,
    resolve_primary_location_text,
    ALIVE_OR_DEAD_LABELS,
    CURRENT_STATUS_LABELS,
    PRESET_ALIVE_KEYS,
    PRESET_STATUS_KEYS,
)


class EntityFieldChoicesTests(unittest.TestCase):
    def test_preset_form_values_matches_label_text(self):
        selected, custom = preset_form_values("Active", CURRENT_STATUS_LABELS, PRESET_STATUS_KEYS)
        self.assertEqual(selected, "active")
        self.assertEqual(custom, "")

    def test_preset_form_values_preserves_unknown_as_custom(self):
        selected, custom = preset_form_values("On vacation", CURRENT_STATUS_LABELS, PRESET_STATUS_KEYS)
        self.assertEqual(selected, "other")
        self.assertEqual(custom, "On vacation")

    def test_resolve_preset_or_custom_uses_label_for_preset(self):
        self.assertEqual(resolve_preset_or_custom("alive", "", ALIVE_OR_DEAD_LABELS), "Alive")

    def test_match_location_id_by_name(self):
        locations = [SimpleNamespace(id=3, name="Stonemarten")]
        selected, custom = match_location_id_by_name(locations, "stonemarten")
        self.assertEqual(selected, "3")
        self.assertEqual(custom, "")

    def test_match_location_id_custom_when_unknown(self):
        locations = [SimpleNamespace(id=3, name="Stonemarten")]
        selected, custom = match_location_id_by_name(locations, "A random alley")
        self.assertEqual(selected, LOCATION_CUSTOM)
        self.assertEqual(custom, "A random alley")

    def test_resolve_primary_location_text_from_id(self):
        locations = [SimpleNamespace(id=3, name="Stonemarten")]
        self.assertEqual(resolve_primary_location_text(locations, "3", ""), "Stonemarten")

    def test_resolve_primary_location_text_from_custom(self):
        locations = [SimpleNamespace(id=3, name="Stonemarten")]
        self.assertEqual(resolve_primary_location_text(locations, LOCATION_CUSTOM, "Alley"), "Alley")


if __name__ == "__main__":
    unittest.main()
