"""Tests for unified entity History panel."""

from sqlmodel import Session, select

from app import database
from app.models import Faction, NPC, PlayerCharacterNote, SessionModel
from app.services.entity_history_panel import build_entity_history_panel
from tests.test_app import CampaignConsoleSmokeTests


class EntityHistoryPanelTests(CampaignConsoleSmokeTests):
    def test_npc_history_panel_shows_first_last_related_and_stats(self):
        campaign = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={"title": "Session Two", "date": "2026-01-01", "notes": "n"},
        )
        self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={"title": "Session Nine", "date": "2026-06-01", "notes": "n"},
        )
        self.client.post(
            f"/campaigns/{campaign}/npcs",
            data={"name": "Baron Kestrel", "role": "Lord", "description": "A baron."},
        )
        self.client.post(
            f"/campaigns/{campaign}/factions",
            data={"name": "Iron Crown", "summary": "A faction."},
        )
        with Session(database.engine) as db:
            sessions = db.exec(
                select(SessionModel).where(SessionModel.campaign_id == int(campaign)).order_by(SessionModel.id)
            ).all()
            npc = db.exec(select(NPC).where(NPC.name == "Baron Kestrel")).first()
            faction = db.exec(select(Faction).where(Faction.name == "Iron Crown")).first()
            npc_id = npc.id
            faction_id = faction.id

        for session in sessions:
            self.client.post(
                f"/campaigns/{campaign}/sessions/{session.id}/edit",
                data={
                    "title": session.title,
                    "date": session.date or "",
                    "notes": session.notes or "",
                    "selected_npcs": [str(npc_id)],
                },
            )

        self.client.post(
            f"/campaigns/{campaign}/npcs/{npc_id}/edit",
            data={
                "name": "Baron Kestrel",
                "role": "Lord",
                "description": "A baron.",
                "selected_factions": [str(faction_id)],
            },
        )

        response = self.client.get(f"/campaigns/{campaign}/npcs/{npc_id}/edit")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"History", response.content)
        self.assertIn(b"First Seen", response.content)
        self.assertIn(b"Last Seen", response.content)
        self.assertIn(b"Session Two", response.content)
        self.assertIn(b"Session Nine", response.content)
        self.assertIn(b"Appears In Sessions", response.content)
        self.assertIn(b"Iron Crown", response.content)
        self.assertIn(b"Statistics", response.content)
        self.assertIn(b"2 session", response.content)

        with Session(database.engine) as db:
            npc = db.get(NPC, npc_id)
            panel = build_entity_history_panel(db, int(campaign), "npcs", npc_id, npc)
            self.assertEqual(panel["first_seen"].title, "Session Two")
            self.assertEqual(panel["last_seen"].title, "Session Nine")
            self.assertEqual(panel["session_count"], 2)
            self.assertIn("factions", panel["related"])
            self.assertEqual(panel["related"]["factions"][0]["name"], "Iron Crown")

    def test_pc_history_panel_shows_party_sessions(self):
        campaign = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={"title": "Session One", "date": "2026-01-01", "notes": "n"},
        )
        self.client.post(
            f"/campaigns/{campaign}/pcs",
            data={"character_name": "Thalia", "notes": "Rogue."},
        )
        with Session(database.engine) as db:
            session = db.exec(select(SessionModel).where(SessionModel.campaign_id == int(campaign))).first()
            pc = db.exec(
                select(PlayerCharacterNote).where(PlayerCharacterNote.character_name == "Thalia")
            ).first()
            session_id = session.id
            pc_id = pc.id

        self.client.post(
            f"/campaigns/{campaign}/ingest/save",
            data={
                "session_title": session.title,
                "session_date": session.date or "",
                "raw_notes": "Thalia scouted ahead.",
                "selected_party_links": [f"party:existing:{pc_id}"],
            },
        )

        response = self.client.get(f"/campaigns/{campaign}/pcs/{pc_id}/edit")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"History", response.content)
        self.assertIn(b"First Seen", response.content)
        self.assertIn(b"Session One", response.content)


if __name__ == "__main__":
    unittest.main()
