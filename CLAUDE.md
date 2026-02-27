# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Gmail MCP (Model Context Protocol) server that exposes Gmail operations as tools for use with Claude Code CLI or Claude Desktop. It uses OAuth 2.0 to authenticate with the Gmail API and exposes three tools: read unread emails, create draft replies, and send drafts.

## Package Manager

This project uses [`uv`](https://docs.astral.sh/uv/) exclusively. Do not use `pip` or `poetry`.

```bash
uv sync              # Install all dependencies (including dev)
uv run <command>     # Run a command in the project virtualenv
```

## Common Commands (via `poe`)

All tasks are defined in `pyproject.toml` under `[tool.poe.tasks]`:

```bash
uv run poe check      # Run all checks: fmt, lint, mypy, tests
uv run poe test       # Run tests (pytest -v)
uv run poe fmt        # Check formatting with black (read-only)
uv run poe fmt-fix    # Auto-fix formatting with black
uv run poe lint       # Check linting with ruff (read-only)
uv run poe lint-fix   # Auto-fix linting with ruff
uv run poe mypy       # Type-check with mypy
uv run poe fix        # Auto-fix formatting + linting
```

Run a single test file:
```bash
uv run pytest tests/test_foo.py -v
```

Run the MCP server directly (for development):
```bash
uv run -m src.server
```

## Architecture

```
src/
  server.py      # FastMCP server — defines the 3 MCP tools exposed to Claude
  gmail_api.py   # OAuth 2.0 auth flow + builds Gmail API service client
  gmail_ops.py   # Gmail operations: list_messages, get_message_content,
                 #   create_draft_message, send_draft
creds/
  credentials.json  # GCP OAuth client credentials (must be created manually)
  token.json        # OAuth token (auto-generated after first auth)
```

**Data flow:** `server.py` tools → `gmail_ops.py` functions → `gmail_api.get_gmail_service()` → Google API.

The OAuth flow in `gmail_api.py` uses two scopes: `gmail.readonly` and `gmail.compose`. On first run (or when `token.json` is missing/expired), it opens a browser for the OAuth consent flow and saves the token.

## Setup Prerequisites

1. GCP OAuth 2.0 credentials file at `creds/credentials.json` (download from Google Cloud Console under Gmail API → Credentials → OAuth 2.0 Client IDs)
2. `uv` installed

## MCP Server Configuration

To register this server in `.mcp.json` (for Claude Code CLI):
```json
{
  "mcpServers": {
    "mcp-gmail": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/mcp-project", "run", "-m", "src.server"]
    }
  }
}
```
