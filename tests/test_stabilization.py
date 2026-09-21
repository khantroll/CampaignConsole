"""Tests for campaign intelligence (Phase 2)."""

import os
import unittest
import unittest.mock
from types import SimpleNamespace

from app.services.campaign_intelligence import (
    _presence_workspace_flag,
    _thread_workspace_flag,
    build_workspace_intelligence,
    find_dormant_threads,
    get_intelligence_gap,
    is_active_thread_status,
)
from app.services.entity_session_presence import EntitySessionPresenceIndex


class CampaignIntelligenceTests(unittest.TestCase):
    def test_is_active_thread_status(self):
        self.assertTrue(is_active_thread_status("Active"))
        self.assertFalse(is_active_thread_status("Resolved"))

    def test_entity_history_from_index(self):
        index = EntitySessionPresenceIndex.__new__(EntitySessionPresenceIndex)
        index.sessions_by_id = {
            1: SimpleNamespace(id=1, title="S1", date="2026-01-01"),
            2: SimpleNamespace(id=2, title="S2", date="2026-02-01"),
            3: SimpleNamespace(id=3, title="S3", date="2026-03-01"),
        }
        index.rank = {1: 0, 2: 1, 3: 2}
        index._entity_sessions = {"npcs": {7: [3, 1, 2]}}

        history = index.presence("npcs", 7)
        self.assertEqual(history["first"].id, 1)
        self.assertEqual(history["last"].id, 3)
        self.assertEqual(history["session_count"], 3)

        ordered_ids = sorted([3, 1, 2], key=lambda sid: index.rank.get(sid, 9999))
        sessions = [index.sessions_by_id[sid] for sid in ordered_ids]
        self.assertEqual([s.id for s in sessions], [1, 2, 3])

    def test_presence_workspace_flag_for_locations(self):
        index = EntitySessionPresenceIndex.__new__(EntitySessionPresenceIndex)
        index.sessions_by_id = {
            1: SimpleNamespace(id=1, title="S1", date="2026-01-01"),
            2: SimpleNamespace(id=2, title="S2", date="2026-02-01"),
        }
        index.rank = {1: 0, 2: 1}
        index._entity_sessions = {
            "locations": {
                10: [1],
                11: [1, 2],
            }
        }

        self.assertEqual(_presence_workspace_flag(index, "locations", 10, 1), "new")
        self.assertEqual(_presence_workspace_flag(index, "locations", 11, 2), "returning")
        self.assertIsNone(_presence_workspace_flag(index, "locations", 11, 1))

    def test_thread_workspace_flag_dormant_and_unlinked(self):
        index = EntitySessionPresenceIndex.__new__(EntitySessionPresenceIndex)
        index.sessions_by_id = {
            1: SimpleNamespace(id=1, title="S1"),
            2: SimpleNamespace(id=2, title="S2"),
            3: SimpleNamespace(id=3, title="S3"),
        }
        index.rank = {1: 0, 2: 1, 3: 2}
        index._entity_sessions = {"threads": {5: [1]}}
        thread = SimpleNamespace(id=5, status="Active")

        self.assertEqual(_thread_workspace_flag(index, thread, 3, gap=2), "dormant")
        self.assertEqual(_thread_workspace_flag(index, thread, 1, gap=2), "new")

        unlinked = SimpleNamespace(id=9, status="Active")
        self.assertEqual(_thread_workspace_flag(index, unlinked, 3, gap=2), "unlinked")

    def test_build_workspace_intelligence_prep_gap(self):
        index = EntitySessionPresenceIndex.__new__(EntitySessionPresenceIndex)
        index.sessions_by_id = {1: SimpleNamespace(id=1, title="S1")}
        index.rank = {1: 0}
        index._entity_sessions = {"npcs": {}, "locations": {}, "threads": {}}

        session_notes_only = SimpleNamespace(
            id=1,
            title="S1",
            notes="Has notes.",
            next_session_prep=None,
            analysis=None,
            analysis_raw=None,
        )
        with unittest.mock.patch(
            "app.services.campaign_intelligence._campaign_session_index",
            return_value=index,
        ), unittest.mock.patch(
            "app.services.campaign_intelligence.session_has_analysis",
            return_value=False,
        ):
            intel = build_workspace_intelligence(
                None,
                1,
                session_notes_only,
                linked_npcs=[],
                linked_locations=[],
                linked_factions=[],
                linked_items=[],
                linked_threads=[],
            )
        self.assertEqual(intel["prep_gap"], "needs_analysis")

        session_analyzed = SimpleNamespace(
            id=1,
            title="S1",
            notes="Has notes.",
            next_session_prep=None,
            analysis="Done.",
            analysis_raw='{"x":1}',
        )
        with unittest.mock.patch(
            "app.services.campaign_intelligence._campaign_session_index",
            return_value=index,
        ), unittest.mock.patch(
            "app.services.campaign_intelligence.session_has_analysis",
            return_value=True,
        ):
            intel = build_workspace_intelligence(
                None,
                1,
                session_analyzed,
                linked_npcs=[],
                linked_locations=[],
                linked_factions=[],
                linked_items=[],
                linked_threads=[],
            )
        self.assertEqual(intel["prep_gap"], "needs_prep")

    def test_get_intelligence_gap(self):
        with unittest.mock.patch.dict(os.environ, {"INTELLIGENCE_GAP": "3"}):
            self.assertEqual(get_intelligence_gap(), 3)
        with unittest.mock.patch.dict(os.environ, {"INTELLIGENCE_GAP": "0"}):
            self.assertEqual(get_intelligence_gap(), 1)
        env = os.environ.copy()
        env.pop("INTELLIGENCE_GAP", None)
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(get_intelligence_gap(), 2)


if __name__ == "__main__":
    unittest.main()
