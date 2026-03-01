# src/knowledge/raw_store.py
# SQLite raw store — source of truth for scraped article content.

import sqlite3

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

DB_PATH = Path("data/medium.db")

_CREATE_ARTICLES = """
CREATE TABLE IF NOT EXISTS articles (
    url              TEXT PRIMARY KEY,
    title            TEXT,
    author           TEXT,
    newsletter_date  DATE,
    scraped_at       TIMESTAMP,
    raw_markdown     TEXT,
    scrape_status    TEXT DEFAULT 'full',
    vector_status    TEXT DEFAULT 'pending'
);
"""

_CREATE_SCRAPE_LOG = """
CREATE TABLE IF NOT EXISTS scrape_log (
    gmail_message_id  TEXT PRIMARY KEY,
    processed_at      TIMESTAMP
);
"""


@dataclass
class ArticleRow:
    url: str
    title: str
    author: str
    newsletter_date: date | None
    scraped_at: datetime
    raw_markdown: str
    scrape_status: str = "full"
    vector_status: str = "pending"


def _connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.executescript(_CREATE_ARTICLES + _CREATE_SCRAPE_LOG)
    conn.commit()
    return conn


def upsert_article(
    url: str,
    title: str,
    author: str,
    newsletter_date: date | None,
    raw_markdown: str,
    scrape_status: str = "full",
    db_path: Path = DB_PATH,
) -> None:
    """Insert or replace an article row. Idempotent on URL."""
    now = datetime.now(tz=timezone.utc).isoformat()
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO articles (url, title, author, newsletter_date, scraped_at, raw_markdown, scrape_status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                title           = excluded.title,
                author          = excluded.author,
                newsletter_date = excluded.newsletter_date,
                scraped_at      = excluded.scraped_at,
                raw_markdown    = excluded.raw_markdown,
                scrape_status   = excluded.scrape_status
            -- vector_status intentionally excluded: re-fetching never resets approved/indexed state
            """,
            (
                url,
                title,
                author,
                newsletter_date.isoformat() if newsletter_date else None,
                now,
                raw_markdown,
                scrape_status,
            ),
        )


def is_processed(gmail_message_id: str, db_path: Path = DB_PATH) -> bool:
    """Return True if this Gmail message has already been processed."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM scrape_log WHERE gmail_message_id = ?",
            (gmail_message_id,),
        ).fetchone()
    return row is not None


def mark_processed(gmail_message_id: str, db_path: Path = DB_PATH) -> None:
    """Record that a Gmail message has been fully processed."""
    now = datetime.now(tz=timezone.utc).isoformat()
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO scrape_log (gmail_message_id, processed_at)
            VALUES (?, ?)
            ON CONFLICT(gmail_message_id) DO NOTHING
            """,
            (gmail_message_id, now),
        )


def get_article_by_url(url: str, db_path: Path = DB_PATH) -> ArticleRow | None:
    """Return a single article by URL, or None if not found."""
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM articles WHERE url = ?", (url,)).fetchone()
    if row is None:
        return None
    return ArticleRow(
        url=row["url"],
        title=row["title"] or "",
        author=row["author"] or "",
        newsletter_date=date.fromisoformat(row["newsletter_date"])
        if row["newsletter_date"]
        else None,
        scraped_at=datetime.fromisoformat(row["scraped_at"]),
        raw_markdown=row["raw_markdown"] or "",
        scrape_status=row["scrape_status"] or "full",
        vector_status=row["vector_status"] or "pending",
    )


def get_all_articles(
    since: date | None = None,
    db_path: Path = DB_PATH,
) -> list[ArticleRow]:
    """Return all articles, optionally filtered to those scraped on or after `since`."""
    with _connect(db_path) as conn:
        if since is None:
            rows = conn.execute("SELECT * FROM articles ORDER BY scraped_at").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM articles WHERE newsletter_date >= ? ORDER BY scraped_at",
                (since.isoformat(),),
            ).fetchall()

    return [
        ArticleRow(
            url=r["url"],
            title=r["title"] or "",
            author=r["author"] or "",
            newsletter_date=date.fromisoformat(r["newsletter_date"])
            if r["newsletter_date"]
            else None,
            scraped_at=datetime.fromisoformat(r["scraped_at"]),
            raw_markdown=r["raw_markdown"] or "",
            scrape_status=r["scrape_status"] or "full",
            vector_status=r["vector_status"] or "pending",
        )
        for r in rows
    ]


def get_articles_by_status(
    status: str,
    db_path: Path = DB_PATH,
) -> list[ArticleRow]:
    """Return all articles with a given scrape_status (e.g. 'snippet_only').

    Useful for retry runs: fetch articles that previously failed full scraping.
    """
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM articles WHERE scrape_status = ? ORDER BY scraped_at",
            (status,),
        ).fetchall()
    return [
        ArticleRow(
            url=r["url"],
            title=r["title"] or "",
            author=r["author"] or "",
            newsletter_date=date.fromisoformat(r["newsletter_date"])
            if r["newsletter_date"]
            else None,
            scraped_at=datetime.fromisoformat(r["scraped_at"]),
            raw_markdown=r["raw_markdown"] or "",
            scrape_status=r["scrape_status"] or "full",
            vector_status=r["vector_status"] or "pending",
        )
        for r in rows
    ]


def set_vector_status(url: str, status: str, db_path: Path = DB_PATH) -> None:
    """Set vector_status for one article ('pending' | 'ready' | 'indexed')."""
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE articles SET vector_status = ? WHERE url = ?",
            (status, url),
        )


def get_articles_by_vector_status(
    status: str,
    db_path: Path = DB_PATH,
) -> list[ArticleRow]:
    """Return all articles with a given vector_status."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM articles WHERE vector_status = ? ORDER BY scraped_at",
            (status,),
        ).fetchall()
    return [
        ArticleRow(
            url=r["url"],
            title=r["title"] or "",
            author=r["author"] or "",
            newsletter_date=date.fromisoformat(r["newsletter_date"])
            if r["newsletter_date"]
            else None,
            scraped_at=datetime.fromisoformat(r["scraped_at"]),
            raw_markdown=r["raw_markdown"] or "",
            scrape_status=r["scrape_status"] or "full",
            vector_status=r["vector_status"] or "pending",
        )
        for r in rows
    ]
