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
from app.models import AppSession, Campaign, CampaignMembership, NPC, User


class AuthAuthorizationTests(unittest.TestCase):
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
        self.client = TestClient(main.app, raise_server_exceptions=True, follow_redirects=False)

    def tearDown(self):
        self.client.close()
        database.engine.dispose()
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def bootstrap(self, username="Admin", password="admin-password-123"):
        return self.client.post(
            "/bootstrap",
            data={"username": username, "display_name": username, "password": password},
        )

    def csrf(self):
        response = self.client.get("/")
        match = re.search(r'<meta name="csrf-token" content="([^"]+)"', response.text)
        self.assertIsNotNone(match)
        return match.group(1)

    def post_auth(self, url, data=None):
        payload = dict(data or {})
        payload["_csrf"] = self.csrf()
        return self.client.post(url, data=payload)

    def csrf_for(self, client):
        response = client.get("/")
        match = re.search(r'<meta name="csrf-token" content="([^"]+)"', response.text)
        self.assertIsNotNone(match)
        return match.group(1)

    def post_with_csrf(self, client, url, data=None):
        payload = dict(data or {})
        payload["_csrf"] = self.csrf_for(client)
        return client.post(url, data=payload)

    def login_client(self, username, password):
        client = TestClient(main.app, follow_redirects=False)
        response = client.post(
            "/login",
            data={"username": username, "password": password, "next": "/"},
        )
        self.assertEqual(response.status_code, 303)
        return client

    def test_bootstrap_normalizes_hashes_and_owns_existing_campaign(self):
        with Session(database.engine) as db:
            campaign = Campaign(name="Legacy", system="Test")
            db.add(campaign)
            db.commit()
            db.refresh(campaign)
            campaign_id = campaign.id
        response = self.bootstrap("ADMIN")
        self.assertEqual(response.status_code, 303)
        with Session(database.engine) as db:
            user = db.exec(select(User)).one()
            self.assertEqual(user.username, "admin")
            self.assertTrue(user.is_admin)
            self.assertNotEqual(user.password_hash, "admin-password-123")
            membership = db.exec(select(CampaignMembership).where(
                CampaignMembership.user_id == user.id,
                CampaignMembership.campaign_id == campaign_id,
            )).one()
            self.assertEqual(membership.role, "owner")

    def test_bootstrap_is_one_time_and_duplicate_username_rejected(self):
        self.bootstrap()
        second = self.client.post(
            "/bootstrap",
            data={"username": "second", "display_name": "Second", "password": "second-password-123"},
        )
        self.assertEqual(second.status_code, 403)
        duplicate = self.post_auth(
            "/admin/users",
            {"username": "  ADMIN  ", "display_name": "Duplicate", "temporary_password": "another-password-123"},
        )
        self.assertEqual(duplicate.status_code, 409)

    def test_login_logout_disabled_user_and_csrf(self):
        self.bootstrap()
        no_csrf = self.client.post("/campaigns", data={"name": "No CSRF"})
        self.assertEqual(no_csrf.status_code, 403)
        logout = self.post_auth("/logout")
        self.assertEqual(logout.status_code, 303)
        self.assertEqual(self.client.get("/").status_code, 303)
        login = self.client.post(
            "/login", data={"username": "ADMIN", "password": "admin-password-123", "next": "/"}
        )
        self.assertEqual(login.status_code, 303)
        with Session(database.engine) as db:
            user = db.exec(select(User)).one()
            user.is_active = False
            db.add(user)
            db.commit()
        self.assertEqual(self.client.get("/").status_code, 303)
        with Session(database.engine) as db:
            self.assertEqual(len(db.exec(select(AppSession)).all()), 0)

    def test_password_change_invalidates_old_session(self):
        self.bootstrap()
        old_token = self.client.cookies.get("campaign_console_session")
        changed = self.post_auth(
            "/account/password",
            {"current_password": "admin-password-123", "new_password": "new-password-456"},
        )
        self.assertEqual(changed.status_code, 303)
        new_token = self.client.cookies.get("campaign_console_session")
        self.assertNotEqual(old_token, new_token)
        other = TestClient(main.app, follow_redirects=False)
        other.cookies.set("campaign_console_session", old_token)
        self.assertEqual(other.get("/").status_code, 303)
        other.close()

    def test_gm_allowed_player_and_unrelated_denied_and_cross_campaign_id_safe(self):
        self.bootstrap()
        one = self.post_auth("/campaigns", {"name": "One"})
        two = self.post_auth("/campaigns", {"name": "Two"})
        one_id = int(re.search(r"/campaigns/(\d+)", one.headers["location"]).group(1))
        two_id = int(re.search(r"/campaigns/(\d+)", two.headers["location"]).group(1))
        with Session(database.engine) as db:
            gm = User(username="gm", display_name="GM", password_hash=hash_password("gm-password-123"))
            player = User(username="player", display_name="Player", password_hash=hash_password("player-password-123"))
            stranger = User(username="stranger", display_name="Stranger", password_hash=hash_password("stranger-password-123"))
            db.add(gm); db.add(player); db.add(stranger); db.commit()
            db.refresh(gm); db.refresh(player)
            db.add(CampaignMembership(campaign_id=one_id, user_id=gm.id, role="gm"))
            db.add(CampaignMembership(campaign_id=one_id, user_id=player.id, role="player"))
            npc = NPC(campaign_id=two_id, name="Other NPC")
            db.add(npc); db.commit(); db.refresh(npc)
            npc_id = npc.id

        for username, password, expected in [
            ("gm", "gm-password-123", 200),
            ("player", "player-password-123", 403),
            ("stranger", "stranger-password-123", 403),
        ]:
            client = TestClient(main.app, follow_redirects=False)
            self.assertEqual(client.post(
                "/login", data={"username": username, "password": password, "next": "/"}
            ).status_code, 303)
            self.assertEqual(client.get(f"/campaigns/{one_id}").status_code, expected)
            client.close()

        cross = self.client.get(f"/campaigns/{one_id}/npcs/{npc_id}/edit")
        self.assertEqual(cross.status_code, 303)

    def test_player_only_user_cannot_create_campaign_and_no_row_is_added(self):
        self.bootstrap()
        seed = self.post_auth("/campaigns", {"name": "Seed"})
        seed_id = int(re.search(r"/campaigns/(\d+)", seed.headers["location"]).group(1))
        with Session(database.engine) as db:
            player = User(
                username="createplayer",
                display_name="Create Player",
                password_hash=hash_password("player-create-password"),
            )
            db.add(player)
            db.commit()
            db.refresh(player)
            db.add(CampaignMembership(campaign_id=seed_id, user_id=player.id, role="player"))
            db.commit()
            before = len(db.exec(select(Campaign)).all())

        player_client = self.login_client("createplayer", "player-create-password")
        response = self.post_with_csrf(player_client, "/campaigns", {"name": "Forbidden Campaign"})
        self.assertEqual(response.status_code, 403)
        with Session(database.engine) as db:
            after = len(db.exec(select(Campaign)).all())
            forbidden = db.exec(select(Campaign).where(Campaign.name == "Forbidden Campaign")).first()
        self.assertEqual(after, before)
        self.assertIsNone(forbidden)
        self.assertNotIn("New Campaign", player_client.get("/").text)
        player_client.close()

    def test_admin_owner_and_gm_can_create_campaigns(self):
        self.bootstrap()
        seed = self.post_auth("/campaigns", {"name": "Seed for Creators"})
        seed_id = int(re.search(r"/campaigns/(\d+)", seed.headers["location"]).group(1))

        with Session(database.engine) as db:
            owner = User(
                username="creatorowner",
                display_name="Creator Owner",
                password_hash=hash_password("owner-create-password"),
            )
            gm = User(
                username="creatorgm",
                display_name="Creator GM",
                password_hash=hash_password("gm-create-password"),
            )
            db.add(owner)
            db.add(gm)
            db.commit()
            db.refresh(owner)
            db.refresh(gm)
            db.add(CampaignMembership(campaign_id=seed_id, user_id=owner.id, role="owner"))
            db.add(CampaignMembership(campaign_id=seed_id, user_id=gm.id, role="gm"))
            db.commit()
            owner_id = owner.id
            gm_id = gm.id

        admin_create = self.post_auth("/campaigns", {"name": "Admin Created"})
        self.assertEqual(admin_create.status_code, 303)

        owner_client = self.login_client("creatorowner", "owner-create-password")
        owner_create = self.post_with_csrf(owner_client, "/campaigns", {"name": "Owner Created"})
        self.assertEqual(owner_create.status_code, 303)
        owner_client.close()

        gm_client = self.login_client("creatorgm", "gm-create-password")
        gm_create = self.post_with_csrf(gm_client, "/campaigns", {"name": "GM Created"})
        self.assertEqual(gm_create.status_code, 303)
        gm_client.close()

        with Session(database.engine) as db:
            owner_campaign = db.exec(select(Campaign).where(Campaign.name == "Owner Created")).one()
            gm_campaign = db.exec(select(Campaign).where(Campaign.name == "GM Created")).one()
            owner_membership = db.exec(select(CampaignMembership).where(
                CampaignMembership.campaign_id == owner_campaign.id,
                CampaignMembership.user_id == owner_id,
            )).one()
            gm_membership = db.exec(select(CampaignMembership).where(
                CampaignMembership.campaign_id == gm_campaign.id,
                CampaignMembership.user_id == gm_id,
            )).one()
        self.assertEqual(owner_membership.role, "owner")
        self.assertEqual(gm_membership.role, "owner")

    def test_rules_lookup_requires_owner_or_gm_membership(self):
        self.bootstrap()
        created = self.post_auth("/campaigns", {"name": "Rules Campaign", "system": "Test"})
        campaign_id = int(re.search(r"/campaigns/(\d+)", created.headers["location"]).group(1))

        with Session(database.engine) as db:
            owner = User(
                username="rulesowner",
                display_name="Rules Owner",
                password_hash=hash_password("rules-owner-password"),
            )
            gm = User(
                username="rulesgm",
                display_name="Rules GM",
                password_hash=hash_password("rules-gm-password"),
            )
            player = User(
                username="rulesplayer",
                display_name="Rules Player",
                password_hash=hash_password("rules-player-password"),
            )
            stranger = User(
                username="rulesstranger",
                display_name="Rules Stranger",
                password_hash=hash_password("rules-stranger-password"),
            )
            db.add(owner)
            db.add(gm)
            db.add(player)
            db.add(stranger)
            db.commit()
            db.refresh(owner)
            db.refresh(gm)
            db.refresh(player)
            db.add(CampaignMembership(campaign_id=campaign_id, user_id=owner.id, role="owner"))
            db.add(CampaignMembership(campaign_id=campaign_id, user_id=gm.id, role="gm"))
            db.add(CampaignMembership(campaign_id=campaign_id, user_id=player.id, role="player"))
            db.commit()

        clients = {
            "owner": self.login_client("rulesowner", "rules-owner-password"),
            "gm": self.login_client("rulesgm", "rules-gm-password"),
            "player": self.login_client("rulesplayer", "rules-player-password"),
            "stranger": self.login_client("rulesstranger", "rules-stranger-password"),
        }
        try:
            self.assertEqual(
                clients["owner"].get(f"/api/workspace/rules-lookup?campaign_id={campaign_id}&text=test").status_code,
                200,
            )
            self.assertEqual(
                clients["gm"].get(f"/api/workspace/rules-lookup?campaign_id={campaign_id}&text=test").status_code,
                200,
            )
            self.assertEqual(
                clients["player"].get(f"/api/workspace/rules-lookup?campaign_id={campaign_id}&text=test").status_code,
                403,
            )
            self.assertEqual(
                clients["stranger"].get(f"/api/workspace/rules-lookup?campaign_id={campaign_id}&text=test").status_code,
                403,
            )
            self.assertEqual(
                clients["owner"].get("/api/workspace/rules-lookup?campaign_id=999999&text=test").status_code,
                403,
            )
        finally:
            for client in clients.values():
                client.close()

    def test_failed_login_is_throttled_at_boundary(self):
        self.bootstrap()
        self.post_auth("/logout")
        for _ in range(5):
            response = self.client.post(
                "/login",
                data={"username": "admin", "password": "wrong-password", "next": "/"},
            )
            self.assertEqual(response.status_code, 401)
        throttled = self.client.post(
            "/login",
            data={"username": "admin", "password": "wrong-password", "next": "/"},
        )
        self.assertEqual(throttled.status_code, 429)

    def test_player_denied_search_export_ingest_and_ai_routes(self):
        self.bootstrap()
        created = self.post_auth("/campaigns", {"name": "Protected"})
        campaign_id = int(re.search(r"/campaigns/(\d+)", created.headers["location"]).group(1))
        with Session(database.engine) as db:
            player = User(
                username="player2",
                display_name="Player Two",
                password_hash=hash_password("player-password-456"),
            )
            db.add(player)
            db.commit()
            db.refresh(player)
            db.add(CampaignMembership(campaign_id=campaign_id, user_id=player.id, role="player"))
            db.commit()

        client = TestClient(main.app, follow_redirects=False)
        self.assertEqual(
            client.post(
                "/login",
                data={"username": "player2", "password": "player-password-456", "next": "/"},
            ).status_code,
            303,
        )
        for path in (
            f"/campaigns/{campaign_id}/search",
            f"/campaigns/{campaign_id}/ingest",
            f"/campaigns/{campaign_id}/backup/json",
            f"/campaigns/{campaign_id}/ai/review",
        ):
            self.assertEqual(client.get(path).status_code, 403, path)
        client.close()


    def test_export_omits_auth_secrets(self):
        self.bootstrap()
        created = self.post_auth("/campaigns", {"name": "Export Safe"})
        campaign_id = int(re.search(r"/campaigns/(\d+)", created.headers["location"]).group(1))
        response = self.client.get(f"/campaigns/{campaign_id}/backup/json")
        self.assertEqual(response.status_code, 200)
        body = response.text.lower()
        self.assertNotIn("password_hash", body)
        self.assertNotIn("token_hash", body)


if __name__ == "__main__":
    unittest.main()
