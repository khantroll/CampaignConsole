"""Tests for faction ↔ NPC/PC cross-links."""

from __future__ import annotations

import unittest

from sqlmodel import Session, select

import app.database as database
from app.models import Faction, Location, NPC, NPCFactionLink, PCFactionLink, PCPlotThreadLink, PlayerCharacterNote
from tests.test_app import CampaignConsoleSmokeTests


class FactionMemberLinkTests(CampaignConsoleSmokeTests):
    def test_faction_edit_tags_npcs_and_pcs(self):
        campaign_id = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign_id}/npcs",
            data={"name": "Baron Kestrel", "role": "Noble", "description": "A patron."},
        )
        self.client.post(
            f"/campaigns/{campaign_id}/pcs",
            data={"character_name": "Aldric", "notes": "Fighter."},
        )
        self.client.post(
            f"/campaigns/{campaign_id}/factions",
            data={"name": "Iron Crown", "summary": "Ruling house."},
        )
        with Session(database.engine) as db:
            faction = db.exec(select(Faction).where(Faction.name == "Iron Crown")).first()
            npc = db.exec(select(NPC).where(NPC.name == "Baron Kestrel")).first()
            pc = db.exec(select(PlayerCharacterNote).where(PlayerCharacterNote.character_name == "Aldric")).first()

        response = self.client.get(f"/campaigns/{campaign_id}/factions/{faction.id}/edit")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Key Figures", response.content)
        self.assertIn(b"Related Party Members", response.content)

        self.client.post(
            f"/campaigns/{campaign_id}/factions/{faction.id}/edit",
            data={
                "name": "Iron Crown",
                "summary": "Ruling house.",
                "selected_npcs": [str(npc.id)],
                "selected_pcs": [str(pc.id)],
            },
        )

        with Session(database.engine) as db:
            npc_links = db.exec(
                select(NPCFactionLink).where(NPCFactionLink.faction_id == faction.id)
            ).all()
            pc_links = db.exec(
                select(PCFactionLink).where(PCFactionLink.faction_id == faction.id)
            ).all()
            self.assertEqual(len(npc_links), 1)
            self.assertEqual(npc_links[0].npc_id, npc.id)
            self.assertEqual(len(pc_links), 1)
            self.assertEqual(pc_links[0].pc_note_id, pc.id)

        npc_edit = self.client.get(f"/campaigns/{campaign_id}/npcs/{npc.id}/edit")
        self.assertIn(b"Iron Crown", npc_edit.content)
        self.assertIn(f'name="selected_factions"'.encode(), npc_edit.content)
        self.assertIn(f'value="{faction.id}" selected'.encode(), npc_edit.content)

        pc_edit = self.client.get(f"/campaigns/{campaign_id}/pcs/{pc.id}/edit")
        self.assertIn(b"Iron Crown", pc_edit.content)
        self.assertIn(f'name="selected_factions"'.encode(), pc_edit.content)
        self.assertIn(f'value="{faction.id}" selected'.encode(), pc_edit.content)

    def test_pc_edit_tags_factions(self):
        campaign_id = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign_id}/factions",
            data={"name": "Delver's Guild", "summary": "Explorers."},
        )
        self.client.post(
            f"/campaigns/{campaign_id}/pcs",
            data={"character_name": "Mira", "notes": "Rogue."},
        )
        with Session(database.engine) as db:
            faction = db.exec(select(Faction).where(Faction.name == "Delver's Guild")).first()
            pc = db.exec(select(PlayerCharacterNote).where(PlayerCharacterNote.character_name == "Mira")).first()

        self.client.post(
            f"/campaigns/{campaign_id}/pcs/{pc.id}/edit",
            data={
                "character_name": "Mira",
                "notes": "Rogue.",
                "selected_factions": [str(faction.id)],
            },
        )

        faction_edit = self.client.get(f"/campaigns/{campaign_id}/factions/{faction.id}/edit")
        self.assertIn(b"Mira", faction_edit.content)
        self.assertIn(f'value="{pc.id}" selected'.encode(), faction_edit.content)

    def test_pc_edit_tags_plot_threads(self):
        campaign_id = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign_id}/threads",
            data={"title": "The Lost Heir", "status": "active", "details": "Royal succession."},
        )
        self.client.post(
            f"/campaigns/{campaign_id}/pcs",
            data={"character_name": "Aldric", "notes": "Fighter."},
        )
        with Session(database.engine) as db:
            from app.models import PlotThread

            thread = db.exec(select(PlotThread).where(PlotThread.title == "The Lost Heir")).first()
            pc = db.exec(select(PlayerCharacterNote).where(PlayerCharacterNote.character_name == "Aldric")).first()

        self.client.post(
            f"/campaigns/{campaign_id}/pcs/{pc.id}/edit",
            data={
                "character_name": "Aldric",
                "notes": "Fighter.",
                "selected_plot_threads": [str(thread.id)],
            },
        )

        with Session(database.engine) as db:
            links = db.exec(
                select(PCPlotThreadLink).where(PCPlotThreadLink.pc_note_id == pc.id)
            ).all()
            self.assertEqual(len(links), 1)
            self.assertEqual(links[0].plot_thread_id, thread.id)

        pc_edit = self.client.get(f"/campaigns/{campaign_id}/pcs/{pc.id}/edit")
        self.assertIn(b"The Lost Heir", pc_edit.content)
        self.assertIn(f'value="{thread.id}" selected'.encode(), pc_edit.content)

    def test_faction_profile_fields_and_related_links(self):
        campaign_id = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign_id}/locations",
            data={"name": "Guild Hall", "location_type": "major", "description": "HQ building."},
        )
        self.client.post(
            f"/campaigns/{campaign_id}/threads",
            data={"title": "Power Struggle", "status": "active", "details": "Leadership contest."},
        )
        self.client.post(
            f"/campaigns/{campaign_id}/factions",
            data={
                "name": "Delver's Guild",
                "faction_type": "guild",
                "summary": "Explorers and cartographers.",
                "plot_notes": "The party owes them a favor.",
            },
        )
        with Session(database.engine) as db:
            faction = db.exec(select(Faction).where(Faction.name == "Delver's Guild")).first()
            location = db.exec(select(Location).where(Location.name == "Guild Hall")).first()
            from app.models import PlotThread

            thread = db.exec(select(PlotThread).where(PlotThread.title == "Power Struggle")).first()

        self.client.post(
            f"/campaigns/{campaign_id}/factions/{faction.id}/edit",
            data={
                "name": "Delver's Guild",
                "faction_type": "guild",
                "summary": "Explorers and cartographers.",
                "hq_location_id": str(location.id),
                "plot_notes": "The party owes them a favor.",
                "selected_locations": [str(location.id)],
                "selected_plot_threads": [str(thread.id)],
            },
        )

        with Session(database.engine) as db:
            faction = db.get(Faction, faction.id)
            self.assertEqual(faction.faction_type, "guild")
            self.assertEqual(faction.hq_location_id, location.id)
            self.assertEqual(faction.plot_notes, "The party owes them a favor.")

        response = self.client.get(f"/campaigns/{campaign_id}/factions/{faction.id}/edit")
        self.assertIn(b"Related Locations", response.content)
        self.assertIn(b"Related Plot Threads", response.content)
        self.assertIn(b"Guild Hall", response.content)
        self.assertIn(b"Power Struggle", response.content)

    def test_faction_other_custom_type(self):
        campaign_id = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign_id}/factions",
            data={"name": "House Vael", "summary": "Old nobility."},
        )
        with Session(database.engine) as db:
            faction = db.exec(select(Faction).where(Faction.name == "House Vael")).first()

        self.client.post(
            f"/campaigns/{campaign_id}/factions/{faction.id}/edit",
            data={
                "name": "House Vael",
                "faction_type": "other",
                "faction_type_custom": "Noble House",
                "summary": "Old nobility.",
            },
        )

        with Session(database.engine) as db:
            faction = db.get(Faction, faction.id)
            self.assertEqual(faction.faction_type, "noble_house")

        response = self.client.get(f"/campaigns/{campaign_id}/factions/{faction.id}/edit")
        self.assertIn(b"Custom Faction Type", response.content)
        self.assertIn(b"Noble House", response.content)
        self.assertIn(b'value="other"', response.content)

    def test_entity_edit_shows_inline_faction_create_form(self):
        campaign_id = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign_id}/npcs",
            data={"name": "Scout", "role": "Guide", "description": "A scout."},
        )
        with Session(database.engine) as db:
            npc = db.exec(select(NPC).where(NPC.name == "Scout")).first()

        response = self.client.get(f"/campaigns/{campaign_id}/npcs/{npc.id}/edit")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Create new faction", response.content)
        self.assertIn(b'name="new_faction_name"', response.content)

    def test_npc_edit_creates_and_links_new_faction(self):
        campaign_id = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign_id}/npcs",
            data={"name": "Merchant", "role": "Trader", "description": "Sells goods."},
        )
        with Session(database.engine) as db:
            npc = db.exec(select(NPC).where(NPC.name == "Merchant")).first()

        response = self.client.post(
            f"/campaigns/{campaign_id}/npcs/{npc.id}/edit",
            data={
                "name": "Merchant",
                "role": "Trader",
                "description": "Sells goods.",
                "new_faction_name": "Silver Consortium",
                "new_faction_type": "guild",
            },
        )
        self.assertEqual(response.status_code, 303)

        with Session(database.engine) as db:
            faction = db.exec(select(Faction).where(Faction.name == "Silver Consortium")).first()
            self.assertIsNotNone(faction)
            self.assertEqual(faction.faction_type, "guild")
            npc = db.get(NPC, npc.id)
            db.refresh(npc)
            self.assertEqual([linked.name for linked in npc.factions], ["Silver Consortium"])
            link = db.exec(
                select(NPCFactionLink).where(
                    NPCFactionLink.npc_id == npc.id,
                    NPCFactionLink.faction_id == faction.id,
                )
            ).first()
            self.assertIsNotNone(link)

    def test_session_edit_creates_and_links_new_faction(self):
        campaign_id = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign_id}/sessions",
            data={"title": "Session 1", "notes": "Opening night."},
        )
        with Session(database.engine) as db:
            from app.models import SessionModel

            session = db.exec(select(SessionModel).where(SessionModel.campaign_id == int(campaign_id))).first()

        response = self.client.post(
            f"/campaigns/{campaign_id}/sessions/{session.id}/edit",
            data={
                "title": "Session 1",
                "notes": "Opening night.",
                "new_faction_name": "Crimson Veil",
                "new_faction_type": "criminal_syndicate",
            },
        )
        self.assertEqual(response.status_code, 303)

        with Session(database.engine) as db:
            from app.models import SessionModel

            faction = db.exec(select(Faction).where(Faction.name == "Crimson Veil")).first()
            self.assertIsNotNone(faction)
            session = db.get(SessionModel, session.id)
            db.refresh(session)
            self.assertEqual([linked.name for linked in session.factions], ["Crimson Veil"])


if __name__ == "__main__":
    unittest.main()
