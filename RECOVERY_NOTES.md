# Campaign Console Recovery Notes

Recovery date: 2026-09-21

## Source

This repository was reconstructed from the latest surviving Campaign Console / DMAssistant archive found in the ChatGPT file library: `DMAssistant (2)(1).zip`, uploaded 2026-06-25. Its source files carry edits through 2026-06-24. Earlier surviving archives include `DMAssistant (12).zip` (2026-06-13) and `DMAssistant(3).zip` (2026-06-17).

This June 25 archive is materially newer than those earlier builds and is the best surviving baseline currently recovered. A still-later local desktop copy may exist and should be compared on a separate branch rather than overwriting this baseline.

## Recovered implementation

The recovered application is the Campaign Console D&D GM-prep system. The archive contains the FastAPI/Jinja/SQLite/HTMX-era implementation, including campaign/session/entity management, ingestion and review, LLM/provider routing, search, export, backups, campaign intelligence, session workspace, relationship/history tooling, campaign briefing, world-state/context enrichment, rules lookup, and Phase 3 structural narrative-block work.

The included `docs/cursor-session-log-2026-06-24.md` is especially valuable: it records the June 24 implementation session and reports successful test milestones including 133 Phase 2 world-state tests and 257 Phase 3 narrative-block tests after fixes.

## Public-repository sanitation

The recovery package intentionally excludes the uploaded runtime databases (`campaign_console.db` and `.bak`), Python virtual environments/caches, backups, and `.env` secrets. A defensive `.gitignore` was added. Do not commit a real `.env`, runtime database, campaign data, or API credentials.

## Validation note

A test run in the recovery environment could not collect because this environment does not have the project's Python dependencies installed (`sqlmodel` is the first missing module). This is an environment/dependency issue, not evidence that the recovered source fails its historical tests. Install `requirements.txt` in a clean virtual environment before validating.

## Recommended recovery workflow

1. Commit this package unchanged as the recovered baseline.
2. Tag it something like `recovery-2026-06-25`.
3. If a newer desktop copy is found, import it on a separate branch.
4. Diff code, migrations/schema, templates, tests, and docs before choosing a new canonical main.
5. Preserve this recovery commit even if the desktop copy proves newer.
