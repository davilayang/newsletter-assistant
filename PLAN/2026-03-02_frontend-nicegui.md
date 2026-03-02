# Frontend — NiceGUI Implementation Plan

## Context

The newsletter assistant already has a complete Python voice agent (`src/agent/agent.py`)
but no browser UI. This plan adds a NiceGUI frontend: a single Python file that serves
a responsive web app (laptop + mobile) showing today's articles, a live transcript, and
notes — while embedding a minimal LiveKit JS audio widget for WebRTC voice.

NiceGUI was chosen over Streamlit because it:
- Uses WebSocket push (no polling for transcript), making updates ~instant
- Is based on Vue.js/Quasar — responsive mobile layouts with Tailwind-like classes
- Runs on top of FastAPI, so custom routes (`/token`, `/transcript`) mount naturally
- Requires zero JS project or build toolchain; JS is a CDN snippet in an HTML string

---

## New Files

### `src/frontend/__init__.py`
Empty. Makes `python -m src.frontend.app` work.

### `src/frontend/app.py`
Single file, five sections:

**A — Imports & shared state**
```python
from nicegui import app, ui
from src.core.config import settings
from src.core.notes import NOTES_DIR
from src.knowledge import raw_store, vector_store
from datetime import date
from pathlib import Path

_transcript: list[dict] = []   # module-level, in-memory, shared across browser tabs
```
Using a module-level list (not `app.storage.general`) keeps the transcript in-memory only,
resets cleanly on server restart, and avoids disk writes.

**B — FastAPI custom routes** (mounted on NiceGUI's internal FastAPI app via `@app.*`)
```python
@app.get("/token")
async def get_token():
    from livekit.api import AccessToken, VideoGrants
    try:
        token = (
            AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
            .with_grants(VideoGrants(room_join=True, room="newsletter"))
            .with_identity("user")
            .to_jwt()
        )
        return {"token": token, "url": str(settings.livekit_url)}
    except Exception as e:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": str(e)}, status_code=503)

@app.post("/transcript")
async def post_transcript(request: Request):
    data = await request.json()
    text = str(data.get("text", "")).strip()
    if text:
        _transcript.append({"role": data.get("role", "user"), "text": text})
    return {"ok": True}
```

**C — LiveKit JS audio widget** (HTML string, loaded from jsDelivr CDN — no build step)

Responsibilities:
- Load `livekit-client@2.17.2` UMD bundle from CDN
- `connectToRoom()`: fetch `/token` → create `Room` → connect → publish mic track →
  register `RoomEvent.TranscriptionReceived` → POST final segments to `/transcript`
- `toggleMute()`: mute/unmute mic track
- `disconnect()`: close room and reset buttons
- Show status text and three buttons (Connect / Mute / Disconnect)

The widget uses `LivekitClient.createLocalAudioTrack()` and publishes it directly —
the agent running in the LiveKit room picks it up via `room_io.AudioInputOptions`.

**D — NiceGUI page** (`@ui.page("/")`):

Layout:
- **Header** — app title + hamburger for drawer toggle
- **Left drawer** (auto-collapses on mobile < 768 px) — article list + search input
- **Main column** — audio widget card + transcript card + notes expansion panel
- All timers are created inside the page function → scoped to that client connection

Key patterns:
```python
# Per-client rendered_count (closure variable, not global)
rendered_count = 0

def refresh_transcript():
    nonlocal rendered_count
    new_turns = _transcript[rendered_count:]
    if not new_turns:
        return
    with transcript_container:            # append-only, no flicker
        for turn in new_turns:
            bg = "blue-1" if turn["role"] == "assistant" else "green-1"
            ui.markdown(f"**{turn['role'].capitalize()}:** {turn['text']}") \
                .classes(f"q-pa-sm rounded bg-{bg} w-full")
    rendered_count += len(new_turns)

def refresh_notes():
    p = NOTES_DIR / f"{date.today()}_medium-notes.md"
    notes_md.set_content(p.read_text() if p.exists() else "*No notes yet today.*")

def refresh_articles():
    articles = raw_store.get_all_articles(since=date.today())
    article_container.clear()
    with article_container:
        if not articles:
            ui.label("No articles scraped today.").classes("text-caption")
        else:
            for art in articles:
                ui.link(art.title or art.url, art.url, new_tab=True).classes("text-body2 q-mb-xs")

def run_search():
    results = vector_store.search(search_input.value.strip(), n_results=5)
    # opens a ui.dialog with result cards

# Timers (per-client, created at page-load)
ui.timer(1.0,  refresh_transcript)
ui.timer(10.0, refresh_notes)
ui.timer(60.0, refresh_articles)
```

**E — Entrypoint**
```python
if __name__ in ("__main__", "__mp_main__"):
    ui.run(
        title="Newsletter Assistant",
        host="0.0.0.0",
        port=8080,
        storage_secret="newsletter-assistant-ui",
        favicon="📰",
        dark=None,    # follows browser preference
        reload=False,
    )
```

---

## Files to Modify

### `pyproject.toml`

1. In `[project].dependencies`, add:
```toml
    # Frontend
    "nicegui>=3.8",
```
`livekit-api` is already a transitive dep of `livekit-agents~=1.3` — no separate
declaration needed.

2. After `[tool.poe.tasks.pipeline]` block, add:
```toml
[tool.poe.tasks.frontend]
cmd = "python -m src.frontend.app"
envfile = ".env"
help = "Run the NiceGUI frontend UI (loads .env)"
```

---

## Implementation Steps

1. Create `src/frontend/__init__.py` (empty)
2. Create `src/frontend/app.py` with sections A–E
3. Edit `pyproject.toml` — add `nicegui>=3.8` + `frontend` poe task
4. `uv sync`

---

## Edge Cases

| Case | Handling |
|---|---|
| No articles today | Shows "No articles scraped today." label |
| Notes file absent | `p.exists()` check before read; shows placeholder |
| Agent not running | JS `connectToRoom()` try/catch → status span shows error |
| LiveKit creds missing | `/token` returns HTTP 503 JSON |
| Mobile mic on LAN IP (http://) | Browser blocks mic; workaround: use `ngrok http 8080` for HTTPS |
| `vector_store.search()` slow | Sync callback — fine for personal use; can move to `run_in_executor` later |

---

## Verification

```bash
# 1. Install
uv sync

# 2. Start
uv run poe frontend
# → "NiceGUI ready at http://localhost:8080"

# 3. Token endpoint
curl http://localhost:8080/token
# → {"token": "eyJ...", "url": "wss://..."}

# 4. Transcript push
curl -X POST http://localhost:8080/transcript \
  -H "Content-Type: application/json" \
  -d '{"role":"user","text":"Hello from curl"}'
# → {"ok": true}; browser panel updates within 1 s

# 5. Full integration
# Terminal 1: uv run poe agent
# Terminal 2: uv run poe frontend
# Open http://localhost:8080 → Connect → speak → transcript appears → save note → notes panel updates
```

---

## Phase 2 — Typed Text Input

Allow the user to type messages to the agent in addition to speaking. Both input modes
share the same transcript panel and the agent treats them identically.

### Data flow

```
User types → NiceGUI text input
           → ui.run_javascript('sendText("...")')
           → JS: room.localParticipant.publishData(payload)   ← LiveKit data channel
           → Agent: ctx.room.on("data_received") handler
           → agent_session.generate_reply(user_input=text)
           → Agent speaks + emits transcript → JS POSTs to /transcript → panel updates
```

No extra IPC or new endpoints needed — the LiveKit room is already the shared channel.

### Change 1 — JS audio widget (`src/frontend/app.py`, `_AUDIO_WIDGET_HTML`)

Add `sendText(text)` function:

```javascript
async function sendText(text) {
    if (!_room) {
        alert("Connect to a session first.");
        return;
    }
    const payload = JSON.stringify({ type: "user_text", text });
    await _room.localParticipant.publishData(
        new TextEncoder().encode(payload),
        { reliable: true }
    );
    // Optimistic: show user turn immediately without waiting for transcript echo
    await fetch('/transcript', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role: 'user', text }),
    });
}
```

### Change 2 — NiceGUI page (`src/frontend/app.py`, `main_page`)

Add a text input row directly below the transcript card:

```python
with ui.row().classes("w-full gap-2 items-center"):
    text_input = ui.input(placeholder="Type a message…") \
        .classes("flex-grow").props("outlined dense")

    def send_typed():
        msg = text_input.value.strip()
        if not msg:
            return
        ui.run_javascript(f'sendText({json.dumps(msg)})')
        text_input.set_value("")

    text_input.on("keydown.enter", send_typed)   # Enter key sends
    ui.button("Send", on_click=send_typed).props("unelevated")
```

### Change 3 — Agent (`src/agent/agent.py`, `session()` function)

After `agent_session.start(...)`, register a data channel listener:

```python
import asyncio, json

@ctx.room.on("data_received")
def on_data_received(packet) -> None:
    try:
        payload = json.loads(packet.data.decode())
    except Exception:
        return
    if payload.get("type") != "user_text":
        return
    text = str(payload.get("text", "")).strip()
    if text:
        asyncio.ensure_future(
            agent_session.generate_reply(user_input=text)
        )
```

### Updated layout

```
┌─ Transcript ─────────────────────────────────────┐
│  User: What's in my newsletter today?   (voice)  │
│  Assistant: You have 5 articles...               │
│  User: Summarise all of them.           (typed)  │
└──────────────────────────────────────────────────┘
[ Type a message…                        ] [ Send ]
```

### Verification

1. Start agent + frontend
2. Click Connect
3. Type a message and press Enter (or Send)
4. Verify the user turn appears immediately in the transcript (optimistic update)
5. Verify the agent responds within a few seconds
6. Verify typed and spoken turns are interleaved correctly in the transcript

---

## Key Source Files Used

| File | Usage |
|---|---|
| `src/core/config.py:10-13` | `settings.livekit_url/api_key/api_secret` for `/token` |
| `src/core/notes.py:7` | `NOTES_DIR` constant for notes path |
| `src/knowledge/raw_store.py:136` | `get_all_articles(since=date.today())` for article panel |
| `src/knowledge/vector_store.py:96` | `search(query, n_results=5)` for search panel |
| `src/agent/agent.py:122` | `@server.rtc_session()` — no agent_name set, so JS client joins unnamed room |
