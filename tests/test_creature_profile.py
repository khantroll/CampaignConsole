"""Tests for creature entity type, relationships, sessions, and ingestion."""

from __future__ import annotations

import unittest

from sqlmodel import Session, select

import app.database as database
from app.models import (
    Creature,
    CreatureFactionLink,
    CreatureLocationLink,
    CreaturePlotThreadLink,
    Faction,
    Location,
    PlotThread,
    SessionCreatureLink,
    SessionModel,
)
from app.services.ingestion import candidates_for_review, normalize_extraction, prepare_review_candidates
from tests.test_app import CampaignConsoleSmokeTests


class CreatureProfileTests(CampaignConsoleSmokeTests):
    def test_creature_monster_profile_fields(self):
        campaign_id = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign_id}/creatures",
            data={
                "name": "Troglodyte (Black-Skinned Subterranean Variant)",
                "classification": "Reptilian Humanoid",
                "habitat": "The Labyrinth, Deep Sewers, Ruins of Ghul's Labyrinth",
                "threat_level": "Moderate / High (En Masse)",
                "physical_description": (
                    "Thick, rubbery, oil-black scales providing near-flawless camouflage.\n"
                    "Sinuous, muscled build adapted for tunneling and ambush."
                ),
                "special_traits": (
                    "Oily Musk Stench: Secretes a pungent chemical aura.\n"
                    "Chameleonic Hide: Dark skin shifts against stone."
                ),
                "campaign_context_tactics": (
                    "Primal Territorialism: Hostile to surface delvers.\n"
                    "Labyrinth Sentinels: Pack encounters mark deeper zones."
                ),
            },
        )
        with Session(database.engine) as db:
            creature = db.exec(
                select(Creature).where(Creature.name == "Troglodyte (Black-Skinned Subterranean Variant)")
            ).first()
            self.assertEqual(creature.classification, "Reptilian Humanoid")
            self.assertIn("oil-black scales", creature.physical_description)

        response = self.client.get(f"/campaigns/{campaign_id}/creatures/{creature.id}/edit")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Classification", response.content)
        self.assertIn(b"Threat Level", response.content)
        self.assertIn(b"Special Traits &amp; Abilities", response.content)
        self.assertIn(b"Campaign Context &amp; Tactics", response.content)

    def test_creature_profile_fields_and_links(self):
        campaign_id = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign_id}/factions",
            data={"name": "Wild Hunt", "summary": "Beast pack."},
        )
        self.client.post(
            f"/campaigns/{campaign_id}/locations",
            data={"name": "Old Mines", "location_type": "sub", "description": "Abandoned tunnels."},
        )
        self.client.post(
            f"/campaigns/{campaign_id}/threads",
            data={"title": "Mine Threat", "status": "active", "details": "Something lurks below."},
        )
        self.client.post(
            f"/campaigns/{campaign_id}/creatures",
            data={
                "name": "Black-skinned Reptilian",
                "creature_type": "hostile",
                "description": "Scaled ambush predators.",
            },
        )
        with Session(database.engine) as db:
            creature = db.exec(select(Creature).where(Creature.name == "Black-skinned Reptilian")).first()
            faction = db.exec(select(Faction).where(Faction.name == "Wild Hunt")).first()
            location = db.exec(select(Location).where(Location.name == "Old Mines")).first()
            thread = db.exec(select(PlotThread).where(PlotThread.title == "Mine Threat")).first()

        self.client.post(
            f"/campaigns/{campaign_id}/creatures/{creature.id}/edit",
            data={
                "name": "Black-skinned Reptilian",
                "creature_type": "other",
                "creature_type_custom": "Reptilian Humanoid",
                "classification": "Reptilian Humanoid",
                "habitat": "Old Mines",
                "threat_level": "Moderate",
                "physical_description": "Scaled ambush predators.",
                "campaign_context_tactics": "Attacked the party near the mines.",
                "selected_factions": [str(faction.id)],
                "selected_locations": [str(location.id)],
                "selected_plot_threads": [str(thread.id)],
            },
        )

        with Session(database.engine) as db:
            creature = db.get(Creature, creature.id)
            self.assertEqual(creature.creature_type, "reptilian_humanoid")
            self.assertEqual(creature.classification, "Reptilian Humanoid")
            self.assertEqual(creature.campaign_context_tactics, "Attacked the party near the mines.")
            self.assertEqual(
                len(db.exec(select(CreatureFactionLink).where(CreatureFactionLink.creature_id == creature.id)).all()),
                1,
            )

        response = self.client.get(f"/campaigns/{campaign_id}/creatures/{creature.id}/edit")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Related Factions", response.content)
        self.assertIn(b"Reptilian Humanoid", response.content)

    def test_creature_session_link_and_lore_board(self):
        campaign_id = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign_id}/creatures",
            data={"name": "Dire Wolf", "creature_type": "beast", "description": "Large wolf."},
        )
        self.client.post(
            f"/campaigns/{campaign_id}/sessions",
            data={"title": "Forest Ambush", "date": "Day 1", "notes": "Wolves attacked."},
        )
        with Session(database.engine) as db:
            creature = db.exec(select(Creature).where(Creature.name == "Dire Wolf")).first()
            session = db.exec(select(SessionModel).where(SessionModel.title == "Forest Ambush")).first()

        self.client.post(
            f"/campaigns/{campaign_id}/sessions/{session.id}/edit",
            data={
                "title": "Forest Ambush",
                "selected_creatures": [str(creature.id)],
            },
        )

        with Session(database.engine) as db:
            links = db.exec(
                select(SessionCreatureLink).where(SessionCreatureLink.session_id == session.id)
            ).all()
            self.assertEqual(len(links), 1)
            creature = db.get(Creature, creature.id)
            self.assertEqual(creature.last_seen_session_id, session.id)

        board = self.client.get(f"/campaigns/{campaign_id}")
        self.assertEqual(board.status_code, 200)
        self.assertIn(b"creatures-section", board.content)
        self.assertIn(b"Dire Wolf", board.content)

    def test_creature_acceptance_extraction(self):
        """Session note about reptilians should normalize to Creatures, not Items/NPCs."""
        note = "The party fought three black-skinned reptilians near the old mines."
        data = {
            "Characters": [],
            "Creatures": ["Black-skinned Reptilian"],
            "Locations": [{"name": "old mines", "type": "sub", "confidence": "high"}],
            "Factions": [],
            "Items": [],
            "PlotThreads": [],
            "SecretsClues": [],
            "UnresolvedHooks": [],
            "EntityRelationships": [],
        }
        normalized = normalize_extraction(data)
        self.assertIn("Black-skinned Reptilian", normalized["extracted_creatures"])
        self.assertNotIn("Black-skinned Reptilian", normalized["extracted_items"])
        self.assertNotIn("Black-skinned Reptilian", normalized["extracted_characters"])

        review = prepare_review_candidates(normalized, [], [])
        candidates = candidates_for_review(review)
        self.assertEqual(candidates["Creatures"], ["Black-skinned Reptilian"])
        self.assertEqual(candidates["Items"], [])
        self.assertEqual(candidates["NPCs"], [])

        captain_data = normalize_extraction(
            {
                "Characters": ["Captain Serana"],
                "Creatures": [],
                "Locations": [],
                "Factions": [],
                "Items": [],
                "PlotThreads": [],
            }
        )
        self.assertIn("Captain Serana", captain_data["extracted_characters"])
        self.assertEqual(captain_data["extracted_creatures"], [])

    def test_misplaced_creature_names_removed_from_items_bucket(self):
        data = {
            "Creatures": ["Goblin"],
            "Items": ["Goblin", "Healing Potion"],
        }
        normalized = normalize_extraction(data)
        self.assertEqual(normalized["extracted_creatures"], ["Goblin"])
        self.assertEqual(normalized["extracted_items"], ["Healing Potion"])


if __name__ == "__main__":
    unittest.main()
