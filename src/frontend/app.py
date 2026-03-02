# src/frontend/app.py
# NiceGUI entrypoint — importing routes and page registers their decorators.

import logging

from nicegui import ui

# ... (rest of imports)
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("nicegui")
logger.setLevel(logging.DEBUG)

from . import page, routes  # noqa: F401
...
if __name__ in ("__main__", "__mp_main__"):
    ui.run(
        title="Newsletter Assistant",
        host="127.0.0.1",
        port=8080,
        storage_secret="newsletter-assistant-ui",
        favicon="📰",
        dark=None,    # follows browser preference
        reload=False,
    )
