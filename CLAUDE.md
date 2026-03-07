# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A personal knowledge assistant built in two phases:
- **Phase 1** — LiveKit voice agent that reads Gmail Medium newsletter emails each morning, summarises articles, answers questions, and takes notes
- **Phase 2** — Daily scraping pipeline accumulates content into SQLite → ChromaDB (vector search) → Neo4j (knowledge graph)

## Package Manager

This project uses [`uv`](https://docs.astral.sh/uv/) exclusively. Do not use `pip` or `poetry`.

```bash
uv sync              # Install all dependencies (including dev)
uv run <command>     # Run a command in the project virtualenv
```

## Common Commands (via `poe`)

```bash
uv run poe check      # Run all checks: fmt, lint, mypy, tests
uv run poe test       # Run tests (pytest -v)
uv run poe fmt-fix    # Auto-fix formatting with black
uv run poe lint-fix   # Auto-fix linting with ruff
uv run poe fix        # Auto-fix formatting + linting
uv run poe mypy       # Type-check with mypy
```

Run a single test file:
```bash
uv run pytest tests/path/to/test_foo.py -v
```

## Entry Points (via `poe`)

```bash
uv run poe agent               # Run voice agent (console mode, loads .env)
uv run poe agent dev           # Run voice agent in dev mode
uv run poe pipeline            # Run scraping pipeline once (loads .env)
uv run poe frontend            # Run NiceGUI UI at http://127.0.0.1:8080 (loads .env)
```

## Architecture

```
src/
  core/               # Shared primitives — imported by all other packages
    config.py         # pydantic-settings (Settings), loads .env
    gmail/
      client.py       # OAuth 2.0 auth flow + Gmail service client
      ops.py          # list_messages, get_message_content, get_message_html_body, create_draft, send_draft
    notes.py          # Append-only markdown notes writer → NOTES/<date>_medium-notes.md

  mcp/                # MCP servers — one sub-package per server
    gmail/
      server.py       # FastMCP: get_unread_emails, create_draft_reply, send_draft_message
    vector_store/     # Phase 2
    graph/            # Phase 2+

  agent/              # LiveKit voice agent (Phase 1)
    agent.py          # AgentServer: Deepgram STT → openai/gpt-4.1-mini LLM → Inworld TTS
    tools.py          # LLM function tools: get_todays_newsletter, read_article, index_article, save_note, search_knowledge

  knowledge/          # Scraping + knowledge pipeline (Phase 2)
    fetcher.py        # Tiered article fetcher: Jina Reader → mediumapi.com → camoufox (browser)
    medium.py         # Medium newsletter HTML parser + camoufox browser fetcher
    the_batch.py      # "The Batch" (DeepLearning.AI) newsletter email parser
    boring_cashcow.py # "Boring Cash Cow" newsletter email parser
    pipeline.py       # run() — cron / Airflow PythonOperator entrypoint
    raw_store.py      # SQLite: articles table + scrape_log for dedup (Medium)
    batch_store.py    # SQLite store for The Batch newsletter
    cashcow_store.py  # SQLite store for Boring Cash Cow newsletter
    vector_store.py   # ChromaDB: chunk → embed → upsert, semantic search
    graph.py          # Neo4j (Phase 2+)

  frontend/           # NiceGUI web UI (served on port 8080)
    app.py            # Entrypoint — ui.run()
    page.py           # Single-page layout: header, drawer (articles + search), voice session, transcript, notes
    routes.py         # FastAPI GET /token — issues LiveKit JWT and dispatches agent to room
    livekit_widget.py # HTML/JS widget for LiveKit audio (WebSocket push to NiceGUI)

config/               # Runtime config files (not gitignored)
  newsletters.yaml    # Newsletter registry: name → Gmail query + metadata
  speech_replacements.yaml  # TTS normalisation regex rules

dags/                 # Airflow DAGs — thin wrappers over knowledge/pipeline.py

data/                 # Runtime — gitignored
  articles.db         # SQLite raw store (source of truth, back this up)
  chroma/             # ChromaDB vector index (rebuildable from articles.db)

creds/                # GCP OAuth credentials — gitignored
  credentials.json    # Download from Google Cloud Console
  token.json          # Auto-generated on first run
```

**Dependency rule:** `core/` is the only shared package. `mcp/`, `agent/`, `knowledge/` never import from each other. `frontend/` is the exception — it imports from `knowledge/` (raw_store, vector_store) for the UI sidebar.

**Article fetcher tiers** (`knowledge/fetcher.py`):
```
Jina Reader (free/paid) → mediumapi.com (RapidAPI) → camoufox (headless browser)
```
`fetch_and_cache(url)` is the single entry point used by both the pipeline and the agent's `read_article` tool — every successful fetch is persisted to `raw_store` automatically.

**Data pipeline (Phase 2):**
```
Gmail → medium.py → raw_store (SQLite) → vector_store (ChromaDB) → graph (Neo4j)
```
ChromaDB is fully rebuildable from `articles.db`. Only `articles.db` needs to be backed up.

**Newsletter parsers:** Each newsletter source has its own parser + SQLite store pair (e.g. `the_batch.py` + `batch_store.py`, `boring_cashcow.py` + `cashcow_store.py`). Parsers take raw email HTML/MIME, extract sections into dataclasses, and the corresponding store persists them. When adding a new newsletter, follow this pattern: create a parser module and a dedicated store module.

## MCP Server Configuration

To register the Gmail MCP server in `.mcp.json` (for Claude Code CLI):
```json
{
  "mcpServers": {
    "mcp-gmail": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/mcp-project", "run", "-m", "src.mcp.gmail.server"]
    }
  }
}
```

## Setup Prerequisites

1. GCP OAuth 2.0 credentials at `creds/credentials.json` (Google Cloud Console → Gmail API → Credentials → OAuth 2.0 Client IDs)
2. `.env` file at project root — required keys (see `src/core/config.py`):
   - `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`
   - `DEEPGRAM_API_KEY`
   - `OPENAI_API_KEY` (agent LLM)
   - `ANTHROPIC_API_KEY`
   - `JINA_API_KEY` *(optional — higher rate limits)*
   - `RAPIDAPI_KEY` *(required for Tier 2 mediumapi.com fetcher)*
   - `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` *(Phase 2+)*
3. `uv` installed
