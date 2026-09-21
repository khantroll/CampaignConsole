from sqlalchemy import text
from sqlmodel import Session, delete

from app.models import (
    Campaign,
    CampaignLoreIndex,
    Creature,
    Faction,
    Item,
    Location,
    LoreChunk,
    NPC,
    PlayerCharacterNote,
    PlotThread,
    SessionModel,
)
from app.services.backup import LINK_TABLE_FILTERS

CAMPAIGN_ENTITY_MODELS = (
    SessionModel,
    NPC,
    Location,
    Faction,
    Item,
    Creature,
    PlotThread,
    PlayerCharacterNote,
    LoreChunk,
)


def delete_campaign_cascade(db: Session, campaign_id: int) -> None:
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise ValueError("Campaign not found.")

    for table, where_clause in LINK_TABLE_FILTERS.items():
        sql = f"DELETE FROM {table} WHERE {where_clause.replace('?', ':campaign_id')}"
        db.execute(text(sql), {"campaign_id": campaign_id})

    for model in CAMPAIGN_ENTITY_MODELS:
        db.exec(delete(model).where(model.campaign_id == campaign_id))

    db.exec(delete(CampaignLoreIndex).where(CampaignLoreIndex.campaign_id == campaign_id))
    db.delete(campaign)
    db.commit()
