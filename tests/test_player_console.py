import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

import app.database as database
import app.main as main
from app.auth import clear_login_throttle_for_tests, hash_password
from app.models import (
    Campaign,
    CampaignMembership,
    Faction,
    Location,
    NPC,
    PCFactionLink,
    PCLocationLink,
    PlayerCharacterNote,
    PlayerReveal,
    PlotThread,
    RevealAudience,
    SessionModel,
    User,
)


class PlayerConsolePhase2Tests(unittest.TestCase):
    def setUp(self):
        clear_login_throttle_for_tests()
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.db_fd)
        database.DB_FILE = Path(self.db_path)
        database.engine = create_engine(
            f"sqlite:///{self.db_path}",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(database.engine)
        database.ensure_auth_indexes()
        database.ensure_player_reveal_indexes()
        self.client = TestClient(main.app, raise_server_exceptions=True, follow_redirects=False)

        with Session(database.engine) as db:
            c1 = Campaign(name="Player Campaign", system="Test")
            c2 = Campaign(name="Other Campaign", system="Other")
            db.add(c1)
            db.add(c2)
            db.commit()
            db.refresh(c1)
            db.refresh(c2)
            self.c1 = c1.id
            self.c2 = c2.id

        bootstrap = self.client.post(
            "/bootstrap",
            data={"username": "owner", "display_name": "Owner", "password": "owner-password-123"},
        )
        self.assertEqual(bootstrap.status_code, 303)

        with Session(database.engine) as db:
            player1 = User(username="player1", display_name="Player One", password_hash=hash_password("player-one-password"))
            player2 = User(username="player2", display_name="Player Two", password_hash=hash_password("player-two-password"))
            gm = User(username="gm2", display_name="GM Two", password_hash=hash_password("gm-two-password"))
            stranger = User(username="stranger2", display_name="Stranger", password_hash=hash_password("stranger-password"))
            db.add(player1); db.add(player2); db.add(gm); db.add(stranger)
            db.commit()
            db.refresh(player1); db.refresh(player2); db.refresh(gm); db.refresh(stranger)

            pc1 = PlayerCharacterNote(
                campaign_id=self.c1,
                character_name="Avery",
                character_archetype="Investigator",
                description="Player-safe character description",
                signature_gear="Old camera",
                key_ties_history="Knows the harbor master",
                campaign_role_plot_notes="PC_SECRET_ROLE_SENTINEL",
                notes="PC_GM_NOTES_SENTINEL",
            )
            pc2 = PlayerCharacterNote(campaign_id=self.c1, character_name="Other Player Character")
            db.add(pc1); db.add(pc2); db.commit(); db.refresh(pc1); db.refresh(pc2)

            m1 = CampaignMembership(campaign_id=self.c1, user_id=player1.id, role="player", player_character_id=pc1.id)
            m2 = CampaignMembership(campaign_id=self.c1, user_id=player2.id, role="player", player_character_id=pc2.id)
            mgm = CampaignMembership(campaign_id=self.c1, user_id=gm.id, role="gm")
            db.add(m1); db.add(m2); db.add(mgm); db.commit()
            db.refresh(m1); db.refresh(m2); db.refresh(mgm)
            self.m1 = m1.id
            self.m2 = m2.id

            visible_npc = NPC(
                campaign_id=self.c1,
                name="Visible NPC",
                description="Canonical description should not be required",
                secrets="NPC_SECRET_SENTINEL",
            )
            hidden_npc = NPC(campaign_id=self.c1, name="Hidden NPC", secrets="HIDDEN_NPC_SECRET_SENTINEL")
            other_npc = NPC(campaign_id=self.c2, name="Other Campaign NPC", secrets="OTHER_SECRET_SENTINEL")
            hidden_location = Location(campaign_id=self.c1, name="Hidden Location", notes="LOCATION_GM_SENTINEL")
            visible_faction = Faction(campaign_id=self.c1, name="Visible Faction", plot_notes="FACTION_GM_SENTINEL")
            thread = PlotThread(
                campaign_id=self.c1,
                title="Revealed Quest",
                secret_notes="THREAD_SECRET_SENTINEL",
                open_clues="UNREVEALED_CLUE_SENTINEL",
                plot_significance_notes="THREAD_PLOT_SENTINEL",
            )
            db.add(visible_npc); db.add(hidden_npc); db.add(other_npc); db.add(hidden_location); db.add(visible_faction); db.add(thread)
            db.commit()
            for obj in (visible_npc, hidden_npc, other_npc, hidden_location, visible_faction, thread):
                db.refresh(obj)
            self.visible_npc = visible_npc.id
            self.hidden_npc = hidden_npc.id
            self.other_npc = other_npc.id
            self.hidden_location = hidden_location.id
            self.visible_faction = visible_faction.id
            self.thread = thread.id

            db.add(PCLocationLink(pc_note_id=pc1.id, location_id=hidden_location.id))
            db.add(PCFactionLink(pc_note_id=pc1.id, faction_id=visible_faction.id))

            session = SessionModel(
                campaign_id=self.c1,
                title="Published Session",
                date="2026-10-01",
                player_recap="PLAYER_RECAP_VISIBLE",
                notes="SESSION_NOTES_SENTINEL",
                analysis="SESSION_ANALYSIS_SENTINEL",
                analysis_raw="SESSION_ANALYSIS_RAW_SENTINEL",
                next_session_prep="SESSION_NEXT_PREP_SENTINEL",
                workspace_notes="SESSION_WORKSPACE_SENTINEL",
            )
            other_session = SessionModel(
                campaign_id=self.c2,
                title="Other Campaign Session",
                player_recap="OTHER_CAMPAIGN_RECAP_SENTINEL",
            )
            db.add(session); db.add(other_session); db.commit(); db.refresh(session); db.refresh(other_session)
            self.session_id = session.id
            self.other_session_id = other_session.id

            all_reveal = PlayerReveal(
                campaign_id=self.c1,
                entity_kind="npc",
                entity_id=visible_npc.id,
                public_summary="SAFE NPC SUMMARY",
                audience_mode="campaign",
                revealed_session_id=session.id,
            )
            selected_reveal = PlayerReveal(
                campaign_id=self.c1,
                entity_kind="plot_thread",
                entity_id=thread.id,
                public_summary="SAFE SELECTED QUEST SUMMARY",
                audience_mode="selected",
            )
            faction_reveal = PlayerReveal(
                campaign_id=self.c1,
                entity_kind="faction",
                entity_id=visible_faction.id,
                public_summary="SAFE FACTION SUMMARY",
                audience_mode="campaign",
            )
            other_reveal = PlayerReveal(
                campaign_id=self.c2,
                entity_kind="npc",
                entity_id=other_npc.id,
                public_summary="OTHER CAMPAIGN REVEAL SENTINEL",
                audience_mode="campaign",
            )
            db.add(all_reveal); db.add(selected_reveal); db.add(faction_reveal); db.add(other_reveal)
            db.commit(); db.refresh(selected_reveal)
            db.add(RevealAudience(reveal_id=selected_reveal.id, membership_id=m1.id))
            db.commit()
            self.selected_reveal_id = selected_reveal.id

    def tearDown(self):
        self.client.close()
        database.engine.dispose()
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def login(self, username, password):
        client = TestClient(main.app, follow_redirects=False)
        response = client.post("/login", data={"username": username, "password": password, "next": "/player"})
        self.assertEqual(response.status_code, 303)
        return client

    def test_player_owner_and_gm_access_player_console_unrelated_denied(self):
        player = self.login("player1", "player-one-password")
        gm = self.login("gm2", "gm-two-password")
        stranger = self.login("stranger2", "stranger-password")
        try:
            self.assertEqual(player.get(f"/player/campaigns/{self.c1}").status_code, 200)
            self.assertEqual(self.client.get(f"/player/campaigns/{self.c1}").status_code, 200)
            self.assertEqual(gm.get(f"/player/campaigns/{self.c1}").status_code, 200)
            self.assertEqual(stranger.get(f"/player/campaigns/{self.c1}").status_code, 404)
            self.assertEqual(player.get(f"/player/campaigns/{self.c2}").status_code, 404)
            self.assertEqual(player.get(f"/campaigns/{self.c1}").status_code, 403)
        finally:
            player.close(); gm.close(); stranger.close()

    def test_reveal_visibility_direct_id_and_revocation(self):
        player1 = self.login("player1", "player-one-password")
        player2 = self.login("player2", "player-two-password")
        try:
            lore1 = player1.get(f"/player/campaigns/{self.c1}/lore")
            lore2 = player2.get(f"/player/campaigns/{self.c1}/lore")
            self.assertEqual(lore1.status_code, 200)
            self.assertIn("Visible NPC", lore1.text)
            self.assertIn("SAFE NPC SUMMARY", lore1.text)
            self.assertNotIn("Hidden NPC", lore1.text)
            self.assertIn("SAFE SELECTED QUEST SUMMARY", lore1.text)
            self.assertNotIn("SAFE SELECTED QUEST SUMMARY", lore2.text)
            self.assertNotIn("OTHER CAMPAIGN REVEAL SENTINEL", lore1.text)

            hidden = player1.get(f"/player/campaigns/{self.c1}/lore/npc/{self.hidden_npc}")
            missing = player1.get(f"/player/campaigns/{self.c1}/lore/npc/999999")
            cross = player1.get(f"/player/campaigns/{self.c1}/lore/npc/{self.other_npc}")
            self.assertEqual(hidden.status_code, 404)
            self.assertEqual(missing.status_code, 404)
            self.assertEqual(cross.status_code, 404)

            with Session(database.engine) as db:
                reveal = db.get(PlayerReveal, self.selected_reveal_id)
                reveal.is_active = False
                db.add(reveal)
                db.commit()
            self.assertNotIn(
                "SAFE SELECTED QUEST SUMMARY",
                player1.get(f"/player/campaigns/{self.c1}/lore").text,
            )
        finally:
            player1.close(); player2.close()

    def test_player_responses_exclude_gm_only_sentinels(self):
        player = self.login("player1", "player-one-password")
        try:
            paths = [
                f"/player/campaigns/{self.c1}",
                f"/player/campaigns/{self.c1}/lore",
                f"/player/campaigns/{self.c1}/lore/npc/{self.visible_npc}",
                f"/player/campaigns/{self.c1}/sessions",
                f"/player/campaigns/{self.c1}/sessions/{self.session_id}",
                f"/player/campaigns/{self.c1}/character",
            ]
            body = "\n".join(player.get(path).text for path in paths)
            for sentinel in (
                "NPC_SECRET_SENTINEL",
                "THREAD_SECRET_SENTINEL",
                "UNREVEALED_CLUE_SENTINEL",
                "THREAD_PLOT_SENTINEL",
                "SESSION_NOTES_SENTINEL",
                "SESSION_ANALYSIS_SENTINEL",
                "SESSION_ANALYSIS_RAW_SENTINEL",
                "SESSION_NEXT_PREP_SENTINEL",
                "SESSION_WORKSPACE_SENTINEL",
                "PC_SECRET_ROLE_SENTINEL",
                "PC_GM_NOTES_SENTINEL",
                "LOCATION_GM_SENTINEL",
                "FACTION_GM_SENTINEL",
            ):
                self.assertNotIn(sentinel, body)
        finally:
            player.close()

    def test_sessions_show_player_recap_and_deny_cross_campaign_session(self):
        player = self.login("player1", "player-one-password")
        try:
            page = player.get(f"/player/campaigns/{self.c1}/sessions/{self.session_id}")
            self.assertEqual(page.status_code, 200)
            self.assertIn("PLAYER_RECAP_VISIBLE", page.text)
            self.assertNotIn("SESSION_NOTES_SENTINEL", page.text)
            cross = player.get(f"/player/campaigns/{self.c1}/sessions/{self.other_session_id}")
            self.assertEqual(cross.status_code, 404)
        finally:
            player.close()

    def test_character_is_linked_character_only_and_hidden_relationships_stay_hidden(self):
        player = self.login("player1", "player-one-password")
        try:
            page = player.get(f"/player/campaigns/{self.c1}/character")
            self.assertEqual(page.status_code, 200)
            self.assertIn("Avery", page.text)
            self.assertNotIn("Other Player Character", page.text)
            self.assertNotIn("Hidden Location", page.text)
            self.assertIn("Visible Faction", page.text)
        finally:
            player.close()


if __name__ == "__main__":
    unittest.main()
