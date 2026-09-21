"""Tests for Mission Control UI helpers."""

import unittest

from app.services.mission_control_ui import (
    append_return_to,
    redirect_after_entity_save,
    resolve_workspace_mode,
    safe_return_to,
    session_id_from_return_to,
    workspace_needs_canonical_redirect,
    workspace_url,
)


class MissionControlUiTests(unittest.TestCase):
    def test_safe_return_to_accepts_internal_paths(self):
        self.assertEqual(safe_return_to("/campaigns/1/workspace?session_id=2"), "/campaigns/1/workspace?session_id=2")

    def test_safe_return_to_rejects_external_urls(self):
        self.assertIsNone(safe_return_to("https://evil.example/phish"))
        self.assertIsNone(safe_return_to("//evil.example/phish"))

    def test_workspace_url_builds_query(self):
        self.assertEqual(
            workspace_url(3, session_id=7, mode="run"),
            "/campaigns/3/workspace?session_id=7&mode=run",
        )

    def test_append_return_to(self):
        url = append_return_to("/campaigns/1/npcs/2/edit", "/campaigns/1/workspace?session_id=3")
        self.assertIn("return_to=", url)
        self.assertIn("workspace", url)

    def test_redirect_after_entity_save_honors_return_to(self):
        target = redirect_after_entity_save(1, "/campaigns/1/workspace?session_id=2&mode=prep")
        self.assertEqual(target, "/campaigns/1/workspace?session_id=2&mode=prep")

    def test_redirect_after_entity_save_defaults_to_lore_board(self):
        self.assertEqual(redirect_after_entity_save(5, None), "/campaigns/5")

    def test_session_id_from_return_to_workspace_url(self):
        self.assertEqual(
            session_id_from_return_to("/campaigns/2/workspace?session_id=9&mode=prep", 2),
            9,
        )

    def test_session_id_from_return_to_session_workflow_url(self):
        self.assertEqual(session_id_from_return_to("/campaigns/2/sessions/11", 2), 11)

    def test_session_id_from_return_to_rejects_other_campaign(self):
        self.assertIsNone(session_id_from_return_to("/campaigns/99/sessions/11", 2))

    def test_resolve_workspace_mode_prefers_explicit(self):
        self.assertEqual(resolve_workspace_mode(None, 1, "run"), "run")

    def test_workspace_needs_canonical_redirect_when_mode_missing(self):
        from types import SimpleNamespace

        request = SimpleNamespace(
            query_params={"session_id": "3"},
        )
        session = SimpleNamespace(id=3)
        self.assertTrue(workspace_needs_canonical_redirect(request, session, "run"))


if __name__ == "__main__":
    unittest.main()
