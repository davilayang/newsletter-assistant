# src/frontend/app.py
# NiceGUI frontend for the newsletter assistant.
# Serves the web UI and mounts two FastAPI routes on the same uvicorn process.

from __future__ import annotations

from datetime import date

from fastapi import Request
from nicegui import app, ui

from src.core.config import settings
from src.core.notes import NOTES_DIR
from src.knowledge import raw_store, vector_store

# ---------------------------------------------------------------------------
# Shared in-memory transcript state
# Resets on server restart; shared across all browser tabs in the same session.
# ---------------------------------------------------------------------------

_transcript: list[dict[str, str]] = []


# ---------------------------------------------------------------------------
# FastAPI custom routes (mounted on NiceGUI's internal FastAPI app)
# ---------------------------------------------------------------------------


_ROOM = "newsletter"
_AGENT_NAME = "newsletter"


@app.get("/token")
async def get_token() -> dict:
    """Return a LiveKit JWT and dispatch the agent to the room."""
    from livekit import api  # noqa: PLC0415
    from livekit.api import AccessToken, VideoGrants  # noqa: PLC0415

    try:
        token = (
            AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
            .with_grants(VideoGrants(room_join=True, room=_ROOM))
            .with_identity("user")
            .to_jwt()
        )
    except Exception as exc:
        from fastapi.responses import JSONResponse  # noqa: PLC0415

        return JSONResponse({"error": str(exc)}, status_code=503)

    # Dispatch the agent to the room so it joins when the user connects.
    # If the agent worker isn't running the dispatch is silently skipped.
    lk = api.LiveKitAPI(
        url=settings.livekit_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    )
    try:
        await lk.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(agent_name=_AGENT_NAME, room=_ROOM)
        )
    except Exception:
        pass  # agent worker not running — user can still join the empty room
    finally:
        await lk.aclose()

    return {"token": token, "url": str(settings.livekit_url)}


@app.post("/transcript")
async def post_transcript(request: Request) -> dict:
    """Receive a final transcript segment from the JS audio widget.

    Expected body: {"role": "user" | "assistant", "text": "..."}
    """
    data = await request.json()
    text = str(data.get("text", "")).strip()
    if text:
        _transcript.append({"role": str(data.get("role", "user")), "text": text})
    return {"ok": True}


# ---------------------------------------------------------------------------
# LiveKit audio widget — split into HTML (ui.html) and JS (ui.add_body_html)
# NiceGUI 3.x forbids <script> tags inside ui.html().
# ---------------------------------------------------------------------------

# The visible controls — no script tags allowed here.
_AUDIO_WIDGET_HTML = """
<div style="display:flex; flex-direction:column; gap:8px;">
  <span id="lk-status" style="font-size:0.85rem; color:#888;">Disconnected</span>
  <div style="display:flex; gap:8px; flex-wrap:wrap;">
    <button id="lk-connect"    onclick="lkConnect()">Connect</button>
    <button id="lk-mute"       onclick="lkToggleMute()" disabled>Mute</button>
    <button id="lk-disconnect" onclick="lkDisconnect()" disabled>Disconnect</button>
  </div>
  <div id="lk-interim" style="font-size:0.85rem; color:#888; font-style:italic; min-height:1.2em;"></div>
</div>
"""

# Script tags injected into <body> via ui.add_body_html() once per page load.
_AUDIO_WIDGET_JS = """
<script src="https://cdn.jsdelivr.net/npm/livekit-client@2.17.2/dist/livekit-client.umd.min.js"></script>
<script>
const { Room, RoomEvent, Track, createLocalAudioTrack } = LivekitClient;

let _room = null;
let _micTrack = null;

function lkSetStatus(msg) {
  document.getElementById('lk-status').textContent = msg;
}

function lkSetButtons(connected) {
  document.getElementById('lk-connect').disabled    = connected;
  document.getElementById('lk-mute').disabled       = !connected;
  document.getElementById('lk-disconnect').disabled = !connected;
}

async function lkConnect() {
  lkSetStatus('Connecting\u2026');
  try {
    const { token, url } = await fetch('/token').then(r => r.json());
    if (!token) throw new Error('No token returned \u2014 check server logs.');

    _room = new Room();

    // Attach any audio track published by a remote participant (the agent).
    _room.on(RoomEvent.TrackSubscribed, (track, _publication, _participant) => {
      if (track.kind === Track.Kind.Audio) {
        track.attach();   // creates an <audio> element and appends it to <body>
      }
    });

    _room.on(RoomEvent.TranscriptionReceived, (segments, participant) => {
      const role = participant?.isAgent ? 'assistant' : 'user';
      for (const seg of segments) {
        if (!seg.final) {
          // Show interim text immediately in the widget — no Python roundtrip.
          document.getElementById('lk-interim').textContent = seg.text;
        } else {
          // Final: clear interim display and commit to Python transcript store.
          document.getElementById('lk-interim').textContent = '';
          fetch('/transcript', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ role, text: seg.text }),
          });
        }
      }
    });

    _room.on(RoomEvent.Disconnected, () => {
      lkSetStatus('Disconnected');
      lkSetButtons(false);
      _room = null;
      _micTrack = null;
    });

    await _room.connect(url, token);
    _micTrack = await createLocalAudioTrack();
    await _room.localParticipant.publishTrack(_micTrack);

    lkSetStatus('Connected \u2014 mic active');
    lkSetButtons(true);
  } catch (err) {
    lkSetStatus('Error: ' + err.message);
    console.error(err);
  }
}

async function lkToggleMute() {
  if (!_micTrack) return;
  if (_micTrack.isMuted) {
    await _micTrack.unmute();
    document.getElementById('lk-mute').textContent = 'Mute';
    lkSetStatus('Connected \u2014 mic active');
  } else {
    await _micTrack.mute();
    document.getElementById('lk-mute').textContent = 'Unmute';
    lkSetStatus('Connected \u2014 mic muted');
  }
}

async function lkDisconnect() {
  if (_room) await _room.disconnect();
}

// Called from NiceGUI's ui.run_javascript() for typed input (Phase 2).
async function sendText(text) {
  if (!_room) { alert('Connect to a session first.'); return; }
  const payload = JSON.stringify({ type: 'user_text', text });
  await _room.localParticipant.publishData(
    new TextEncoder().encode(payload),
    { reliable: true }
  );
  await fetch('/transcript', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role: 'user', text }),
  });
}
</script>
"""


# ---------------------------------------------------------------------------
# NiceGUI page
# ---------------------------------------------------------------------------


@ui.page("/")
def main_page() -> None:
    """Single-page app: header + left drawer (articles/search) + main content."""

    # Per-client render cursor — tracks how many transcript turns have been displayed.
    # Defined as a list so the nested closure can mutate it.
    rendered = [0]

    # Inject LiveKit JS once per page load — must be called before layout elements.
    ui.add_body_html(_AUDIO_WIDGET_JS)

    # ── Header ──────────────────────────────────────────────────────────────
    with ui.header(elevated=True).classes("items-center gap-2"):
        ui.button(icon="menu", on_click=lambda: drawer.toggle()).props("flat round dense")
        ui.label("Newsletter Assistant").classes("text-h6")

    # ── Left drawer — articles + search ────────────────────────────────────
    with ui.left_drawer(top_corner=True, bottom_corner=True).props(
        "breakpoint=768 width=280"
    ) as drawer:
        ui.label("Today's Articles").classes("text-subtitle1 q-mb-sm")
        article_container = ui.column().classes("w-full gap-1")

        ui.separator().classes("q-my-md")
        ui.label("Search Knowledge Base").classes("text-subtitle2 q-mb-xs")
        search_input = ui.input(placeholder="Search…").classes("w-full").props(
            "outlined dense"
        )

        def run_search() -> None:
            query = search_input.value.strip()
            if not query:
                return
            results = vector_store.search(query, n_results=5)
            with ui.dialog() as dlg, ui.card().classes("w-full").style(
                "max-width:560px"
            ):
                ui.label(f'Results for "{query}"').classes("text-subtitle1 q-mb-sm")
                if not results:
                    ui.label("No results found.").classes("text-caption")
                for r in results:
                    with ui.card().classes("w-full q-mb-sm"):
                        ui.link(r.title or r.url, r.url, new_tab=True).classes(
                            "text-body2 text-weight-medium"
                        )
                        ui.label(r.author).classes("text-caption text-grey")
                        ui.label(r.chunk[:200] + "…").classes("text-body2")
                ui.button("Close", on_click=dlg.close).props("flat").classes(
                    "q-mt-sm"
                )
            dlg.open()

        ui.button("Search", on_click=run_search).props("unelevated").classes(
            "w-full q-mt-xs"
        )

    # ── Main content ────────────────────────────────────────────────────────
    with ui.column().classes("w-full q-pa-md gap-4"):

        # Voice session card
        with ui.card().classes("w-full"):
            ui.label("Voice Session").classes("text-subtitle1 q-mb-sm")
            ui.html(_AUDIO_WIDGET_HTML, sanitize=False)

        # Transcript card — append-only, no full rebuild each tick
        with ui.card().classes("w-full"):
            ui.label("Transcript").classes("text-subtitle1 q-mb-sm")
            transcript_container = ui.column().classes("w-full gap-2 overflow-auto").style(
                "max-height:400px"
            ).props('id=transcript-scroll')

        # Today's notes — collapsed by default
        with ui.expansion("Today's Notes", icon="notes").classes("w-full"):
            notes_md = ui.markdown("*No notes saved yet today.*").classes("w-full")

    # ── Refresh callbacks ────────────────────────────────────────────────────

    def refresh_articles() -> None:
        # No date filter — newsletter_date is NULL for manually scraped articles.
        # Reverse so most recently scraped articles appear at the top.
        articles = list(reversed(raw_store.get_all_articles()))
        article_container.clear()
        with article_container:
            if not articles:
                ui.label("No articles in database yet.").classes("text-caption text-grey")
            else:
                for art in articles:
                    ui.link(
                        art.title or art.url, art.url, new_tab=True
                    ).classes("text-body2 q-mb-xs")

    def refresh_transcript() -> None:
        new_turns = _transcript[rendered[0] :]
        if not new_turns:
            return
        with transcript_container:
            for turn in new_turns:
                bg = "blue-1" if turn["role"] == "assistant" else "green-1"
                ui.markdown(
                    f"**{turn['role'].capitalize()}:** {turn['text']}"
                ).classes(f"q-pa-sm rounded bg-{bg} w-full")
        rendered[0] += len(new_turns)
        ui.run_javascript(
            "const el = document.getElementById('transcript-scroll');"
            "if (el) el.scrollTop = el.scrollHeight;"
        )

    def refresh_notes() -> None:
        p = NOTES_DIR / f"{date.today()}_medium-notes.md"
        notes_md.set_content(
            p.read_text() if p.exists() else "*No notes saved yet today.*"
        )

    # Initial load
    refresh_articles()
    refresh_notes()

    # Timers — scoped to this client connection
    ui.timer(0.25, refresh_transcript)
    ui.timer(10.0, refresh_notes)
    ui.timer(60.0, refresh_articles)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

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
