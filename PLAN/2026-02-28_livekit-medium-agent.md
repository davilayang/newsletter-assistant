# Plan: LiveKit Voice Agent for Medium Newsletter

## Context

Two-phase project built on top of the existing Gmail MCP server.

**Phase 1** — A LiveKit voice agent that reads Gmail live each morning session: fetches Medium newsletter emails, summarises articles, answers questions, takes notes.

**Phase 2** — Content accumulates daily into SQLite (raw store) → ChromaDB (vector index) → Neo4j (knowledge graph), growing into a personal knowledge assistant.

---

## Codebase Structure

```
src/
  core/                     # Shared primitives — imported by all components
    __init__.py
    config.py               # pydantic-settings, loads .env
    gmail/
      __init__.py
      client.py             # OAuth + Gmail service setup  (was gmail_api.py)
      ops.py                # list / get / draft / send   (was gmail_ops.py)
    notes.py                # Append-only local markdown note writer

  mcp/                      # MCP servers — one sub-package per server
    gmail/
      __init__.py
      server.py             # FastMCP Gmail tools         (was src/server.py)
    vector_store/           # Phase 2
      __init__.py
      server.py             # FastMCP ChromaDB query tools
    graph/                  # Phase 2+
      __init__.py
      server.py             # FastMCP Neo4j query tools

  agent/                    # LiveKit voice agent
    __init__.py
    agent.py                # VoicePipelineAgent wiring
    tools.py                # LLM function tools (gmail, notes; Phase 2: +search, +graph)

  knowledge/                # Phase 2: knowledge accumulation pipeline
    __init__.py
    medium.py               # Newsletter HTML parser + Jina Reader fetch
    pipeline.py             # run() — entry point for cron or Airflow PythonOperator
    raw_store.py            # SQLite: write raw markdown, dedup, metadata
    vector_store.py         # ChromaDB: read SQLite → chunk → embed → upsert
    graph.py                # Neo4j: entities, relationships, graph queries (Phase 2+)

dags/                       # Airflow DAGs — thin wrappers over knowledge/pipeline.py
  medium_pipeline_dag.py
  graph_enrichment_dag.py   # Phase 2+

tests/
  core/
  mcp/
  agent/
  knowledge/

data/                       # Runtime data — gitignored
  articles.db               # SQLite raw store (source of truth)
  chroma/                   # ChromaDB vector index (rebuildable from articles.db)

logs/                       # gitignored
NOTES/                      # User's saved session notes
PLAN/
```

**Dependency rule — no circular imports:**
```
core  ←  mcp/*
core  ←  agent
core  ←  knowledge
         knowledge  ←  dags/
```

**Entry points:**
```bash
uv run python -m src.mcp.gmail.server        # Gmail MCP server
uv run python -m src.mcp.vector_store.server # Vector store MCP server (Phase 2)
uv run python -m src.agent.agent             # LiveKit voice agent
uv run python -m src.knowledge.pipeline      # Run scraper once (or via cron)
```

---

## Data Flow

### Phase 1 — Live session (agent reads Gmail directly)

```
Morning session:
  User voice
    → Deepgram STT
    → Claude LLM  ←→  tools.py:
                         get_todays_newsletter()  →  core.gmail.ops
                         save_note(...)           →  core.notes
    → ElevenLabs TTS
    → User hears response
```

### Phase 2 — Knowledge accumulation (scheduled pipeline)

```
Daily cron / Airflow:
  knowledge.pipeline.run()
    → core.gmail.ops          fetch unread Medium newsletter emails
    → knowledge.medium        parse HTML → articles, fetch via Jina Reader
    → knowledge.raw_store     write raw markdown to SQLite (articles.db)
    → knowledge.vector_store  read SQLite → chunk → embed → ChromaDB

Agent session (Phase 2):
  tools.py gains:
    search_knowledge(query)   →  knowledge.vector_store.search()
    query_graph(question)     →  knowledge.graph.query()       (Phase 2+)
```

### SQLite schema (`data/articles.db`)

```sql
CREATE TABLE articles (
    url           TEXT PRIMARY KEY,
    title         TEXT,
    author        TEXT,
    newsletter_date DATE,
    scraped_at    TIMESTAMP,
    raw_markdown  TEXT               -- source of truth
);

CREATE TABLE scrape_log (
    gmail_message_id  TEXT PRIMARY KEY,
    processed_at      TIMESTAMP
);
```

ChromaDB is fully rebuildable from `articles.db` at any time.
`articles.db` is the only file that needs to be backed up.

---

## New Dependencies

```toml
# Phase 1 — agent
"livekit-agents>=0.8"
"livekit-plugins-deepgram"
"livekit-plugins-elevenlabs"
"livekit-plugins-anthropic"

# Phase 1 — newsletter parsing
"beautifulsoup4>=4.12"

# Phase 2 — knowledge pipeline
"chromadb>=0.6"
```

`httpx` already present — used for Jina Reader calls.
SQLite — stdlib `sqlite3`, no extra dependency.
Embeddings: ChromaDB default (`all-MiniLM-L6-v2`, local, no extra API key).

---

## Environment Variables (`src/core/config.py`)

```
# Agent
LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET
DEEPGRAM_API_KEY
ELEVENLABS_API_KEY
ANTHROPIC_API_KEY

# Phase 2
NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
```

Loaded from `.env` at project root via pydantic-settings.

---

## Implementation Phases

### Phase 1A — Restructure existing code (no logic changes)

1. `src/gmail_api.py` → `src/core/gmail/client.py`
2. `src/gmail_ops.py` → `src/core/gmail/ops.py`
3. `src/server.py` → `src/mcp/gmail/server.py`, update imports
4. Add `__init__.py` files for all new packages
5. Add `src/core/config.py` (pydantic-settings Settings)

### Phase 1B — `src/core/notes.py`

```python
def save_note(content: str, article_title: str, article_url: str) -> Path:
    # Appends to NOTES/<YYYY-MM-DD>_medium-notes.md
    # ## <title>\n> <url>\n\n<content>\n\n---
```

### Phase 1C — `src/agent/tools.py` + `src/agent/agent.py`

**`tools.py`** — LLM function tools for Phase 1:
- `get_todays_newsletter()` — calls `gmail.ops.list_messages(query="from:noreply@medium.com is:unread")`, fetches and parses each email body with BeautifulSoup, returns structured article list for LLM context
- `save_note(content, article_title, article_url)` — delegates to `core.notes`

**`agent.py`** — LiveKit VoicePipelineAgent:

```python
VoicePipelineAgent(
    vad=silero.VAD.load(),
    stt=deepgram.STT(),
    llm=anthropic.LLM(model="claude-sonnet-4-6"),
    tts=elevenlabs.TTS(),
    chat_ctx=initial_ctx,   # system prompt: reading assistant for Medium newsletters
)
```

### Phase 2A — `src/knowledge/raw_store.py`

- `upsert_article(url, title, author, newsletter_date, raw_markdown)` — INSERT OR REPLACE into `articles`
- `is_processed(gmail_message_id) -> bool` — check `scrape_log`
- `mark_processed(gmail_message_id)` — insert into `scrape_log`
- `get_all_articles(since: date | None) -> list[ArticleRow]` — for re-embedding

### Phase 2B — `src/knowledge/medium.py`

- `parse_newsletter_email(html_body: str) -> list[Article]` — BeautifulSoup on email HTML
- `fetch_article_content(url: str, fallback_snippet: str) -> str` — Jina Reader first, fallback to snippet

### Phase 2C — `src/knowledge/vector_store.py`

- `upsert_article(url, raw_markdown, metadata)` — chunk (~800 tokens, 100 overlap), embed, upsert to ChromaDB
- `search(query, n_results=5) -> list[SearchResult]`
- `rebuild_from_db()` — reads all rows from SQLite, re-embeds everything

### Phase 2D — `src/knowledge/pipeline.py`

```python
def run():
    """Idempotent — safe to rerun. Called by cron or Airflow PythonOperator."""
    for email in gmail.ops.list_messages(query="from:noreply@medium.com is:unread"):
        if raw_store.is_processed(email["id"]):
            continue
        body = gmail.ops.get_message_content(email["id"])["body"]
        for article in medium.parse_newsletter_email(body):
            text = medium.fetch_article_content(article.url, article.snippet)
            raw_store.upsert_article(article.url, article.title, ..., text)
            vector_store.upsert_article(article.url, text, {...})
        raw_store.mark_processed(email["id"])
```

**Cron (initial):**
```
0 7 * * *  cd /abs/path && uv run python -m src.knowledge.pipeline >> logs/scraper.log 2>&1
```

**Airflow (`dags/medium_pipeline_dag.py`):**
```python
from src.knowledge.pipeline import run
with DAG("medium_scraper", schedule="0 7 * * *", ...):
    PythonOperator(task_id="scrape", python_callable=run)
```

### Phase 2E — Extend `src/agent/tools.py`

Add two tools (no changes to `agent.py`):
- `search_knowledge(query)` — `vector_store.search(query)`
- `query_graph(question)` — `graph.query(question)` (Phase 2+)

---

## Verification

**Phase 1:**
```bash
uv run python -m src.agent.agent
# "What's in my newsletter today?"
# "Summarise the first article"
# "Take a note: relevant to my RAG project"
# → NOTES/<today>_medium-notes.md written
```

**Phase 2:**
```bash
uv run python -m src.knowledge.pipeline
# → data/articles.db populated
# → data/chroma/ populated

# In agent session:
# "What have I read about knowledge graphs?"
# → semantic search across all accumulated articles
```

**Unit tests** mirror package structure under `tests/`.
Key: `raw_store`, `medium`, `vector_store` are independently testable with mocks.
