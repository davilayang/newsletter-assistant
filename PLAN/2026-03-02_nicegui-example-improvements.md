# NiceGUI Example Improvements — Plan

## Sources reviewed

- `zauberzeug/nicegui/examples/chat_app` — `ui.chat_message`, timestamps, `@ui.refreshable`
- `zauberzeug/nicegui/examples/ai_interface` — `run.io_bound()` for blocking calls
- `zauberzeug/nicegui/examples/single_page_app` — `ui.sub_pages`, catch-all route

---

## Changes to implement now

### 1. `ui.chat_message()` for transcript turns (from chat_app)

**File:** `src/frontend/page.py` → `on_transcript()`

**Current:**
```python
bg = "blue-1" if role == "assistant" else "green-1"
with transcript_container:
    ui.markdown(f"**{role.capitalize()}:** {text}").classes(
        f"q-pa-sm rounded bg-{bg} w-full"
    )
```

**After:**
```python
with transcript_container:
    ui.chat_message(
        text=text,
        name="Assistant" if role == "assistant" else "You",
        stamp=datetime.now().strftime("%H:%M"),
        sent=(role == "user"),   # right-align user, left-align agent
    )
```

`sent=True` renders right-aligned (outgoing); `sent=False` renders left-aligned (incoming).
Timestamps are carried by the message itself — no extra UI element needed.

Also add `from datetime import datetime` to imports (replace `from datetime import date`
with `from datetime import date, datetime`).

---

### 2. `run.io_bound()` for blocking I/O (from ai_interface)

**File:** `src/frontend/page.py`

SQLite and ChromaDB calls currently run synchronously in the event loop inside timer
callbacks and click handlers. Use `nicegui.run.io_bound()` to offload them to a
thread pool.

**`refresh_articles`** — called by `ui.timer(60.0)`:
```python
# before
def refresh_articles() -> None:
    articles = list(reversed(raw_store.get_all_articles()))
    ...

# after
async def refresh_articles() -> None:
    articles = list(reversed(await run.io_bound(raw_store.get_all_articles)))
    ...
```

**`refresh_notes`** — called by `ui.timer(10.0)`:
```python
# before
def refresh_notes() -> None:
    p = NOTES_DIR / f"{date.today()}_medium-notes.md"
    notes_md.set_content(p.read_text() if p.exists() else "...")

# after
async def refresh_notes() -> None:
    p = NOTES_DIR / f"{date.today()}_medium-notes.md"
    content = await run.io_bound(p.read_text) if p.exists() else "..."
    notes_md.set_content(content)
```

**`run_search`** — called on button click:
```python
# before
def run_search() -> None:
    results = vector_store.search(query, n_results=5)
    ...

# after
async def run_search() -> None:
    results = await run.io_bound(vector_store.search, query, n_results=5)
    ...
```

Add `from nicegui import run, ui` (extend existing import).

NiceGUI's `ui.timer` and event handlers support `async def` callbacks natively.

---

### 3. Catch-all route (from single_page_app)

**File:** `src/frontend/page.py`

Add a second `@ui.page` decorator so refreshing on any path returns the app
instead of a NiceGUI 404:

```python
@ui.page("/")
@ui.page("/{_:path}")
def main_page() -> None:
    ...
```

Two-line change, zero functional impact.

> [!CAUTION]
> **Issue encountered:** This greedy route currently intercepts internal NiceGUI
> JSON/JS requests (like `_nicegui_ws`), causing "Unexpected token '<'" errors.
> Implementation is deferred until a safer regex or path-exclusion logic is added.

---

## Changes to defer

| Pattern | Reason to defer |
|---|---|
| `ui.sub_pages` multi-route layout | Only one content area now; add when Notes/Articles get dedicated pages |
| `@ui.refreshable` transcript | Our `ui.on()` push-append is more efficient than full rebuild |
| `ui.footer()` input bar | Phase 2 — typed text input to agent |
| Per-user UUID + avatar | We have two fixed roles, not multi-user |

---

## Files to change

| File | Change |
|---|---|
| `src/frontend/page.py` | `ui.chat_message` in `on_transcript`; `run.io_bound` in callbacks; catch-all route |

No other files need to change.

---

## Verification

```bash
uv run poe frontend
# → open http://localhost:8080
# → connect to LiveKit session, speak a few words
# → transcript shows chat bubbles with timestamps, user right-aligned, agent left-aligned
# → search the knowledge base → no UI freeze during ChromaDB query
# → refresh browser on http://localhost:8080/anything → returns to app, no 404
```
