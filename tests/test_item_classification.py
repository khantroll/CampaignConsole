"""Unit tests for item type normalization."""

from __future__ import annotations

import unittest

from app.services.item_classification import (
    ITEM_TYPE_OTHER,
    ITEM_TYPE_RELIC,
    build_item_type_options,
    item_type_form_values,
    item_type_label,
    resolve_item_type,
)


class ItemClassificationTests(unittest.TestCase):
    def test_resolve_custom_type_when_other_selected(self):
        self.assertEqual(resolve_item_type("other", "Cursed Artifact"), "cursed_artifact")

    def test_resolve_preset_type(self):
        self.assertEqual(resolve_item_type("relic", ""), ITEM_TYPE_RELIC)

    def test_resolve_other_without_custom(self):
        self.assertEqual(resolve_item_type("other", ""), ITEM_TYPE_OTHER)

    def test_resolve_custom_slug_selected_directly(self):
        self.assertEqual(resolve_item_type("spell_scroll", ""), "spell_scroll")

    def test_resolve_custom_when_normalize_returns_none(self):
        self.assertEqual(resolve_item_type("other", "!!!"), ITEM_TYPE_OTHER)

    def test_form_values_for_custom_type(self):
        select_value, custom_value = item_type_form_values("cursed_artifact")
        self.assertEqual(select_value, "cursed_artifact")
        self.assertEqual(custom_value, "")

    def test_label_for_custom_type(self):
        self.assertEqual(item_type_label("cursed_artifact"), "Cursed Artifact")

    def test_build_item_type_options_includes_campaign_custom_types(self):
        from sqlmodel import Session

        import app.database as database
        from app.models import Campaign, Item

        with Session(database.engine) as db:
            campaign = Campaign(name="Type Test", system="D&D")
            db.add(campaign)
            db.commit()
            db.refresh(campaign)
            db.add(
                Item(
                    campaign_id=campaign.id,
                    name="Scroll",
                    item_type="spell_scroll",
                    description="Arcane.",
                )
            )
            db.commit()
            options = build_item_type_options(db, campaign.id)
        values = [option["value"] for option in options]
        self.assertIn("spell_scroll", values)
        self.assertEqual(
            "Spell Scroll",
            next(option["label"] for option in options if option["value"] == "spell_scroll"),
        )


if __name__ == "__main__":
    unittest.main()
