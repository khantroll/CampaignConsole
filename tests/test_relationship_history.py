"""Tests for relationship history audit log."""

import unittest

from sqlmodel import Session, select

from app import database
from app.models import EntityRelationshipEvent, Faction, NPC, SessionModel
from app.services.relationship_history import get_entity_relationship_history, log_relationship_event
from tests.test_app import CampaignConsoleSmokeTests


class RelationshipHistoryTests(CampaignConsoleSmokeTests):
    def test_entity_edit_logs_link_and_unlink(self):
        campaign = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign}/npcs",
            data={"name": "Hero NPC", "role": "Guide", "description": "Test NPC."},
        )
        self.client.post(
            f"/campaigns/{campaign}/factions",
            data={"name": "Test Guild", "summary": "A faction."},
        )
        with Session(database.engine) as db:
            npc = db.exec(select(NPC).where(NPC.campaign_id == int(campaign))).first()
            faction = db.exec(select(Faction).where(Faction.campaign_id == int(campaign))).first()
            npc_id = npc.id
            faction_id = faction.id

        self.client.post(
            f"/campaigns/{campaign}/npcs/{npc_id}/edit",
            data={
                "name": "Hero NPC",
                "role": "Guide",
                "description": "Test NPC.",
                "selected_factions": [str(faction_id)],
            },
        )

        with Session(database.engine) as db:
            events = db.exec(
                select(EntityRelationshipEvent).where(EntityRelationshipEvent.campaign_id == int(campaign))
            ).all()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].action, "linked")
            self.assertEqual(events[0].source_kind, "npcs")
            self.assertEqual(events[0].target_kind, "factions")

        self.client.post(
            f"/campaigns/{campaign}/npcs/{npc_id}/edit",
            data={
                "name": "Hero NPC",
                "role": "Guide",
                "description": "Test NPC.",
            },
        )

        with Session(database.engine) as db:
            events = db.exec(
                select(EntityRelationshipEvent)
                .where(EntityRelationshipEvent.campaign_id == int(campaign))
                .order_by(EntityRelationshipEvent.created_at)
            ).all()
            self.assertEqual(len(events), 2)
            self.assertEqual(events[1].action, "unlinked")

        response = self.client.get(f"/campaigns/{campaign}/npcs/{npc_id}/edit")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Relationship History", response.content)
        self.assertIn(b"Test Guild", response.content)
        self.assertIn(b"Linked", response.content)
        self.assertIn(b"Unlinked", response.content)

    def test_entity_edit_attributes_session_from_return_to(self):
        campaign = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={"title": "Prep Night", "date": "2026-01-01", "notes": "n"},
        )
        self.client.post(
            f"/campaigns/{campaign}/npcs",
            data={"name": "Scout", "role": "Guide", "description": "Tracks paths."},
        )
        self.client.post(
            f"/campaigns/{campaign}/factions",
            data={"name": "Rangers", "summary": "Woodland order."},
        )
        with Session(database.engine) as db:
            session = db.exec(select(SessionModel).where(SessionModel.campaign_id == int(campaign))).first()
            npc = db.exec(select(NPC).where(NPC.name == "Scout")).first()
            faction = db.exec(select(Faction).where(Faction.name == "Rangers")).first()
            session_id = session.id
            npc_id = npc.id
            faction_id = faction.id

        return_to = f"/campaigns/{campaign}/workspace?session_id={session_id}&mode=prep"
        self.client.post(
            f"/campaigns/{campaign}/npcs/{npc_id}/edit",
            data={
                "name": "Scout",
                "role": "Guide",
                "description": "Tracks paths.",
                "selected_factions": [str(faction_id)],
                "return_to": return_to,
            },
        )

        with Session(database.engine) as db:
            event = db.exec(
                select(EntityRelationshipEvent).where(EntityRelationshipEvent.campaign_id == int(campaign))
            ).first()
            self.assertIsNotNone(event)
            self.assertEqual(event.session_id, session_id)

        response = self.client.get(f"/campaigns/{campaign}/npcs/{npc_id}/edit")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Prep Night", response.content)
        self.assertNotIn(b"via entity edit", response.content)

    def test_entity_edit_attributes_session_from_persisted_cookie(self):
        campaign = self._create_campaign()
        self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={"title": "Session Alpha", "date": "2026-01-01", "notes": "n"},
        )
        self.client.post(
            f"/campaigns/{campaign}/sessions",
            data={"title": "Session Beta", "date": "2026-02-01", "notes": "n"},
        )
        self.client.post(
            f"/campaigns/{campaign}/npcs",
            data={"name": "Cleric", "role": "Healer", "description": "Holy support."},
        )
        self.client.post(
            f"/campaigns/{campaign}/factions",
            data={"name": "Temple", "summary": "Faithful order."},
        )
        with Session(database.engine) as db:
            sessions = db.exec(
                select(SessionModel).where(SessionModel.campaign_id == int(campaign)).order_by(SessionModel.id)
            ).all()
            npc = db.exec(select(NPC).where(NPC.name == "Cleric")).first()
            faction = db.exec(select(Faction).where(Faction.name == "Temple")).first()
            session_id = sessions[-1].id
            npc_id = npc.id
            faction_id = faction.id

        self.client.cookies.set(f"mc_session_{campaign}", str(session_id))
        self.client.post(
            f"/campaigns/{campaign}/npcs/{npc_id}/edit",
            data={
                "name": "Cleric",
                "role": "Healer",
                "description": "Holy support.",
                "selected_factions": [str(faction_id)],
            },
        )

        with Session(database.engine) as db:
            event = db.exec(
                select(EntityRelationshipEvent).where(EntityRelationshipEvent.campaign_id == int(campaign))
            ).first()
            self.assertIsNotNone(event)
            self.assertEqual(event.session_id, session_id)

        response = self.client.get(f"/campaigns/{campaign}/npcs/{npc_id}/edit")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Session Beta", response.content)

    def test_get_entity_relationship_history_partner_resolution(self):
        campaign_id = int(self._create_campaign())
        with Session(database.engine) as db:
            npc = NPC(campaign_id=campaign_id, name="A", role="r", description="d")
            faction = Faction(campaign_id=campaign_id, name="B", summary="s")
            db.add(npc)
            db.add(faction)
            db.commit()
            db.refresh(npc)
            db.refresh(faction)
            log_relationship_event(
                db,
                campaign_id,
                "npcs",
                npc.id,
                "factions",
                faction.id,
                "linked",
            )
            db.commit()

            history = get_entity_relationship_history(db, campaign_id, "factions", faction.id)
            self.assertIsNotNone(history)
            self.assertEqual(history["event_count"], 1)
            self.assertEqual(history["events"][0]["partner_name"], "A")
            self.assertEqual(history["events"][0]["partner_kind"], "npcs")


if __name__ == "__main__":
    unittest.main()
