# src/frontend/app.py
# NiceGUI entrypoint — importing routes and page registers their decorators.

import os

from nicegui import ui

from src.frontend import page, routes  # noqa: F401 — imported to register decorators

if __name__ in ("__main__", "__mp_main__"):
    ui.run(
        title="Newsletter Assistant",
        host=os.environ.get("APP_HOST", "127.0.0.1"),
        port=8080,
        storage_secret="newsletter-assistant-ui",
        favicon="📰",
        dark=None,  # follows browser preference
        reload=False,
    )
