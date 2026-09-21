"""Tests for PC/NPC conversion and PC related locations."""

from __future__ import annotations

import unittest

from sqlmodel import Session, select

import app.database as database
from app.models import Location, NPC, NPCLocationLink, PCLocationLink, PlayerCharacterNote, SessionModel, SessionPartyMemberLink
from tests.test_app import CampaignConsoleSmokeTests


class CharacterConversionIntegrationTests(CampaignConsoleSmokeTests):
    def test_npc_edit_shows_convert_to_pc_button(self):
        campaign_id = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign_id}/npcs",
            data={"name": "Rival", "role": "Antagonist", "description": "A foe."},
        )
        with Session(database.engine) as db:
            npc = db.exec(select(NPC).where(NPC.campaign_id == int(campaign_id))).first()
            npc_id = npc.id

        response = self.client.get(f"/campaigns/{campaign_id}/npcs/{npc_id}/edit")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Convert to PC", response.content)

    def test_convert_npc_to_pc_via_route(self):
        campaign_id = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign_id}/sessions",
            data={"title": "Session One", "date": "2026-01-01", "notes": "Played."},
        )
        self.client.post(
            f"/campaigns/{campaign_id}/npcs",
            data={"name": "Former NPC", "role": "Ally", "description": "Will become PC."},
        )
        self.client.post(
            f"/campaigns/{campaign_id}/locations",
            data={"name": "Home Base", "location_type": "major", "description": "HQ"},
        )
        with Session(database.engine) as db:
            session = db.exec(
                select(SessionModel).where(SessionModel.campaign_id == int(campaign_id))
            ).first()
            npc = db.exec(select(NPC).where(NPC.campaign_id == int(campaign_id))).first()
            location = db.exec(select(Location).where(Location.campaign_id == int(campaign_id))).first()
            self.client.post(
                f"/campaigns/{campaign_id}/sessions/{session.id}/edit",
                data={
                    "title": session.title,
                    "date": session.date or "",
                    "notes": session.notes or "",
                    "selected_npcs": [str(npc.id)],
                },
            )
            self.client.post(
                f"/campaigns/{campaign_id}/npcs/{npc.id}/edit",
                data={
                    "name": npc.name,
                    "role": npc.role or "",
                    "description": npc.description or "",
                    "selected_locations": [str(location.id)],
                },
            )
            npc_id = npc.id

        response = self.client.post(f"/campaigns/{campaign_id}/npcs/{npc_id}/convert-to-pc")
        self.assertEqual(response.status_code, 303)
        self.assertIn("/pcs/", response.headers["location"])

        with Session(database.engine) as db:
            self.assertIsNone(db.get(NPC, npc_id))
            pc = db.exec(select(PlayerCharacterNote).where(PlayerCharacterNote.campaign_id == int(campaign_id))).first()
            self.assertIsNotNone(pc)
            self.assertEqual(pc.character_name, "Former NPC")
            self.assertTrue(db.exec(select(PCLocationLink).where(PCLocationLink.pc_note_id == pc.id)).first())
            self.assertTrue(
                db.exec(
                    select(SessionPartyMemberLink).where(SessionPartyMemberLink.pc_note_id == pc.id)
                ).first()
            )

    def test_pc_edit_related_locations_and_convert_to_npc(self):
        campaign_id = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign_id}/pcs",
            data={"character_name": "Hero", "notes": "Main character."},
        )
        self.client.post(
            f"/campaigns/{campaign_id}/locations",
            data={"name": "Castle", "location_type": "major", "description": "Seat of power."},
        )
        with Session(database.engine) as db:
            pc = db.exec(select(PlayerCharacterNote).where(PlayerCharacterNote.campaign_id == int(campaign_id))).first()
            location = db.exec(select(Location).where(Location.campaign_id == int(campaign_id))).first()
            pc_id = pc.id

        response = self.client.get(f"/campaigns/{campaign_id}/pcs/{pc_id}/edit")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Related Locations", response.content)
        self.assertIn(b"Convert to NPC", response.content)

        self.client.post(
            f"/campaigns/{campaign_id}/pcs/{pc_id}/edit",
            data={
                "character_name": "Hero",
                "notes": "Main character.",
                "selected_locations": [str(location.id)],
            },
        )

        with Session(database.engine) as db:
            self.assertTrue(
                db.exec(
                    select(PCLocationLink).where(
                        PCLocationLink.pc_note_id == pc_id,
                        PCLocationLink.location_id == location.id,
                    )
                ).first()
            )

        response = self.client.post(f"/campaigns/{campaign_id}/pcs/{pc_id}/convert-to-npc")
        self.assertEqual(response.status_code, 303)
        self.assertIn("/npcs/", response.headers["location"])

        with Session(database.engine) as db:
            self.assertIsNone(db.get(PlayerCharacterNote, pc_id))
            npc = db.exec(select(NPC).where(NPC.campaign_id == int(campaign_id))).first()
            self.assertEqual(npc.name, "Hero")
            self.assertTrue(
                db.exec(
                    select(NPCLocationLink).where(
                        NPCLocationLink.npc_id == npc.id,
                        NPCLocationLink.location_id == location.id,
                    )
                ).first()
            )


class PartyMemberDiscoverabilityTests(CampaignConsoleSmokeTests):
    def test_incomplete_party_member_appears_in_needs_attention(self):
        campaign_id = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign_id}/pcs",
            data={"character_name": "Thalia", "notes": ""},
        )
        with Session(database.engine) as db:
            pc = db.exec(select(PlayerCharacterNote).where(PlayerCharacterNote.character_name == "Thalia")).first()

        response = self.client.get(f"/campaigns/{campaign_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Needs Attention", response.content)
        self.assertIn(b"Thalia", response.content)
        self.assertIn(f"/campaigns/{campaign_id}/pcs/{pc.id}/edit".encode(), response.content)

    def test_lore_board_links_to_party_members_section(self):
        campaign_id = self._create_campaign()
        response = self.client.get(f"/campaigns/{campaign_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"#pcs-section", response.content)
        self.assertIn(b"Party Members", response.content)


class PartyMemberProfileTests(CampaignConsoleSmokeTests):
    def test_pc_edit_form_includes_profile_fields(self):
        campaign_id = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign_id}/pcs",
            data={"character_name": "Agnarr", "notes": "Legacy note."},
        )
        with Session(database.engine) as db:
            pc = db.exec(select(PlayerCharacterNote).where(PlayerCharacterNote.character_name == "Agnarr")).first()

        response = self.client.get(f"/campaigns/{campaign_id}/pcs/{pc.id}/edit")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Character Archetype", response.content)
        self.assertIn(b"Signature Gear", response.content)
        self.assertIn(b"Key Ties &amp; History", response.content)
        self.assertIn(b"Campaign Role &amp; Plot Notes", response.content)

    def test_pc_profile_fields_save_and_display(self):
        campaign_id = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign_id}/pcs",
            data={"character_name": "Agnarr"},
        )
        with Session(database.engine) as db:
            pc = db.exec(select(PlayerCharacterNote).where(PlayerCharacterNote.character_name == "Agnarr")).first()

        self.client.post(
            f"/campaigns/{campaign_id}/pcs/{pc.id}/edit",
            data={
                "character_name": "Agnarr",
                "character_archetype": "Frontline Juggernaut / Tribal Barbarian",
                "description": "A towering, fierce warrior from the northern wilderness.",
                "signature_gear": "Masterwork Greatsword, Kilt, Red Elk Symbol.",
                "key_ties_history": "Hails from the northern plains and bears the markings of the Red Elk Tribe.",
                "campaign_role_plot_notes": "Agnarr serves as the party's primary physical shield and shock trooper.",
            },
        )

        with Session(database.engine) as db:
            pc = db.get(PlayerCharacterNote, pc.id)
            self.assertEqual(pc.character_archetype, "Frontline Juggernaut / Tribal Barbarian")
            self.assertIn("northern wilderness", pc.description)
            self.assertIn("Red Elk Symbol", pc.signature_gear)

        board = self.client.get(f"/campaigns/{campaign_id}")
        self.assertIn(b"Frontline Juggernaut / Tribal Barbarian", board.content)
        self.assertIn(b"Signature Gear:", board.content)
        self.assertIn(b"Red Elk Tribe", board.content)


if __name__ == "__main__":
    unittest.main()
