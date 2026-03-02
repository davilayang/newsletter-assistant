# Frontend Review — agent-starter-python + agent-starter-react

Date: 2026-03-02

---

## 1. Our Agent is Already on the Modern API

The plan references `VoicePipelineAgent` (old API), but `src/agent/agent.py` already
uses the current API: `AgentServer`, `AgentSession`, `Agent`. The example repo
(`agent-starter-python`) uses the exact same pattern, so no agent changes are required
for frontend integration.

---

## 2. Official Frontend: React/Next.js, Not Streamlit

The LiveKit examples README explicitly recommends
[`agent-starter-react`](https://github.com/livekit-examples/agent-starter-react) as the
companion frontend. It is a Next.js app built on the **Agents UI** component library
(`@livekit/agents-ui`) which ships:

- Real-time transcription panel (native, no polling)
- Audio visualizers: `bar`, `wave`, `grid`, `radial`, `aura`
- Control bar: mute, end session, camera, screen share
- Light/dark theme
- Agent dispatch config (agent name → maps to our `@server.rtc_session()`)

All built on `livekit-client` JS SDK with React hooks.

### Implication for the Plan

| Plan assumption | Reality |
|---|---|
| Streamlit can embed a "small JS audio snippet" | LiveKit audio is a full client-side stack — the JS is non-trivial |
| No JS knowledge needed | React starter eliminates that concern by providing everything pre-built |
| Polling required for live transcripts | Agents UI handles transcripts via WebSocket natively — zero polling |

**Recommendation: use `agent-starter-react` as the shell instead of Streamlit.**

---

## 3. What Still Needs to Be Built

Even with the React starter, we still need custom additions:

### FastAPI token endpoint (unchanged from plan)
`GET /token` → LiveKit JWT. Minimal FastAPI app in `src/frontend/server.py`.

### Article panel
The React starter has no concept of "today's articles". Add a sidebar component that:
- Fetches from a new `GET /articles/today` endpoint (reads `raw_store`)
- Shows title + URL, clickable

### Notes panel
Similarly, a `GET /notes/today` endpoint returns today's notes markdown;
rendered in a read-only panel.

### Knowledge search
`POST /search` → calls `vector_store.search()`, returns hits.

---

## 4. Revised Architecture

```
Browser (Next.js / agent-starter-react)
  ├── Agents UI components  →  LiveKit room (WebRTC audio + transcripts)
  ├── Article sidebar       →  GET /articles/today  (FastAPI)
  ├── Notes panel           →  GET /notes/today     (FastAPI)
  └── Search input          →  POST /search         (FastAPI)

FastAPI  (src/frontend/server.py)
  ├── GET  /token            →  LiveKit JWT
  ├── GET  /articles/today   →  raw_store.get_all_articles()
  ├── GET  /notes/today      →  reads NOTES/<date>_medium-notes.md
  └── POST /search           →  vector_store.search()

LiveKit room
  └── Python agent  (src/agent/agent.py — unchanged)
```

No transcript polling file needed — transcripts come from LiveKit natively.

---

## 5. Revised Priority Order

| Priority | Step | Effort |
|---|---|---|-|
| 1 | FastAPI server (`/token` + `/articles/today` + `/notes/today`) | 1 hr |
| 2 | Clone & configure `agent-starter-react` (point at our FastAPI token endpoint) | 30 min |
| 3 | Add article sidebar component to React app | 1 hr |
| 4 | Add notes panel to React app | 30 min |
| 5 | Add search input + `/search` endpoint | 1 hr |
| 6 | Poe tasks: `poe backend`, `poe frontend` | 15 min |

Total Phase 1: ~4 hours vs ~5 in original plan, with better real-time behavior.

---

## 6. Dependency Changes (revised)

Python side only needs:
```toml
"fastapi>=0.115",
"uvicorn>=0.30",
"livekit-api>=0.8",
```

No `streamlit`. The React app manages its own `node_modules` via `pnpm`.

---

## 7. Token Endpoint — Agent Name

The React starter supports `agentName` in `app-config.ts` (dispatches to a named agent
via `@server.rtc_session(agent_name="...")`). Our agent currently uses the default
(no name). Either:
- Leave `agentName: undefined` in the React config (works with unnamed session), or
- Add `agent_name="newsletter"` to `@server.rtc_session()` and set it in config.
