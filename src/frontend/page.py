# src/frontend/page.py
# NiceGUI page layout, refresh callbacks, and timers.

from __future__ import annotations

from datetime import date

from nicegui import ui

from src.core.notes import NOTES_DIR
from src.knowledge import raw_store, vector_store

from .livekit_widget import _AUDIO_WIDGET_HTML, _AUDIO_WIDGET_JS
from .routes import _transcript

_CSS = """
body { font-size: 16px; }
#lk-connect, #lk-mute, #lk-disconnect {
  padding: 8px 22px;
  font-size: 0.95rem;
  font-weight: 500;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  transition: opacity 0.15s, filter 0.15s;
}
#lk-connect    { background: #1976d2; color: #fff; }
#lk-mute       { background: #546e7a; color: #fff; }
#lk-disconnect { background: #c62828; color: #fff; }
#lk-connect:hover:not(:disabled)    { filter: brightness(1.12); }
#lk-mute:hover:not(:disabled)       { filter: brightness(1.12); }
#lk-disconnect:hover:not(:disabled) { filter: brightness(1.12); }
#lk-connect:disabled, #lk-mute:disabled, #lk-disconnect:disabled {
  opacity: 0.35;
  cursor: default;
}
"""


@ui.page("/")
def main_page() -> None:
    """Single-page app: header + left drawer (articles/search) + main content."""

    # Per-client render cursor — tracks how many transcript turns have been displayed.
    # Defined as a list so the nested closure can mutate it.
    rendered = [0]

    # Inject LiveKit JS once per page load — must be called before layout elements.
    ui.add_body_html(_AUDIO_WIDGET_JS)

    # Set Quasar theme colors and global CSS overrides.
    ui.colors(primary="#1976d2", negative="#c62828")
    ui.add_css(_CSS)

    # ── Header ──────────────────────────────────────────────────────────────
    dark = ui.dark_mode()
    with ui.header(elevated=True).classes("items-center gap-2"):
        ui.button(icon="menu", on_click=lambda: drawer.toggle()).props("flat round dense")
        ui.label("Newsletter Assistant").classes("text-h6 flex-1")
        ui.switch("Dark").bind_value(dark).props("dense")

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
