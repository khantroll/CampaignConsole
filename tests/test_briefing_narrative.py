"""Tests for briefing narrative (P3)."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.models import Campaign
from app.services.briefing_narrative import (
    build_local_briefing_narrative,
    generate_ai_briefing_narrative,
)


class BriefingNarrativeTests(unittest.TestCase):
    def test_local_narrative_mentions_current_and_attention(self):
        campaign = Campaign(id=1, name="Test Campaign", system="D&D")
        briefing = {
            "current_session": SimpleNamespace(title="Session Three", date="2026-03-01"),
            "returning_npcs": [{"npc": SimpleNamespace(name="Guide")}],
            "signals": {"dormant_count": 1, "stale_count": 2},
            "next_session": SimpleNamespace(title="Session Four"),
            "dashboard_summary": {"session_count": 3},
        }
        text = build_local_briefing_narrative(campaign, briefing)
        self.assertIn("Session Three", text)
        self.assertIn("Guide", text)
        self.assertIn("dormant thread", text)
        self.assertIn("Session Four", text)

    def test_local_narrative_all_clear_when_no_signals(self):
        campaign = Campaign(id=1, name="Quiet Campaign")
        briefing = {
            "current_session": SimpleNamespace(title="Latest", date=None),
            "returning_npcs": [],
            "signals": {"dormant_count": 0, "stale_count": 0},
            "dashboard_summary": {"session_count": 2},
        }
        text = build_local_briefing_narrative(campaign, briefing)
        self.assertIn("No dormant threads", text)

    @patch("app.services.briefing_narrative.generate", return_value="The party prepares for the next leg of the journey.")
    @patch("app.services.briefing_narrative.provider_available", return_value=True)
    def test_generate_ai_briefing_narrative(self, _available, _generate):
        campaign = Campaign(id=1, name="AI Campaign")
        briefing = {
            "current_session": SimpleNamespace(title="S1", date="2026-01-01"),
            "signals": {},
            "dashboard_summary": {"session_count": 1},
        }
        text, error = generate_ai_briefing_narrative(campaign, briefing)
        self.assertIsNone(error)
        self.assertIn("party prepares", text or "")


if __name__ == "__main__":
    unittest.main()
