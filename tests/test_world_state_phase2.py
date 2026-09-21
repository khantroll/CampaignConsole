import json
import unittest

from sqlmodel import Session, select

from app import database
from app.models import Campaign, Faction, Location, NPC, PlotThread
from tests.test_app import CampaignConsoleSmokeTests


class WorldStatePhase2Tests(CampaignConsoleSmokeTests):
    def test_faction_world_status_persists_and_exports(self):
        campaign = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign}/factions",
            data={"name": "Iron Crown", "summary": "Rulers."},
        )
        with Session(database.engine) as db:
            faction = db.exec(select(Faction).where(Faction.name == "Iron Crown")).first()
            faction_id = faction.id

        response = self.client.post(
            f"/campaigns/{campaign}/factions/{faction_id}/edit",
            data={
                "name": "Iron Crown",
                "summary": "Rulers.",
                "world_status": "hostile",
                "state_notes": "Openly hostile after Session 9.",
            },
        )
        self.assertEqual(response.status_code, 303)

        edit_page = self.client.get(f"/campaigns/{campaign}/factions/{faction_id}/edit")
        self.assertIn(b"hostile", edit_page.content)
        self.assertIn(b"Openly hostile after Session 9", edit_page.content)

        export = self.client.get(f"/campaigns/{campaign}/export/markdown")
        self.assertIn(b"Status: hostile", export.content)
        self.assertIn(b"State Notes: Openly hostile after Session 9", export.content)

    def test_location_world_status(self):
        campaign = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign}/locations",
            data={"name": "Lower Vault", "description": "Sealed."},
        )
        with Session(database.engine) as db:
            location = db.exec(select(Location).where(Location.name == "Lower Vault")).first()

        self.client.post(
            f"/campaigns/{campaign}/locations/{location.id}/edit",
            data={
                "name": "Lower Vault",
                "description": "Sealed.",
                "world_status": "explored",
                "state_notes": "Explored but lower vault remains sealed.",
            },
        )
        edit_page = self.client.get(f"/campaigns/{campaign}/locations/{location.id}/edit")
        self.assertIn(b"explored", edit_page.content)

    def test_plot_thread_clues_and_mystery_status(self):
        campaign = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign}/threads",
            data={"title": "Baron Mystery", "details": "Disappearances."},
        )
        with Session(database.engine) as db:
            thread = db.exec(select(PlotThread).where(PlotThread.title == "Baron Mystery")).first()

        self.client.post(
            f"/campaigns/{campaign}/threads/{thread.id}/edit",
            data={
                "title": "Baron Mystery",
                "status": "active",
                "mystery_status": "partially_revealed",
                "details": "Disappearances.",
                "open_clues": "Baron met a stranger\nTown guard is lying",
                "revealed_clues": "Party found a torn letter",
                "secret_notes": "The stranger is the baron's brother.",
            },
        )

        edit_page = self.client.get(f"/campaigns/{campaign}/threads/{thread.id}/edit")
        self.assertIn(b"partially_revealed", edit_page.content)
        self.assertIn(b"Baron met a stranger", edit_page.content)
        self.assertIn(b"Secret Notes", edit_page.content)

        briefing = self.client.get(f"/campaigns/{campaign}/briefing")
        self.assertEqual(briefing.status_code, 200)
        self.assertIn(b"Open Mysteries", briefing.content)
        self.assertIn(b"Baron met a stranger", briefing.content)

    def test_npc_world_status_field(self):
        campaign = self._create_campaign()
        self.client.post(f"/campaigns/{campaign}/npcs", data={"name": "Baron Kestrel", "role": "Lord"})
        with Session(database.engine) as db:
            npc = db.exec(select(NPC).where(NPC.name == "Baron Kestrel")).first()

        self.client.post(
            f"/campaigns/{campaign}/npcs/{npc.id}/edit",
            data={
                "name": "Baron Kestrel",
                "world_status": "missing",
                "state_notes": "Missing after the lodge ambush.",
            },
        )
        with Session(database.engine) as db:
            npc = db.get(NPC, npc.id)
            self.assertEqual(npc.world_status, "missing")


    def test_ingest_clue_review_attaches_to_plot_thread(self):
        campaign = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign}/threads",
            data={"title": "Baron Disappearances", "details": "Missing nobles."},
        )

        clue_text = "The party learned that Baron Kestrel met a stranger before the disappearances."
        with Session(database.engine) as db:
            thread = db.exec(select(PlotThread).where(PlotThread.title == "Baron Disappearances")).first()
            thread_id = thread.id

        response = self.client.post(
            f"/campaigns/{campaign}/ingest/save",
            data={
                "session_title": "Session 9",
                "session_date": "2026-01-10",
                "raw_notes": clue_text,
                "ingest_clues_json": json.dumps([clue_text]),
                "selected_clue_actions": [f"0|revealed:existing:{thread_id}"],
            },
        )
        self.assertEqual(response.status_code, 303)

        with Session(database.engine) as db:
            thread = db.get(PlotThread, thread_id)
            self.assertIn("Baron Kestrel met a stranger", thread.revealed_clues or "")

    def test_player_export_hides_secret_notes_and_open_clues(self):
        campaign = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign}/threads",
            data={"title": "Hidden Plot", "details": "Secret arc."},
        )
        with Session(database.engine) as db:
            thread = db.exec(select(PlotThread).where(PlotThread.title == "Hidden Plot")).first()

        self.client.post(
            f"/campaigns/{campaign}/threads/{thread.id}/edit",
            data={
                "title": "Hidden Plot",
                "status": "active",
                "details": "Secret arc.",
                "open_clues": "Hidden clue",
                "revealed_clues": "Public clue",
                "secret_notes": "GM only secret",
            },
        )

        gm_export = self.client.get(f"/campaigns/{campaign}/export/markdown")
        player_export = self.client.get(f"/campaigns/{campaign}/export/markdown?scope=player")
        self.assertIn(b"GM only secret", gm_export.content)
        self.assertIn(b"Hidden clue", gm_export.content)
        self.assertNotIn(b"GM only secret", player_export.content)
        self.assertNotIn(b"Hidden clue", player_export.content)
        self.assertIn(b"Public clue", player_export.content)


if __name__ == "__main__":
    unittest.main()
