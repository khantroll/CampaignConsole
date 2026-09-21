"""Tests for workspace rules lookup and RuleIndexerService text matching."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

import app.database as database
import app.main as main
from app.models import Campaign
from app.services import rule_indexer as rule_indexer_module
from app.services.rule_indexer import RuleIndexerService


class RuleIndexerTextLookupTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        systems_root = Path(self.temp_dir.name)
        profile_dir = systems_root / "DND5E"
        profile_dir.mkdir()
        (profile_dir / "rules.md").write_text(
            "## Fireball\nCast a fireball.\n\n## Exhaustion\nExhaustion levels apply.\n",
            encoding="utf-8",
        )
        self.indexer = RuleIndexerService(systems_root=systems_root)
        self.indexer.load()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_resolve_system_id_accepts_aliases(self):
        self.assertEqual(self.indexer.resolve_system_id("D&D 5e"), "DND5E")
        self.assertEqual(self.indexer.resolve_system_id("dnd5e"), "DND5E")
        self.assertIsNone(self.indexer.resolve_system_id("Unknown RPG"))

    def test_lookup_rules_in_text_matches_mentioned_rules(self):
        snippets = self.indexer.lookup_rules_in_text(
            "DND5E",
            "The wizard casts Fireball while suffering from Exhaustion.",
        )
        self.assertEqual(len(snippets), 2)
        joined = "\n".join(snippets)
        self.assertIn("## Fireball", joined)
        self.assertIn("## Exhaustion", joined)

    def test_lookup_rules_in_text_returns_empty_for_unknown_profile(self):
        self.assertEqual(self.indexer.lookup_rules_in_text("No Such System", "Fireball"), [])


class WorkspaceRulesLookupEndpointTests(unittest.TestCase):
    def setUp(self):
        self.systems_dir = tempfile.TemporaryDirectory()
        systems_root = Path(self.systems_dir.name)
        profile_dir = systems_root / "DND5E"
        profile_dir.mkdir()
        (profile_dir / "rules.md").write_text("## Fireball\nCast a fireball.\n", encoding="utf-8")

        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.db_fd)
        database.DB_FILE = Path(self.db_path)
        database.engine = create_engine(
            f"sqlite:///{self.db_path}",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(database.engine)

        self.indexer = RuleIndexerService(systems_root=systems_root)
        self.indexer.load()
        rule_indexer_module.rule_indexer = self.indexer

        self.client = TestClient(main.app, raise_server_exceptions=True)

    def tearDown(self):
        self.client.close()
        rule_indexer_module.rule_indexer = None
        database.engine.dispose()
        self.systems_dir.cleanup()
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_rules_lookup_endpoint_returns_matching_snippets(self):
        with Session(database.engine) as db:
            campaign = Campaign(name="Rules Test", system="DND5E")
            db.add(campaign)
            db.commit()
            db.refresh(campaign)
            campaign_id = campaign.id

        response = self.client.get(
            "/api/workspace/rules-lookup",
            params={
                "campaign_id": campaign_id,
                "text": "The sorcerer casts Fireball at the goblins.",
            },
        )
        self.assertEqual(response.status_code, 200)
        snippets = response.json()
        self.assertIsInstance(snippets, list)
        self.assertTrue(any("## Fireball" in snippet for snippet in snippets))

    def test_rules_lookup_endpoint_returns_empty_for_unknown_system(self):
        with Session(database.engine) as db:
            campaign = Campaign(name="Rules Test", system="Test System")
            db.add(campaign)
            db.commit()
            db.refresh(campaign)
            campaign_id = campaign.id

        response = self.client.get(
            "/api/workspace/rules-lookup",
            params={"campaign_id": campaign_id, "text": "Fireball"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_render_markdown_endpoint_returns_html(self):
        response = self.client.post(
            "/api/workspace/render-markdown",
            json={"snippets": ["## Fireball\nDeal damage."]},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("html", payload)
        self.assertIn("<h2>Fireball</h2>", payload["html"][0])


if __name__ == "__main__":
    unittest.main()
