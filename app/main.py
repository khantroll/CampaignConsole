from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.database import create_db_and_tables
from app.middleware import AuthMiddleware
from app.services.provider_router import log_active_llm_config
from app.services import rule_indexer as rule_indexer_module
from app.services.rule_indexer import RuleIndexerService
from app.routers import auth, campaigns, debug, entities, export, ingestion, llm, locations, player, player_journal, search, sessions, workspace, workspace_narrative

rule_indexer: RuleIndexerService | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global rule_indexer

    create_db_and_tables()
    log_active_llm_config()

    rule_indexer = RuleIndexerService()
    rule_indexer.load()
    rule_indexer_module.rule_indexer = rule_indexer
    app.state.rule_indexer = rule_indexer

    yield


app = FastAPI(title="Campaign Console", lifespan=lifespan)
app.add_middleware(AuthMiddleware)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth.router)
app.include_router(campaigns.router)
app.include_router(player.router)
app.include_router(player_journal.router)
app.include_router(sessions.router)
app.include_router(workspace.router)
app.include_router(workspace_narrative.router)
app.include_router(entities.router)
app.include_router(locations.router)
app.include_router(ingestion.router)
app.include_router(export.router)
app.include_router(search.router)
app.include_router(llm.router)
app.include_router(debug.router)
