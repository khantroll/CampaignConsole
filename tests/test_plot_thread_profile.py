"""Tests for plot thread profile fields and related actor/location links."""

from __future__ import annotations

from sqlmodel import Session, select

import app.database as database
from app.models import (
    Creature,
    CreaturePlotThreadLink,
    Faction,
    FactionPlotThreadLink,
    Location,
    NPC,
    NPCPlotThreadLink,
    PCPlotThreadLink,
    PlayerCharacterNote,
    PlotThread,
    LocationPlotThreadLink,
    PlotThreadRelatedPlotThreadLink,
)
from app.services.plot_thread_links import load_related_plot_threads
from tests.test_app import CampaignConsoleSmokeTests


class PlotThreadProfileTests(CampaignConsoleSmokeTests):
    def test_plot_thread_profile_fields_and_related_links(self):
        campaign_id = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign_id}/npcs",
            data={"name": "Shilukar", "role": "Guide", "description": "Mysterious elf."},
        )
        self.client.post(
            f"/campaigns/{campaign_id}/pcs",
            data={"character_name": "Agnarr", "notes": "Fighter."},
        )
        self.client.post(
            f"/campaigns/{campaign_id}/locations",
            data={"name": "Ghostly Minstrel", "location_type": "major", "description": "The inn."},
        )
        self.client.post(
            f"/campaigns/{campaign_id}/factions",
            data={"name": "Iron Crown", "summary": "A secretive order."},
        )
        self.client.post(
            f"/campaigns/{campaign_id}/creatures",
            data={"name": "Shadow Wolf", "creature_type": "beast", "description": "A stalker in the dark."},
        )
        self.client.post(
            f"/campaigns/{campaign_id}/threads",
            data={
                "title": "The Mystery of Their Amnesia",
                "thread_type": "Campaign Master Arc / Metaplot",
                "status": "active",
                "details": "The party woke with no memory at the inn.",
                "plot_significance_notes": "This thread motivates the party's search for answers.",
            },
        )

        with Session(database.engine) as db:
            thread = db.exec(
                select(PlotThread).where(PlotThread.title == "The Mystery of Their Amnesia")
            ).first()
            npc = db.exec(select(NPC).where(NPC.name == "Shilukar")).first()
            pc = db.exec(select(PlayerCharacterNote).where(PlayerCharacterNote.character_name == "Agnarr")).first()
            location = db.exec(select(Location).where(Location.name == "Ghostly Minstrel")).first()
            faction = db.exec(select(Faction).where(Faction.name == "Iron Crown")).first()
            creature = db.exec(select(Creature).where(Creature.name == "Shadow Wolf")).first()
            self.assertEqual(thread.thread_type, "Campaign Master Arc / Metaplot")
            self.assertIn("no memory", thread.details)

        self.client.post(
            f"/campaigns/{campaign_id}/threads/{thread.id}/edit",
            data={
                "title": "The Mystery of Their Amnesia",
                "thread_type": "Campaign Master Arc / Metaplot",
                "status": "active",
                "details": "The party woke with no memory at the inn.",
                "plot_significance_notes": "This thread motivates the party's search for answers.",
                "selected_npcs": [str(npc.id)],
                "selected_pcs": [str(pc.id)],
                "selected_locations": [str(location.id)],
                "selected_factions": [str(faction.id)],
                "selected_creatures": [str(creature.id)],
            },
        )

        with Session(database.engine) as db:
            thread = db.get(PlotThread, thread.id)
            self.assertEqual(thread.plot_significance_notes, "This thread motivates the party's search for answers.")
            npc_links = db.exec(
                select(NPCPlotThreadLink).where(NPCPlotThreadLink.plot_thread_id == thread.id)
            ).all()
            pc_links = db.exec(
                select(PCPlotThreadLink).where(PCPlotThreadLink.plot_thread_id == thread.id)
            ).all()
            location_links = db.exec(
                select(LocationPlotThreadLink).where(LocationPlotThreadLink.plot_thread_id == thread.id)
            ).all()
            faction_links = db.exec(
                select(FactionPlotThreadLink).where(FactionPlotThreadLink.plot_thread_id == thread.id)
            ).all()
            creature_links = db.exec(
                select(CreaturePlotThreadLink).where(CreaturePlotThreadLink.plot_thread_id == thread.id)
            ).all()
            self.assertEqual(len(npc_links), 1)
            self.assertEqual(npc_links[0].npc_id, npc.id)
            self.assertEqual(len(pc_links), 1)
            self.assertEqual(pc_links[0].pc_note_id, pc.id)
            self.assertEqual(len(location_links), 1)
            self.assertEqual(location_links[0].location_id, location.id)
            self.assertEqual(len(faction_links), 1)
            self.assertEqual(faction_links[0].faction_id, faction.id)
            self.assertEqual(len(creature_links), 1)
            self.assertEqual(creature_links[0].creature_id, creature.id)

        edit_page = self.client.get(f"/campaigns/{campaign_id}/threads/{thread.id}/edit")
        self.assertEqual(edit_page.status_code, 200)
        self.assertIn(b"Thread Type", edit_page.content)
        self.assertIn(b"Plot Significance / Notes", edit_page.content)
        self.assertIn(b"Key Actors (NPCs)", edit_page.content)
        self.assertIn(b"Key Actors (Party Members)", edit_page.content)
        self.assertIn(b"Key Locations", edit_page.content)
        self.assertIn(b"Related Factions", edit_page.content)
        self.assertIn(b"Related Creatures", edit_page.content)
        self.assertIn(f'value="{npc.id}" selected'.encode(), edit_page.content)
        self.assertIn(f'value="{pc.id}" selected'.encode(), edit_page.content)
        self.assertIn(f'value="{location.id}" selected'.encode(), edit_page.content)
        self.assertIn(f'value="{faction.id}" selected'.encode(), edit_page.content)
        self.assertIn(f'value="{creature.id}" selected'.encode(), edit_page.content)

    def test_plot_thread_related_plot_threads(self):
        campaign_id = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign_id}/threads",
            data={"title": "Main Arc", "status": "active", "details": "Overarching mystery."},
        )
        self.client.post(
            f"/campaigns/{campaign_id}/threads",
            data={"title": "Side Quest", "status": "active", "details": "A detour."},
        )
        with Session(database.engine) as db:
            main = db.exec(select(PlotThread).where(PlotThread.title == "Main Arc")).first()
            side = db.exec(select(PlotThread).where(PlotThread.title == "Side Quest")).first()

        self.client.post(
            f"/campaigns/{campaign_id}/threads/{main.id}/edit",
            data={
                "title": "Main Arc",
                "status": "active",
                "details": "Overarching mystery.",
                "selected_related_plot_threads": [str(side.id)],
            },
        )

        with Session(database.engine) as db:
            links = db.exec(
                select(PlotThreadRelatedPlotThreadLink).where(
                    PlotThreadRelatedPlotThreadLink.plot_thread_id == main.id
                )
            ).all()
            reverse_links = db.exec(
                select(PlotThreadRelatedPlotThreadLink).where(
                    PlotThreadRelatedPlotThreadLink.plot_thread_id == side.id
                )
            ).all()
            self.assertEqual(len(links), 1)
            self.assertEqual(links[0].related_plot_thread_id, side.id)
            self.assertEqual(len(reverse_links), 1)
            self.assertEqual(reverse_links[0].related_plot_thread_id, main.id)
            related = load_related_plot_threads(db, int(campaign_id), main.id)
            self.assertEqual([thread.title for thread in related], ["Side Quest"])

        edit_page = self.client.get(f"/campaigns/{campaign_id}/threads/{main.id}/edit")
        self.assertIn(b"Related Plot Threads", edit_page.content)
        self.assertIn(f'value="{side.id}" selected'.encode(), edit_page.content)
