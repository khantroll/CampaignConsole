"""Tests for entity co-appearance timeline (P3)."""

import unittest

from sqlmodel import Session, select

from app import database
from app.models import Faction, NPC, SessionModel
from app.services.coappearance import get_entity_coappearance_timeline
from tests.test_app import CampaignConsoleSmokeTests


class CoappearanceTests(CampaignConsoleSmokeTests):
    def test_coappearance_shows_shared_sessions_with_linked_faction(self):
        campaign = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={"title": "Shared Session", "date": "2026-01-01", "notes": "n"},
        )
        self.client.post(
            f"/campaigns/{campaign}/npcs",
            data={"name": "Ally", "role": "NPC", "description": "Helper."},
        )
        self.client.post(
            f"/campaigns/{campaign}/factions",
            data={"name": "Order", "summary": "Knights."},
        )
        with Session(database.engine) as db:
            session = db.exec(
                select(SessionModel).where(SessionModel.campaign_id == int(campaign))
            ).first()
            npc = db.exec(select(NPC).where(NPC.name == "Ally")).first()
            faction = db.exec(select(Faction).where(Faction.name == "Order")).first()
            session_id = session.id
            npc_id = npc.id
            faction_id = faction.id

        self.client.post(
            f"/campaigns/{campaign}/sessions/{session_id}/edit",
            data={
                "title": "Shared Session",
                "date": "2026-01-01",
                "notes": "n",
                "selected_npcs": [str(npc_id)],
                "selected_factions": [str(faction_id)],
            },
        )
        self.client.post(
            f"/campaigns/{campaign}/npcs/{npc_id}/edit",
            data={
                "name": "Ally",
                "role": "NPC",
                "description": "Helper.",
                "selected_factions": [str(faction_id)],
            },
        )

        with Session(database.engine) as db:
            timeline = get_entity_coappearance_timeline(db, int(campaign), "npcs", npc_id)
            self.assertIsNotNone(timeline)
            self.assertEqual(timeline["entry_count"], 1)
            self.assertEqual(timeline["entries"][0]["session"].title, "Shared Session")
            self.assertEqual(timeline["entries"][0]["partners"][0]["name"], "Order")

        response = self.client.get(f"/campaigns/{campaign}/npcs/{npc_id}/edit")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Co-appearance Timeline", response.content)
        self.assertIn(b"Shared Session", response.content)
        self.assertIn(b"Order", response.content)


if __name__ == "__main__":
    unittest.main()
