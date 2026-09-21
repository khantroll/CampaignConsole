"""Tests for location-to-location related links."""

from __future__ import annotations

import unittest

from sqlmodel import Session, select

import app.database as database
from app.models import Location, LocationRelatedLocationLink
from app.services.location_links import load_related_locations, related_location_ids
from tests.test_app import CampaignConsoleSmokeTests


class LocationRelatedLinksTests(CampaignConsoleSmokeTests):
    def test_location_edit_shows_related_locations(self):
        campaign_id = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign_id}/locations",
            data={"name": "Castle", "location_type": "major", "description": "Keep."},
        )
        self.client.post(
            f"/campaigns/{campaign_id}/locations",
            data={"name": "Village", "location_type": "sub", "description": "Town below."},
        )
        with Session(database.engine) as db:
            castle = db.exec(select(Location).where(Location.name == "Castle")).first()

        response = self.client.get(f"/campaigns/{campaign_id}/locations/{castle.id}/edit")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Related Locations", response.content)
        self.assertIn(b"Village", response.content)
        self.assertIn(b'value="2"', response.content)
        self.assertIn(b'mc-relationship-select', response.content)

    def test_location_related_links_are_symmetric(self):
        campaign_id = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign_id}/locations",
            data={"name": "Castle", "location_type": "major", "description": "Keep."},
        )
        self.client.post(
            f"/campaigns/{campaign_id}/locations",
            data={"name": "Village", "location_type": "sub", "description": "Town below."},
        )
        with Session(database.engine) as db:
            castle = db.exec(select(Location).where(Location.name == "Castle")).first()
            village = db.exec(select(Location).where(Location.name == "Village")).first()

        self.client.post(
            f"/campaigns/{campaign_id}/locations/{castle.id}/edit",
            data={
                "name": "Castle",
                "location_type": "major",
                "description": "Keep.",
                "selected_related_locations": [str(village.id)],
            },
        )

        with Session(database.engine) as db:
            self.assertIn(village.id, related_location_ids(db, castle.id))
            self.assertIn(castle.id, related_location_ids(db, village.id))
            related = load_related_locations(db, int(campaign_id), castle.id)
            self.assertEqual([loc.name for loc in related], ["Village"])

    def test_markdown_export_includes_related_locations(self):
        campaign_id = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign_id}/locations",
            data={"name": "Harbor", "location_type": "major", "description": "Port."},
        )
        self.client.post(
            f"/campaigns/{campaign_id}/locations",
            data={"name": "Market", "location_type": "sub", "description": "Bazaar."},
        )
        with Session(database.engine) as db:
            harbor = db.exec(select(Location).where(Location.name == "Harbor")).first()
            market = db.exec(select(Location).where(Location.name == "Market")).first()

        self.client.post(
            f"/campaigns/{campaign_id}/locations/{harbor.id}/edit",
            data={
                "name": "Harbor",
                "location_type": "major",
                "description": "Port.",
                "selected_related_locations": [str(market.id)],
            },
        )

        response = self.client.get(f"/campaigns/{campaign_id}/export/markdown")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Related Locations", response.text)
        self.assertIn("Market", response.text)

    def test_location_notes_on_create_and_edit(self):
        campaign_id = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign_id}/locations",
            data={
                "name": "Ebbert's Outfitters",
                "location_type": "major",
                "description": "General store in the Old Town.",
                "notes": "Owner owes the party a favor.",
            },
        )
        with Session(database.engine) as db:
            location = db.exec(select(Location).where(Location.name == "Ebbert's Outfitters")).first()
            self.assertIsNotNone(location)
            self.assertEqual(location.notes, "Owner owes the party a favor.")

        response = self.client.get(f"/campaigns/{campaign_id}/locations/{location.id}/edit")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Notes", response.content)
        self.assertIn(b"Owner owes the party a favor.", response.content)

        self.client.post(
            f"/campaigns/{campaign_id}/locations/{location.id}/edit",
            data={
                "name": "Ebbert's Outfitters",
                "location_type": "major",
                "description": "General store in the Old Town.",
                "notes": "Hidden back room with contraband.",
            },
        )
        with Session(database.engine) as db:
            location = db.get(Location, location.id)
            self.assertEqual(location.notes, "Hidden back room with contraband.")

    def test_location_key_npcs_cross_link(self):
        campaign_id = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign_id}/locations",
            data={"name": "Ebbert's Outfitters", "location_type": "major", "description": "General store."},
        )
        self.client.post(
            f"/campaigns/{campaign_id}/npcs",
            data={"name": "Ebbert", "role": "Shopkeeper", "description": "Friendly merchant."},
        )
        with Session(database.engine) as db:
            location = db.exec(select(Location).where(Location.name == "Ebbert's Outfitters")).first()
            from app.models import NPC

            npc = db.exec(select(NPC).where(NPC.name == "Ebbert")).first()

        response = self.client.get(f"/campaigns/{campaign_id}/locations/{location.id}/edit")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Key NPCs", response.content)
        self.assertIn(b"Ebbert", response.content)

        self.client.post(
            f"/campaigns/{campaign_id}/locations/{location.id}/edit",
            data={
                "name": "Ebbert's Outfitters",
                "location_type": "major",
                "description": "General store.",
                "selected_npcs": [str(npc.id)],
            },
        )

        with Session(database.engine) as db:
            from app.models import NPCLocationLink

            links = db.exec(
                select(NPCLocationLink).where(NPCLocationLink.location_id == location.id)
            ).all()
            self.assertEqual(len(links), 1)
            self.assertEqual(links[0].npc_id, npc.id)

        npc_edit = self.client.get(f"/campaigns/{campaign_id}/npcs/{npc.id}/edit")
        self.assertIn(b"Ebbert&#39;s Outfitters", npc_edit.content)
        self.assertIn(f'value="{location.id}" selected'.encode(), npc_edit.content)


if __name__ == "__main__":
    unittest.main()
