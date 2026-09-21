# Campaign Console MVP

A private AI-assisted GM prep tool built with FastAPI, SQLite, SQLModel, and server-rendered HTML templates.

## Features

- Campaign, Session, NPC, Location, Faction, Item, Plot Thread, and Player Character note CRUD
- SQLite persistence with SQLModel
- Session detail page with notes editing, player recap, GM recap, and next-session prep
- AI session analysis and recap generation (OpenAI, Ollama, Claude/Anthropic, and other HTTP providers)
- Session ingestion workflow: paste raw notes, extract candidates, review links, and save
- Campaign-wide keyword search, semantic vector search, and RAG-style Q&A over lore
- Markdown export, Obsidian-style zip export, and per-campaign JSON/SQLite backups
- Cascade-safe campaign, session, and entity deletion

## Setup

### Quick setup (recommended)

From the project root in PowerShell:

```powershell
.\setup.ps1
```

Or double-click `setup.bat`. To skip the test suite:

```powershell
.\setup.ps1 -SkipTests
```

The script creates `.venv`, installs dependencies, copies `.env.example` to `.env` if needed, and runs tests.

### Manual setup

1. Create a virtual environment:

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Run the development server:

```bash
uvicorn app.main:app --reload
```

4. Open `http://127.0.0.1:8000`

## LLM setup

Copy the example environment file and edit your credentials:

```bash
copy .env.example .env
```

Or open **LLM Settings** in the web UI at `http://127.0.0.1:8000/settings/llm` after starting the server. Settings are saved to `.env` in the project root.

Supported providers:
- `openai`
- `ollama`
- `gemini`
- `mistral`
- `copilot`
- `groq`
- `claude`
- `deepseek`

Example OpenAI setup:

```bash
CAMPAIGN_CONSOLE_LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
```

Example Ollama setup:

```bash
CAMPAIGN_CONSOLE_LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=llama2
```

Example Claude/Anthropic setup:

```bash
CAMPAIGN_CONSOLE_LLM_PROVIDER=claude
ANTHROPIC_API_KEY=sk-ant-...
CLAUDE_MODEL=claude-3-5-sonnet-20241022
```

Example Gemini setup (free-tier friendly defaults):

```bash
CAMPAIGN_CONSOLE_LLM_PROVIDER=gemini
GEMINI_API_KEY=AIza...
GEMINI_MODEL=gemini-2.5-flash-lite
GEMINI_FAST_MODEL=gemini-2.5-flash-lite
GEMINI_REASONING_MODEL=gemini-2.5-flash
GEMINI_DISABLED=false
GEMINI_MIN_INTERVAL_SECONDS=30
```

- **Fast model** (`GEMINI_FAST_MODEL`): ingestion, entity extraction, LLM test
- **Reasoning model** (`GEMINI_REASONING_MODEL`): session analysis, AI review, RAG answers
- **`GEMINI_MODEL`**: fallback default when the task-specific model is not set

`GEMINI_API_URL` is optional. If omitted, the app uses Google's `generateContent` endpoint automatically.

**Anti-spam safeguards (built in):**
- Each AI action makes **one** Gemini call (Analyze, Ingest, AI Review, LLM Test are POST-only).
- Rate limits (429/503) are **not retried** — you get a clear error instead of a retry storm.
- **`GEMINI_MIN_INTERVAL_SECONDS`** (default **30**) spaces out requests on the free tier. Increase to 60 if you still hit limits.
- **`GEMINI_DISABLED`** is an emergency kill switch only — leave it `false` for normal use.

Set `GEMINI_MIN_INTERVAL_SECONDS=0` only if you need to disable throttling (not recommended on free tier).

For other HTTP providers, set the corresponding endpoint and API key:

```bash
CAMPAIGN_CONSOLE_LLM_PROVIDER=groq
GROQ_API_URL=https://api.groq.com/openai/v1/chat/completions
GROQ_API_KEY=...
```

Disable providers you do not use:

```bash
CAMPAIGN_CONSOLE_DISABLED_LLM_PROVIDERS=gemini,mistral,claude
```

Test your provider at `/llm/test`. The tiered test page shows the **active** provider's tiers plus any **other configured** providers (e.g. ChatGPT when Gemini is active). Each tier is one API call.

## Embeddings / semantic search

Embeddings default to **local_fallback** (offline hashed vectors). Hosted embedding APIs are never auto-selected from an API key alone.

```bash
CAMPAIGN_CONSOLE_EMBEDDING_PROVIDER=local_fallback
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

Supported modes: `local_fallback`, `openai`, or `ollama`. Legacy `auto` is treated as `local_fallback`.

- **Rebuild Lore Index** is the only way to build or refresh the search index (never happens on page load).
- Semantic search and Ask warn when the index is missing or stale instead of auto-rebuilding.
- OpenAI bulk embedding (>5 texts) is blocked unless `OPENAI_EMBEDDING_BULK_OK=true`.

## Running tests

```bash
python -m unittest tests.test_app -v
```
