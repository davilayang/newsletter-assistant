# src/knowledge/cashcow_store.py
# SQLite store for Boring Cash Cow newsletter sections.

from __future__ import annotations

import sqlite3

from datetime import date
from pathlib import Path

from src.knowledge.boring_cashcow import CashCowSection

DB_PATH = Path("data/boring_cashcow.db")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS sections (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    newsletter_date  DATE,
    title            TEXT,
    content_md       TEXT,
    stored_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(newsletter_date, title)
);
"""


def _connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.executescript(_CREATE_TABLE)
    conn.commit()
    return conn


def upsert_section(
    section: CashCowSection,
    db_path: Path = DB_PATH,
) -> None:
    """Insert or replace a section. Idempotent on (newsletter_date, title)."""
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO sections (newsletter_date, title, content_md)
            VALUES (?, ?, ?)
            ON CONFLICT(newsletter_date, title) DO UPDATE SET
                content_md = excluded.content_md,
                stored_at  = CURRENT_TIMESTAMP
            """,
            (
                section.newsletter_date.isoformat()
                if section.newsletter_date
                else None,
                section.title,
                section.content_md,
            ),
        )


def get_sections(
    since: date | None = None,
    db_path: Path = DB_PATH,
) -> list[CashCowSection]:
    """Return sections, optionally filtered to those on or after *since*."""
    with _connect(db_path) as conn:
        if since is None:
            rows = conn.execute(
                "SELECT * FROM sections ORDER BY newsletter_date, id"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM sections WHERE newsletter_date >= ? ORDER BY newsletter_date, id",
                (since.isoformat(),),
            ).fetchall()

    return [
        CashCowSection(
            title=r["title"],
            content_md=r["content_md"],
            newsletter_date=date.fromisoformat(r["newsletter_date"])
            if r["newsletter_date"]
            else None,
        )
        for r in rows
    ]
