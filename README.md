# mcp-project

A personal knowledge assistant built on Gmail and LiveKit. Talk to your Medium newsletter every morning by voice — ask questions, get summaries, take notes.

## Prerequisites

1. **Python 3.13** and [`uv`](https://docs.astral.sh/uv/)
2. **GCP OAuth 2.0 credentials** for Gmail API
   - Google Cloud Console → Gmail API → Credentials → OAuth 2.0 Client IDs → Download JSON
   - Save as `creds/credentials.json`
3. **API keys** — create a `.env` file at the project root:

```env
ANTHROPIC_API_KEY=...

LIVEKIT_URL=...
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...

DEEPGRAM_API_KEY=...
ELEVENLABS_API_KEY=...
```

## Setup

```bash
uv sync
```

On first run the Gmail OAuth consent flow will open in your browser and save a token to `creds/token.json`.

## Usage

### Voice agent (Phase 1)

Start the agent and connect via a LiveKit console:

```bash
# In console mode
uv run --env-file .env python -m src.agent.agent console

# In Livekit room
uv run --env-file .env python -m src.agent.agent dev --reload
## (If using iterm2)
TERM_PROGRAM=0 uv run --env-file .env python -m src.agent.agent dev --reload
# Then, visit https://agents-playground.livekit.io/
```

Then speak or type to it — example session:

> "Load my newsletter."
> "Summarise the third article."
> "Take a note: this is relevant to my RAG project."

Notes are saved to `NOTES/<today's date>_medium-notes.md`.

### Gmail MCP server

Exposes three tools to Claude: `get_unread_emails`, `create_draft_reply`, `send_draft_message`.

#### With Claude Code CLI

Register with Claude Code CLI by adding to `.mcp.json`:

```json
// Replace "/absolute/path/to/mcp-project" with the real path
{
  "mcpServers": {
    "mcp-gmail": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/mcp-project", "run", "-m", "src.mcp.gmail.server"]
    }
  }
}
```

Check with `claude mcp list`.

#### With Claude Desktop

> On MacOS, install with `brew install claude`

1. Open Claude Desktop
2. Click on "Settings" → "Developer"
3. Under "Local MCP servers", click "Edit Config"
4. Add the following configuration:

```json
// Replace "/Users/absolute/path/mcp-project" with the real path
{
  "mcpServers": {
    "mcp-gmail": {
      "command": "uv",
      "args": [
        "--directory", "/Users/absolute/path/mcp-project", "run", "-m", "src.mcp.gmail.server"
      ]
    }
  }
}
```

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
  agent/         # LiveKit voice agent (Phase 1)
  knowledge/     # Scraping pipeline + vector store (Phase 2)
dags/            # Airflow DAGs (Phase 2)
NOTES/           # Your saved session notes
```

## References

- https://modelcontextprotocol.io/docs/develop/connect-local-servers
