"""Tests for Campaign Briefing Phase 1 section builders."""

from __future__ import annotations

import unittest

from sqlmodel import Session, select

import app.database as database
from app.models import NPC, PlotThread, SessionModel
from app.services.briefing_sections import (
    build_campaign_briefing_sections,
    build_unresolved_questions_section,
)
from app.services.campaign_intelligence import load_campaign_briefing_data
from app.services.entity_health import prepare_entity_lists
from tests.test_app import CampaignConsoleSmokeTests


class BriefingSectionsUnitTests(unittest.TestCase):
    def test_unresolved_questions_from_thread_details(self):
        thread = PlotThread(
            campaign_id=1,
            title="Mystery",
            status="Active",
            details="Who is The Widow?\nSome notes.",
        )
        rows = build_unresolved_questions_section([], [thread])
        self.assertTrue(any("Widow" in row["text"] for row in rows))


class BriefingSectionsIntegrationTests(CampaignConsoleSmokeTests):
    def test_build_campaign_briefing_sections_populated(self):
        campaign_id = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign_id}/sessions",
            data={
                "title": "Session One",
                "date": "2026-01-01",
                "notes": "Party explored the mine.",
                "player_recap": "We found a sealed door.",
            },
        )
        self.client.post(
            f"/campaigns/{campaign_id}/threads",
            data={
                "title": "Mine Shipments",
                "status": "Active",
                "importance": "Critical",
                "details": "Why are shipments heading to the mines?",
            },
        )
        self.client.post(
            f"/campaigns/{campaign_id}/npcs",
            data={"name": "Captain Vex", "role": "Guard", "description": "Leads the watch."},
        )

        with Session(database.engine) as db:
            session = db.exec(
                select(SessionModel).where(SessionModel.campaign_id == int(campaign_id))
            ).first()
            thread = db.exec(
                select(PlotThread).where(PlotThread.campaign_id == int(campaign_id))
            ).first()
            npc = db.exec(select(NPC).where(NPC.campaign_id == int(campaign_id))).first()
            self.client.post(
                f"/campaigns/{campaign_id}/sessions/{session.id}/edit",
                data={
                    "title": session.title,
                    "date": session.date or "",
                    "notes": session.notes or "",
                    "player_recap": "We found a sealed door.",
                    "selected_plot_threads": [str(thread.id)],
                    "selected_npcs": [str(npc.id)],
                },
            )

            db.expire_all()
            _health, entity_context = prepare_entity_lists(db, int(campaign_id))
            entity_lists = {
                "npcs": entity_context["npcs"],
                "locations": entity_context["locations"],
                "factions": entity_context["factions"],
                "items": entity_context["items"],
                "threads": entity_context["threads"],
            }
            sorted_sessions = db.exec(
                select(SessionModel)
                .where(SessionModel.campaign_id == int(campaign_id))
                .order_by(SessionModel.id)
            ).all()
            sections = build_campaign_briefing_sections(
                db,
                int(campaign_id),
                sorted_sessions=sorted_sessions,
                entity_lists=entity_lists,
                dashboard_summary={"needs_attention": []},
                signals={"stale_count": 0},
                current_session=sorted_sessions[-1] if sorted_sessions else None,
                completeness_overview=entity_context["completeness_overview"],
            )

        self.assertIsNotNone(sections["last_session"])
        self.assertEqual(sections["last_session"]["session"].title, "Session One")
        self.assertIn("sealed door", sections["last_session"]["recap_preview"].lower())
        self.assertTrue(sections["active_threads"])
        self.assertEqual(sections["active_threads"][0]["thread"].title, "Mine Shipments")
        self.assertTrue(sections["important_npcs"])
        self.assertTrue(any("mines" in q["text"].lower() for q in sections["unresolved_questions"]))
        self.assertIn("campaign_health", sections)
        self.assertTrue(sections["quick_actions"])

    def test_load_campaign_briefing_data_includes_sections_without_ai(self):
        campaign_id = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign_id}/sessions",
            data={"title": "Only Session", "date": "2026-01-01", "notes": "Notes."},
        )
        with Session(database.engine) as db:
            briefing = load_campaign_briefing_data(db, int(campaign_id))
        self.assertIn("sections", briefing)
        self.assertIn("last_session", briefing["sections"])
        self.assertIn("needs_attention", briefing["sections"])

    def test_brief_me_page_shows_all_phase1_sections(self):
        campaign_id = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign_id}/sessions",
            data={"title": "Latest Session", "date": "2026-06-01", "notes": "Played."},
        )
        response = self.client.get(f"/campaigns/{campaign_id}/briefing")
        self.assertEqual(response.status_code, 200)
        for heading in (
            b"Last Session",
            b"Active Plot Threads",
            b"Important NPCs",
            b"Recent Developments",
            b"Unresolved Questions",
            b"Dormant Threads",
            b"Needs Attention",
        ):
            self.assertIn(heading, response.content)
        self.assertIn(b"Latest Session", response.content)

    def test_lore_board_shows_brief_me_entry(self):
        campaign_id = self._create_campaign()
        response = self.client.get(f"/campaigns/{campaign_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Brief Me", response.content)


if __name__ == "__main__":
    unittest.main()
