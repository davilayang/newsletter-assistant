# Email Newsletter Assistant

A personal knowledge assistant built on Gmail and LiveKit. Talk to your newsletters by voice — ask questions, get summaries, take notes. A daily scraping pipeline accumulates article content into SQLite and ChromaDB for semantic search.

## Project Structure

```
src/
  core/          # Shared: Gmail client, config (pydantic-settings), notes writer
  agent/         # LiveKit voice agent + LLM function tools
  knowledge/     # Scraping pipeline, newsletter parsers, SQLite + ChromaDB stores
  mcp/gmail/     # MCP server for Claude Code / Desktop
  frontend/      # NiceGUI web UI (voice session, article sidebar, transcript)
config/          # Newsletter registry (newsletters.yaml), TTS rules
scripts/         # One-time setup scripts (e.g. medium_login.py)
dags/            # Airflow DAGs — thin wrappers over knowledge/pipeline.py
data/            # Runtime data — gitignored (articles.db, chroma/)
creds/           # OAuth credentials — gitignored
NOTES/           # Saved session notes
```

## Usage

### Prerequisites

1. **Python 3.13** and [`uv`](https://docs.astral.sh/uv/)
2. **GCP OAuth 2.0 credentials** for Gmail API
   - Google Cloud Console → Gmail API → Credentials → OAuth 2.0 Client IDs → Download JSON
   - Save as `creds/credentials.json`
3. **API keys** — create a `.env` file from `.env.example` at the project root

```bash
uv sync
```

On first run the Gmail OAuth consent flow will open in your browser and save a token to `creds/token.json`.

#### Medium authentication (required for full article content)

Run once to save your Medium session credentials:

```bash
uv run python scripts/medium_login.py
```

A browser window will open — log in to Medium, then press Enter in the terminal. Auth state is saved to `creds/medium_auth.json`. Re-run when fetching stops working (sessions typically last weeks to months).

### Voice Agent

**Console mode** — text I/O in the terminal, no LiveKit room needed:

```bash
uv run poe agent
```

**Dev mode** — connects to a LiveKit room with hot reload:

```bash
uv run poe agent dev

# If using iTerm2, suppress the conflicting TERM_PROGRAM variable:
TERM_PROGRAM=0 uv run poe agent dev
```

Then open https://agents-playground.livekit.io/ and connect with your LiveKit credentials.

The agent has four tools:

| Tool | When it's called |
|---|---|
| `get_todays_newsletter` | "Load my newsletter", "What arrived this morning?" |
| `read_article` | "Read me that article", "Summarise it in detail" |
| `save_note` | "Take a note", "Remember this" |
| `search_knowledge` | "What have I read about RAG?", "Find that article on transformers" |

Notes are saved to `NOTES/<today's date>_medium-notes.md`.

### Web UI

```bash
uv run poe frontend
```

Opens at `http://127.0.0.1:8080`. The UI provides a voice session widget, article sidebar, and transcript view.

#### Mobile testing over local network (HTTPS)

Mobile browsers require HTTPS for microphone access. Use [`mkcert`](https://github.com/FiloSottile/mkcert) to create locally-trusted certificates:

```bash
brew install mkcert && mkcert -install
mkcert 192.168.1.38 localhost 127.0.0.1   # use your local IP
```

Then run with SSL:

```bash
APP_HOST=0.0.0.0 \
SSL_CERTFILE=./192.168.1.38+2.pem \
SSL_KEYFILE=./192.168.1.38+2-key.pem \
uv run poe frontend
```

On your phone, install the mkcert root CA (`mkcert -CAROOT` → transfer `rootCA.pem` → Settings → General → VPN & Device Management → Install), then open `https://<your-mac-ip>:8080`.

### Scraping Pipeline

```bash
uv run poe pipeline
```

Reads unread newsletter emails from Gmail, fetches full article content, and stores everything in SQLite + ChromaDB. Idempotent — safe to run multiple times. Run daily via cron or Airflow.

**Data files** (gitignored — back up `articles.db`):
- `data/articles.db` — SQLite source of truth
- `data/chroma/` — ChromaDB vector index (rebuildable from articles.db)

### Gmail MCP Server

Exposes three tools to Claude: `get_unread_emails`, `create_draft_reply`, `send_draft_message`.

Register in `.mcp.json`:

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

Verify with `claude mcp list`.

## Development

```bash
uv run poe check       # Run all checks: fmt, lint, mypy, tests
uv run poe test        # Run tests (pytest -v)
uv run poe fix         # Auto-fix formatting (black) + linting (ruff)
uv run poe mypy        # Type-check with mypy
uv run pytest tests/path/to/test_file.py -v   # Single test file
```

## Others

### References

- https://github.com/livekit-examples/python-agents-examples
- https://github.com/livekit-examples/agent-starter-python
- https://github.com/livekit/python-sdks
- https://modelcontextprotocol.io/docs/develop/connect-local-servers
- https://support.google.com/mail/answer/7190
