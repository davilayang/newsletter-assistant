# Plan: Historical Transcript Storage and /history Page

## Context

Voice session transcripts are displayed in real-time but never persisted — all conversation data is lost on page refresh or disconnect. This plan adds SQLite-backed session and segment storage, and a `/history` page where past sessions can be browsed by date.

---

## Data Flow (Current → New)

```
CURRENT:
LiveKit JS → emitEvent('transcript', {role, text}) → on_transcript() → UI only (lost on refresh)

NEW:
/token response includes session_id (UUID, created in DB at request time)
  ↓
JS stores session_id, attaches it to every emitEvent('transcript', {role, text, session_id})
  ↓
on_transcript() → save to DB + display in UI
  ↓
on_lk_status(connected=false) → mark session ended in DB
```

---

## New Module: `src/core/transcript_store.py`

SQLite at `data/transcripts.db`. Two tables:

```sql
CREATE TABLE sessions (
    id          TEXT PRIMARY KEY,   -- UUID4
    started_at  TEXT NOT NULL,      -- ISO-8601 UTC
    ended_at    TEXT,               -- NULL until disconnect
    room        TEXT NOT NULL DEFAULT 'newsletter'
);

CREATE TABLE transcript_segments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL REFERENCES sessions(id),
    ts          TEXT NOT NULL,      -- ISO-8601 UTC
    role        TEXT NOT NULL,      -- 'user' | 'assistant'
    text        TEXT NOT NULL
);
CREATE INDEX idx_segments_session ON transcript_segments(session_id);
```

Public API (all synchronous, thread-safe):
| Function | Description |
|---|---|
| `create_session(session_id, room)` | Insert a new session row |
| `end_session(session_id)` | Set `ended_at = now()` |
| `save_segment(session_id, role, text)` | Insert a segment, timestamp internally |
| `get_sessions() -> list[Session]` | All sessions, newest first, with `turn_count` |
| `get_segments(session_id) -> list[Segment]` | All segments for a session, oldest first |

Follow the connection pattern of `src/knowledge/raw_store.py` (module-level `sqlite3.connect`, WAL mode, `check_same_thread=False`).

---

## Changes to Existing Files

### `src/frontend/routes.py`
- Import `uuid` and `src.core.transcript_store`
- Generate `session_id = str(uuid.uuid4())`
- Call `transcript_store.create_session(session_id)` before returning
- Add `"session_id": session_id` to the response dict

### `src/frontend/livekit_widget.py` (JS section)
- Store `session_id` from the `/token` response in a JS variable
- Attach it to every `emitEvent('transcript', {role, text, session_id})`
- Attach it to `emitEvent('lk_status', {connected, session_id})`

### `src/frontend/page.py`
- `on_transcript`: after UI update, call `run.io_bound(transcript_store.save_segment, session_id, role, text)`
- `on_lk_status`: when `connected=false`, call `run.io_bound(transcript_store.end_session, session_id)`
- Header: add `ui.button("History", on_click=lambda: ui.navigate.to("/history"))` next to the dark-mode switch

### `src/frontend/app.py`
- Add `from src.frontend import history` to register the `/history` page decorator

---

## New File: `src/frontend/history.py`

`@ui.page("/history")` layout:
```
Header with "← Back" button
  └── ui.label("Past Sessions")

For each date group (parsed from session.started_at):
  ui.label("March 3, 2026")          ← date heading
  ui.expansion("{time}  ·  {n} turns", icon="chat")
    └── Segments loaded lazily on expand (on_value_change)
          ui.chat_message(text, name, stamp, sent=(role=="user"))
```

Segments are loaded **lazily** per session (only when the expansion panel is opened) to avoid fetching all DB content at page load.

---

## File Summary

| File | Action |
|---|---|
| `src/core/transcript_store.py` | **Create** |
| `src/frontend/routes.py` | **Edit** — add session_id to /token response |
| `src/frontend/livekit_widget.py` | **Edit** — propagate session_id through JS events |
| `src/frontend/page.py` | **Edit** — persist segments, end session on disconnect, History button |
| `src/frontend/history.py` | **Create** — /history NiceGUI page |
| `src/frontend/app.py` | **Edit** — import history module |

---

## Verification

1. `uv run poe frontend` + `uv run poe agent`
2. Connect, speak a few turns, disconnect
3. Check `data/transcripts.db`: `sessions` has `ended_at` set; `transcript_segments` has rows
4. Open `http://localhost:8080/history` — session appears with correct turn count
5. Expand session — transcript replays in chat-message format
6. Multiple sessions → all visible, grouped by date, newest first
