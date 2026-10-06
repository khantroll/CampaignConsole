import os
import re
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

import app.database as database
import app.main as main
from app.auth import clear_login_throttle_for_tests, hash_password
from app.services.backup import export_campaign_json
from app.services.campaign_deletion import delete_campaign_cascade
from app.models import (
    Campaign,
    CampaignMembership,
    Faction,
    Location,
    NPC,
    PCFactionLink,
    PCLocationLink,
    PlayerCharacterNote,
    PlayerJournalEntry,
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

    def post_player_form(self, client, form_url, post_url, data):
        form = client.get(form_url)
        self.assertEqual(form.status_code, 200)
        match = re.search(r'name="_csrf" value="([^"]+)"', form.text)
        self.assertIsNotNone(match)
        payload = dict(data)
        payload["_csrf"] = match.group(1)
        return client.post(post_url, data=payload)

    def make_unlinked_player(self, username="unlinked", password="unlinked-password"):
        with Session(database.engine) as db:
            user = User(
                username=username,
                display_name=username.title(),
                password_hash=hash_password(password),
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            membership = CampaignMembership(campaign_id=self.c1, user_id=user.id, role="player")
            db.add(membership)
            db.commit()
            db.refresh(membership)
            return user.id, membership.id

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

    def test_unlinked_player_sees_choose_and_create_character_actions(self):
        self.make_unlinked_player()
        client = self.login("unlinked", "unlinked-password")
        try:
            page = client.get(f"/player/campaigns/{self.c1}/character")
            self.assertEqual(page.status_code, 200)
            self.assertIn("Choose Existing Character", page.text)
            self.assertIn("Create New Character", page.text)
        finally:
            client.close()

    def test_player_can_select_unclaimed_same_campaign_character(self):
        _, membership_id = self.make_unlinked_player("selector", "selector-password")
        with Session(database.engine) as db:
            pc = PlayerCharacterNote(
                campaign_id=self.c1,
                character_name="Unclaimed Hero",
                character_archetype="Scout",
                description="Available character",
            )
            db.add(pc)
            db.commit()
            db.refresh(pc)
            pc_id = pc.id

        client = self.login("selector", "selector-password")
        try:
            select_page = client.get(f"/player/campaigns/{self.c1}/character/select")
            self.assertEqual(select_page.status_code, 200)
            self.assertIn("Unclaimed Hero", select_page.text)
            self.assertNotIn("Other Player Character", select_page.text)
            response = self.post_player_form(
                client,
                f"/player/campaigns/{self.c1}/character/select",
                f"/player/campaigns/{self.c1}/character/select",
                {"player_character_id": str(pc_id)},
            )
            self.assertEqual(response.status_code, 303)
        finally:
            client.close()

        with Session(database.engine) as db:
            membership = db.get(CampaignMembership, membership_id)
            self.assertEqual(membership.player_character_id, pc_id)

    def test_player_cannot_select_cross_campaign_or_claimed_character(self):
        _, membership_id = self.make_unlinked_player("blockedselector", "blocked-password")
        with Session(database.engine) as db:
            foreign_pc = PlayerCharacterNote(campaign_id=self.c2, character_name="Foreign Hero")
            db.add(foreign_pc)
            db.commit()
            db.refresh(foreign_pc)
            foreign_id = foreign_pc.id

            claimed_id = db.exec(
                select(CampaignMembership.player_character_id).where(
                    CampaignMembership.id == self.m2
                )
            ).one()

        client = self.login("blockedselector", "blocked-password")
        try:
            page = client.get(f"/player/campaigns/{self.c1}/character/select")
            self.assertNotIn("Other Player Character", page.text)
            self.assertNotIn("Foreign Hero", page.text)
            for bad_id in (foreign_id, claimed_id):
                response = self.post_player_form(
                    client,
                    f"/player/campaigns/{self.c1}/character/select",
                    f"/player/campaigns/{self.c1}/character/select",
                    {"player_character_id": str(bad_id)},
                )
                self.assertEqual(response.status_code, 400)
        finally:
            client.close()

        with Session(database.engine) as db:
            membership = db.get(CampaignMembership, membership_id)
            self.assertIsNone(membership.player_character_id)

    def test_player_can_create_and_link_safe_character_without_gm_fields(self):
        _, membership_id = self.make_unlinked_player("creator", "creator-password")
        client = self.login("creator", "creator-password")
        try:
            response = self.post_player_form(
                client,
                f"/player/campaigns/{self.c1}/character/new",
                f"/player/campaigns/{self.c1}/character/new",
                {
                    "character_name": "Created Hero",
                    "character_archetype": "Seeker",
                    "description": "Player description",
                    "signature_gear": "Silver compass",
                    "key_ties_history": "Old academy friend",
                    "campaign_role_plot_notes": "CRAFTED_GM_ROLE_SENTINEL",
                    "notes": "CRAFTED_GM_NOTES_SENTINEL",
                },
            )
            self.assertEqual(response.status_code, 303)
        finally:
            client.close()

        with Session(database.engine) as db:
            membership = db.get(CampaignMembership, membership_id)
            self.assertIsNotNone(membership.player_character_id)
            pc = db.get(PlayerCharacterNote, membership.player_character_id)
            self.assertEqual(pc.campaign_id, self.c1)
            self.assertEqual(pc.character_name, "Created Hero")
            self.assertEqual(pc.character_archetype, "Seeker")
            self.assertEqual(pc.description, "Player description")
            self.assertEqual(pc.signature_gear, "Silver compass")
            self.assertEqual(pc.key_ties_history, "Old academy friend")
            self.assertIsNone(pc.campaign_role_plot_notes)
            self.assertIsNone(pc.notes)

    def test_another_player_cannot_hijack_existing_linked_character(self):
        _, membership_id = self.make_unlinked_player("hijacker", "hijacker-password")
        with Session(database.engine) as db:
            claimed_id = db.exec(
                select(CampaignMembership.player_character_id).where(
                    CampaignMembership.id == self.m1
                )
            ).one()

        client = self.login("hijacker", "hijacker-password")
        try:
            response = self.post_player_form(
                client,
                f"/player/campaigns/{self.c1}/character/select",
                f"/player/campaigns/{self.c1}/character/select",
                {"player_character_id": str(claimed_id)},
            )
            self.assertEqual(response.status_code, 400)
        finally:
            client.close()

        with Session(database.engine) as db:
            membership = db.get(CampaignMembership, membership_id)
            self.assertIsNone(membership.player_character_id)

    def test_owner_or_gm_test_link_does_not_reserve_character_from_player(self):
        _, membership_id = self.make_unlinked_player("aftergm", "aftergm-password")
        with Session(database.engine) as db:
            pc = PlayerCharacterNote(campaign_id=self.c1, character_name="GM Test Character")
            db.add(pc)
            db.commit()
            db.refresh(pc)
            pc_id = pc.id
            gm_membership = db.exec(
                select(CampaignMembership).where(
                    CampaignMembership.campaign_id == self.c1,
                    CampaignMembership.role == "gm",
                )
            ).one()
            gm_membership.player_character_id = pc_id
            db.add(gm_membership)
            db.commit()

        client = self.login("aftergm", "aftergm-password")
        try:
            page = client.get(f"/player/campaigns/{self.c1}/character/select")
            self.assertIn("GM Test Character", page.text)
            response = self.post_player_form(
                client,
                f"/player/campaigns/{self.c1}/character/select",
                f"/player/campaigns/{self.c1}/character/select",
                {"player_character_id": str(pc_id)},
            )
            self.assertEqual(response.status_code, 303)
        finally:
            client.close()

        with Session(database.engine) as db:
            membership = db.get(CampaignMembership, membership_id)
            self.assertEqual(membership.player_character_id, pc_id)

    def test_existing_admin_membership_assignment_still_links_player_character(self):
        with Session(database.engine) as db:
            user = User(
                username="adminassigned",
                display_name="Admin Assigned",
                password_hash=hash_password("admin-assigned-password"),
            )
            pc = PlayerCharacterNote(campaign_id=self.c1, character_name="Admin Assigned Hero")
            db.add(user)
            db.add(pc)
            db.commit()
            db.refresh(user)
            db.refresh(pc)
            user_id = user.id
            pc_id = pc.id

        page = self.client.get("/")
        match = re.search(r'<meta name="csrf-token" content="([^"]+)"', page.text)
        self.assertIsNotNone(match)
        response = self.client.post(
            f"/admin/users/{user_id}/memberships",
            data={
                "_csrf": match.group(1),
                "campaign_id": str(self.c1),
                "role": "player",
                "player_character_id": str(pc_id),
            },
        )
        self.assertEqual(response.status_code, 303)
        with Session(database.engine) as db:
            membership = db.exec(
                select(CampaignMembership).where(
                    CampaignMembership.user_id == user_id,
                    CampaignMembership.campaign_id == self.c1,
                )
            ).one()
            self.assertEqual(membership.player_character_id, pc_id)

    def test_campaign_backup_includes_reveals_without_auth_credentials(self):
        with Session(database.engine) as db:
            payload = export_campaign_json(db, self.c1)
        self.assertTrue(payload["player_reveals"])
        self.assertTrue(payload["reveal_audiences"])
        serialized = str(payload).lower()
        self.assertNotIn("password_hash", serialized)
        self.assertNotIn("token_hash", serialized)

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


    def test_player_journal_visibility_and_gm_inbox(self):
        player1 = self.login("player1", "player-one-password")
        player2 = self.login("player2", "player-two-password")
        gm = self.login("gm2", "gm-two-password")
        try:
            for visibility, title in (
                ("private", "PRIVATE_THOUGHT_SENTINEL"),
                ("gm", "GM_THOUGHT_SENTINEL"),
                ("party", "PARTY_THOUGHT_SENTINEL"),
            ):
                response = self.post_player_form(
                    player1,
                    f"/player/campaigns/{self.c1}/journal",
                    f"/player/campaigns/{self.c1}/journal",
                    {
                        "entry_type": "theory",
                        "visibility": visibility,
                        "title": title,
                        "body": f"{title} body",
                        "session_id": "",
                        "linked_reveal_id": "",
                    },
                )
                self.assertEqual(response.status_code, 303)

            p1 = player1.get(f"/player/campaigns/{self.c1}/journal").text
            p2 = player2.get(f"/player/campaigns/{self.c1}/journal").text
            gm_page = gm.get(f"/campaigns/{self.c1}/player-journal").text

            self.assertIn("PRIVATE_THOUGHT_SENTINEL", p1)
            self.assertIn("GM_THOUGHT_SENTINEL", p1)
            self.assertIn("PARTY_THOUGHT_SENTINEL", p1)
            self.assertNotIn("PRIVATE_THOUGHT_SENTINEL", p2)
            self.assertNotIn("GM_THOUGHT_SENTINEL", p2)
            self.assertIn("PARTY_THOUGHT_SENTINEL", p2)
            self.assertNotIn("PRIVATE_THOUGHT_SENTINEL", gm_page)
            self.assertIn("GM_THOUGHT_SENTINEL", gm_page)
            self.assertIn("PARTY_THOUGHT_SENTINEL", gm_page)
        finally:
            player1.close(); player2.close(); gm.close()

    def test_player_question_can_be_answered_and_resolved_by_gm(self):
        player = self.login("player1", "player-one-password")
        gm = self.login("gm2", "gm-two-password")
        try:
            response = self.post_player_form(
                player,
                f"/player/campaigns/{self.c1}/journal",
                f"/player/campaigns/{self.c1}/journal",
                {
                    "entry_type": "question",
                    "visibility": "gm",
                    "title": "Do I recognize this?",
                    "body": "Does Avery recognize the symbol?",
                    "session_id": str(self.session_id),
                    "linked_reveal_id": "",
                },
            )
            self.assertEqual(response.status_code, 303)
            with Session(database.engine) as db:
                entry = db.exec(
                    select(PlayerJournalEntry).where(
                        PlayerJournalEntry.title == "Do I recognize this?"
                    )
                ).one()
                entry_id = entry.id

            response = self.post_player_form(
                gm,
                f"/campaigns/{self.c1}/player-journal",
                f"/campaigns/{self.c1}/player-journal/{entry_id}/respond",
                {"gm_response": "Yes. It belongs to the old academy.", "resolved": "1"},
            )
            self.assertEqual(response.status_code, 303)
            page = player.get(f"/player/campaigns/{self.c1}/journal").text
            self.assertIn("Yes. It belongs to the old academy.", page)
            self.assertIn("Resolved", page)
        finally:
            player.close(); gm.close()

    def test_journal_rejects_cross_campaign_or_unrevealed_links(self):
        player = self.login("player1", "player-one-password")
        try:
            response = self.post_player_form(
                player,
                f"/player/campaigns/{self.c1}/journal",
                f"/player/campaigns/{self.c1}/journal",
                {
                    "entry_type": "note",
                    "visibility": "gm",
                    "title": "Bad session",
                    "body": "Should fail",
                    "session_id": str(self.other_session_id),
                    "linked_reveal_id": "",
                },
            )
            self.assertEqual(response.status_code, 400)

            with Session(database.engine) as db:
                other_reveal = db.exec(
                    select(PlayerReveal).where(PlayerReveal.campaign_id == self.c2)
                ).first()
                other_reveal_id = other_reveal.id
            response = self.post_player_form(
                player,
                f"/player/campaigns/{self.c1}/journal",
                f"/player/campaigns/{self.c1}/journal",
                {
                    "entry_type": "note",
                    "visibility": "gm",
                    "title": "Bad lore",
                    "body": "Should fail",
                    "session_id": "",
                    "linked_reveal_id": str(other_reveal_id),
                },
            )
            self.assertEqual(response.status_code, 400)
        finally:
            player.close()

    def test_player_dashboard_surfaces_leads_party_and_journal(self):
        player = self.login("player1", "player-one-password")
        try:
            self.post_player_form(
                player,
                f"/player/campaigns/{self.c1}/journal",
                f"/player/campaigns/{self.c1}/journal",
                {
                    "entry_type": "goal",
                    "visibility": "gm",
                    "title": "Find the lighthouse",
                    "body": "Follow the clue before next session.",
                    "session_id": "",
                    "linked_reveal_id": str(self.selected_reveal_id),
                },
            )
            page = player.get(f"/player/campaigns/{self.c1}").text
            self.assertIn("Leads &amp; Quests", page)
            self.assertIn("Revealed Quest", page)
            self.assertIn("Party", page)
            self.assertIn("Avery", page)
            self.assertIn("Other Player Character", page)
            self.assertIn("Find the lighthouse", page)
            self.assertNotIn("THREAD_SECRET_SENTINEL", page)
        finally:
            player.close()

    def test_campaign_delete_cleans_memberships_reveals_audiences_and_journal(self):
        with Session(database.engine) as db:
            player = db.exec(select(User).where(User.username == "player1")).one()
            db.add(PlayerJournalEntry(
                campaign_id=self.c1,
                author_user_id=player.id,
                author_display_name=player.display_name,
                entry_type="note",
                visibility="gm",
                body="Delete with campaign.",
            ))
            db.commit()
            delete_campaign_cascade(db, self.c1)

        with Session(database.engine) as db:
            self.assertIsNone(db.get(Campaign, self.c1))
            self.assertFalse(db.exec(select(CampaignMembership).where(CampaignMembership.campaign_id == self.c1)).all())
            self.assertFalse(db.exec(select(PlayerReveal).where(PlayerReveal.campaign_id == self.c1)).all())
            self.assertFalse(db.exec(select(PlayerJournalEntry).where(PlayerJournalEntry.campaign_id == self.c1)).all())
            self.assertFalse(db.exec(select(RevealAudience)).all())

    def test_campaign_backup_includes_player_journal(self):
        with Session(database.engine) as db:
            player = db.exec(select(User).where(User.username == "player1")).one()
            db.add(PlayerJournalEntry(
                campaign_id=self.c1,
                author_user_id=player.id,
                author_display_name=player.display_name,
                entry_type="note",
                visibility="gm",
                title="BACKUP_JOURNAL_SENTINEL",
                body="Preserve this campaign memory.",
            ))
            db.commit()
            payload = export_campaign_json(db, self.c1)
        self.assertTrue(payload["player_journal"])
        self.assertEqual(payload["player_journal"][0]["title"], "BACKUP_JOURNAL_SENTINEL")


if __name__ == "__main__":
    unittest.main()
