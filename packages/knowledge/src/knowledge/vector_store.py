# src/knowledge/vector_store.py
# ChromaDB vector store — chunk, embed, and search article content.

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import chromadb

from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

from .raw_store import DB_PATH as SQLITE_DB_PATH
from .raw_store import get_all_articles

CHROMA_PATH = Path("data/chroma")
COLLECTION_NAME = "medium_articles"

# Chunking parameters (rough token estimate: 1 token ≈ 4 chars)
CHUNK_SIZE = 800  # target tokens per chunk
CHUNK_OVERLAP = 100  # overlap tokens between consecutive chunks
_CHARS_PER_TOKEN = 4


@dataclass
class SearchResult:
    url: str
    title: str
    author: str
    chunk: str
    distance: float


def _get_collection(chroma_path: Path = CHROMA_PATH) -> chromadb.Collection:
    chroma_path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(chroma_path))
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=DefaultEmbeddingFunction(),  # type: ignore[arg-type]  # all-MiniLM-L6-v2 (384-dim, runs locally)
        metadata={"hnsw:space": "cosine"},
    )


def _chunk_text(
    text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP
) -> list[str]:
    """Split `text` into overlapping chunks (measured in approximate tokens)."""
    chunk_chars = chunk_size * _CHARS_PER_TOKEN
    overlap_chars = overlap * _CHARS_PER_TOKEN

    if len(text) <= chunk_chars:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_chars
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap_chars

    return chunks


def upsert_article(
    url: str,
    raw_markdown: str,
    metadata: dict,
    chroma_path: Path = CHROMA_PATH,
) -> None:
    """Chunk `raw_markdown`, embed each chunk, and upsert into ChromaDB.

    Existing chunks for `url` are deleted before upserting so reruns stay
    idempotent. `metadata` should contain at minimum {title, author, newsletter_date}.
    """
    collection = _get_collection(chroma_path)

    # Delete any pre-existing chunks for this URL
    existing = collection.get(where={"url": url})
    if existing["ids"]:
        collection.delete(ids=existing["ids"])

    chunks = _chunk_text(raw_markdown)
    if not chunks:
        return

    ids = [f"{url}::chunk{i}" for i in range(len(chunks))]
    chunk_metadata = [
        {**metadata, "url": url, "chunk_index": i} for i in range(len(chunks))
    ]

    collection.upsert(ids=ids, documents=chunks, metadatas=chunk_metadata)  # type: ignore[arg-type]


def search(
    query: str,
    n_results: int = 5,
    chroma_path: Path = CHROMA_PATH,
) -> list[SearchResult]:
    """Semantic search over all stored article chunks."""
    collection = _get_collection(chroma_path)
    if collection.count() == 0:
        return []

    results = collection.query(
        query_texts=[query],
        n_results=min(n_results, collection.count()),
        include=["documents", "metadatas", "distances"],
    )

    output: list[SearchResult] = []
    docs = results["documents"][0] if results["documents"] else []
    metas = results["metadatas"][0] if results["metadatas"] else []
    dists = results["distances"][0] if results["distances"] else []

    for doc, meta, dist in zip(docs, metas, dists):
        output.append(
            SearchResult(
                url=str(meta.get("url", "")),
                title=str(meta.get("title", "")),
                author=str(meta.get("author", "")),
                chunk=doc,
                distance=float(dist),
            )
        )

    return output


def rebuild_from_db(
    sqlite_path: Path = SQLITE_DB_PATH,
    chroma_path: Path = CHROMA_PATH,
) -> int:
    """Re-embed all articles from SQLite into ChromaDB. Returns count of articles processed."""
    articles = get_all_articles(db_path=sqlite_path)
    for article in articles:
        upsert_article(
            url=article.url,
            raw_markdown=article.raw_markdown,
            metadata={
                "title": article.title,
                "author": article.author,
                "newsletter_date": article.newsletter_date.isoformat()
                if article.newsletter_date
                else "",
            },
            chroma_path=chroma_path,
        )
    return len(articles)
