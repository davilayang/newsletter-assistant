# LiveKit Widget — WebSocket Transcript Plan

## Discovery

NiceGUI exposes a global `emitEvent(name, payload)` function in the browser that
routes over the **existing NiceGUI WebSocket** to a Python `ui.on(name, handler)`
listener. This is a push mechanism — no HTTP, no polling.

`ui.audio()` is a static file player only (no mic/WebRTC). Skipped.
`anywidget` adds deps for no meaningful gain over emitEvent. Skipped.

---

## Current transcript flow (to be replaced)

```
LiveKit JS (TranscriptionReceived)
  → POST /transcript   (HTTP round-trip)
    → routes._transcript.append({role, text})
      → ui.timer(0.25s, refresh_transcript) polls list
        → appends markdown turns to transcript_container
```

Problems:
- Two extra hops: HTTP POST + polling timer
- Up to 250 ms lag between final segment and UI update
- Shared mutable `_transcript` list couples routes.py ↔ page.py
- `/transcript` FastAPI endpoint exists solely to bridge JS → Python

---

## New transcript flow

```
LiveKit JS (TranscriptionReceived — final segment)
  → emitEvent('transcript', {role, text})   (NiceGUI WebSocket)
    → ui.on('transcript', handler)
      → appends markdown turn to transcript_container immediately
```

Benefits:
- Push-based, zero polling lag
- No HTTP POST, no shared list, no timer for transcripts
- Cleaner separation: routes.py only owns /token

Connection state will also be pushed:

```
LiveKit JS (Connected / Disconnected)
  → emitEvent('lk_status', {connected: bool})
    → ui.on('lk_status', handler)
      → updates a status chip element in Python
```

---

## Files to change

### `src/frontend/livekit_widget.py`

In `_AUDIO_WIDGET_JS`, replace the two places that POST to `/transcript`:

**TranscriptionReceived — final segment:**
```js
// before
fetch('/transcript', { method: 'POST', ... body: JSON.stringify({role, text}) });

// after
emitEvent('transcript', { role, text });
```

Also emit connection state on connect/disconnect:
```js
// after _room.connect() + publishTrack:
emitEvent('lk_status', { connected: true });

// in RoomEvent.Disconnected handler:
emitEvent('lk_status', { connected: false });
```

### `src/frontend/routes.py`

- Delete `_transcript` list
- Delete `post_transcript()` route
- Keep `get_token()` route (JS still needs the return value over HTTP)
- Keep `_ROOM` / `_AGENT_NAME` constants

### `src/frontend/page.py`

- Remove `from .routes import _transcript`
- Remove `rendered = [0]` closure state
- Remove `refresh_transcript()` function
- Remove `ui.timer(0.25, refresh_transcript)`
- Add `ui.on('transcript', on_transcript)` handler that appends turns directly
- Add `ui.on('lk_status', on_lk_status)` handler to update a status element
- Add a status chip/badge in the Voice Session card showing Connected / Disconnected

---

## Risk

`emitEvent` is a NiceGUI global injected into the page. It is available inside
scripts added via `ui.add_body_html()` — confirmed in GitHub discussions. If it
is not available in the LiveKit callback scope (async closure), fallback is to
assign it at module level:

```js
const _emit = window.emitEvent ?? (() => {});
```

---

## Files to change summary

| File | Change |
|---|---|
| `src/frontend/livekit_widget.py` | Replace fetch('/transcript') with emitEvent; emit lk_status on connect/disconnect |
| `src/frontend/routes.py` | Delete _transcript list + post_transcript route |
| `src/frontend/page.py` | Replace timer + refresh_transcript with ui.on handlers; add status indicator |
