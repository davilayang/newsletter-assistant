# src/core/notes.py
# Append-only local markdown note storage

from datetime import date
from pathlib import Path

NOTES_DIR = Path("NOTES")


def save_note(content: str, article_title: str, article_url: str) -> Path:
    """Append a note to today's markdown file under NOTES/.

    Returns the path of the file written to.
    """
    NOTES_DIR.mkdir(exist_ok=True)
    filepath = NOTES_DIR / f"{date.today()}_medium-notes.md"

    with filepath.open("a") as f:
        f.write(f"## {article_title}\n> {article_url}\n\n{content}\n\n---\n\n")

    return filepath
