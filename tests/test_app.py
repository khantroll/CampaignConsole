import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

import app.database as database
import app.main as main
from app.llm import llm_available, provider_available
from app.services.provider_router import (
    SMOKE_TEST_PROMPT,
    _parse_chat_completion_body,
    _parse_gemini_body,
    gemini_is_disabled,
    get_configured_model,
    get_endpoint_url,
)
from app.models import Campaign, Faction, Item, Location, LoreChunk, NPC, PlayerCharacterNote, PlotThread, SessionModel
from app.services.analysis import (
    apply_parsed_ai_output,
    compose_analysis_display,
    extract_player_recap,
    parse_ai_analysis,
    parse_ai_analysis_sections,
    prep_overwrite_requires_confirmation,
)
from app.services.llm_json import strip_markdown_fences
from app.services.campaign_deletion import delete_campaign_cascade
from app.services.embeddings import embed_texts, get_active_embedding_provider
from app.services.lore_index import rebuild_lore_index
from app.services.env_config import get_llm_settings_for_form, parse_env_file, update_env_file
from app.services.ingestion import (
    build_candidate_link_options,
    build_entity_relationship_options,
    build_location_link_options,
    build_unclassified_character_options,
    classify_characters,
    extract_candidates_from_notes,
    normalize_extraction,
    parse_entity_links,
    prepare_review_candidates,
)
from app.services.entity_health import CampaignEntityHealth, prepare_entity_lists
from app.services.location_admin import merge_locations
from app.services.location_classification import (
    LOCATION_TYPE_MAJOR,
    LOCATION_TYPE_SCENE,
    LOCATION_TYPE_SUB,
    classify_location,
    is_generic_scene_feature,
)


class CampaignConsoleSmokeTests(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.db_fd)
        database.DB_FILE = Path(self.db_path)
        database.engine = create_engine(
            f"sqlite:///{self.db_path}",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(database.engine)
        self.client = TestClient(
            main.app,
            raise_server_exceptions=True,
            follow_redirects=False,
        )

    def tearDown(self):
        self.client.close()
        database.engine.dispose()
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_campaign_creation(self):
        response = self.client.post(
            "/campaigns",
            data={"name": "Smoke Test Campaign", "system": "Test System", "description": "Smoke test."},
        )
        self.assertEqual(response.status_code, 303)
        self.assertIn("/campaigns/", response.headers["location"])

    def test_session_creation(self):
        campaign = self._create_campaign()
        response = self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={"title": "Session 1", "date": "2026-06-05", "notes": "First session notes."},
        )
        self.assertEqual(response.status_code, 303)

    def test_npc_creation(self):
        campaign = self._create_campaign()
        response = self.client.post(
            f"/campaigns/{campaign}/npcs",
            data={"name": "Test NPC", "role": "Guide", "description": "An important NPC."},
        )
        self.assertEqual(response.status_code, 303)

    def test_npc_edit_route(self):
        campaign = self._create_campaign()
        create_response = self.client.post(
            f"/campaigns/{campaign}/npcs",
            data={"name": "Edit NPC", "role": "Role", "description": "Before edit."},
        )
        self.assertEqual(create_response.status_code, 303)
        with Session(database.engine) as db:
            npc = db.exec(select(NPC).where(NPC.campaign_id == int(campaign))).first()
        self.assertIsNotNone(npc)
        response = self.client.get(f"/campaigns/{campaign}/npcs/{npc.id}/edit")
        self.assertEqual(response.status_code, 200)
        update_response = self.client.post(
            f"/campaigns/{campaign}/npcs/{npc.id}/edit",
            data={
                "name": "Edited NPC",
                "role": "Guide",
                "description": "After edit.",
                "world_status": "active",
                "current_location_id": "__custom__",
                "current_location_custom": "City",
                "relationship_to_party": "Friendly",
                "goals": "Help the party.",
                "secrets": "Unknown.",
            },
        )
        self.assertEqual(update_response.status_code, 303)

    def test_markdown_export_route(self):
        campaign = self._create_campaign()
        response = self.client.get(f"/campaigns/{campaign}/export/markdown")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "text/markdown; charset=utf-8")
        self.assertIn("# Smoke Test Campaign", response.text)

    def test_campaign_json_backup_route(self):
        campaign = self._create_campaign()
        create_npc = self.client.post(
            f"/campaigns/{campaign}/npcs",
            data={"name": "Backup NPC", "role": "Guide", "description": "For backup test."},
        )
        self.assertEqual(create_npc.status_code, 303)

        response = self.client.get(f"/campaigns/{campaign}/backup/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/json")
        payload = json.loads(response.content)
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["campaign"]["name"], "Smoke Test Campaign")
        self.assertEqual(len(payload["npcs"]), 1)
        self.assertEqual(payload["npcs"][0]["name"], "Backup NPC")

    def test_campaign_sqlite_backup_route(self):
        campaign = self._create_campaign()
        response = self.client.get(f"/campaigns/{campaign}/backup/db")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/x-sqlite3")

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp.write(response.content)
            tmp_path = tmp.name
        try:
            conn = sqlite3.connect(tmp_path)
            campaign_count = conn.execute("SELECT COUNT(*) FROM campaign").fetchone()[0]
            npc_count = conn.execute("SELECT COUNT(*) FROM npc").fetchone()[0]
            conn.close()
            self.assertEqual(campaign_count, 1)
            self.assertEqual(npc_count, 0)
        finally:
            os.unlink(tmp_path)

    def test_player_view_shows_recap_without_gm_notes(self):
        campaign = self._create_campaign()
        create_session = self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={
                "title": "Session 2",
                "date": "2026-06-06",
                "notes": "SECRET: the mayor is a dragon.",
            },
        )
        self.assertEqual(create_session.status_code, 303)
        with Session(database.engine) as db:
            session = db.exec(select(SessionModel).where(SessionModel.campaign_id == int(campaign))).first()
            session_id = session.id

        update_session = self.client.post(
            f"/campaigns/{campaign}/sessions/{session_id}/edit",
            data={
                "title": "Session 2",
                "date": "2026-06-06",
                "notes": "SECRET: the mayor is a dragon.",
                "player_recap": "The party explored the town square and met the mayor.",
                "recap": "Mayor is secretly a dragon.",
                "next_session_prep": "Plan the dragon reveal.",
            },
        )
        self.assertEqual(update_session.status_code, 303)

        response = self.client.get(f"/campaigns/{campaign}/sessions/{session_id}/player")
        self.assertEqual(response.status_code, 200)
        self.assertIn("explored the town square", response.text)
        self.assertNotIn("SECRET", response.text)
        self.assertNotIn("dragon reveal", response.text)

    def test_extract_player_recap_from_ai_markdown(self):
        markdown = "## Player-Facing Recap\nThey saved the village.\n\n## Private GM Recap\nThe cult is still active."
        self.assertEqual(extract_player_recap(markdown), "They saved the village.")

    def test_parse_ai_analysis_sections_extracts_fields(self):
        payload = """
=== PLAYER RECAP ===
The party met the mayor.

=== GM RECAP ===
The mayor is a dragon.

=== ANALYSIS ===
Player Choices:
- Accepted the mayor's invitation

=== NEXT SESSION PREP ===
(none)

=== NPC UPDATES ===
- Mayor seemed nervous

=== PLOT THREAD UPDATES ===
- Hidden tunnel discovered
"""
        parsed, error = parse_ai_analysis_sections(payload)
        self.assertIsNone(error)
        self.assertEqual(parsed["player_recap"], "The party met the mayor.")
        display = compose_analysis_display(parsed)
        self.assertIn("Accepted the mayor's invitation", display)
        self.assertIn("NPC Updates:", display)
        self.assertIn("Mayor seemed nervous", display)

    def test_parse_ai_analysis_sections_ignores_empty_none_sections(self):
        payload = """
=== PLAYER RECAP ===
Safe recap.

=== GM RECAP ===
(none)

=== ANALYSIS ===
Strong session pacing.

=== NEXT SESSION PREP ===

=== NPC UPDATES ===
none

=== PLOT THREAD UPDATES ===
"""
        parsed, error = parse_ai_analysis_sections(payload)
        self.assertIsNone(error)
        self.assertEqual(parsed["player_recap"], "Safe recap.")
        self.assertNotIn("gm_recap", parsed)

    def test_strip_markdown_fences_removes_json_fence(self):
        raw = "```json\n{\"ok\": true}\n```"
        self.assertEqual(strip_markdown_fences(raw), '{"ok": true}')

    def test_parse_ai_analysis_sections_finds_headers_with_prose(self):
        payload = (
            "Sure! Here is your analysis:\n\n"
            "=== PLAYER RECAP ===\nRecap\n\n"
            "=== GM RECAP ===\nGM\n\n"
            "=== ANALYSIS ===\nAnalysis body\n\n"
            "=== NEXT SESSION PREP ===\n(none)\n\n"
            "=== NPC UPDATES ===\n(none)\n\n"
            "=== PLOT THREAD UPDATES ===\n(none)\n"
        )
        parsed, error = parse_ai_analysis_sections(payload)
        self.assertIsNone(error)
        self.assertEqual(parsed["player_recap"], "Recap")

    def test_parse_ai_analysis_json_format(self):
        payload = json.dumps(
            {
                "player_recap": "Safe recap.",
                "gm_recap": "Full recap.",
                "analysis": "Strong pacing.",
                "next_session_prep": "",
                "npc_updates": ["Mayor seemed nervous"],
                "plot_thread_updates": [],
            }
        )
        parsed, error, parse_format, diagnostics = parse_ai_analysis(payload)
        self.assertIsNone(error)
        self.assertEqual(parse_format, "json")
        self.assertEqual(parsed["player_recap"], "Safe recap.")
        self.assertEqual(diagnostics["normalized_keys"], ["player_recap", "gm_recap", "analysis", "npc_updates"])
        display = compose_analysis_display(parsed)
        self.assertIn("Mayor seemed nervous", display)

    def test_plot_thread_updates_format_structured_dicts(self):
        payload = json.dumps(
            {
                "player_recap": "Recap.",
                "gm_recap": "GM recap.",
                "analysis": "Player Choices:\n- Investigated the keep",
                "plot_thread_updates": {
                    "Active Threads": [
                        {
                            "Thread": "Determine the fate of Corwin Hale",
                            "Status": "Ongoing",
                            "Notes": "Corwin's notebook suggests he was investigating Blackstone Keep.",
                        },
                        {
                            "Thread": "Decode the remainder of Corwin's notebook",
                            "Status": "Partially resolved",
                            "Notes": "Portions decoded reveal suspicious activity.",
                        },
                    ],
                    "New Threads": [
                        {
                            "Thread": "Uncover the purpose of the silver spyglass",
                            "Status": "New",
                            "Notes": "The spyglass may belong to Corwin.",
                        },
                    ],
                },
            }
        )
        parsed, error, parse_format, _diagnostics = parse_ai_analysis(payload)
        self.assertIsNone(error)
        display = compose_analysis_display(parsed)
        self.assertIn("Investigated the keep", display)
        self.assertIn("Active Threads:", display)
        self.assertIn("Determine the fate of Corwin Hale (Ongoing):", display)
        self.assertIn("Uncover the purpose of the silver spyglass (New):", display)
        self.assertNotIn("{'Thread':", display)
        self.assertNotIn('"Thread":', display)

    def test_parse_nested_player_recap_key_variants(self):
        for key in ("PLAYER RECAP", "Player Recap", "player_recap"):
            payload = json.dumps({key: {"Session Overview": ["foo", "bar"]}})
            parsed, error, parse_format, diagnostics = parse_ai_analysis(payload)
            self.assertIsNone(error, msg=key)
            self.assertEqual(parse_format, "json", msg=key)
            self.assertIn("Session Overview:", parsed["player_recap"], msg=key)
            self.assertIn("- foo", parsed["player_recap"], msg=key)
            self.assertEqual(diagnostics["raw_keys"], [key], msg=key)
            self.assertEqual(diagnostics["normalized_keys"], ["player_recap"], msg=key)
            self.assertEqual(diagnostics["finalized_keys"], ["player_recap"], msg=key)

    def test_parse_nested_player_recap_string_json_value(self):
        inner = {"Session Overview": ["foo", "bar"]}
        payload = json.dumps({"PLAYER RECAP": json.dumps(inner)})
        parsed, error, parse_format, _diagnostics = parse_ai_analysis(payload)
        self.assertIsNone(error)
        self.assertEqual(parse_format, "json")
        self.assertIn("Session Overview:", parsed["player_recap"])
        self.assertIn("- foo", parsed["player_recap"])
        self.assertNotIn('{"Session Overview"', parsed["player_recap"])

    def test_parse_nested_dicts_not_rejected_as_blob(self):
        payload = json.dumps(
            {
                "PLAYER RECAP": {"Session Overview": ["foo"]},
                "GM RECAP": {"Hidden Context": ["secret"]},
                "ANALYSIS": {"Player Choices": ["acted boldly"]},
            }
        )
        session = SessionModel(campaign_id=1, title="Session 1")
        result = apply_parsed_ai_output(
            session,
            payload,
            update_fields={"player_recap", "gm_recap", "analysis"},
            task_name="sessions/analyze",
            session_id=1,
            save_raw_on_failure=False,
        )
        self.assertTrue(result["fields_extracted"])
        self.assertEqual(result["updated_fields"], ["player_recap", "gm_recap", "analysis"])
        self.assertIn("Session Overview:", session.player_recap)
        self.assertIn("Hidden Context:", session.recap)
        self.assertIn("Player Choices:", session.analysis)

    def test_parse_ai_analysis_python_dict_format(self):
        payload = """{
    'PLAYER RECAP': ['Met the mayor', 'Explored the square'],
    'GM RECAP': 'The mayor is a dragon.',
    'ANALYSIS': 'Players were cautious.',
    'NEXT SESSION PREP': '(none)',
    'NPC UPDATES': ['Mayor seemed nervous'],
    'PLOT THREAD UPDATES': []
}"""
        parsed, error, parse_format, _diagnostics = parse_ai_analysis(payload)
        self.assertIsNone(error)
        self.assertIn(parse_format, ("json", "python_dict"))
        self.assertIn("Met the mayor", parsed["player_recap"])
        self.assertEqual(parsed["gm_recap"], "The mayor is a dragon.")

    def test_parse_ai_analysis_markdown_headings(self):
        payload = """
## Player Recap
The party explored the town.

## GM Recap
The mayor is suspicious.

## Analysis
Players split the party.

## Next Session Prep
(none)

## NPC Updates
- Mayor asked for a favor

## Plot Thread Updates
- Missing shipment
"""
        parsed, error, parse_format, _diagnostics = parse_ai_analysis(payload)
        self.assertIsNone(error)
        self.assertEqual(parse_format, "markdown")
        self.assertEqual(parsed["player_recap"], "The party explored the town.")
        self.assertIn("Missing shipment", compose_analysis_display(parsed))

    def test_parse_ai_analysis_prefers_json_over_sections(self):
        payload = """
=== PLAYER RECAP ===
Section recap

=== GM RECAP ===
Section gm

=== ANALYSIS ===
Section analysis

=== NEXT SESSION PREP ===
(none)

=== NPC UPDATES ===
(none)

=== PLOT THREAD UPDATES ===
(none)

{"player_recap": "JSON recap", "gm_recap": "JSON gm", "analysis": "JSON analysis",
 "next_session_prep": "", "npc_updates": [], "plot_thread_updates": []}
"""
        parsed, error, parse_format, _diagnostics = parse_ai_analysis(payload)
        self.assertIsNone(error)
        self.assertEqual(parse_format, "json")
        self.assertEqual(parsed["player_recap"], "JSON recap")

    def test_apply_parsed_ai_output_splits_session_and_prep_fields(self):
        session = SessionModel(
            campaign_id=1,
            title="Session 1",
            player_recap="Old player recap",
            recap="Old gm recap",
            analysis="Old analysis",
            next_session_prep="Old prep",
        )
        payload = """
=== PLAYER RECAP ===
New player recap

=== GM RECAP ===
New gm recap

=== ANALYSIS ===
Player Choices:
- Chose to parley

=== NEXT SESSION PREP ===
Opening Scene:
Begin at the tavern.

Likely Player Goals:
- Speak with the baron

=== NPC UPDATES ===
(none)

=== PLOT THREAD UPDATES ===
(none)
"""
        result = apply_parsed_ai_output(
            session,
            payload,
            update_fields={"player_recap", "gm_recap", "analysis"},
            task_name="sessions/analyze",
            session_id=1,
        )
        self.assertTrue(result["fields_extracted"])
        self.assertEqual(session.player_recap, "New player recap")
        self.assertEqual(session.recap, "New gm recap")
        self.assertIn("Chose to parley", session.analysis)
        self.assertEqual(session.next_session_prep, "Old prep")

        prep_result = apply_parsed_ai_output(
            session,
            payload,
            update_fields={"next_session_prep"},
            task_name="ai/review",
            session_id=1,
            save_raw_on_failure=False,
        )
        self.assertTrue(prep_result["fields_extracted"])
        self.assertIn("Begin at the tavern.", session.next_session_prep)
        self.assertFalse(session.next_session_prep_manually_edited)
        self.assertEqual(session.player_recap, "New player recap")

    def test_apply_parsed_ai_output_does_not_overwrite_on_parse_failure(self):
        session = SessionModel(
            campaign_id=1,
            title="Session 1",
            player_recap="Keep me",
            recap="Keep gm",
            next_session_prep="Keep prep",
        )
        result = apply_parsed_ai_output(
            session,
            "not a sectioned response",
            update_fields={"player_recap", "gm_recap", "analysis"},
            task_name="sessions/analyze",
            session_id=1,
        )
        self.assertFalse(result["json_parsed"])
        self.assertEqual(session.player_recap, "Keep me")
        self.assertEqual(session.recap, "Keep gm")
        self.assertEqual(session.next_session_prep, "Keep prep")
        self.assertEqual(session.analysis_raw, "not a sectioned response")

    def test_apply_parsed_ai_output_rejects_blob_in_next_session_prep(self):
        session = SessionModel(
            campaign_id=1,
            title="Session 1",
            next_session_prep="Keep prep",
        )
        raw_blob = """
=== PLAYER RECAP ===
Player text

=== GM RECAP ===
GM text

=== ANALYSIS ===
Analysis text

=== NEXT_SESSION_PREP ===
Opening Scene:
Begin at the tavern.

=== NPC UPDATES ===
(none)

=== PLOT THREAD UPDATES ===
(none)
"""
        malformed = json.dumps({"next_session_prep": raw_blob})
        result = apply_parsed_ai_output(
            session,
            malformed,
            update_fields={"next_session_prep"},
            task_name="ai/review",
            session_id=1,
            save_raw_on_failure=False,
        )
        self.assertTrue(result["json_parsed"] or result.get("missing_requested_fields"))
        self.assertNotIn("next_session_prep", result["updated_fields"])
        self.assertEqual(session.next_session_prep, "Keep prep")

    def test_apply_parsed_ai_output_leaves_prep_unchanged_when_prep_missing(self):
        session = SessionModel(
            campaign_id=1,
            title="Session 1",
            next_session_prep="Existing prep",
        )
        payload = """
=== PLAYER RECAP ===
Recap text

=== GM RECAP ===
GM recap

=== ANALYSIS ===
Some analysis

=== NEXT_SESSION_PREP ===
(none)

=== NPC UPDATES ===
(none)

=== PLOT THREAD UPDATES ===
(none)
"""
        result = apply_parsed_ai_output(
            session,
            payload,
            update_fields={"next_session_prep"},
            task_name="ai/review",
            session_id=1,
            save_raw_on_failure=False,
        )
        self.assertFalse(result["fields_extracted"])
        self.assertEqual(session.next_session_prep, "Existing prep")
        self.assertIn("next_session_prep", result["missing_requested_fields"])

    def test_build_ai_parse_message_partial_and_failure(self):
        from app.services.analysis import build_ai_parse_message

        self.assertEqual(
            build_ai_parse_message({"updated_fields": [], "missing_requested_fields": ["analysis"]}, context="analyze"),
            "AI response could not be parsed.",
        )
        self.assertEqual(
            build_ai_parse_message(
                {"updated_fields": ["player_recap"], "missing_requested_fields": ["analysis", "gm_recap"]},
                context="analyze",
            ),
            "AI response partially parsed. Some optional sections were not found.",
        )
        self.assertEqual(
            build_ai_parse_message(
                {"updated_fields": ["player_recap", "analysis"], "missing_requested_fields": ["gm_recap"]},
                context="analyze",
            ),
            "AI response partially parsed. Some optional sections were not found.",
        )
        self.assertIsNone(
            build_ai_parse_message(
                {"updated_fields": ["player_recap", "gm_recap", "analysis"], "missing_requested_fields": []},
                context="analyze",
            )
        )
        self.assertEqual(
            build_ai_parse_message(
                {
                    "updated_fields": [],
                    "missing_requested_fields": ["next_session_prep"],
                    "parse_format": "sections",
                    "prep_detected_in_raw": True,
                },
                context="review",
            ),
            "No next-session prep section found.",
        )
        self.assertEqual(
            build_ai_parse_message(
                {"updated_fields": [], "missing_requested_fields": ["next_session_prep"], "parse_format": None},
                context="review",
            ),
            "AI response could not be parsed.",
        )

    def test_clear_session_ai_fields_route(self):
        campaign = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={"title": "Session 1", "date": "2026-06-05", "notes": "Notes"},
        )
        with Session(database.engine) as db:
            session = db.exec(select(SessionModel).where(SessionModel.campaign_id == int(campaign))).first()
            session.player_recap = "Player"
            session.recap = "GM"
            session.analysis = "Analysis"
            session.analysis_raw = '{"blob": true}'
            session.next_session_prep = '{"next_session_prep": "blob"}'
            session.ai_last_run_metadata = '{"provider": "openai", "model": "gpt-4"}'
            db.add(session)
            db.commit()
            session_id = session.id

        response = self.client.post(f"/campaigns/{campaign}/sessions/{session_id}/clear-ai-fields")
        self.assertEqual(response.status_code, 303)

        with Session(database.engine) as db:
            session = db.get(SessionModel, session_id)
            self.assertIsNone(session.player_recap)
            self.assertIsNone(session.recap)
            self.assertIsNone(session.analysis)
            self.assertIsNone(session.analysis_raw)
            self.assertIsNone(session.next_session_prep)
            self.assertFalse(session.next_session_prep_manually_edited)
            self.assertIsNone(session.ai_last_run_metadata)

    def test_parse_accepts_next_session_prep_section_header(self):
        payload = """
=== NEXT_SESSION_PREP ===
Opening Scene:
Begin at the inn.
"""
        parsed, error, parse_format, _diagnostics = parse_ai_analysis(payload)
        self.assertIsNone(error)
        self.assertEqual(parse_format, "sections")
        self.assertIn("Begin at the inn.", parsed["next_session_prep"])

    def test_parse_next_session_prep_json_object(self):
        payload = json.dumps(
            {
                "NEXT_SESSION_PREP": {
                    "Opening Scene": "Cold open at the market square.",
                    "Likely Player Actions": "- Track the thief\n- Question witnesses",
                    "NPC Agendas": "Baron wants the party gone.",
                    "GM Notes": "Keep pacing tight.",
                }
            }
        )
        parsed, error, parse_format, _diagnostics = parse_ai_analysis(payload)
        self.assertIsNone(error)
        self.assertEqual(parse_format, "json")
        self.assertIn("Opening Scene:", parsed["next_session_prep"])
        self.assertIn("Cold open at the market square.", parsed["next_session_prep"])
        self.assertIn("NPC Agendas:", parsed["next_session_prep"])
        self.assertNotIn('{"Opening Scene"', parsed["next_session_prep"])

        session = SessionModel(campaign_id=1, title="Session 1", next_session_prep="Old prep")
        result = apply_parsed_ai_output(
            session,
            payload,
            update_fields={"next_session_prep"},
            task_name="ai/review",
            session_id=1,
            save_raw_on_failure=False,
        )
        self.assertTrue(result["fields_extracted"])
        self.assertIn("Cold open at the market square.", session.next_session_prep)
        self.assertNotIn("Old prep", session.next_session_prep)

    def test_parse_next_session_prep_spaced_json_key(self):
        payload = json.dumps(
            {
                "Next Session Prep": {
                    "Opening Scene": "Begin at the inn.",
                    "Complications": "The guards arrive early.",
                }
            }
        )
        parsed, error, _format, _diagnostics = parse_ai_analysis(payload)
        self.assertIsNone(error)
        self.assertIn("Begin at the inn.", parsed["next_session_prep"])

    def test_parse_next_session_prep_truncated_json(self):
        payload = """{
"PLAYER RECAP": "(none)",
"GM RECAP": "(none)",
"ANALYSIS": "(none)",
"NEXT_SESSION_PREP": {
    "Opening Scene": [
        "The session begins with the party returning to Blackstone Keep...",
        "As the party enters, they notice fresh wagon tracks..."
    ]
}
"""
        parsed, error, parse_format, _diagnostics = parse_ai_analysis(payload)
        self.assertIsNone(error)
        self.assertIn("Blackstone Keep", parsed["next_session_prep"])
        session = SessionModel(campaign_id=1, title="Session 1")
        result = apply_parsed_ai_output(
            session,
            payload,
            update_fields={"next_session_prep"},
            task_name="ai/review",
            session_id=1,
            save_raw_on_failure=False,
        )
        self.assertTrue(result["fields_extracted"])
        self.assertIn("Blackstone Keep", session.next_session_prep)

    def test_does_not_save_lone_brace_as_prep(self):
        payload = """{
"PLAYER RECAP": "(none)",
"GM RECAP": "(none)",
"ANALYSIS": "(none)",
"NEXT_SESSION_PREP": {"""
        session = SessionModel(campaign_id=1, title="Session 1", next_session_prep="Existing prep")
        result = apply_parsed_ai_output(
            session,
            payload,
            update_fields={"next_session_prep"},
            task_name="ai/review",
            session_id=1,
            save_raw_on_failure=False,
        )
        self.assertFalse(result["fields_extracted"])
        self.assertEqual(session.next_session_prep, "Existing prep")
        self.assertIn("next_session_prep", result["missing_requested_fields"])

    def test_parse_labeled_sections_mistral_style(self):
        payload = """
Player Recap:
The party explored the Ghostly Minstrel and met Elestra.

GM Recap:
Agnarr wore a silky outfit. Tee found a hidden door.

Analysis:
Strong roleplay focus. Watch the amnesia hook.

NPC Updates:
- Elestra: spoke with Sheva Callister
"""
        parsed, error, parse_format, diagnostics = parse_ai_analysis(payload)
        self.assertIsNone(error)
        self.assertEqual(parse_format, "sections")
        self.assertIn("Ghostly Minstrel", parsed["player_recap"])
        self.assertIn("silky outfit", parsed["gm_recap"])
        self.assertIn("amnesia hook", parsed["analysis"])
        self.assertIn("npc_updates", diagnostics.get("finalized_keys", parsed.keys()))

    def test_parse_truncated_analyze_json_lenient(self):
        payload = """{
"PLAYER RECAP": "The party woke at the inn.",
"GM RECAP": "Hidden reptilian watchers observed them.",
"ANALYSIS": "Pacing was strong but the amnesia thread needs follow-up."""
        parsed, error, parse_format, _diagnostics = parse_ai_analysis(payload)
        self.assertIsNone(error)
        self.assertEqual(parse_format, "json")
        self.assertIn("woke at the inn", parsed["player_recap"])
        self.assertIn("reptilian watchers", parsed["gm_recap"])

        session = SessionModel(campaign_id=1, title="Session 1")
        result = apply_parsed_ai_output(
            session,
            payload,
            update_fields={"player_recap", "gm_recap", "analysis"},
            task_name="sessions/analyze",
            session_id=1,
        )
        self.assertTrue(result["fields_extracted"])
        self.assertIn("player_recap", result["updated_fields"])
        self.assertIn("gm_recap", result["updated_fields"])
        self.assertIsNone(session.analysis_raw)

    def test_apply_parsed_ai_output_saves_raw_when_parsed_has_no_usable_fields(self):
        session = SessionModel(
            campaign_id=1,
            title="Session 1",
            player_recap="Keep me",
        )
        payload = """
=== PLAYER RECAP ===
(none)

=== GM RECAP ===
(none)

=== ANALYSIS ===
(none)
"""
        result = apply_parsed_ai_output(
            session,
            payload,
            update_fields={"player_recap", "gm_recap", "analysis"},
            task_name="sessions/analyze",
            session_id=1,
        )
        self.assertFalse(result["fields_extracted"])
        self.assertEqual(session.player_recap, "Keep me")
        self.assertEqual(session.analysis_raw, payload)
        self.assertEqual(result["raw_output"], payload)

    @patch("app.routers.sessions.generate")
    @patch("app.routers.sessions.llm_available", return_value=True)
    def test_save_and_analyze_shows_info_when_parse_fails(self, _mock_available, mock_generate):
        campaign = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={"title": "Session 1", "date": "2026-06-05", "notes": "Old notes."},
        )
        with Session(database.engine) as db:
            session = db.exec(select(SessionModel).where(SessionModel.campaign_id == int(campaign))).first()
            session_id = session.id

        mock_generate.return_value = "The model returned plain prose with no sections."
        response = self.client.post(
            f"/campaigns/{campaign}/sessions/{session_id}/save-and-analyze",
            data={"notes": "Updated notes from form."},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Notes saved.", response.content)
        self.assertNotIn(b"AI recaps/analysis updated", response.content)
        self.assertIn(b"AI response could not be parsed", response.content)

    @patch("app.services.ai_workflow.generate")
    @patch("app.routers.llm.llm_available", return_value=True)
    def test_ai_review_warns_when_prep_section_missing(self, _mock_available, mock_generate):
        campaign = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={"title": "Session 1", "date": "2026-06-05", "notes": "Session notes here."},
        )
        with Session(database.engine) as db:
            session = db.exec(select(SessionModel).where(SessionModel.campaign_id == int(campaign))).first()
            session.next_session_prep = "Existing prep"
            db.add(session)
            db.commit()

        mock_generate.return_value = """
=== PLAYER RECAP ===
(none)

=== GM RECAP ===
(none)

=== ANALYSIS ===
(none)

=== NEXT_SESSION_PREP ===
(none)

=== NPC UPDATES ===
(none)

=== PLOT THREAD UPDATES ===
(none)
"""
        response = self.client.post(
            f"/campaigns/{campaign}/ai/review",
            data={"session_id": "1", "notes": "Session notes here.", "confirm_overwrite": "1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"No next-session prep section found.", response.content)

        with Session(database.engine) as db:
            session = db.exec(select(SessionModel).where(SessionModel.campaign_id == int(campaign))).first()
            self.assertEqual(session.next_session_prep, "Existing prep")

    @patch("app.services.ai_workflow.generate")
    @patch("app.routers.llm.llm_available", return_value=True)
    def test_ai_review_empty_session_id_uses_latest_session(self, _mock_available, mock_generate):
        campaign = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={"title": "Session 1", "date": "2026-06-05", "notes": "First session."},
        )
        self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={"title": "Session 2", "date": "2026-06-06", "notes": "Latest session notes."},
        )
        response = self.client.post(
            f"/campaigns/{campaign}/ai/review",
            data={"session_id": "", "notes": ""},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Select a session to save prep to.", response.content)
        mock_generate.assert_not_called()

    def test_prep_overwrite_requires_confirmation(self):
        session = SessionModel(
            campaign_id=1,
            title="Session 1",
            next_session_prep="Manual prep",
            next_session_prep_manually_edited=True,
        )
        self.assertTrue(prep_overwrite_requires_confirmation(session))
        session.next_session_prep_manually_edited = False
        self.assertFalse(prep_overwrite_requires_confirmation(session))

    @patch("app.services.ai_workflow.generate")
    @patch("app.routers.llm.llm_available", return_value=True)
    def test_ai_review_warns_before_overwriting_manual_prep(self, _mock_available, mock_generate):
        campaign = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={"title": "Session 1", "date": "2026-06-05", "notes": "Session notes here."},
        )
        with Session(database.engine) as db:
            session = db.exec(select(SessionModel).where(SessionModel.campaign_id == int(campaign))).first()
            session.next_session_prep = "My custom prep"
            session.next_session_prep_manually_edited = True
            db.add(session)
            db.commit()

        response = self.client.post(
            f"/campaigns/{campaign}/ai/review",
            data={"session_id": "1", "notes": "Session notes here."},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Manual prep will be overwritten", response.text)
        mock_generate.assert_not_called()

    @patch("app.routers.sessions.generate")
    @patch("app.routers.sessions.llm_available", return_value=True)
    def test_save_and_analyze_saves_notes_before_analysis(self, _mock_available, mock_generate):
        campaign = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={"title": "Session 1", "date": "2026-06-05", "notes": "Old notes."},
        )
        with Session(database.engine) as db:
            session = db.exec(select(SessionModel).where(SessionModel.campaign_id == int(campaign))).first()
            session_id = session.id

        mock_generate.return_value = json.dumps(
            {
                "player_recap": "Player safe recap.",
                "gm_recap": "GM private recap.",
                "analysis": "Strong pacing.",
            }
        )
        response = self.client.post(
            f"/campaigns/{campaign}/sessions/{session_id}/save-and-analyze",
            data={"notes": "Updated notes from form."},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Save &amp; Analyze Session", response.content)
        self.assertIn(b"AI recaps/analysis updated", response.content)
        with Session(database.engine) as db:
            session = db.get(SessionModel, session_id)
            self.assertEqual(session.notes, "Updated notes from form.")
            self.assertEqual(session.player_recap, "Player safe recap.")

    @patch("app.services.ai_workflow.generate")
    @patch("app.routers.sessions.llm_available", return_value=True)
    def test_session_generate_prep_writes_draft_not_saved_until_accept(self, _mock_available, mock_generate):
        campaign = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={"title": "Session 1", "date": "2026-06-05", "notes": "Ridge investigation notes."},
        )
        with Session(database.engine) as db:
            session = db.exec(select(SessionModel).where(SessionModel.campaign_id == int(campaign))).first()
            session_id = session.id
            session.next_session_prep = "Existing saved prep"
            db.add(session)
            db.commit()

        mock_generate.return_value = """
=== PLAYER RECAP ===
(none)

=== GM RECAP ===
(none)

=== ANALYSIS ===
(none)

=== NEXT SESSION PREP ===
Opening Scene:
Cold open at the tavern.

=== NPC UPDATES ===
(none)

=== PLOT THREAD UPDATES ===
(none)
"""
        response = self.client.post(
            f"/campaigns/{campaign}/sessions/{session_id}/generate-prep",
            data={"notes": "Ridge investigation notes."},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Cold open at the tavern.", response.content)
        self.assertIn(b"Prep draft generated", response.content)
        with Session(database.engine) as db:
            session = db.get(SessionModel, session_id)
            self.assertEqual(session.next_session_prep, "Existing saved prep")

    @patch("app.services.ai_workflow.generate")
    @patch("app.routers.sessions.llm_available", return_value=True)
    def test_session_generate_prep_warns_without_analysis(self, _mock_available, mock_generate):
        campaign = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={"title": "Session 1", "date": "2026-06-05", "notes": "Notes only."},
        )
        with Session(database.engine) as db:
            session = db.exec(select(SessionModel).where(SessionModel.campaign_id == int(campaign))).first()
            session_id = session.id

        mock_generate.return_value = json.dumps(
            {"NEXT_SESSION_PREP": {"Opening Scene": ["Start here."]}}
        )
        response = self.client.post(
            f"/campaigns/{campaign}/sessions/{session_id}/generate-prep",
            data={"notes": "Notes only."},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"No analysis exists yet", response.content)
        self.assertIn(b"Start here.", response.content)

    def test_save_session_ai_drafts(self):
        campaign = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={"title": "Session 1", "date": "2026-06-05", "notes": "Notes."},
        )
        with Session(database.engine) as db:
            session = db.exec(select(SessionModel).where(SessionModel.campaign_id == int(campaign))).first()
            session_id = session.id

        response = self.client.post(
            f"/campaigns/{campaign}/sessions/{session_id}/ai-drafts",
            data={
                "player_recap": "Player draft",
                "recap": "GM draft",
                "analysis": "Analysis draft",
                "next_session_prep": "Prep draft",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"AI drafts saved.", response.content)
        with Session(database.engine) as db:
            session = db.get(SessionModel, session_id)
            self.assertEqual(session.player_recap, "Player draft")
            self.assertEqual(session.next_session_prep, "Prep draft")
            self.assertTrue(session.next_session_prep_manually_edited)

    def test_save_session_prep_marks_manual_edit(self):
        campaign = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={"title": "Session 1", "date": "2026-06-05", "notes": "Notes."},
        )
        with Session(database.engine) as db:
            session = db.exec(select(SessionModel).where(SessionModel.campaign_id == int(campaign))).first()
            session_id = session.id

        response = self.client.post(
            f"/campaigns/{campaign}/sessions/{session_id}/prep",
            data={"next_session_prep": "Edited prep content"},
        )
        self.assertEqual(response.status_code, 303)
        with Session(database.engine) as db:
            session = db.get(SessionModel, session_id)
            self.assertEqual(session.next_session_prep, "Edited prep content")
            self.assertTrue(session.next_session_prep_manually_edited)

    def test_build_candidate_link_options_only_lists_relevant_existing(self):
        existing = [
            NPC(id=1, campaign_id=1, name="Baron Kestrel"),
            NPC(id=2, campaign_id=1, name="Unrelated NPC"),
        ]
        options = build_candidate_link_options(["Baron Kestrel"], existing, "name")
        self.assertEqual(len(options), 1)
        values = [option["value"] for option in options[0]["options"]]
        self.assertIn("skip", values)
        self.assertIn("existing:1", values)
        self.assertNotIn("existing:2", values)

    def test_normalize_extraction_parses_entity_relationships(self):
        normalized = normalize_extraction(
            {
                "NPCs": ["Baron Kestrel"],
                "Factions": ["Iron Crown"],
                "NPCRelationships": [
                    {"npc": "Baron Kestrel", "faction": "Iron Crown", "location": "Blackstone Keep"},
                ],
            }
        )
        self.assertEqual(normalized["extracted_characters"], ["Baron Kestrel"])
        self.assertEqual(len(normalized["EntityRelationships"]), 2)
        labels = {(row["rel_type"], row["to_name"]) for row in normalized["EntityRelationships"]}
        self.assertIn(("npc_faction", "Iron Crown"), labels)
        self.assertIn(("npc_location", "Blackstone Keep"), labels)

    def test_classify_characters_routes_by_exact_match(self):
        thalia = SimpleNamespace(id=1, character_name="Thalia")
        baron = SimpleNamespace(id=2, name="Baron Kestrel")
        party, npcs, unclassified = classify_characters(
            ["Thalia", "Baron Kestrel", "Mystery Stranger"],
            [thalia],
            [baron],
        )
        self.assertEqual(party, ["Thalia"])
        self.assertEqual(npcs, ["Baron Kestrel"])
        self.assertEqual(unclassified, ["Mystery Stranger"])

    def test_normalize_extraction_extracts_character_names_from_dict_entries(self):
        normalized = normalize_extraction(
            {
                "Characters": [
                    {"NAME": "TEE"},
                    {"name": "Agnarr"},
                    '{"name": "Ranthir"}',
                    "Elestra",
                ]
            }
        )
        self.assertEqual(
            normalized["extracted_characters"],
            ["TEE", "Agnarr", "Ranthir", "Elestra"],
        )

    def test_prepare_review_candidates_matches_party_from_dict_character_names(self):
        tee = SimpleNamespace(id=1, character_name="Tee")
        agnarr = SimpleNamespace(id=2, character_name="Agnarr")
        normalized = normalize_extraction({"Characters": [{"NAME": "TEE"}, {"name": "Agnarr"}, "Elestra"]})
        review = prepare_review_candidates(normalized, [tee, agnarr], [])
        self.assertEqual(review["extracted_party_members"], ["TEE", "Agnarr"])
        self.assertEqual(review["unclassified_characters"], ["Elestra"])

    def test_ingest_save_updates_matching_session_instead_of_duplicating(self):
        campaign = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={
                "title": "Session 1C: Meeting Elestra",
                "date": "2026-06-05",
                "notes": "Placeholder notes from Lore Board.",
            },
        )
        with Session(database.engine) as db:
            sessions_before = db.exec(select(SessionModel).where(SessionModel.campaign_id == int(campaign))).all()
            self.assertEqual(len(sessions_before), 1)
            existing_id = sessions_before[0].id

        response = self.client.post(
            f"/campaigns/{campaign}/ingest/save",
            data={
                "session_title": "Session 1C: Meeting Elestra",
                "session_date": "2026-06-05",
                "raw_notes": "Full ingested session notes with more detail.",
                "ingest_save_mode": "update_existing",
                "matched_session_id": str(existing_id),
            },
        )
        self.assertEqual(response.status_code, 303)
        self.assertIn(f"/sessions/{existing_id}?hub_message=updated", response.headers["location"])

        with Session(database.engine) as db:
            sessions_after = db.exec(select(SessionModel).where(SessionModel.campaign_id == int(campaign))).all()
            self.assertEqual(len(sessions_after), 1)
            session = sessions_after[0]
            self.assertEqual(session.notes, "Full ingested session notes with more detail.")

    def test_prepare_review_candidates_puts_new_names_in_unclassified(self):
        thalia = SimpleNamespace(id=1, character_name="Thalia")
        normalized = normalize_extraction({"Characters": ["Thalia", "New NPC"]})
        review = prepare_review_candidates(normalized, [thalia], [])
        self.assertEqual(review["extracted_party_members"], ["Thalia"])
        self.assertEqual(review["unclassified_characters"], ["New NPC"])
        self.assertEqual(review["extracted_npcs"], [])

    def test_unclassified_character_options_default_to_create_npc(self):
        options = build_unclassified_character_options(["Mystery Stranger"])
        self.assertEqual(len(options), 1)
        selected = [option for option in options[0]["options"] if option["selected"]]
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["value"], "npc:new:Mystery Stranger")

    def test_plot_thread_similarity_suggests_existing_match(self):
        from types import SimpleNamespace

        existing = [
            SimpleNamespace(
                id=1,
                title="Baron Kestrel's secret meetings",
                details="Secret shipments and disappearances tied to the baron.",
                related_npcs="Baron Kestrel",
                related_locations="",
                status="Active",
            )
        ]
        options = build_candidate_link_options(
            ["Investigate Baron Kestrel's meetings"],
            existing,
            "title",
            bucket="thread",
            similarity_extra_attrs=("details", "related_npcs", "related_locations", "status"),
        )
        self.assertEqual(len(options), 1)
        values = [option["value"] for option in options[0]["options"]]
        self.assertIn("existing:1", values)
        selected = [option for option in options[0]["options"] if option["selected"]]
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["value"], "existing:1")
        self.assertGreater(options[0]["debug"]["confidence"], 0.48)

    def test_entity_relationship_options_only_auto_check_high_confidence(self):
        options = build_entity_relationship_options(
            [
                {"rel_type": "npc_faction", "from_name": "Baron", "to_name": "Iron Crown", "confidence": 0.95},
                {"rel_type": "item_npc", "from_name": "Seal", "to_name": "Baron", "confidence": 0.6},
            ]
        )
        checked = [option for option in options if option["checked"]]
        self.assertEqual(len(checked), 1)
        self.assertEqual(checked[0]["rel_type"], "npc_faction")

    def test_ingest_save_marks_party_members_without_creating_npcs(self):
        campaign = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign}/pcs",
            data={"character_name": "Thalia", "notes": "Party wizard."},
        )
        with Session(database.engine) as db:
            thalia = db.exec(select(PlayerCharacterNote).where(PlayerCharacterNote.character_name == "Thalia")).first()
            self.assertIsNotNone(thalia)
            thalia_id = thalia.id

        response = self.client.post(
            f"/campaigns/{campaign}/ingest/save",
            data={
                "session_title": "Session 1",
                "session_date": "2026-06-05",
                "raw_notes": "Thalia and Baron Kestrel explored the keep.",
                "selected_party_links": [f"party:existing:{thalia_id}"],
                "selected_unclassified_links": ["npc:new:Baron Kestrel"],
            },
        )
        self.assertEqual(response.status_code, 303)
        with Session(database.engine) as db:
            self.assertEqual(len(db.exec(select(NPC)).all()), 1)
            session = db.exec(select(SessionModel).where(SessionModel.campaign_id == int(campaign))).first()
            db.refresh(session)
            self.assertEqual(len(session.party_members), 1)
            self.assertEqual(session.party_members[0].character_name, "Thalia")
            self.assertEqual(len(session.npcs), 1)
            self.assertEqual(session.npcs[0].name, "Baron Kestrel")

    def test_ingest_save_links_only_selected_session_entities(self):
        campaign = self._create_campaign()
        for name in ["Baron Kestrel", "Other NPC"]:
            response = self.client.post(
                f"/campaigns/{campaign}/npcs",
                data={"name": name, "role": "NPC", "description": "Background."},
            )
            self.assertEqual(response.status_code, 303)
        for name in ["Iron Crown", "Veiled Covenant"]:
            response = self.client.post(
                f"/campaigns/{campaign}/factions",
                data={"name": name, "summary": "A faction."},
            )
            self.assertEqual(response.status_code, 303)

        with Session(database.engine) as db:
            baron = db.exec(select(NPC).where(NPC.name == "Baron Kestrel")).first()
            iron_crown = db.exec(select(Faction).where(Faction.name == "Iron Crown")).first()
            self.assertIsNotNone(baron)
            self.assertIsNotNone(iron_crown)
            baron_id = baron.id
            iron_crown_id = iron_crown.id

        response = self.client.post(
            f"/campaigns/{campaign}/ingest/save",
            data={
                "session_title": "Session 8",
                "session_date": "2026-06-05",
                "raw_notes": "Baron Kestrel met the party at Blackstone Keep.",
                "selected_npc_links": [f"existing:{baron_id}"],
                "selected_faction_links": [f"existing:{iron_crown_id}"],
            },
        )
        self.assertEqual(response.status_code, 303)

        with Session(database.engine) as db:
            session = db.exec(select(SessionModel).where(SessionModel.campaign_id == int(campaign))).first()
            db.refresh(session)
            self.assertEqual(len(session.npcs), 1)
            self.assertEqual(session.npcs[0].name, "Baron Kestrel")
            self.assertEqual(len(session.factions), 1)
            self.assertEqual(session.factions[0].name, "Iron Crown")
            baron = db.get(NPC, baron_id)
            db.refresh(baron)
            self.assertEqual(len(baron.factions), 0)

    def test_ingest_save_applies_only_approved_npc_relationships(self):
        campaign = self._create_campaign()
        create_baron = self.client.post(
            f"/campaigns/{campaign}/npcs",
            data={"name": "Baron Kestrel", "role": "Lord", "description": "A baron."},
        )
        self.assertEqual(create_baron.status_code, 303)
        for name in ["Iron Crown", "Veiled Covenant"]:
            response = self.client.post(
                f"/campaigns/{campaign}/factions",
                data={"name": name, "summary": "A faction."},
            )
            self.assertEqual(response.status_code, 303)

        with Session(database.engine) as db:
            baron = db.exec(select(NPC).where(NPC.name == "Baron Kestrel")).first()
            iron_crown = db.exec(select(Faction).where(Faction.name == "Iron Crown")).first()
            self.assertIsNotNone(baron)
            self.assertIsNotNone(iron_crown)
            baron_id = baron.id

        response = self.client.post(
            f"/campaigns/{campaign}/ingest/save",
            data={
                "session_title": "Session 8",
                "session_date": "2026-06-05",
                "raw_notes": "Baron Kestrel spoke for Iron Crown.",
                "selected_npc_links": [f"existing:{baron_id}"],
                "selected_npc_relationships": [f"faction|Baron Kestrel|Iron Crown"],
            },
        )
        self.assertEqual(response.status_code, 303)

        with Session(database.engine) as db:
            baron = db.get(NPC, baron_id)
            db.refresh(baron)
            faction_names = sorted(f.name for f in baron.factions)
            self.assertEqual(faction_names, ["Iron Crown"])

    def test_ingest_save_updates_npc_last_seen_session(self):
        campaign = self._create_campaign()
        create_npc = self.client.post(
            f"/campaigns/{campaign}/npcs",
            data={"name": "Innkeeper Mara", "role": "Innkeeper", "description": "Runs the Rusty Tankard."},
        )
        self.assertEqual(create_npc.status_code, 303)
        with Session(database.engine) as db:
            npc = db.exec(select(NPC).where(NPC.campaign_id == int(campaign))).first()
            self.assertIsNotNone(npc)
            npc_id = npc.id

        response = self.client.post(
            f"/campaigns/{campaign}/ingest/save",
            data={
                "session_title": "Session at the Inn",
                "session_date": "2026-06-05",
                "raw_notes": "The party met Mara at the inn.",
                "selected_npc_links": [f"existing:{npc_id}"],
            },
        )
        self.assertEqual(response.status_code, 303)

        with Session(database.engine) as db:
            npc = db.get(NPC, npc_id)
            session = db.exec(select(SessionModel).where(SessionModel.campaign_id == int(campaign))).first()
            self.assertIsNotNone(session)
            self.assertEqual(npc.last_seen_session_id, session.id)

    @patch.dict(os.environ, {"CAMPAIGN_CONSOLE_EMBEDDING_PROVIDER": "local_fallback"}, clear=False)
    def test_semantic_search_ranks_relevant_lore(self):
        campaign = self._create_campaign()
        for name, description in [
            ("Dragon Keeper", "Guards the ancient dragon vault beneath the mountain temple."),
            ("Shopkeeper", "Sells rope, lanterns, and trail rations in the market square."),
        ]:
            response = self.client.post(
                f"/campaigns/{campaign}/npcs",
                data={"name": name, "role": "NPC", "description": description},
            )
            self.assertEqual(response.status_code, 303)

        with Session(database.engine) as db:
            rebuild_lore_index(db, campaign, force=True)

        response = self.client.post(
            f"/campaigns/{campaign}/search",
            data={"query": "dragon vault beneath the temple", "mode": "semantic"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Dragon Keeper", response.text)
        self.assertLess(response.text.index("Dragon Keeper"), response.text.index("Shopkeeper"))

    @patch.dict(os.environ, {"CAMPAIGN_CONSOLE_EMBEDDING_PROVIDER": "local_fallback"}, clear=False)
    def test_semantic_search_warns_when_index_stale(self):
        campaign = self._create_campaign()
        response = self.client.post(
            f"/campaigns/{campaign}/npcs",
            data={"name": "Dragon Keeper", "role": "NPC", "description": "Dragon vault beneath the temple."},
        )
        self.assertEqual(response.status_code, 303)

        with Session(database.engine) as db:
            rebuild_lore_index(db, campaign, force=True)

        response = self.client.post(
            f"/campaigns/{campaign}/npcs",
            data={"name": "New NPC", "role": "NPC", "description": "Added after index build."},
        )
        self.assertEqual(response.status_code, 303)

        with patch("app.services.lore_index.embed_texts") as mock_embed:
            response = self.client.post(
                f"/campaigns/{campaign}/search",
                data={"query": "dragon vault", "mode": "semantic"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Search index is missing or stale", response.text)
        mock_embed.assert_not_called()

    def test_timeline_orders_sessions_by_parsed_date(self):
        campaign = self._create_campaign()
        for title, session_date in [
            ("Late Session", "2026-10-01"),
            ("Early Session", "2026-2-15"),
            ("Middle Session", "2026-06-05"),
            ("Undated Session", ""),
        ]:
            response = self.client.post(
                f"/campaigns/{campaign}/sessions",
                data={"title": title, "date": session_date, "notes": f"Notes for {title}."},
            )
            self.assertEqual(response.status_code, 303)

        response = self.client.get(f"/campaigns/{campaign}/timeline")
        self.assertEqual(response.status_code, 200)
        early_index = response.text.index("Early Session")
        middle_index = response.text.index("Middle Session")
        late_index = response.text.index("Late Session")
        undated_index = response.text.index("Undated Session")
        self.assertLess(early_index, middle_index)
        self.assertLess(middle_index, late_index)
        self.assertLess(late_index, undated_index)

    def test_llm_settings_page_loads(self):
        response = self.client.get("/settings/llm")
        self.assertEqual(response.status_code, 200)
        self.assertIn("LLM Settings", response.text)
        self.assertIn("Active LLM Provider", response.text)
        self.assertIn("provider-opt-openai", response.text)
        self.assertIn("selectProvider(", response.text)

    def test_llm_settings_provider_toggle_persists(self):
        import app.services.env_config as env_config_module

        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("CAMPAIGN_CONSOLE_LLM_PROVIDER=openai\n", encoding="utf-8")
            original_env_file = env_config_module.ENV_FILE
            env_config_module.ENV_FILE = env_path
            try:
                response = self.client.post(
                    "/settings/llm/provider",
                    data={"provider": "mistral"},
                    headers={"Accept": "application/json"},
                )
            finally:
                env_config_module.ENV_FILE = original_env_file

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertTrue(data["ok"])
            self.assertEqual(data["provider"], "mistral")
            saved = parse_env_file(env_path)
            self.assertEqual(saved["CAMPAIGN_CONSOLE_LLM_PROVIDER"], "mistral")

    def test_env_config_updates_provider_without_clearing_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "CAMPAIGN_CONSOLE_LLM_PROVIDER=openai\nOPENAI_API_KEY=keep-me-secret\n",
                encoding="utf-8",
            )
            update_env_file(
                {
                    "CAMPAIGN_CONSOLE_LLM_PROVIDER": "ollama",
                    "OPENAI_API_KEY": "",
                    "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
                    "OLLAMA_MODEL": "llama2",
                },
                path=env_path,
            )
            saved = parse_env_file(env_path)
            self.assertEqual(saved["CAMPAIGN_CONSOLE_LLM_PROVIDER"], "ollama")
            self.assertEqual(saved["OPENAI_API_KEY"], "keep-me-secret")

    def test_llm_settings_save_persists_provider(self):
        import app.services.env_config as env_config_module

        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("CAMPAIGN_CONSOLE_LLM_PROVIDER=openai\n", encoding="utf-8")
            original_env_file = env_config_module.ENV_FILE
            env_config_module.ENV_FILE = env_path
            try:
                response = self.client.post(
                    "/settings/llm",
                    data={
                        "CAMPAIGN_CONSOLE_LLM_PROVIDER": "ollama",
                        "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
                        "OLLAMA_MODEL": "mistral",
                    },
                )
            finally:
                env_config_module.ENV_FILE = original_env_file

            self.assertEqual(response.status_code, 200)
            self.assertIn("Settings saved", response.text)
            saved = parse_env_file(env_path)
            self.assertEqual(saved["CAMPAIGN_CONSOLE_LLM_PROVIDER"], "ollama")
            self.assertEqual(saved["OLLAMA_MODEL"], "mistral")

    def test_get_llm_settings_for_form_masks_secrets(self):
        with patch(
            "app.services.env_config.parse_env_file",
            return_value={"OPENAI_API_KEY": "supersecretkey"},
        ):
            settings = get_llm_settings_for_form()
        self.assertEqual(settings["OPENAI_API_KEY"], "")
        self.assertIn("••••", settings["OPENAI_API_KEY__masked"])

    @patch("app.routers.llm.generate")
    def test_llm_test_get_shows_form_without_calling_llm(self, mock_generate):
        response = self.client.get("/llm/test")
        self.assertEqual(response.status_code, 200)
        self.assertIn("LLM Provider Test", response.text)
        self.assertIn("Run provider test", response.text)
        mock_generate.assert_not_called()

    @patch("app.routers.llm.generate", return_value="OK")
    def test_llm_test_post_runs_once(self, mock_generate):
        with patch.dict(
            os.environ,
            {"CAMPAIGN_CONSOLE_LLM_PROVIDER": "mistral", "MISTRAL_API_KEY": "test-key"},
            clear=False,
        ):
            response = self.client.post("/llm/test")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Provider test passed", response.text)
        mock_generate.assert_called_once()

    @patch("app.routers.llm.generate", return_value="not ok")
    def test_llm_test_post_shows_failure(self, mock_generate):
        with patch.dict(
            os.environ,
            {"CAMPAIGN_CONSOLE_LLM_PROVIDER": "mistral", "MISTRAL_API_KEY": "test-key"},
            clear=False,
        ):
            response = self.client.post("/llm/test")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Expected response OK", response.text)

    @patch.dict(
        os.environ,
        {"CAMPAIGN_CONSOLE_LLM_PROVIDER": "gemini", "GEMINI_API_KEY": "test-key"},
        clear=False,
    )
    def test_get_configured_model_defaults(self):
        os.environ.pop("GEMINI_MODEL", None)
        self.assertEqual(get_configured_model("gemini"), "gemini-2.5-flash-lite")
        self.assertEqual(get_configured_model("openai"), "gpt-4o-mini")
        self.assertEqual(get_configured_model("mistral"), "mistral-small-latest")

    @patch.dict(os.environ, {"MISTRAL_MODEL": "mistral"}, clear=False)
    def test_get_configured_model_normalizes_mistral_alias(self):
        self.assertEqual(get_configured_model("mistral"), "mistral-small-latest")
        self.assertEqual(get_configured_model("mistral", "mistral"), "mistral-small-latest")
        self.assertEqual(get_configured_model("mistral", "mistral-large-latest"), "mistral-large-latest")

    def test_get_endpoint_url_gemini(self):
        url = get_endpoint_url("gemini", "gemini-2.5-flash-lite")
        self.assertEqual(
            url,
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent",
        )

    def test_get_endpoint_url_mistral(self):
        self.assertEqual(
            get_endpoint_url("mistral"),
            "https://api.mistral.ai/v1/chat/completions",
        )

    def test_parse_gemini_body_extracts_text(self):
        text = _parse_gemini_body(
            {"candidates": [{"content": {"parts": [{"text": "  OK  "}]}}]}
        )
        self.assertEqual(text, "OK")

    def test_parse_chat_completion_body_extracts_text(self):
        text = _parse_chat_completion_body(
            {"choices": [{"message": {"content": "  Parsed answer  "}}]}
        )
        self.assertEqual(text, "Parsed answer")

    @patch.dict(os.environ, {"GEMINI_DISABLED": "true", "GEMINI_API_KEY": "test-key"}, clear=False)
    def test_gemini_is_disabled(self):
        self.assertTrue(gemini_is_disabled())

    @patch.dict(
        os.environ,
        {"GEMINI_DISABLED": "true", "GEMINI_API_KEY": "test-key", "CAMPAIGN_CONSOLE_LLM_PROVIDER": "gemini"},
        clear=False,
    )
    def test_llm_available_false_when_gemini_disabled(self):
        self.assertFalse(llm_available())

    @patch.dict(os.environ, {"MISTRAL_API_KEY": "test-key"}, clear=False)
    def test_provider_available_mistral_requires_key_only(self):
        self.assertTrue(provider_available("mistral"))

    @patch.dict(os.environ, {"MISTRAL_API_KEY": ""}, clear=False)
    def test_provider_available_mistral_false_without_key(self):
        self.assertFalse(provider_available("mistral"))

    @patch("app.routers.debug.list_provider_diagnostics")
    def test_debug_providers_lists_without_api_calls(self, mock_rows):
        mock_rows.return_value = [
            {
                "provider": "mistral",
                "endpoint_url": "https://api.mistral.ai/v1/chat/completions",
                "model": "mistral-small-latest",
                "api_key_present": True,
            }
        ]
        response = self.client.get("/debug/providers")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Provider Diagnostics", response.text)
        self.assertIn("mistral-small-latest", response.text)
        self.assertIn("API Key Present", response.text)

    @patch("app.routers.debug.list_provider_diagnostics")
    @patch("app.routers.debug.get_active_provider_or_none", return_value="mistral")
    def test_debug_provider_test_form(self, _mock_provider, mock_rows):
        mock_rows.return_value = [
            {
                "provider": "mistral",
                "endpoint_url": "https://api.mistral.ai/v1/chat/completions",
                "model": "mistral-small-latest",
                "api_key_present": True,
            }
        ]
        response = self.client.get("/debug/provider-test")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Provider Smoke Test", response.text)
        self.assertIn(SMOKE_TEST_PROMPT, response.text)

    @patch("app.routers.debug.run_provider_smoke_test")
    def test_debug_provider_test_post_returns_raw_result(self, mock_smoke):
        mock_smoke.return_value = {
            "provider": "mistral",
            "model": "mistral-small-latest",
            "endpoint_url": "https://api.mistral.ai/v1/chat/completions",
            "status_code": 200,
            "body": {"choices": [{"message": {"content": "OK"}}]},
            "parsed_text": "OK",
        }
        response = self.client.post("/debug/provider-test")
        self.assertEqual(response.status_code, 200)
        self.assertIn("OK", response.text)
        mock_smoke.assert_called_once()

    @patch("app.services.provider_router._api_key_for", return_value="test-key")
    @patch("app.services.provider_router.requests.post")
    def test_mistral_generate_posts_chat_completions(self, mock_post, _mock_key):
        from app.services.provider_router import generate, reload_settings

        reload_settings()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"choices":[{"message":{"content":"OK"}}]}'
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "OK"}}],
        }
        mock_post.return_value = mock_response

        with patch.dict(
            os.environ,
            {
                "CAMPAIGN_CONSOLE_LLM_PROVIDER": "mistral",
                "MISTRAL_API_KEY": "test-key",
                "MISTRAL_MODEL": "mistral-small-latest",
            },
            clear=False,
        ):
            reload_settings()
            result = generate(SMOKE_TEST_PROMPT, max_tokens=20, task_name="test/mistral")

        self.assertEqual(result, "OK")
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://api.mistral.ai/v1/chat/completions")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(kwargs["json"]["model"], "mistral-small-latest")
        self.assertEqual(kwargs["json"]["messages"], [{"role": "user", "content": SMOKE_TEST_PROMPT}])
        self.assertEqual(kwargs["timeout"], 45)

    @patch("app.services.ingestion.llm_available", return_value=False)
    def test_extract_candidates_from_notes_requires_llm(self, _mock_available):
        campaign = MagicMock(name="Test Campaign")
        with self.assertRaises(RuntimeError) as ctx:
            extract_candidates_from_notes(campaign, "Some session notes.")
        self.assertIn("LLM provider not configured", str(ctx.exception))

    def test_parse_llm_json_lenient_recovers_truncated_ingestion_json(self):
        from app.services.llm_json import parse_llm_json_lenient

        payload = (
            '{"Characters": ["Tee", "Agnarr", "Jory"], '
            '"Locations": ["Blackstone Keep", "The Ridge"], '
            '"Factions": ["Iron Crown"], '
            '"Items": ["Silver spyglass"], '
            '"PlotThreads": ["Smoke on the Ridge"], '
            '"SecretsClues": ["Fresh wagon tracks"], '
            '"UnresolvedHooks": ["Who hired the scouts"], '
            '"EntityRelationships": [{"from_type": "npc", "from": "Jory", "to_type": "location", "to": "Blackstone Keep", "confidence": "high"}'
        )
        data, warning = parse_llm_json_lenient(payload, fallback_keys=[
            "Characters", "Locations", "Factions", "Items", "PlotThreads",
            "SecretsClues", "UnresolvedHooks", "EntityRelationships",
        ])
        self.assertIsNotNone(warning)
        self.assertIn("Tee", data["Characters"])
        self.assertIn("Blackstone Keep", data["Locations"])
        normalized = normalize_extraction(data)
        self.assertIn("Tee", normalized["extracted_characters"])
        location_names = [entry["name"] for entry in normalized["extracted_locations"]]
        self.assertIn("Blackstone Keep", location_names)

    @patch("app.services.ingestion.generate")
    @patch("app.services.ingestion.llm_available", return_value=True)
    def test_ingest_review_shows_partial_candidates_on_truncated_json(self, _mock_available, mock_generate):
        campaign = self._create_campaign()
        mock_generate.return_value = (
            '{"Characters": ["Tee", "Agnarr"], "Locations": ["The Ridge"], '
            '"Factions": [], "Items": [], "PlotThreads": ["Missing shipment"], '
            '"SecretsClues": [], "UnresolvedHooks": ['
        )
        response = self.client.post(
            f"/campaigns/{campaign}/ingest",
            data={
                "session_title": "Session 1",
                "session_date": "2026-06-05",
                "raw_notes": "Tee and Agnarr investigated the ridge.",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"partially parsed", response.content)
        self.assertIn(b"Tee", response.content)
        self.assertIn(b"The Ridge", response.content)

    @patch("app.routers.ingestion.gemini_is_disabled", return_value=False)
    @patch("app.routers.ingestion.llm_available", return_value=False)
    def test_ingest_without_llm_shows_config_message(self, _mock_available, _mock_disabled):
        campaign = self._create_campaign()
        response = self.client.post(
            f"/campaigns/{campaign}/ingest",
            data={
                "session_title": "Session 1",
                "session_date": "2026-06-05",
                "raw_notes": "The party met a mysterious stranger.",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("LLM provider not configured", response.text)

    @patch("app.routers.sessions.gemini_is_disabled", return_value=False)
    @patch("app.routers.sessions.llm_available", return_value=True)
    @patch("app.routers.sessions.generate", side_effect=RuntimeError("provider unavailable"))
    def test_analyze_session_llm_failure_shows_warning(self, _mock_generate, _mock_available, _mock_disabled):
        campaign = self._create_campaign()
        create_session = self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={"title": "Analyze Me", "date": "2026-06-05", "notes": "The party explored ruins."},
        )
        self.assertEqual(create_session.status_code, 303)
        with Session(database.engine) as db:
            session = db.exec(select(SessionModel).where(SessionModel.campaign_id == int(campaign))).first()
            session_id = session.id

        response = self.client.post(f"/campaigns/{campaign}/sessions/{session_id}/analyze")
        self.assertEqual(response.status_code, 200)
        self.assertIn("AI analysis failed: provider unavailable", response.text)

    def test_get_active_embedding_provider_defaults_to_local_fallback(self):
        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "test-key", "CAMPAIGN_CONSOLE_EMBEDDING_PROVIDER": "auto"},
            clear=False,
        ):
            provider = get_active_embedding_provider()
        self.assertEqual(provider, "local_fallback")

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key", "CAMPAIGN_CONSOLE_EMBEDDING_PROVIDER": "openai"}, clear=False)
    def test_get_active_embedding_provider_never_auto_selects_openai(self):
        self.assertEqual(get_active_embedding_provider(), "local_fallback")

    @patch.dict(os.environ, {"CAMPAIGN_CONSOLE_EMBEDDING_PROVIDER": "openai", "OPENAI_API_KEY": "test-key"}, clear=False)
    @patch("app.services.embeddings.OpenAI")
    def test_openai_bulk_embedding_requires_opt_in(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        texts = [f"chunk {index}" for index in range(6)]
        with self.assertRaises(RuntimeError) as ctx:
            embed_texts(texts, provider="openai", task_name="test/bulk")
        self.assertIn("OPENAI_EMBEDDING_BULK_OK", str(ctx.exception))
        mock_client.embeddings.create.assert_not_called()

    def test_parse_entity_links_rejects_other_campaign_entities(self):
        with Session(database.engine) as db:
            campaign_a = Campaign(name="Campaign A")
            campaign_b = Campaign(name="Campaign B")
            db.add(campaign_a)
            db.add(campaign_b)
            db.commit()
            db.refresh(campaign_a)
            db.refresh(campaign_b)

            foreign_npc = NPC(campaign_id=campaign_b.id, name="Foreign NPC")
            db.add(foreign_npc)
            db.commit()
            db.refresh(foreign_npc)

            linked = parse_entity_links(
                db,
                campaign_a.id,
                [f"existing:{foreign_npc.id}"],
                NPC,
                "name",
            )
            self.assertEqual(linked, [])

    def test_npc_edit_clears_factions_and_plot_threads(self):
        campaign = self._create_campaign()
        create_npc = self.client.post(
            f"/campaigns/{campaign}/npcs",
            data={"name": "Linked NPC", "role": "Lord", "description": "Has links."},
        )
        self.assertEqual(create_npc.status_code, 303)
        create_faction = self.client.post(
            f"/campaigns/{campaign}/factions",
            data={"name": "Iron Crown", "summary": "A faction."},
        )
        self.assertEqual(create_faction.status_code, 303)
        create_thread = self.client.post(
            f"/campaigns/{campaign}/threads",
            data={"title": "Hidden Heir", "status": "Active", "details": "A plot thread."},
        )
        self.assertEqual(create_thread.status_code, 303)

        with Session(database.engine) as db:
            npc = db.exec(select(NPC).where(NPC.campaign_id == int(campaign))).first()
            faction = db.exec(select(Faction).where(Faction.campaign_id == int(campaign))).first()
            thread = db.exec(select(PlotThread).where(PlotThread.campaign_id == int(campaign))).first()
            npc_id = npc.id
            faction_id = faction.id
            thread_id = thread.id

        link_response = self.client.post(
            f"/campaigns/{campaign}/npcs/{npc_id}/edit",
            data={
                "name": "Linked NPC",
                "role": "Lord",
                "description": "Has links.",
                "selected_factions": [str(faction_id)],
                "selected_plot_threads": [str(thread_id)],
            },
        )
        self.assertEqual(link_response.status_code, 303)

        with Session(database.engine) as db:
            npc = db.get(NPC, npc_id)
            db.refresh(npc)
            self.assertEqual(len(npc.factions), 1)
            self.assertEqual(len(npc.plot_threads), 1)

        edit_page = self.client.get(f"/campaigns/{campaign}/npcs/{npc_id}/edit")
        self.assertEqual(edit_page.status_code, 200)
        self.assertIn(f'value="{faction_id}" selected', edit_page.text)
        self.assertIn(f'value="{thread_id}" selected', edit_page.text)
        self.assertIn('mc-relationship-select', edit_page.text)

        clear_response = self.client.post(
            f"/campaigns/{campaign}/npcs/{npc_id}/edit",
            data={
                "name": "Linked NPC",
                "role": "Lord",
                "description": "Has links.",
            },
        )
        self.assertEqual(clear_response.status_code, 303)

        with Session(database.engine) as db:
            npc = db.get(NPC, npc_id)
            db.refresh(npc)
            self.assertEqual(npc.factions, [])
            self.assertEqual(npc.plot_threads, [])

    def test_npc_edit_preserves_links_when_only_name_changes(self):
        campaign = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign}/npcs",
            data={"name": "Stable NPC", "role": "Guide", "description": "Keep links."},
        )
        self.client.post(
            f"/campaigns/{campaign}/factions",
            data={"name": "Keep Faction", "summary": "Linked."},
        )
        with Session(database.engine) as db:
            npc = db.exec(select(NPC).where(NPC.campaign_id == int(campaign))).first()
            faction = db.exec(select(Faction).where(Faction.campaign_id == int(campaign))).first()
            npc_id = npc.id
            faction_id = faction.id

        self.client.post(
            f"/campaigns/{campaign}/npcs/{npc_id}/edit",
            data={
                "name": "Stable NPC",
                "role": "Guide",
                "description": "Keep links.",
                "selected_factions": [str(faction_id)],
            },
        )

        response = self.client.post(
            f"/campaigns/{campaign}/npcs/{npc_id}/edit",
            data={
                "name": "Renamed NPC",
                "role": "Guide",
                "description": "Keep links.",
                "selected_factions": [str(faction_id)],
            },
        )
        self.assertEqual(response.status_code, 303)

        with Session(database.engine) as db:
            npc = db.get(NPC, npc_id)
            db.refresh(npc)
            self.assertEqual(npc.name, "Renamed NPC")
            self.assertEqual(len(npc.factions), 1)
            self.assertEqual(npc.factions[0].name, "Keep Faction")

    def test_delete_session_removes_session_exclusive_entities(self):
        campaign_id = int(self._create_campaign())
        create_npc = self.client.post(
            f"/campaigns/{campaign_id}/npcs",
            data={"name": "Session Only NPC", "role": "Guide", "description": "Only in one session."},
        )
        self.assertEqual(create_npc.status_code, 303)
        create_faction = self.client.post(
            f"/campaigns/{campaign_id}/factions",
            data={"name": "Session Only Faction", "summary": "Only in one session."},
        )
        self.assertEqual(create_faction.status_code, 303)

        with Session(database.engine) as db:
            npc = db.exec(select(NPC).where(NPC.name == "Session Only NPC")).first()
            faction = db.exec(select(Faction).where(Faction.name == "Session Only Faction")).first()
            npc_id = npc.id
            faction_id = faction.id

        save_response = self.client.post(
            f"/campaigns/{campaign_id}/ingest/save",
            data={
                "session_title": "One-Off Session",
                "session_date": "2026-06-05",
                "raw_notes": "The party met the guide and the faction.",
                "selected_npc_links": [f"existing:{npc_id}"],
                "selected_faction_links": [f"existing:{faction_id}"],
            },
        )
        self.assertEqual(save_response.status_code, 303)

        with Session(database.engine) as db:
            session = db.exec(select(SessionModel).where(SessionModel.campaign_id == campaign_id)).first()
            session_id = session.id
            rebuild_lore_index(db, campaign_id, force=True)
            lore_count = len(
                db.exec(
                    select(LoreChunk).where(
                        LoreChunk.source_type == "session",
                        LoreChunk.source_id == session_id,
                    )
                ).all()
            )
            self.assertGreater(lore_count, 0)
            npc_row = db.get(NPC, npc_id)
            npc_row.last_seen_session_id = session_id
            db.add(npc_row)
            db.commit()

        delete_response = self.client.post(f"/campaigns/{campaign_id}/sessions/{session_id}/delete")
        self.assertEqual(delete_response.status_code, 303)

        with Session(database.engine) as db:
            self.assertIsNone(db.get(SessionModel, session_id))
            self.assertIsNone(db.get(NPC, npc_id))
            self.assertIsNone(db.get(Faction, faction_id))
            lore_count = len(
                db.exec(
                    select(LoreChunk).where(
                        LoreChunk.source_type == "session",
                        LoreChunk.source_id == session_id,
                    )
                ).all()
            )
            self.assertEqual(lore_count, 0)

    def test_delete_session_keeps_entities_linked_to_other_sessions(self):
        campaign_id = int(self._create_campaign())
        create_npc = self.client.post(
            f"/campaigns/{campaign_id}/npcs",
            data={"name": "Recurring NPC", "role": "Guide", "description": "Appears twice."},
        )
        self.assertEqual(create_npc.status_code, 303)

        with Session(database.engine) as db:
            npc = db.exec(select(NPC).where(NPC.name == "Recurring NPC")).first()
            npc_id = npc.id

        for title in ["Session A", "Session B"]:
            response = self.client.post(
                f"/campaigns/{campaign_id}/ingest/save",
                data={
                    "session_title": title,
                    "session_date": "2026-06-05",
                    "raw_notes": f"Notes for {title}.",
                    "selected_npc_links": [f"existing:{npc_id}"],
                },
            )
            self.assertEqual(response.status_code, 303)

        with Session(database.engine) as db:
            sessions = db.exec(
                select(SessionModel).where(SessionModel.campaign_id == campaign_id).order_by(SessionModel.id)
            ).all()
            self.assertEqual(len(sessions), 2)
            delete_session_id = sessions[0].id
            keep_session_id = sessions[1].id
            npc = db.get(NPC, npc_id)
            npc.last_seen_session_id = delete_session_id
            db.add(npc)
            db.commit()

        delete_response = self.client.post(f"/campaigns/{campaign_id}/sessions/{delete_session_id}/delete")
        self.assertEqual(delete_response.status_code, 303)

        with Session(database.engine) as db:
            self.assertIsNone(db.get(SessionModel, delete_session_id))
            self.assertIsNotNone(db.get(SessionModel, keep_session_id))
            npc = db.get(NPC, npc_id)
            db.refresh(npc)
            self.assertIsNotNone(npc)
            self.assertIsNone(npc.last_seen_session_id)
            self.assertEqual(len(npc.sessions), 1)
            self.assertEqual(npc.sessions[0].id, keep_session_id)

    def test_delete_npc_removes_session_link_rows(self):
        campaign_id = int(self._create_campaign())
        create_npc = self.client.post(
            f"/campaigns/{campaign_id}/npcs",
            data={"name": "Delete Me NPC", "role": "Guide", "description": "Link cleanup test."},
        )
        self.assertEqual(create_npc.status_code, 303)
        with Session(database.engine) as db:
            npc = db.exec(select(NPC).where(NPC.campaign_id == campaign_id)).first()
            npc_id = npc.id

        save_response = self.client.post(
            f"/campaigns/{campaign_id}/ingest/save",
            data={
                "session_title": "Linked Session",
                "session_date": "2026-06-05",
                "raw_notes": "The party met the guide.",
                "selected_npc_links": [f"existing:{npc_id}"],
            },
        )
        self.assertEqual(save_response.status_code, 303)

        conn = sqlite3.connect(self.db_path)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sessionnpclink").fetchone()[0], 1)
        finally:
            conn.close()

        delete_response = self.client.post(f"/campaigns/{campaign_id}/npcs/{npc_id}/delete")
        self.assertEqual(delete_response.status_code, 303)

        conn = sqlite3.connect(self.db_path)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sessionnpclink").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM npc WHERE id = ?", (npc_id,)).fetchone()[0], 0)
        finally:
            conn.close()

    def test_session_detail_shows_saved_prep_in_analysis_panel(self):
        campaign = self._create_campaign()
        create_session = self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={"title": "Prep Session", "date": "2026-06-05", "notes": "Notes here."},
        )
        self.assertEqual(create_session.status_code, 303)
        with Session(database.engine) as db:
            session = db.exec(select(SessionModel).where(SessionModel.campaign_id == int(campaign))).first()
            session.next_session_prep = "## Saved Prep\nBring torches."
            db.add(session)
            db.commit()
            session_id = session.id

        response = self.client.get(f"/campaigns/{campaign}/sessions/{session_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Bring torches", response.text)

    def test_delete_campaign_removes_sessions_entities_and_links(self):
        campaign_id = int(self._create_campaign())
        create_npc = self.client.post(
            f"/campaigns/{campaign_id}/npcs",
            data={"name": "Linked NPC", "role": "Guide", "description": "For deletion test."},
        )
        self.assertEqual(create_npc.status_code, 303)
        with Session(database.engine) as db:
            npc = db.exec(select(NPC).where(NPC.campaign_id == campaign_id)).first()
            npc_id = npc.id

        save_response = self.client.post(
            f"/campaigns/{campaign_id}/ingest/save",
            data={
                "session_title": "Linked Session",
                "session_date": "2026-06-05",
                "raw_notes": "The party spoke with the guide.",
                "selected_npc_links": [f"existing:{npc_id}"],
            },
        )
        self.assertEqual(save_response.status_code, 303)

        with Session(database.engine) as db:
            delete_campaign_cascade(db, campaign_id)
            self.assertIsNone(db.get(Campaign, campaign_id))
            self.assertEqual(
                len(db.exec(select(SessionModel).where(SessionModel.campaign_id == campaign_id)).all()),
                0,
            )
            self.assertEqual(len(db.exec(select(NPC).where(NPC.campaign_id == campaign_id)).all()), 0)

        conn = sqlite3.connect(self.db_path)
        try:
            session_count = conn.execute(
                "SELECT COUNT(*) FROM sessionmodel WHERE campaign_id = ?", (campaign_id,)
            ).fetchone()[0]
            npc_count = conn.execute("SELECT COUNT(*) FROM npc WHERE campaign_id = ?", (campaign_id,)).fetchone()[0]
            link_count = conn.execute("SELECT COUNT(*) FROM sessionnpclink").fetchone()[0]
            self.assertEqual(session_count, 0)
            self.assertEqual(npc_count, 0)
            self.assertEqual(link_count, 0)
        finally:
            conn.close()

    def test_location_classification_examples(self):
        self.assertEqual(classify_location("Ptolus")["location_type"], LOCATION_TYPE_MAJOR)
        self.assertEqual(classify_location("Midtown")["location_type"], LOCATION_TYPE_MAJOR)
        self.assertEqual(classify_location("Iridithil's Home")["location_type"], LOCATION_TYPE_SUB)
        self.assertEqual(classify_location("a side passage")["location_type"], LOCATION_TYPE_SCENE)
        self.assertFalse(classify_location("a side passage")["should_create"])
        self.assertTrue(is_generic_scene_feature("a chest"))
        self.assertTrue(is_generic_scene_feature("shallow pool of water"))
        self.assertTrue(is_generic_scene_feature("dead-end"))
        self.assertFalse(is_generic_scene_feature("The Ghostly Minstrel"))

    def test_build_location_link_options_skips_scene_features_by_default(self):
        classified = [
            classify_location("Ptolus"),
            classify_location("a side passage"),
        ]
        options = build_location_link_options(classified, [])
        by_name = {row["candidate"]: row for row in options}
        self.assertTrue(
            any(option["selected"] and option["value"].startswith("new:") for option in by_name["Ptolus"]["options"])
        )
        self.assertTrue(by_name["a side passage"]["options"][0]["selected"])
        self.assertEqual(by_name["a side passage"]["options"][0]["value"], "skip")

    def test_parse_entity_links_sets_location_type(self):
        with Session(database.engine) as db:
            campaign = Campaign(name="Loc Test")
            db.add(campaign)
            db.commit()
            db.refresh(campaign)
            linked = parse_entity_links(
                db,
                campaign.id,
                [f"new:Iridithil's Home|{LOCATION_TYPE_SUB}"],
                Location,
                "name",
            )
            db.commit()
            self.assertEqual(len(linked), 1)
            self.assertEqual(linked[0].location_type, LOCATION_TYPE_SUB)

    def test_merge_locations_relinks_and_deletes_duplicate(self):
        with Session(database.engine) as db:
            campaign = Campaign(name="Merge Test")
            db.add(campaign)
            db.commit()
            db.refresh(campaign)
            keep = Location(campaign_id=campaign.id, name="Ptolus", location_type=LOCATION_TYPE_MAJOR)
            dup = Location(campaign_id=campaign.id, name="Ptolus District", location_type=LOCATION_TYPE_SUB)
            db.add(keep)
            db.add(dup)
            db.commit()
            db.refresh(keep)
            db.refresh(dup)
            merged = merge_locations(db, campaign.id, keep.id, [dup.id])
            db.commit()
            self.assertIsNotNone(merged)
            remaining = db.exec(select(Location).where(Location.campaign_id == campaign.id)).all()
            self.assertEqual(len(remaining), 1)
            self.assertEqual(remaining[0].name, "Ptolus")

    def test_location_admin_page_loads(self):
        campaign = self._create_campaign()
        response = self.client.get(f"/campaigns/{campaign}/locations/admin")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Location Admin", response.content)
        self.assertIn(b"Merge Locations", response.content)

    def test_entity_health_scoring(self):
        with Session(database.engine) as db:
            campaign = Campaign(name="Health Test")
            db.add(campaign)
            db.commit()
            db.refresh(campaign)

            npc = NPC(campaign_id=campaign.id, name="Baron", description="A noble.", role="Quest giver")
            sparse = NPC(campaign_id=campaign.id, name="Guard")
            db.add(npc)
            db.add(sparse)
            db.commit()
            db.refresh(npc)
            db.refresh(sparse)

            health = CampaignEntityHealth(db, campaign.id)
            full = health.score_npc(npc)
            empty = health.score_npc(sparse)

            self.assertGreater(full["score"], empty["score"])
            self.assertIn("Relationships", empty["missing"])
            self.assertEqual(full["status"], "partial")

    def test_entity_health_overview_and_sort(self):
        with Session(database.engine) as db:
            campaign = Campaign(name="Overview Test")
            db.add(campaign)
            db.commit()
            db.refresh(campaign)

            complete = Faction(campaign_id=campaign.id, name="Complete Faction", summary="Known group.")
            sparse = Faction(campaign_id=campaign.id, name="Sparse Faction")
            db.add(complete)
            db.add(sparse)
            db.commit()

            _service, context = prepare_entity_lists(db, campaign.id, entity_sort="completeness")
            overview = context["completeness_overview"]
            self.assertEqual(overview["total_entities"], 2)
            self.assertIn("sections", overview)
            self.assertGreater(context["factions"][0].name, "")  # sorted list returned
            self.assertGreaterEqual(
                context["health_maps"]["factions"][complete.id]["score"],
                context["health_maps"]["factions"][sparse.id]["score"],
            )

    def test_session_workspace_save_and_copy_prep(self):
        campaign = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={"title": "Workspace Session", "date": "2026-06-05", "notes": "Notes."},
        )
        with Session(database.engine) as db:
            session = db.exec(select(SessionModel).where(SessionModel.campaign_id == int(campaign))).first()
            session_id = session.id
            session.next_session_prep = "Opening at the tavern."
            db.add(session)
            db.commit()

        response = self.client.get(f"/campaigns/{campaign}/workspace?session_id={session_id}&mode=prep")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Save Workspace", response.content)
        self.assertIn(b"Copy AI Prep", response.content)

        save = self.client.post(
            f"/campaigns/{campaign}/workspace/save",
            data={"session_id": session_id, "workspace_notes": "# Prep\n\nScene one.", "mode": "prep"},
        )
        self.assertEqual(save.status_code, 303)

        with Session(database.engine) as db:
            session = db.get(SessionModel, session_id)
            self.assertEqual(session.workspace_notes, "# Prep\n\nScene one.")
            self.assertEqual(session.next_session_prep, "Opening at the tavern.")

        copy = self.client.post(
            f"/campaigns/{campaign}/workspace/copy-prep",
            data={"session_id": session_id, "mode": "prep"},
        )
        self.assertEqual(copy.status_code, 303)
        with Session(database.engine) as db:
            session = db.get(SessionModel, session_id)
            self.assertIn("Opening at the tavern.", session.workspace_notes)
            self.assertIn("AI Session Prep", session.workspace_notes)

    def test_workspace_ref_panel_shows_entity_session_history(self):
        campaign = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={"title": "Session One", "date": "2026-01-01", "notes": "n"},
        )
        self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={"title": "Session Two", "date": "2026-02-01", "notes": "n"},
        )
        self.client.post(
            f"/campaigns/{campaign}/npcs",
            data={"name": "Guide", "role": "NPC", "description": "Helps the party."},
        )
        with Session(database.engine) as db:
            sessions = db.exec(
                select(SessionModel).where(SessionModel.campaign_id == int(campaign)).order_by(SessionModel.id)
            ).all()
            npc = db.exec(select(NPC).where(NPC.name == "Guide")).first()
            for session in sessions:
                self.client.post(
                    f"/campaigns/{campaign}/sessions/{session.id}/edit",
                    data={
                        "title": session.title,
                        "date": session.date or "",
                        "notes": session.notes or "",
                        "selected_npcs": [str(npc.id)],
                    },
                )

        response = self.client.get(
            f"/campaigns/{campaign}/workspace?session_id={sessions[-1].id}&mode=prep"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Session history", response.content)
        self.assertIn(b"Session One", response.content)
        self.assertIn(b"Session Two", response.content)
        self.assertIn(b"current", response.content)
        self.assertIn(b"first", response.content)

    def test_workspace_ref_panel_shows_location_returning_flag(self):
        campaign = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={"title": "Session One", "date": "2026-01-01", "notes": "n"},
        )
        self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={"title": "Session Two", "date": "2026-02-01", "notes": "n"},
        )
        self.client.post(
            f"/campaigns/{campaign}/locations",
            data={"name": "Tavern", "description": "Old haunt.", "location_type": "major"},
        )
        with Session(database.engine) as db:
            sessions = db.exec(
                select(SessionModel).where(SessionModel.campaign_id == int(campaign)).order_by(SessionModel.id)
            ).all()
            location = db.exec(select(Location).where(Location.name == "Tavern")).first()
            for session in sessions:
                self.client.post(
                    f"/campaigns/{campaign}/sessions/{session.id}/edit",
                    data={
                        "title": session.title,
                        "date": session.date or "",
                        "notes": session.notes or "",
                        "selected_locations": [str(location.id)],
                    },
                )

        response = self.client.get(
            f"/campaigns/{campaign}/workspace?session_id={sessions[-1].id}&mode=prep"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Active Locations", response.content)
        self.assertIn(b"Tavern", response.content)
        self.assertIn(b"returning", response.content)

    def test_entity_edit_return_to_redirects_to_workspace(self):
        campaign = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign}/npcs",
            data={"name": "Return Test NPC", "role": "Test", "description": ""},
        )
        with Session(database.engine) as db:
            npc_row = db.exec(select(NPC).where(NPC.name == "Return Test NPC")).first()
            npc_id = npc_row.id
        return_to = f"/campaigns/{campaign}/workspace?session_id=1&mode=prep"
        response = self.client.post(
            f"/campaigns/{campaign}/npcs/{npc_id}/edit",
            data={"name": "Return Test NPC", "role": "Updated", "return_to": return_to},
        )
        self.assertEqual(response.status_code, 303)
        self.assertIn("/workspace", response.headers.get("location", ""))

    def test_workspace_redirects_to_persisted_session_and_mode(self):
        campaign = self._create_campaign()
        first = self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={"title": "Session A", "date": "2026-01-01", "notes": "A"},
        )
        self.assertEqual(first.status_code, 303)
        second = self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={"title": "Session B", "date": "2026-01-02", "notes": "B"},
        )
        self.assertEqual(second.status_code, 303)
        with Session(database.engine) as db:
            sessions = db.exec(
                select(SessionModel).where(SessionModel.campaign_id == int(campaign)).order_by(SessionModel.id)
            ).all()
            session_b_id = sessions[-1].id

        self.client.cookies.set(f"mc_session_{campaign}", str(session_b_id))
        self.client.cookies.set(f"mc_mode_{campaign}", "run")
        response = self.client.get(f"/campaigns/{campaign}/workspace", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        location = response.headers.get("location", "")
        self.assertIn(f"session_id={session_b_id}", location)
        self.assertIn("mode=run", location)

    def test_session_edit_updates_npc_last_seen(self):
        campaign = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={"title": "Session One", "date": "2026-01-01", "notes": "Notes"},
        )
        self.client.post(
            f"/campaigns/{campaign}/npcs",
            data={"name": "Tracked NPC", "role": "Guide", "description": ""},
        )
        with Session(database.engine) as db:
            session = db.exec(select(SessionModel).where(SessionModel.campaign_id == int(campaign))).first()
            npc = db.exec(select(NPC).where(NPC.name == "Tracked NPC")).first()
            session_id = session.id
            npc_id = npc.id

        self.client.post(
            f"/campaigns/{campaign}/sessions/{session_id}/edit",
            data={
                "title": "Session One",
                "date": "2026-01-01",
                "notes": "Updated",
                "selected_npcs": [str(npc_id)],
            },
        )
        with Session(database.engine) as db:
            npc = db.get(NPC, npc_id)
            self.assertEqual(npc.last_seen_session_id, session_id)

    def test_session_edit_updates_location_faction_item_last_seen(self):
        campaign = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={"title": "Session One", "date": "2026-01-01", "notes": "Notes"},
        )
        self.client.post(
            f"/campaigns/{campaign}/locations",
            data={"name": "Tavern", "description": "A place.", "location_type": "major"},
        )
        self.client.post(
            f"/campaigns/{campaign}/factions",
            data={"name": "Guild", "summary": "A faction."},
        )
        self.client.post(
            f"/campaigns/{campaign}/items",
            data={"name": "Sword", "description": "A blade."},
        )
        with Session(database.engine) as db:
            session = db.exec(select(SessionModel).where(SessionModel.campaign_id == int(campaign))).first()
            location = db.exec(select(Location).where(Location.name == "Tavern")).first()
            faction = db.exec(select(Faction).where(Faction.name == "Guild")).first()
            item = db.exec(select(Item).where(Item.name == "Sword")).first()
            session_id = session.id

        self.client.post(
            f"/campaigns/{campaign}/sessions/{session_id}/edit",
            data={
                "title": "Session One",
                "date": "2026-01-01",
                "notes": "Updated",
                "selected_locations": [str(location.id)],
                "selected_factions": [str(faction.id)],
                "selected_items": [str(item.id)],
            },
        )
        with Session(database.engine) as db:
            location = db.get(Location, location.id)
            faction = db.get(Faction, faction.id)
            item = db.get(Item, item.id)
            self.assertEqual(location.last_seen_session_id, session_id)
            self.assertEqual(faction.last_seen_session_id, session_id)
            self.assertEqual(item.last_seen_session_id, session_id)

    def test_world_list_shows_last_seen_for_linked_entities(self):
        campaign = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={"title": "The Heist", "date": "2026-01-01", "notes": "Notes"},
        )
        self.client.post(
            f"/campaigns/{campaign}/locations",
            data={"name": "Vault", "description": "Secure.", "location_type": "major"},
        )
        with Session(database.engine) as db:
            session = db.exec(select(SessionModel).where(SessionModel.campaign_id == int(campaign))).first()
            location = db.exec(select(Location).where(Location.name == "Vault")).first()

        self.client.post(
            f"/campaigns/{campaign}/sessions/{session.id}/edit",
            data={
                "title": "The Heist",
                "date": "2026-01-01",
                "notes": "Updated",
                "selected_locations": [str(location.id)],
            },
        )
        response = self.client.get(f"/campaigns/{campaign}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Last seen:", response.content)
        self.assertIn(b"The Heist", response.content)

    def test_world_dashboard_includes_needs_attention(self):
        campaign = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign}/npcs",
            data={"name": "Sparse NPC", "role": "", "description": ""},
        )
        response = self.client.get(f"/campaigns/{campaign}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Needs Attention", response.content)
        self.assertIn(b"Quick Resume", response.content)

    def test_entity_edit_shows_session_appearances(self):
        campaign = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={"title": "S1", "date": "2026-01-01", "notes": "n"},
        )
        self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={"title": "S2", "date": "2026-02-01", "notes": "n"},
        )
        self.client.post(
            f"/campaigns/{campaign}/npcs",
            data={"name": "Traveler", "role": "NPC", "description": "Desc"},
        )
        with Session(database.engine) as db:
            sessions = db.exec(
                select(SessionModel).where(SessionModel.campaign_id == int(campaign)).order_by(SessionModel.id)
            ).all()
            npc = db.exec(select(NPC).where(NPC.name == "Traveler")).first()
            for session in sessions:
                self.client.post(
                    f"/campaigns/{campaign}/sessions/{session.id}/edit",
                    data={
                        "title": session.title,
                        "date": session.date or "",
                        "notes": session.notes or "",
                        "selected_npcs": [str(npc.id)],
                    },
                )
        response = self.client.get(f"/campaigns/{campaign}/npcs/{npc.id}/edit")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"History", response.content)
        self.assertIn(b"S1", response.content)
        self.assertIn(b"S2", response.content)

    def test_campaign_briefing_page_loads(self):
        campaign = self._create_campaign()
        response = self.client.get(f"/campaigns/{campaign}/briefing")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Brief Me", response.content)
        self.assertIn(b"Last Session", response.content)
        self.assertIn(b"Active Plot Threads", response.content)
        self.assertIn(b"Important NPCs", response.content)
        self.assertIn(b"Recent Developments", response.content)
        self.assertIn(b"Unresolved Questions", response.content)
        self.assertIn(b"Dormant Threads", response.content)
        self.assertIn(b"Needs Attention", response.content)
        self.assertIn(b"Print / Export", response.content)
        self.assertIn(b"Download Markdown", response.content)

    def test_campaign_briefing_shows_local_summary(self):
        campaign = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={"title": "Opening Night", "date": "2026-01-01", "notes": "Start."},
        )
        response = self.client.get(f"/campaigns/{campaign}/briefing")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Opening Night", response.content)
        self.assertIn(b"mc-briefing-narrative", response.content)

    def test_lore_board_shows_intelligence_all_clear(self):
        campaign = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={"title": "Only Session", "date": "2026-01-01", "notes": "n"},
        )
        response = self.client.get(f"/campaigns/{campaign}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Campaign Intelligence", response.content)
        self.assertIn(b"All clear", response.content)

    def test_campaign_briefing_print_view_loads(self):
        campaign = self._create_campaign()
        response = self.client.get(f"/campaigns/{campaign}/briefing/print")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Brief Me", response.content)
        self.assertIn(b"print.css", response.content)
        self.assertIn(b"window.print()", response.content)
        self.assertNotIn(b"mc-topbar", response.content)

    def test_campaign_briefing_markdown_export(self):
        campaign = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={"title": "Opening Session", "date": "2026-01-01", "notes": "Notes."},
        )
        response = self.client.get(f"/campaigns/{campaign}/briefing/export/markdown")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "text/markdown; charset=utf-8")
        self.assertIn("# Brief Me: Smoke Test Campaign", response.text)
        self.assertIn("Last Session", response.text)
        self.assertIn("Opening Session", response.text)

    def test_lore_board_shows_intelligence_widget_for_dormant_thread(self):
        campaign = self._create_campaign()
        for idx, title in enumerate(["Session One", "Session Two", "Session Three"], start=1):
            self.client.post(
                f"/campaigns/{campaign}/sessions",
                data={"title": title, "date": f"2026-0{idx}-01", "notes": "n"},
            )
        self.client.post(
            f"/campaigns/{campaign}/threads",
            data={"title": "Old Plot", "status": "Active", "details": "Forgotten thread."},
        )
        with Session(database.engine) as db:
            sessions = db.exec(
                select(SessionModel).where(SessionModel.campaign_id == int(campaign)).order_by(SessionModel.id)
            ).all()
            thread = db.exec(select(PlotThread).where(PlotThread.title == "Old Plot")).first()
            first_session_id = sessions[0].id

        self.client.post(
            f"/campaigns/{campaign}/sessions/{first_session_id}/edit",
            data={
                "title": "Session One",
                "date": "2026-01-01",
                "notes": "n",
                "selected_plot_threads": [str(thread.id)],
            },
        )

        response = self.client.get(f"/campaigns/{campaign}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Campaign Intelligence", response.content)
        self.assertIn(b"Dormant Threads", response.content)
        self.assertIn(b"Old Plot", response.content)

    def test_lore_board_shows_stale_location(self):
        campaign = self._create_campaign()
        for idx, title in enumerate(["Session One", "Session Two", "Session Three"], start=1):
            self.client.post(
                f"/campaigns/{campaign}/sessions",
                data={"title": title, "date": f"2026-0{idx}-01", "notes": "n"},
            )
        self.client.post(
            f"/campaigns/{campaign}/locations",
            data={"name": "Forgotten Hall", "description": "Old place.", "location_type": "major"},
        )
        with Session(database.engine) as db:
            sessions = db.exec(
                select(SessionModel).where(SessionModel.campaign_id == int(campaign)).order_by(SessionModel.id)
            ).all()
            location = db.exec(select(Location).where(Location.name == "Forgotten Hall")).first()
            first_session_id = sessions[0].id

        self.client.post(
            f"/campaigns/{campaign}/sessions/{first_session_id}/edit",
            data={
                "title": "Session One",
                "date": "2026-01-01",
                "notes": "n",
                "selected_locations": [str(location.id)],
            },
        )

        response = self.client.get(f"/campaigns/{campaign}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Stale Locations", response.content)
        self.assertIn(b"Forgotten Hall", response.content)

    def test_workspace_ref_panel_shows_faction_returning_flag(self):
        campaign = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={"title": "Session One", "date": "2026-01-01", "notes": "n"},
        )
        self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={"title": "Session Two", "date": "2026-02-01", "notes": "n"},
        )
        self.client.post(
            f"/campaigns/{campaign}/factions",
            data={"name": "Merchants", "summary": "Trade guild."},
        )
        with Session(database.engine) as db:
            sessions = db.exec(
                select(SessionModel).where(SessionModel.campaign_id == int(campaign)).order_by(SessionModel.id)
            ).all()
            faction = db.exec(select(Faction).where(Faction.name == "Merchants")).first()
            for session in sessions:
                self.client.post(
                    f"/campaigns/{campaign}/sessions/{session.id}/edit",
                    data={
                        "title": session.title,
                        "date": session.date or "",
                        "notes": session.notes or "",
                        "selected_factions": [str(faction.id)],
                    },
                )

        response = self.client.get(
            f"/campaigns/{campaign}/workspace?session_id={sessions[-1].id}&mode=prep"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Active Factions", response.content)
        self.assertIn(b"Merchants", response.content)
        self.assertIn(b"returning", response.content)

    def test_campaign_briefing_markdown_export_includes_stale_location(self):
        campaign = self._create_campaign()
        for idx, title in enumerate(["Session One", "Session Two", "Session Three"], start=1):
            self.client.post(
                f"/campaigns/{campaign}/sessions",
                data={"title": title, "date": f"2026-0{idx}-01", "notes": "n"},
            )
        self.client.post(
            f"/campaigns/{campaign}/locations",
            data={"name": "Stale Keep", "description": "Castle.", "location_type": "major"},
        )
        with Session(database.engine) as db:
            sessions = db.exec(
                select(SessionModel).where(SessionModel.campaign_id == int(campaign)).order_by(SessionModel.id)
            ).all()
            location = db.exec(select(Location).where(Location.name == "Stale Keep")).first()

        self.client.post(
            f"/campaigns/{campaign}/sessions/{sessions[0].id}/edit",
            data={
                "title": "Session One",
                "date": "2026-01-01",
                "notes": "n",
                "selected_locations": [str(location.id)],
            },
        )

        response = self.client.get(f"/campaigns/{campaign}/briefing/export/markdown")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Stale Locations", response.text)
        self.assertIn("Stale Keep", response.text)

    def test_workspace_shows_prep_gap_when_notes_without_analysis(self):
        campaign = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={"title": "Prep Gap Session", "date": "2026-01-01", "notes": "Raw session notes."},
        )
        with Session(database.engine) as db:
            session = db.exec(select(SessionModel).where(SessionModel.campaign_id == int(campaign))).first()

        response = self.client.get(f"/campaigns/{campaign}/workspace?session_id={session.id}&mode=prep")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"no AI analysis yet", response.content)

    def _create_campaign(self):
        response = self.client.post(
            "/campaigns",
            data={"name": "Smoke Test Campaign", "system": "Test System", "description": "Smoke test."},
        )
        self.assertEqual(response.status_code, 303)
        import re

        match = re.search(r"/campaigns/(\d+)", response.headers["location"])
        self.assertIsNotNone(match)
        return match.group(1)


if __name__ == "__main__":
    unittest.main()
