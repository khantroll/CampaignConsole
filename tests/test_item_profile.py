"""Tests for item profile fields and relationships."""

from __future__ import annotations

import unittest

from sqlmodel import Session, select

import app.database as database
from app.models import Faction, Item, ItemFactionLink, Location, NPC, PlayerCharacterNote, PlotThread
from tests.test_app import CampaignConsoleSmokeTests


class ItemProfileTests(CampaignConsoleSmokeTests):
    def test_item_profile_fields_owner_and_links(self):
        campaign_id = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign_id}/npcs",
            data={"name": "Riven", "role": "Rogue", "description": "Thief."},
        )
        self.client.post(
            f"/campaigns/{campaign_id}/factions",
            data={"name": "Iron Crown", "summary": "Royal house."},
        )
        self.client.post(
            f"/campaigns/{campaign_id}/locations",
            data={"name": "Vault", "location_type": "sub", "description": "Hidden cache."},
        )
        self.client.post(
            f"/campaigns/{campaign_id}/threads",
            data={"title": "Crown Heist", "status": "active", "details": "Steal the sigil."},
        )
        self.client.post(
            f"/campaigns/{campaign_id}/items",
            data={
                "name": "Shadowblade",
                "item_type": "magic_weapon",
                "description": "A dark shortsword.",
                "origin": "Found in the Vault.",
            },
        )
        with Session(database.engine) as db:
            item = db.exec(select(Item).where(Item.name == "Shadowblade")).first()
            npc = db.exec(select(NPC).where(NPC.name == "Riven")).first()
            faction = db.exec(select(Faction).where(Faction.name == "Iron Crown")).first()
            location = db.exec(select(Location).where(Location.name == "Vault")).first()
            thread = db.exec(select(PlotThread).where(PlotThread.title == "Crown Heist")).first()

        self.client.post(
            f"/campaigns/{campaign_id}/items/{item.id}/edit",
            data={
                "name": "Shadowblade",
                "item_type": "other",
                "item_type_custom": "Cursed Artifact",
                "description": "A dark shortsword.",
                "current_owner": f"npc-{npc.id}",
                "origin": "Found in the Vault.",
                "plot_notes": "Whispers when blood is near.",
                "selected_factions": [str(faction.id)],
                "selected_locations": [str(location.id)],
                "selected_plot_threads": [str(thread.id)],
            },
        )

        with Session(database.engine) as db:
            item = db.get(Item, item.id)
            self.assertEqual(item.item_type, "cursed_artifact")
            self.assertEqual(item.owner_npc_id, npc.id)
            self.assertIsNone(item.owner_pc_id)
            self.assertEqual(item.plot_notes, "Whispers when blood is near.")
            faction_links = db.exec(
                select(ItemFactionLink).where(ItemFactionLink.item_id == item.id)
            ).all()
            self.assertEqual(len(faction_links), 1)

        response = self.client.get(f"/campaigns/{campaign_id}/items/{item.id}/edit")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Current Owner / Carrier", response.content)
        self.assertIn(b"Related Factions", response.content)
        self.assertIn(b"Cursed Artifact", response.content)
        self.assertIn(f"npc-{npc.id}".encode(), response.content)

    def test_item_other_custom_type(self):
        campaign_id = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign_id}/items",
            data={
                "name": "Sunstone",
                "item_type": "other",
                "item_type_custom": "Divine Focus",
                "description": "Glows faintly.",
            },
        )
        with Session(database.engine) as db:
            item = db.exec(select(Item).where(Item.name == "Sunstone")).first()
            self.assertEqual(item.item_type, "divine_focus")

        response = self.client.get(f"/campaigns/{campaign_id}/items/{item.id}/edit")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Custom Item Type", response.content)
        self.assertIn(b"Divine Focus", response.content)
        self.assertIn(b'value="divine_focus"', response.content)
        self.assertIn(b'data-mc-reveals="item_type_custom"', response.content)

        board = self.client.get(f"/campaigns/{campaign_id}")
        self.assertIn(b"Divine Focus", board.content)
        self.assertIn(b'value="divine_focus"', board.content)

    def test_item_custom_type_appears_in_add_form_after_create(self):
        campaign_id = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign_id}/items",
            data={
                "name": "Ancient Tome",
                "item_type": "other",
                "item_type_custom": "Spell Scroll",
                "description": "Arcane writing.",
            },
        )
        board = self.client.get(f"/campaigns/{campaign_id}")
        self.assertIn(b'value="spell_scroll"', board.content)
        self.assertIn(b"Spell Scroll", board.content)

    def test_item_owner_can_be_pc(self):
        campaign_id = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign_id}/items",
            data={"name": "Healing Potion", "item_type": "consumable", "description": "Red vial."},
        )
        self.client.post(
            f"/campaigns/{campaign_id}/pcs",
            data={"character_name": "Mira", "notes": "Cleric."},
        )
        with Session(database.engine) as db:
            item = db.exec(select(Item).where(Item.name == "Healing Potion")).first()
            pc = db.exec(select(PlayerCharacterNote).where(PlayerCharacterNote.character_name == "Mira")).first()

        self.client.post(
            f"/campaigns/{campaign_id}/items/{item.id}/edit",
            data={
                "name": "Healing Potion",
                "item_type": "consumable",
                "description": "Red vial.",
                "current_owner": f"pc-{pc.id}",
            },
        )

        with Session(database.engine) as db:
            item = db.get(Item, item.id)
            self.assertEqual(item.owner_pc_id, pc.id)
            self.assertIsNone(item.owner_npc_id)


if __name__ == "__main__":
    unittest.main()
