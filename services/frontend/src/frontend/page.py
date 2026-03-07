# src/frontend/page.py
# NiceGUI page layout, refresh callbacks, and timers.

from __future__ import annotations

from datetime import date, datetime

from core.notes import NOTES_DIR
from knowledge import raw_store, vector_store
from nicegui import run, ui

from .livekit_widget import _AUDIO_WIDGET_HTML, _AUDIO_WIDGET_JS

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
async def main_page() -> None:
    """Single-page app: header + left drawer (articles/search) + main content."""

    # Inject LiveKit JS once per page load — must be called before layout elements.
    ui.add_body_html(_AUDIO_WIDGET_JS)

    # Set Quasar theme colors and global CSS overrides.
    ui.colors(primary="#1976d2", negative="#c62828")
    ui.add_css(_CSS)

    # ── Header ──────────────────────────────────────────────────────────────
    dark = ui.dark_mode()
    with ui.header(elevated=True).classes("items-center gap-2"):
        ui.button(icon="menu", on_click=lambda: drawer.toggle()).props(  # type: ignore[has-type]
            "flat round dense"
        )
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
        search_input = (
            ui.input(placeholder="Search…").classes("w-full").props("outlined dense")
        )

        async def run_search() -> None:
            query = search_input.value.strip()
            if not query:
                return
            search_btn.props("loading")  # type: ignore[has-type]
            try:
                results = await run.io_bound(vector_store.search, query, n_results=5)
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
            finally:
                search_btn.props(remove="loading")  # type: ignore[has-type]

        search_btn = (
            ui.button("Search", on_click=run_search)
            .props("unelevated")
            .classes("w-full q-mt-xs")
        )

    # ── Main content ────────────────────────────────────────────────────────
    with ui.column().classes("w-full q-pa-md gap-4"):
        # Voice session card
        with ui.card().classes("w-full"):
            with ui.row().classes("items-center q-mb-sm gap-2"):
                ui.label("Voice Session").classes("text-subtitle1")
                status_badge = ui.badge("Disconnected", color="grey").props("rounded")
            ui.html(_AUDIO_WIDGET_HTML, sanitize=False)

        # Transcript card — turns appended directly via ui.on('transcript')
        with ui.card().classes("w-full"):
            ui.label("Transcript").classes("text-subtitle1 q-mb-sm")
            transcript_container = (
                ui.column()
                .classes("w-full gap-2 overflow-auto")
                .style("max-height:400px")
                .props("id=transcript-scroll")
            )

        # Today's notes — collapsed by default
        with ui.expansion("Today's Notes", icon="notes").classes("w-full"):
            notes_md = ui.markdown("*No notes saved yet today.*").classes("w-full")

    # ── Callbacks ────────────────────────────────────────────────────────────

    async def refresh_articles() -> None:
        # No date filter — newsletter_date is NULL for manually scraped articles.
        # Reverse so most recently scraped articles appear at the top.
        articles = list(reversed(await run.io_bound(raw_store.get_all_articles)))
        article_container.clear()
        with article_container:
            if not articles:
                ui.label("No articles in database yet.").classes(
                    "text-caption text-grey"
                )
            else:
                for art in articles:
                    ui.link(art.title or art.url, art.url, new_tab=True).classes(
                        "text-body2 q-mb-xs"
                    )

    async def refresh_notes() -> None:
        p = NOTES_DIR / f"{date.today()}_medium-notes.md"
        content = (
            await run.io_bound(p.read_text)
            if p.exists()
            else "*No notes saved yet today.*"
        )
        notes_md.set_content(content)

    # ── WebSocket push handlers (replaces HTTP POST + polling timer) ─────────

    def on_transcript(e) -> None:
        """Called instantly when JS emits a final transcript segment."""
        role = e.args.get("role", "user")
        text = e.args.get("text", "").strip()
        if not text:
            return
        with transcript_container:
            ui.chat_message(
                text=text,
                name="Assistant" if role == "assistant" else "You",
                stamp=datetime.now().strftime("%H:%M"),
                sent=(role == "user"),
            )
        ui.run_javascript(
            "const el = document.getElementById('transcript-scroll');"
            "if (el) el.scrollTop = el.scrollHeight;"
        )

    def on_lk_status(e) -> None:
        """Update the Python-side status badge when LiveKit connects/disconnects."""
        if e.args.get("connected"):
            status_badge.set_text("Connected")
            status_badge.props("color=positive")
        else:
            status_badge.set_text("Disconnected")
            status_badge.props("color=grey")

    ui.on("transcript", on_transcript)
    ui.on("lk_status", on_lk_status)

    # Initial load
    await refresh_articles()
    await refresh_notes()

    # Timers — scoped to this client connection
    ui.timer(10.0, refresh_notes)
    ui.timer(60.0, refresh_articles)
