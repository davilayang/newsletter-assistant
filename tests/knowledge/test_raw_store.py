# tests/knowledge/test_raw_store.py

from datetime import date
from pathlib import Path

import pytest

from knowledge.raw_store import (
    get_all_articles,
    get_articles_by_vector_status,
    is_processed,
    mark_processed,
    set_vector_status,
    upsert_article,
)


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


def test_upsert_and_retrieve(db: Path) -> None:
    upsert_article(
        url="https://medium.com/article/foo",
        title="Foo Article",
        author="Alice",
        newsletter_date=date(2026, 2, 28),
        raw_markdown="# Foo\n\nContent here.",
        db_path=db,
    )
    rows = get_all_articles(db_path=db)
    assert len(rows) == 1
    assert rows[0].url == "https://medium.com/article/foo"
    assert rows[0].title == "Foo Article"
    assert rows[0].author == "Alice"
    assert rows[0].newsletter_date == date(2026, 2, 28)
    assert "Content here" in rows[0].raw_markdown


def test_upsert_is_idempotent(db: Path) -> None:
    for _ in range(3):
        upsert_article(
            url="https://medium.com/article/bar",
            title="Bar",
            author="Bob",
            newsletter_date=None,
            raw_markdown="Updated",
            db_path=db,
        )
    rows = get_all_articles(db_path=db)
    assert len(rows) == 1
    assert rows[0].raw_markdown == "Updated"


def test_upsert_updates_fields(db: Path) -> None:
    upsert_article(
        "https://medium.com/u", "Old Title", "A", date(2026, 1, 1), "v1", db_path=db
    )
    upsert_article(
        "https://medium.com/u", "New Title", "A", date(2026, 1, 1), "v2", db_path=db
    )
    rows = get_all_articles(db_path=db)
    assert rows[0].title == "New Title"
    assert rows[0].raw_markdown == "v2"


def test_scrape_log_not_processed(db: Path) -> None:
    assert not is_processed("msg-001", db_path=db)


def test_scrape_log_mark_and_check(db: Path) -> None:
    mark_processed("msg-001", db_path=db)
    assert is_processed("msg-001", db_path=db)
    assert not is_processed("msg-002", db_path=db)


def test_scrape_log_mark_idempotent(db: Path) -> None:
    mark_processed("msg-dup", db_path=db)
    mark_processed("msg-dup", db_path=db)  # should not raise
    assert is_processed("msg-dup", db_path=db)


def test_get_all_articles_since_filter(db: Path) -> None:
    upsert_article(
        "https://medium.com/old", "Old", "", date(2025, 12, 1), "old", db_path=db
    )
    upsert_article(
        "https://medium.com/new", "New", "", date(2026, 2, 28), "new", db_path=db
    )

    rows = get_all_articles(since=date(2026, 1, 1), db_path=db)
    assert len(rows) == 1
    assert rows[0].url == "https://medium.com/new"


def test_get_all_articles_no_filter(db: Path) -> None:
    upsert_article("https://medium.com/a", "A", "", date(2026, 1, 1), "a", db_path=db)
    upsert_article("https://medium.com/b", "B", "", date(2026, 2, 1), "b", db_path=db)
    rows = get_all_articles(db_path=db)
    assert len(rows) == 2


def test_none_newsletter_date(db: Path) -> None:
    upsert_article(
        "https://medium.com/nodatearticle", "No Date", "", None, "content", db_path=db
    )
    rows = get_all_articles(db_path=db)
    assert rows[0].newsletter_date is None


def test_default_vector_status_is_pending(db: Path) -> None:
    upsert_article("https://medium.com/a", "A", "", None, "content", db_path=db)
    rows = get_all_articles(db_path=db)
    assert rows[0].vector_status == "pending"


def test_set_vector_status(db: Path) -> None:
    upsert_article("https://medium.com/a", "A", "", None, "content", db_path=db)
    set_vector_status("https://medium.com/a", "indexed", db_path=db)
    rows = get_all_articles(db_path=db)
    assert rows[0].vector_status == "indexed"


def test_upsert_preserves_vector_status(db: Path) -> None:
    upsert_article("https://medium.com/a", "A", "", None, "v1", db_path=db)
    set_vector_status("https://medium.com/a", "indexed", db_path=db)
    # Re-fetch should NOT reset vector_status back to 'pending'
    upsert_article("https://medium.com/a", "A", "", None, "v2", db_path=db)
    rows = get_all_articles(db_path=db)
    assert rows[0].vector_status == "indexed"


def test_get_articles_by_vector_status(db: Path) -> None:
    upsert_article("https://medium.com/a", "A", "", None, "content", db_path=db)
    upsert_article("https://medium.com/b", "B", "", None, "content", db_path=db)
    set_vector_status("https://medium.com/a", "indexed", db_path=db)

    pending = get_articles_by_vector_status("pending", db_path=db)
    indexed = get_articles_by_vector_status("indexed", db_path=db)

    assert len(pending) == 1
    assert pending[0].url == "https://medium.com/b"
    assert len(indexed) == 1
    assert indexed[0].url == "https://medium.com/a"
