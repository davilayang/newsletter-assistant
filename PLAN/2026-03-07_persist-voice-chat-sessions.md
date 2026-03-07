# Plan: Persist Voice Chat Sessions Across Page Refresh

## Context

Currently, voice chat sessions are fully ephemeral. Page refresh destroys the transcript (DOM-only), disconnects from LiveKit (room destroyed when empty), and the agent starts fresh with no memory. The user wants:

1. **Transcript persistence** — chat messages survive page refresh
2. **Agent context continuity** — after reconnect, the agent knows what was discussed
3. **Explicit disconnect** — only the Disconnect button ends a session
4. **History view** — browse past conversations in the sidebar

## Implementation

### 1. New file: `src/core/chat_store.py` — SQLite chat session store

Place in `core/` so both `agent/` and `frontend/` can import it (dependency rule).
Follow the `batch_store.py` pattern: module-level functions, `_connect()` with WAL mode.

**DB:** `data/chat.db`

**Schema:**
```sql
CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    started_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ended_at     TIMESTAMP,
    title        TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL REFERENCES sessions(session_id),
    role         TEXT NOT NULL,       -- 'user' | 'assistant'
    content      TEXT NOT NULL,
    timestamp    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
```

**Dataclasses:** `ChatMessage(role, content, timestamp)`, `ChatSession(session_id, started_at, ended_at, title, messages)`

**Functions:**
- `create_session(session_id: str) -> None`
- `end_session(session_id: str) -> None` — sets `ended_at`
- `add_message(session_id: str, role: str, content: str) -> None` — INSERT OR IGNORE
- `get_session(session_id: str) -> ChatSession | None` — with messages
- `get_messages(session_id: str, limit: int = 50) -> list[ChatMessage]`
- `get_active_session() -> str | None` — return session_id where `ended_at IS NULL`, most recent
- `list_sessions(limit: int = 20) -> list[ChatSession]` — without messages, ordered by `started_at DESC`

### 2. Modify `src/frontend/routes.py` — session-aware `/token`

- Accept optional query param `session_id`
- If not provided, generate `uuid4`, call `chat_store.create_session()`
- Use `f"newsletter-{session_id[:8]}"` as the room name (avoids stale room conflicts)
- Pass `session_id` as `metadata` in `CreateAgentDispatchRequest`
- Return `session_id` in the JSON response alongside `token` and `url`

```python
@app.get("/token", response_model=None)
async def get_token(session_id: str | None = None) -> dict | JSONResponse:
    if session_id is None:
        session_id = str(uuid.uuid4())
        chat_store.create_session(session_id)
    room_name = f"newsletter-{session_id[:8]}"
    # ... token with room=room_name ...
    # ... dispatch with metadata=session_id ...
    return {"token": token, "url": ..., "session_id": session_id}
```

### 3. Modify `src/frontend/livekit_widget.py` — JS session flow

**Add state:**
```javascript
let _sessionId = null;
let _intentionalDisconnect = false;
```

**`lkConnect()` changes:**
- Accept session_id param (set from Python via `ui.run_javascript`)
- Fetch `/token?session_id=<id>` if reconnecting, or `/token` for new
- Store `_sessionId` from response
- Emit `lk_session_started` event with `{ session_id }` to Python

**`lkDisconnect()` changes:**
- Set `_intentionalDisconnect = true`
- Emit `lk_disconnect` event with `{ session_id }` before disconnecting

**`RoomEvent.Disconnected` handler:**
- Only clear `_sessionId` if `_intentionalDisconnect` was true
- Reset `_intentionalDisconnect = false`

**Add function:** `lkSetSessionId(id)` — called from Python to set `_sessionId` for reconnect

### 4. Modify `src/frontend/page.py` — persistence + history UI

**On page load:**
- Read `app.storage.user.get('session_id')`
- If exists and `chat_store.get_active_session()` returns it, restore messages from DB into `transcript_container`
- Set JS `_sessionId` via `ui.run_javascript(f'_sessionId = "{sid}"')`

**`on_transcript` handler — add persistence:**
```python
async def on_transcript(e) -> None:
    # ... existing render logic ...
    sid = app.storage.user.get('session_id')
    if sid:
        await run.io_bound(chat_store.add_message, sid, role, text)
```

**New `on_lk_session_started` handler:**
- Store `session_id` in `app.storage.user['session_id']`
- Set title from first user message (later, in `on_transcript`)

**New `on_lk_disconnect` handler:**
- Call `chat_store.end_session(session_id)`
- Remove `session_id` from `app.storage.user`

**Auto-title:** In `on_transcript`, if `role == "user"` and session has no title yet, set `title = content[:60]`

**History section in left drawer:**
- After the search section, add "Chat History" heading
- List recent sessions from `chat_store.list_sessions(10)`
- Each entry shows title or date, with "Active" badge if `ended_at` is None
- Click opens a dialog showing all messages for that session
- Refresh on a 30s timer

### 5. Modify `src/agent/agent.py` — context continuity on reconnect

**`NewsletterAssistant.__init__`** — accept optional `chat_ctx`:
```python
def __init__(self, chat_ctx: llm.ChatContext | None = None) -> None:
    kwargs = {}
    if chat_ctx is not None:
        kwargs["chat_ctx"] = chat_ctx
    super().__init__(instructions=..., tools=..., **kwargs)
```

**`session()` function** — load history from dispatch metadata:
```python
@server.rtc_session(agent_name="newsletter")
async def session(ctx: JobContext):
    session_id = ctx.job.metadata or None

    prior_ctx = None
    if session_id:
        messages = chat_store.get_messages(session_id, limit=50)
        if messages:
            prior_ctx = llm.ChatContext()
            for msg in messages:
                prior_ctx.add_message(role=msg.role, content=msg.content)

    agent = NewsletterAssistant(chat_ctx=prior_ctx)
    # ... start session ...

    if prior_ctx and len(prior_ctx.items) > 0:
        await agent_session.generate_reply(
            instructions="The user has reconnected. Briefly acknowledge you remember "
            "the conversation and ask how to continue."
        )
    else:
        await agent_session.generate_reply(instructions="Greet the user...")
```

### 6. Session lifecycle

| Event | What happens |
|-------|-------------|
| Click Connect (new) | `/token` → new session in DB → store `session_id` in `app.storage.user` → agent gets empty context |
| Page refresh | Transcript restored from DB → user sees prior messages → clicks Connect → `/token?session_id=X` → agent loads history via `chat_ctx` |
| Click Disconnect | `end_session()` → clear `app.storage.user` → room destroyed → session appears in history |
| Stale session | On page load, if active session's last message is >4h old, auto-end it |

## Files to modify

| File | Change |
|------|--------|
| `src/core/chat_store.py` | **New** — SQLite store |
| `src/frontend/routes.py` | Session-aware `/token` endpoint |
| `src/frontend/livekit_widget.py` | JS session ID flow, disconnect event |
| `src/frontend/page.py` | Restore transcript, persist messages, history sidebar, disconnect handling |
| `src/agent/agent.py` | Accept `chat_ctx`, read dispatch metadata |

## Verified SDK APIs

- `Agent.__init__` accepts `chat_ctx: llm.ChatContext`
- `ChatContext.add_message(role=..., content=...)` — role is `ChatRole` type
- `CreateAgentDispatchRequest` has a `metadata` string field
- `ctx.job.metadata` accessible from agent session (protobuf field on `Job`)
- NiceGUI `app.storage.user` available via `storage_secret`

## Verification

1. `uv run poe check` — all checks pass (fmt, lint, mypy, tests)
2. Write unit tests for `chat_store.py` (CRUD operations, edge cases)
3. Manual test flow:
   - Start agent worker + frontend
   - Connect, chat, verify messages appear
   - Refresh page → transcript should restore, click Connect → agent acknowledges prior conversation
   - Click Disconnect → session ends, appears in history sidebar
   - Click a history entry → dialog shows full conversation
