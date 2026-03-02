# Richer Knowledge Retrieval — Plan

## Problem

`search_knowledge` returns raw text chunks from ChromaDB. These are arbitrary 800-char
fragments of article text — the same article can surface 3–4 times with different
passages, and none of the results tell you what the article is *about*. Memory recovery
requires the agent (and user) to infer context from a fragment.

## Current data flow

```
index_article()
  → vector_store.upsert_article(url, raw_markdown, {title, author, newsletter_date})
    → _chunk_text() → N chunks, each embedded and stored in ChromaDB
    → metadata per chunk: {url, title, author, newsletter_date, chunk_index}

search_knowledge(query)
  → vector_store.search(query, n=5)
    → ChromaDB.query() → top-5 chunks (any article, any position)
    → SearchResult(url, title, author, chunk, distance)
  → format: "Title — first 300 chars of chunk…"
```

Two structural weaknesses:
1. **No article-level summary** — only raw chunks exist, no "what is this article about"
2. **No deduplication** — the same article fills multiple result slots with different chunks

---

## Phase 1 — Auto-summaries + deduplication (no LLM calls)

### 1a. Add `summary` column to SQLite

`ALTER TABLE articles ADD COLUMN summary TEXT;`

Run as a migration in `raw_store._connect()` using `IF NOT EXISTS` logic (SQLite
does not support `ADD COLUMN IF NOT EXISTS` before 3.37 — check with `PRAGMA
table_info` and add conditionally).

Update `ArticleRow` dataclass to include `summary: str = ""`.
Update `upsert_article()` to write/update `summary`.

### 1b. Auto-extract intro as summary (heuristic, free)

In `vector_store.upsert_article()`, before chunking:
- Extract the first ~400 chars trimmed to the nearest sentence boundary
- Store as `metadata["summary"]` in every chunk for that article
- Also write to SQLite `articles.summary` via `raw_store.set_summary(url, summary)`

This gives immediate context without LLM cost. Intro paragraphs of Medium articles
almost always contain the thesis.

### 1c. Deduplicate search results by article URL

In `vector_store.search()`, after the ChromaDB query:
- Group chunks by `url`
- Keep only the highest-scoring (lowest distance) chunk per article
- Return at most `n_results` unique articles

This makes `n_results=5` mean "5 distinct articles" not "5 random chunks".

### 1d. Update `SearchResult` and tool output

Add `summary: str` to `SearchResult`.

`search_knowledge` output becomes:
```
1. Article Title — Author Name
   medium.com/p/abc123
   Summary: This article argues that alignment is the key challenge…
   Relevant passage: "…the safety mechanisms implemented in the base model…"
```

---

## Phase 2 — LLM-generated summaries (better quality)

### 2a. Generate summary on `index_article`

`index_article` in `tools.py` already has the agent `context` (RunContext) available.
After indexing, make one LLM call:

```python
summary = await context.session.llm.complete(
    f"Summarise this article in 2-3 sentences for future recall:\n\n{raw_markdown[:3000]}"
)
raw_store.set_summary(url, summary)
vector_store.update_chunk_metadata(url, {"summary": summary})
```

Or: have the agent `save_note`-style tool store the summary automatically as part
of `index_article` — keeping everything in the existing notes system.

### 2b. `set_summary` in raw_store

```python
def set_summary(url: str, summary: str, db_path: Path = DB_PATH) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE articles SET summary = ? WHERE url = ?", (summary, url)
        )
        conn.commit()
```

### 2c. `update_chunk_metadata` in vector_store (optional)

ChromaDB supports `collection.update(ids=[...], metadatas=[...])`. Update all chunk
metadata for a URL to include the new `summary` so retrieval is self-contained
(no SQLite join needed at query time).

---

## Phase 3 — Notes as memory

User-saved notes are already the highest-signal memory (human-curated). They should
be searchable.

### Option A: Index notes into ChromaDB with `source="note"` tag

When `save_note()` is called, also upsert the note text into ChromaDB:
```python
vector_store.upsert_article(
    url=f"note::{article_url}",
    raw_markdown=content,
    metadata={"title": article_title, "author": "user-note",
               "source": "note", "date": str(date.today())}
)
```

`search_knowledge` then returns both article chunks and notes, with notes visually
distinguished in the output.

### Option B: Separate `search_notes` tool

Read all `NOTES/*.md` files, build a simple in-memory index (or SQLite FTS), return
matching notes. No ChromaDB dependency. Simpler but less semantically powerful.

---

## Files to change

| File | Change |
|---|---|
| `src/knowledge/raw_store.py` | Add `summary TEXT` column; `ArticleRow.summary`; `set_summary()`; migration in `_connect()` |
| `src/knowledge/vector_store.py` | Auto-extract intro summary in `upsert_article()`; add `summary` to chunk metadata; deduplicate by URL in `search()`; add `summary` to `SearchResult` |
| `src/agent/tools.py` | Update `search_knowledge` output format; update `index_article` to call `set_summary` with LLM-generated text (Phase 2) |

---

## Priority

| Phase | Effort | Benefit |
|---|---|---|
| 1a–1d (auto-summary + dedup) | ~1 hr | Immediate — no LLM cost, removes duplicate results |
| 2a–2c (LLM summaries) | ~1 hr | High — accurate summaries, best recall quality |
| 3A (notes in ChromaDB) | ~30 min | High — makes user notes retrievable |
| 3B (separate notes tool) | ~30 min | Medium — simpler alternative to 3A |
