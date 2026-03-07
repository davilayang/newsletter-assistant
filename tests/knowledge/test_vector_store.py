# tests/knowledge/test_vector_store.py

from pathlib import Path

import pytest

from knowledge.vector_store import _chunk_text, search, upsert_article

# ---------------------------------------------------------------------------
# Unit tests for chunking logic (no ChromaDB needed)
# ---------------------------------------------------------------------------


def test_chunk_short_text_is_single_chunk() -> None:
    text = "Short text."
    chunks = _chunk_text(text, chunk_size=100, overlap=10)
    assert chunks == [text]


def test_chunk_long_text_produces_multiple_chunks() -> None:
    # ~5000 chars, chunk_size=100 tokens → ~400 chars per chunk
    text = "word " * 1000  # 5000 chars
    chunks = _chunk_text(text, chunk_size=100, overlap=10)
    assert len(chunks) > 1


def test_chunk_overlap() -> None:
    # chunk_size=10 tokens → 40 chars, overlap=2 tokens → 8 chars
    text = "A" * 100
    chunks = _chunk_text(text, chunk_size=10, overlap=2)
    # Each chunk except first should overlap with previous
    assert len(chunks) >= 2
    # Verify: end of chunk[0] == beginning of chunk[1] shifted by overlap chars
    overlap_chars = 2 * 4
    assert chunks[0][-overlap_chars:] == chunks[1][:overlap_chars]


def test_chunk_no_empty_chunks() -> None:
    text = "Hello world " * 500
    chunks = _chunk_text(text, chunk_size=50, overlap=5)
    assert all(c.strip() for c in chunks)


# ---------------------------------------------------------------------------
# Integration tests with real ChromaDB (in tmp_path)
# ---------------------------------------------------------------------------


@pytest.fixture()
def chroma(tmp_path: Path) -> Path:
    return tmp_path / "chroma"


def test_upsert_and_search(chroma: Path) -> None:
    upsert_article(
        url="https://medium.com/article/rag",
        raw_markdown="# RAG Pipelines\n\nRetrieval-Augmented Generation improves LLM accuracy.",
        metadata={
            "title": "RAG Pipelines",
            "author": "Alice",
            "newsletter_date": "2026-02-28",
        },
        chroma_path=chroma,
    )
    results = search("retrieval augmented generation", n_results=3, chroma_path=chroma)
    assert len(results) >= 1
    assert results[0].url == "https://medium.com/article/rag"
    assert results[0].title == "RAG Pipelines"


def test_upsert_idempotent(chroma: Path) -> None:
    for _ in range(3):
        upsert_article(
            url="https://medium.com/article/idempotent",
            raw_markdown="Content stays the same.",
            metadata={"title": "T", "author": "", "newsletter_date": ""},
            chroma_path=chroma,
        )
    results = search("stays the same", n_results=10, chroma_path=chroma)
    # Should not duplicate — only one unique document
    urls = [r.url for r in results]
    assert urls.count("https://medium.com/article/idempotent") == 1


def test_search_empty_collection(chroma: Path) -> None:
    results = search("anything", chroma_path=chroma)
    assert results == []


def test_search_result_fields(chroma: Path) -> None:
    upsert_article(
        url="https://medium.com/article/fields",
        raw_markdown="Discussing vector databases and embeddings.",
        metadata={"title": "Vectors", "author": "Bob", "newsletter_date": "2026-01-01"},
        chroma_path=chroma,
    )
    results = search("vector databases", chroma_path=chroma)
    r = results[0]
    assert r.url == "https://medium.com/article/fields"
    assert r.title == "Vectors"
    assert r.author == "Bob"
    assert isinstance(r.distance, float)
    assert isinstance(r.chunk, str)
