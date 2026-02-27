# Plan: LiveKit Voice Agent for Medium Newsletter

## Context

The project already has a Gmail MCP server (`src/server.py`) that can read emails, create drafts, and send them. The `add-medium-access` branch is the starting point for extending this.

The goal is to build a **voice agent** (LiveKit) that:
- Reads Medium newsletter emails from Gmail
- Fetches full article content from Medium article URLs
- Lets the user converse: summarise articles, ask questions, take notes
- Saves notes to local dated markdown files

The LiveKit agent is a **separate entry point** from the MCP server — it's a standalone voice app that shares the Gmail/Medium library code, not a new MCP tool.

---

## Suggested Additional Features

Beyond the three stated goals, these are worth including:

1. **"What's trending this week?"** — cross-article theme synthesis across the whole newsletter
2. **Skip / flag articles** — "skip this one" / "flag this as interesting" to build a session reading list
3. **Session summary** — at end of session, auto-save a digest of all articles discussed + any notes taken
4. **Article source in notes** — every note automatically includes the article title, URL, and date for easy reference later

---

## Architecture

```
src/
  gmail_api.py        (existing) — OAuth + Gmail service client
  gmail_ops.py        (existing) — list_messages, get_message_content, etc.
  server.py           (existing) — MCP server entry point (unchanged for now)
  medium_ops.py       (NEW) — parse newsletter emails, fetch full article content
  agent.py            (NEW) — LiveKit voice agent entry point
  notes.py            (NEW) — save/append notes to local markdown files
```

### Data Flow

```
User voice input
  → LiveKit STT (Deepgram)
  → Agent LLM (Claude via livekit-plugins-anthropic)
  ↕  calls internal functions:
      gmail_ops.list_messages(query="from:noreply@medium.com is:unread")
      medium_ops.parse_newsletter_email(email_content)  → [ArticleLink, ...]
      medium_ops.fetch_article(url)                     → ArticleContent
      notes.save_note(text, article_title, url)         → writes to .md file
  → LiveKit TTS (ElevenLabs)
  → User hears response
```

---

## New Dependencies

```toml
# Core agent runtime
"livekit-agents>=0.8"
"livekit-plugins-deepgram"      # STT
"livekit-plugins-elevenlabs"    # TTS
"livekit-plugins-anthropic"     # LLM (Claude)

# Article scraping
"beautifulsoup4>=4.12"
```

`httpx` is already a dependency — used for article fetching.

---

## Environment Variables Needed

```
LIVEKIT_URL
LIVEKIT_API_KEY
LIVEKIT_API_SECRET
DEEPGRAM_API_KEY
ELEVENLABS_API_KEY
ANTHROPIC_API_KEY
```

Use `pydantic-settings` (already a dev dep) to load these from a `.env` file via a new `src/config.py`.

---

## Implementation Phases

### Phase 1 — `src/medium_ops.py`

Two responsibilities:

**1. Newsletter parser** — given a raw email body, extract a list of `(title, url, snippet)` tuples.
- Medium newsletter emails contain `<a href="https://medium.com/...">` links
- Use `BeautifulSoup` to parse the HTML body and extract article links + titles
- Filter out non-article links (unsubscribe, social) by checking URL pattern (`/p/` or `/@`)

**2. Article fetcher** — given a Medium article URL, fetch and return the readable text.
- `httpx.get(url)` with a browser-like User-Agent header
- Parse with `BeautifulSoup`, extract `<article>` tag or fallback to main `<section>`
- Strip scripts, styles, navigation; return plain text (title + body)
- Note: paywalled articles will return a truncated preview — acceptable

### Phase 2 — `src/notes.py`

Append-only note store:

```python
def save_note(content: str, article_title: str, article_url: str) -> Path:
    # Writes to NOTES/<YYYY-MM-DD>_medium-notes.md
    # Appends: ## <article_title>\n> <article_url>\n\n<content>\n\n---\n
```

- Creates `NOTES/` directory at project root if it doesn't exist
- One file per day, multiple notes appended

### Phase 3 — `src/agent.py`

LiveKit `VoicePipelineAgent`:

```python
agent = VoicePipelineAgent(
    vad=silero.VAD.load(),
    stt=deepgram.STT(),
    llm=anthropic.LLM(model="claude-sonnet-4-6"),
    tts=elevenlabs.TTS(),
    chat_ctx=initial_ctx,
)
```

**System prompt:** reading assistant for Medium articles; summarise clearly; invite follow-up; confirm note saves.

**LLM function tools:**
- `load_newsletter()` — fetches today's Medium newsletter via Gmail + scrapes articles
- `save_note(content, article_title, article_url)` — persists to markdown
- `flag_article(article_title)` — adds to in-session reading list
- `get_session_summary()` — digest of articles, flags, and notes from the session

Run with: `uv run python -m src.agent`

### Phase 4 — `src/server.py` (optional, low priority)

Optionally expose `load_medium_newsletter` and `fetch_article` as MCP tools for Claude Code CLI access.

---

## Verification

1. **Unit tests** for `medium_ops.py`:
   - Mock newsletter HTML → assert correct article titles/URLs extracted
   - Mock `httpx` response → assert article text parsed correctly

2. **Unit tests** for `notes.py`:
   - Assert file created with correct name and appended content

3. **Manual integration test**:
   - `uv run python -m src.agent`
   - Say: "Load my latest Medium newsletter"
   - Say: "Summarise the first article"
   - Say: "Take a note: this is relevant to my work"
   - Verify note file created under `NOTES/`
