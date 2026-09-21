import unittest

from sqlmodel import Session, select

from app import database
from app.models import Encounter, Location, NPC, Objective, PlotThread, Scene, SessionModel
from app.services.narrative_blocks import load_session_narrative_blocks
from tests.test_app import CampaignConsoleSmokeTests


class NarrativeBlocksPhase3Tests(CampaignConsoleSmokeTests):
    def _seed_iron_gates_fixture(self, campaign_id: int) -> dict:
        loc = self.client.post(
            f"/campaigns/{campaign_id}/locations",
            data={"name": "Iron Gates", "description": "Ancient gates."},
        )
        npc = self.client.post(
            f"/campaigns/{campaign_id}/npcs",
            data={"name": "Gatekeeper", "role": "Guard"},
        )
        thread = self.client.post(
            f"/campaigns/{campaign_id}/threads",
            data={"title": "The Lost Vault", "details": "Hidden vault."},
        )
        session = self.client.post(
            f"/campaigns/{campaign_id}/sessions",
            data={"title": "Session 10", "date": "2026-02-01", "notes": "Arrival."},
        )
        self.assertEqual(session.status_code, 303)

        with Session(database.engine) as db:
            location = db.exec(select(Location).where(Location.name == "Iron Gates")).first()
            gatekeeper = db.exec(select(NPC).where(NPC.name == "Gatekeeper")).first()
            vault_thread = db.exec(select(PlotThread).where(PlotThread.title == "The Lost Vault")).first()
            sessions = db.exec(select(SessionModel).where(SessionModel.campaign_id == campaign_id)).all()
            session_model = sessions[-1]

            self.client.post(
                f"/campaigns/{campaign_id}/threads/{vault_thread.id}/edit",
                data={
                    "title": "The Lost Vault",
                    "open_clues": "The passphrase is carved on the inner gate",
                },
            )

        scene_resp = self.client.post(
            f"/campaigns/{campaign_id}/workspace/scenes",
            data={
                "session_id": session_model.id,
                "title": "Arrival at the Iron Gates",
                "narrative_goal": "Establish danger and reveal the gate's guardian.",
                "location_id": str(location.id),
                "npc_ids": [str(gatekeeper.id)],
                "thread_ids": [str(vault_thread.id)],
                "mode": "prep",
            },
        )
        self.assertEqual(scene_resp.status_code, 303)

        with Session(database.engine) as db:
            scene = db.exec(
                select(Scene).where(Scene.title == "Arrival at the Iron Gates")
            ).first()
            scene_id = scene.id

        enc_resp = self.client.post(
            f"/campaigns/{campaign_id}/workspace/encounters",
            data={
                "session_id": session_model.id,
                "scene_id": str(scene_id),
                "title": "Gatekeeper Challenge",
                "encounter_type": "social",
                "stakes": "Entry to the vault",
                "mode": "prep",
            },
        )
        self.assertEqual(enc_resp.status_code, 303)

        obj_resp = self.client.post(
            f"/campaigns/{campaign_id}/workspace/objectives",
            data={
                "session_id": session_model.id,
                "scene_id": str(scene_id),
                "title": "Learn the passphrase",
                "objective_type": "clue",
                "priority": "high",
                "description": "Discover how to open the vault.",
                "mode": "prep",
            },
        )
        self.assertEqual(obj_resp.status_code, 303)

        return {
            "session_id": session_model.id,
            "scene_id": scene_id,
            "location_id": location.id,
            "npc_id": gatekeeper.id,
            "thread_id": vault_thread.id,
        }

    def test_session_builder_and_active_scene_intelligence(self):
        campaign = self._create_campaign()
        ids = self._seed_iron_gates_fixture(campaign)

        workspace = self.client.get(
            f"/campaigns/{campaign}/workspace?session_id={ids['session_id']}&mode=prep"
        )
        self.assertEqual(workspace.status_code, 200)
        self.assertIn(b"Session Builder", workspace.content)
        self.assertIn(b"Arrival at the Iron Gates", workspace.content)
        self.assertIn(b"Gatekeeper Challenge", workspace.content)
        self.assertIn(b"Learn the passphrase", workspace.content)

        activate = self.client.post(
            f"/campaigns/{campaign}/workspace/scenes/{ids['scene_id']}/activate",
            data={"session_id": ids["session_id"], "mode": "run"},
        )
        self.assertEqual(activate.status_code, 303)

        run_workspace = self.client.get(
            f"/campaigns/{campaign}/workspace?session_id={ids['session_id']}&mode=run"
        )
        self.assertIn(b"Active Scene Intelligence", run_workspace.content)
        self.assertIn(b"Quick Rules Reference", run_workspace.content)
        self.assertIn(b"data-mc-quick-rules", run_workspace.content)
        self.assertIn(b"Gatekeeper", run_workspace.content)
        self.assertIn(b"Iron Gates", run_workspace.content)
        self.assertIn(b"The Lost Vault", run_workspace.content)
        self.assertIn(b"passphrase", run_workspace.content)

    def test_export_and_entity_pages_show_narrative_blocks(self):
        campaign = self._create_campaign()
        ids = self._seed_iron_gates_fixture(campaign)

        export = self.client.get(
            f"/campaigns/{campaign}/sessions/{ids['session_id']}/export/markdown"
        )
        self.assertIn(b"## Scenes", export.content)
        self.assertIn(b"Arrival at the Iron Gates", export.content)
        self.assertIn(b"Gatekeeper Challenge", export.content)
        self.assertIn(b"Learn the passphrase", export.content)

        npc_page = self.client.get(f"/campaigns/{campaign}/npcs/{ids['npc_id']}/edit")
        self.assertIn(b"Narrative Blocks", npc_page.content)
        self.assertIn(b"Arrival at the Iron Gates", npc_page.content)

        loc_page = self.client.get(f"/campaigns/{campaign}/locations/{ids['location_id']}/edit")
        self.assertIn(b"Arrival at the Iron Gates", loc_page.content)

        thread_page = self.client.get(f"/campaigns/{campaign}/threads/{ids['thread_id']}/edit")
        self.assertIn(b"Arrival at the Iron Gates", thread_page.content)

    def test_workspace_modes_show_review_section(self):
        campaign = self._create_campaign()
        ids = self._seed_iron_gates_fixture(campaign)
        review = self.client.get(
            f"/campaigns/{campaign}/workspace?session_id={ids['session_id']}&mode=review"
        )
        self.assertIn(b"Session Review", review.content)


if __name__ == "__main__":
    unittest.main()
