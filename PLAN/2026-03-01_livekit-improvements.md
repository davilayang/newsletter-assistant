# LiveKit Agent Improvements — Brainstorm

Reviewed: https://github.com/livekit-examples/python-agents-examples

## What we have today

| Component | Status |
|---|---|
| Voice agent (STT → LLM → TTS) | Done |
| 4 function tools (`get_todays_newsletter`, `read_article`, `save_note`, `search_knowledge`) | Done |
| Multi-newsletter support via `newsletters.yaml` | Done |
| SQLite raw store + ChromaDB vector store | Done |
| Medium scraping pipeline (camoufox) | Done |
| Gmail MCP server | Done |

---

## Ideas from LiveKit examples

### 1. VAD prewarming — Quick win, high impact
**Source:** `personal_shopper`, `medical_office_triage` examples

Currently `silero.VAD.load()` runs inside the session handler, so the first time someone speaks there is a noticeable lag while the model loads.

**Fix:** Prewarm VAD once at process startup in `userdata`, reuse across sessions.

```python
# In agent.py — before session handler
server = AgentServer(userdata={"vad": silero.VAD.load()})

@server.rtc_session()
async def session(ctx: JobContext):
    vad = ctx.userdata["vad"]
    agent_session = AgentSession(..., vad=vad)
```

**Effort:** 30 min. No new deps.

---

### 2. TTS pipeline node — pronunciation of article titles
**Source:** `tts_node_override` example

Medium article titles and author names often contain acronyms, camelCase, or non-English words that TTS renders poorly (e.g. "RAG" → "rag", "DeepMind" → weird pause).

**Fix:** Add a `before_tts_node` that normalises common patterns before synthesis:
- Expand acronyms: `RAG → Retrieval Augmented Generation`
- Insert spaces in camelCase names
- Normalise numbers/currency

**Effort:** 2–3 hours. No new deps.

---

### 3. Conversation transcript logging
**Source:** `conversation_monitor` example

Currently there is no record of what was said in a session. Useful for debugging and for reviewing what the agent summarised.

**Fix:** Attach a listener to `session.on("conversation_item_added")` and append transcripts to a session log file (e.g. `NOTES/<date>_session-transcript.md`).

**Effort:** 1–2 hours. No new deps, reuses existing `NOTES/` pattern.

---

### 4. Multi-agent routing with scoped web search
**Source:** `medical_office_triage`, `personal_shopper` examples

One `NewsletterAssistant` agent handles everything today. As tools grow, the LLM's job gets harder and response quality degrades.

**Proposed split:**

| Agent | Responsibility | Tools |
|---|---|---|
| `GreeterAgent` | Loads newsletter, presents article list, routes to specialists | `get_todays_newsletter`, `save_note` |
| `ReaderAgent` | Deep-reads a single article, answers specific questions about it | `read_article`, `save_note`, `search_web` |
| `KnowledgeAgent` | Searches past articles, finds connections across topics | `search_knowledge`, `search_web` |

Agents hand off via `session.update_agent()` and pass conversation context.

#### `search_web` — scoped web search tool

The current knowledge base only contains what newsletters have covered. Follow-up questions frequently go outside that:

> "This article mentions LangGraph — what's the current stable version?"
> "What else has this author written?"
> "Is the technique they describe widely adopted now?"

**Key design constraint: scope it to newsletter context, not open-ended search.**
Only activate when there is an article in context — searches *about* something the user is already reading, not cold arbitrary queries. This keeps the assistant's identity as a newsletter reading aid rather than a general-purpose assistant.

**Appropriate queries:**
- Extending an article: "What's the latest on X?" (X was mentioned in article)
- Author context: "What else has this author published?"
- Finding linked resources: paper, repo, or docs referenced in the article

**Out of scope** (agent should decline): weather, recipes, sports scores, anything unrelated to the current reading session.

**Implementation options:**
- Brave Search API or Tavily (designed for LLM use, clean JSON responses)
- DuckDuckGo (free, no API key, rate-limited)
- Restrict results to `medium.com`, `arxiv.org`, `github.com` for tighter scoping

**Effort:** 1–2 days for multi-agent routing + 2–3 hours for `search_web` tool.

---

### 5. Metrics and observability
**Source:** `metrics_langfuse`, `llm_metrics`, `tts_metrics` examples

No visibility into latency, token usage, or cost today.

**Fix:** Attach `metrics_collected` event listeners to log:
- Time-to-first-token (TTFT) — key for voice UX
- LLM token counts (cost tracking)
- STT/TTS latency

Optional: forward to Langfuse for session tracing and replay.

**Effort:** 2–3 hours for local logging, +1 day for Langfuse integration.

---

### 6. Context variables — personalisation
**Source:** `context_variables` example

Agent instructions are static today. Could inject dynamic context at session start:
- Today's date (already implied but not explicit)
- Number of unread newsletters
- Last read article title (from `raw_store`)
- User's most-read topics (derived from `vector_store`)

**Effort:** 2–3 hours. No new deps.

---

### 7. MCP server for knowledge base
**Source:** `stdio_mcp_client`, `http_mcp_client` examples

The Gmail MCP server already exists. The SQLite + ChromaDB knowledge base could also be exposed as an MCP server, making it queryable by Claude Code directly (not just via the voice agent).

**Proposed tools:**
- `search_articles(query)` — semantic search via ChromaDB
- `get_article(url)` — retrieve full markdown from SQLite
- `list_recent_articles(days)` — browse recent scrapes

This would also let Claude Code answer questions like "what have I read about transformers?" without running the voice agent.

**Effort:** 3–4 hours. Reuses existing `raw_store` and `vector_store` functions.

---

### 8. Realtime API
**Source:** `openai_realtime`, `gemini_live` examples

Current pipeline: Deepgram STT → OpenAI GPT-4.1-mini → Inworld TTS (3 round trips).

Realtime API collapses this to a single model with native audio I/O — lower latency and more natural conversation flow. Good fit for a morning assistant where snappy responses matter.

**Trade-offs:**
- Higher cost per session than the current pipeline
- Less control over STT/TTS individually
- Requires OpenAI Realtime or Gemini Live account

**Effort:** 3–4 hours to prototype.

---

## Priority order

| Priority | Idea | Effort | Value |
|---|---|---|---|
| 1 | VAD prewarming | 30 min | Immediate latency fix |
| 2 | Transcript logging | 1–2 h | Debugging + personal record |
| 3 | Context variables | 2–3 h | Better UX, more natural greetings |
| 4 | TTS pronunciation node | 2–3 h | Polish |
| 5 | Metrics logging | 2–3 h | Observability |
| 6 | Knowledge base MCP server | 3–4 h | Unlocks Claude Code queries |
| 7 | Realtime API | 3–4 h | Latency step-change |
| 8 | Multi-agent routing + scoped web search | 1–2 d | Scale as tools grow + fills knowledge gaps |
