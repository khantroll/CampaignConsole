"""Unit tests for faction type normalization."""

from __future__ import annotations

import unittest

from app.services.faction_classification import (
    FACTION_TYPE_GUILD,
    FACTION_TYPE_OTHER,
    faction_type_form_values,
    faction_type_label,
    resolve_faction_type,
)


class FactionClassificationTests(unittest.TestCase):
    def test_resolve_custom_type_when_other_selected(self):
        self.assertEqual(resolve_faction_type("other", "Noble House"), "noble_house")

    def test_resolve_preset_type(self):
        self.assertEqual(resolve_faction_type("guild", ""), FACTION_TYPE_GUILD)

    def test_resolve_other_without_custom(self):
        self.assertEqual(resolve_faction_type("other", ""), FACTION_TYPE_OTHER)

    def test_form_values_for_custom_type(self):
        select_value, custom_value = faction_type_form_values("noble_house")
        self.assertEqual(select_value, FACTION_TYPE_OTHER)
        self.assertEqual(custom_value, "Noble House")

    def test_label_for_custom_type(self):
        self.assertEqual(faction_type_label("noble_house"), "Noble House")


if __name__ == "__main__":
    unittest.main()
