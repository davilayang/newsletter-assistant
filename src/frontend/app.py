# src/frontend/app.py
# NiceGUI entrypoint — importing routes and page registers their decorators.

from nicegui import ui

if __name__ in ("__main__", "__mp_main__"):
    ui.run(
        title="Newsletter Assistant",
        host="127.0.0.1",
        port=8080,
        storage_secret="newsletter-assistant-ui",
        favicon="📰",
        dark=None,  # follows browser preference
        reload=False,
    )
