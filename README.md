# Email Newsletter Assistant

A personal knowledge assistant built on Gmail and LiveKit. Talk to your Medium newsletter by voice — ask questions, get summaries, take notes. A daily scraping pipeline accumulates article content into a searchable knowledge base.

## Prerequisites

1. **Python 3.13** and [`uv`](https://docs.astral.sh/uv/)
2. **GCP OAuth 2.0 credentials** for Gmail API
   - Google Cloud Console → Gmail API → Credentials → OAuth 2.0 Client IDs → Download JSON
   - Save as `creds/credentials.json`
3. **API keys** — create a `.env` file at the project root:

```env
OPENAI_API_KEY=...

LIVEKIT_URL=...
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...
```

## Setup

```bash
uv sync
```

On first run the Gmail OAuth consent flow will open in your browser and save a token to `creds/token.json`.

### Medium authentication (required for full article content)

The scraping pipeline and the agent's `read_article` tool fetch full article content through your Medium account. Run this once to save your session credentials:

```bash
uv run python scripts/medium_login.py
```

A browser window will open — log in to Medium, then press Enter in the terminal. Auth state is saved to `creds/medium_auth.json`. Re-run when fetching stops working (sessions typically last weeks to months).

## Usage

### Voice Agent

**Console mode** — text I/O in the terminal, no LiveKit room needed:

```bash
uv run poe agent
# or equivalently:
uv run --env-file .env python -m src.agent.agent console
```

**Dev mode** — connects to a LiveKit room with hot reload:

```bash
uv run poe agent dev
# or equivalently:
uv run --env-file .env python -m src.agent.agent dev --reload

# If using iTerm2, suppress the conflicting TERM_PROGRAM variable:
TERM_PROGRAM=0 uv run --env-file .env python -m src.agent.agent dev --reload
```

Then open https://agents-playground.livekit.io/ and connect with your LiveKit credentials to speak with the agent.

The agent has four tools:

| Tool | When it's called |
|---|---|
| `get_todays_newsletter` | "Load my newsletter", "What arrived this morning?" |
| `read_article` | "Read me that article", "Summarise it in detail" |
| `save_note` | "Take a note", "Remember this" |
| `search_knowledge` | "What have I read about RAG?", "Find that article on transformers" |

Example session:

> "Load my newsletter."
> "Read the second article."
> "Take a note: relevant to my RAG project."
> "What have I read about vector databases?"

Notes are saved to `NOTES/<today's date>_medium-notes.md`.

### Scraping pipeline

The pipeline reads unread Medium newsletter emails from Gmail, fetches full article content via a headless Firefox browser (camoufox), and stores everything in SQLite + ChromaDB for later search.

```bash
uv run poe pipeline
# or equivalently:
uv run --env-file .env python -m src.knowledge.pipeline
```

Run this daily (cron / Airflow) to keep the knowledge base up to date. The pipeline is idempotent — safe to run multiple times.

**Data files** (gitignored, back up `articles.db`):

```
data/
  articles.db   # SQLite — source of truth for all scraped articles
  chroma/       # ChromaDB vector index (rebuildable from articles.db)
```

### Gmail MCP server

Exposes three tools to Claude: `get_unread_emails`, `create_draft_reply`, `send_draft_message`.

#### With Claude Code CLI

Register with Claude Code CLI by adding to `.mcp.json`:

```json
{
  "mcpServers": {
    "mcp-gmail": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/newsletter-assistant", "run", "-m", "src.mcp.gmail.server"]
    }
  }
}
```

Check with `claude mcp list`.

## Development

```bash
uv run poe check       # fmt + lint + typecheck + tests
uv run poe fix         # auto-fix formatting and linting
uv run pytest tests/path/to/test_file.py -v  # single test file
```

## Project structure

```
src/
  core/          # Shared: Gmail client, config, notes writer
  mcp/gmail/     # MCP server for Claude Code / Desktop
  agent/         # LiveKit voice agent + function tools (Phase 1)
  knowledge/     # Scraping pipeline, SQLite store, ChromaDB (Phase 2)
scripts/
  medium_login.py   # One-time Medium auth setup
dags/             # Airflow DAGs (Phase 2)
data/             # Runtime data — gitignored
  articles.db     # SQLite raw store
  chroma/         # ChromaDB vector index
creds/            # OAuth credentials — gitignored
NOTES/            # Your saved session notes
```

## References

- https://github.com/livekit-examples/python-agents-examples
- https://github.com/livekit-examples/agent-starter-python
- https://github.com/livekit/python-sdks
- https://modelcontextprotocol.io/docs/develop/connect-local-servers
- https://support.google.com/mail/answer/7190
