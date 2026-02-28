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

## Architecture

```
src/
  core/               # Shared primitives — imported by all components
    config.py         # pydantic-settings, loads .env
    gmail/
      client.py       # OAuth 2.0 auth flow + Gmail service client
      ops.py          # list_messages, get_message_content, create_draft, send_draft
    notes.py          # Append-only markdown notes writer → NOTES/<date>_medium-notes.md

  mcp/                # MCP servers — one sub-package per server
    gmail/
      server.py       # FastMCP: get_unread_emails, create_draft_reply, send_draft_message
    vector_store/     # Phase 2
    graph/            # Phase 2+

  agent/              # LiveKit voice agent (Phase 1)
    agent.py          # VoicePipelineAgent: Deepgram STT → Claude LLM → ElevenLabs TTS
    tools.py          # LLM function tools: get_todays_newsletter, save_note

  knowledge/          # Scraping + knowledge pipeline (Phase 2)
    medium.py         # Newsletter HTML parser + Jina Reader fetch
    pipeline.py       # run() — cron / Airflow PythonOperator entrypoint
    raw_store.py      # SQLite: articles table + scrape_log for dedup
    vector_store.py   # ChromaDB: chunk → embed → upsert, semantic search
    graph.py          # Neo4j (Phase 2+)

dags/                 # Airflow DAGs — thin wrappers over knowledge/pipeline.py

data/                 # Runtime — gitignored
  articles.db         # SQLite raw store (source of truth, back this up)
  chroma/             # ChromaDB vector index (rebuildable from articles.db)

creds/                # GCP OAuth credentials — gitignored
  credentials.json    # Download from Google Cloud Console
  token.json          # Auto-generated on first run
```

**Dependency rule:** only `core/` is imported by other packages. `mcp/`, `agent/`, `knowledge/` never import from each other.

**Data pipeline (Phase 2):**
```
Gmail → medium.py → raw_store (SQLite) → vector_store (ChromaDB) → graph (Neo4j)
```
ChromaDB is fully rebuildable from `articles.db`. Only `articles.db` needs to be backed up.

## Entry Points

```bash
uv run python -m src.mcp.gmail.server       # Gmail MCP server
uv run python -m src.agent.agent            # LiveKit voice agent
uv run python -m src.knowledge.pipeline     # Run scraper once
```

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
2. `.env` file at project root with keys for LiveKit, Deepgram, ElevenLabs, Anthropic (see `src/core/config.py` for all keys)
3. `uv` installed
