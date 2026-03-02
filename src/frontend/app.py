# src/frontend/app.py
# NiceGUI entrypoint — importing routes and page registers their decorators.

from nicegui import ui

from . import page, routes  # noqa: F401 — side-effects: @app.* and @ui.page("/")

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
