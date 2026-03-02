# Plan: Decouple raw store from vector store indexing

## Context

Pipeline fetches go straight into both raw_store and vector_store automatically.
The user wants explicit control: raw_store always captures everything, but vector_store
only gets articles the user has consciously engaged with.

Raw store = always write on fetch (source of truth).
Vector store = write only on explicit approval (agent or manual).

---

## `vector_status` values (3 states)

| Value | Meaning |
|---|---|
| `'pending'` | Fetched and stored; not yet reviewed or indexed |
| `'ready'` | Approved for indexing (by agent or manually), but batch not yet run |
| `'indexed'` | In vector store |

Flow:
```
fetch → 'pending'
           │
    agent index_article tool    OR    manual set_vector_status(url, 'ready')
           │                                    │
           ▼                                    ▼
       'indexed'                   index_ready() batch run → 'indexed'
```

The agent tool indexes immediately (pending → indexed in one step).
The manual path is two steps: mark ready, then batch index.

---

## Schema change — `src/knowledge/raw_store.py`

No migration — drop and recreate the table (dev stage).

Add to `_CREATE_ARTICLES`:
```sql
vector_status    TEXT DEFAULT 'pending'
```

`upsert_article` ON CONFLICT — do NOT include `vector_status` in the UPDATE SET list
so re-fetching an article never resets an approved/indexed status.

**New `ArticleRow` field**: `vector_status: str = "pending"`

**New functions**:
```python
def set_vector_status(url: str, status: str, db_path: Path = DB_PATH) -> None:
    """Manually set vector_status for one article ('pending'|'ready'|'indexed')."""

def get_articles_by_vector_status(
    status: str, db_path: Path = DB_PATH
) -> list[ArticleRow]:
    """Return all articles with a given vector_status."""
```

---

## `src/knowledge/fetcher.py` changes

Remove `vector_store` import and the `vector_store.upsert_article()` block from
`fetch_and_cache()`. Raw store upsert unchanged.

---

## `src/knowledge/pipeline.py` changes

Remove `vector_store` import and the `vector_store.upsert_article()` call in the
main article loop. Raw store upserts unchanged.

Add two manual-trigger functions:

```python
def set_article_vector_status(url: str, status: str) -> None:
    """Mark a single article's vector_status manually.

    Example:
        uv run python -c "
        from src.knowledge.pipeline import set_article_vector_status
        set_article_vector_status('https://medium.com/...', 'ready')
        "
    """
    raw_store.set_vector_status(url, status)
    logger.info("Set vector_status=%r for %s", status, url)


def index_ready() -> None:
    """Index all articles with vector_status='ready' into the vector store.

    Run manually:
        uv run python -m src.knowledge.pipeline index
    """
    articles = raw_store.get_articles_by_vector_status("ready")
    logger.info("Indexing %d ready article(s) into vector store.", len(articles))
    for article in articles:
        vector_store.upsert_article(
            url=article.url,
            raw_markdown=article.raw_markdown,
            metadata={
                "title": article.title,
                "author": article.author,
                "newsletter_date": article.newsletter_date.isoformat()
                if article.newsletter_date else "",
            },
        )
        raw_store.set_vector_status(article.url, "indexed")
        logger.info("  Indexed: %s", article.url)
    logger.info("Done.")
```

Update `__main__`:
```python
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if len(sys.argv) > 1 and sys.argv[1] == "index":
        index_ready()
    else:
        run()
```

---

## `src/agent/tools.py` — changes

**`read_article`** — fetch and return content only. Remove any vector_store calls.

**New tool `index_article`** — agent calls this only after user confirms:
```python
@function_tool()
async def index_article(context: RunContext, url: str) -> str:
    """Add an article to the searchable knowledge base (vector store).

    Call this ONLY after the user explicitly confirms they want to save it
    when you asked them. Never call without asking first.

    Args:
        url: The article URL, exactly as shown in the newsletter listing.
    """
    loop = asyncio.get_event_loop()
    cached = await loop.run_in_executor(None, lambda: raw_store.get_article_by_url(url))
    if not cached or not cached.raw_markdown:
        raise ToolError(f"Article not in local store: {url}. Read it first.")
    if cached.vector_status == "indexed":
        return f"Already indexed: {cached.title or url}"

    await loop.run_in_executor(
        None,
        lambda: vector_store.upsert_article(
            url=url,
            raw_markdown=cached.raw_markdown,
            metadata={
                "title": cached.title,
                "author": cached.author,
                "newsletter_date": cached.newsletter_date.isoformat()
                if cached.newsletter_date else "",
            },
        ),
    )
    await loop.run_in_executor(None, lambda: raw_store.set_vector_status(url, "indexed"))
    return f"Indexed: {cached.title or url}"
```

Register `index_article` in the agent's tool list alongside the existing tools.

---

## `src/agent/agent.py` — system prompt

No code hooks needed. The LLM tracks conversational context and already knows which
article it just discussed. Add one instruction to `NewsletterAssistant.instructions`:

```
- After you have introduced or summarised any article, ask the user:
  "Would you like me to save this one to your knowledge base for future searches?"
  Call index_article only if they say yes.
```

**Conversation flow:**
```
Agent summarises article
  → "Would you like me to save this to your knowledge base?"
  → User: "yes"  →  agent calls index_article(url)
  → User: "no"   →  agent moves on
```

---

## Files changed

| File | Change |
|---|---|
| `src/knowledge/raw_store.py` | Add `vector_status` to CREATE TABLE; update `ArticleRow`; add `set_vector_status`, `get_articles_by_vector_status`; drop `vector_status` from ON CONFLICT UPDATE |
| `src/knowledge/fetcher.py` | Remove `vector_store` import + upsert block from `fetch_and_cache` |
| `src/knowledge/pipeline.py` | Remove `vector_store` import + upsert; add `set_article_vector_status`, `index_ready`; update `__main__` |
| `src/agent/tools.py` | Remove vector store logic from `read_article`; add `index_article` tool |
| `src/agent/agent.py` | Add indexing instruction to system prompt; register `index_article` in tool list |

## Tests to update

- `tests/knowledge/test_raw_store.py` — add tests for `set_vector_status` and `get_articles_by_vector_status`
- `tests/knowledge/test_fetcher.py` — `test_fetch_and_cache_stores_full_content` asserts `mock_vec_upsert.assert_called_once()` → change to `assert_not_called()`

## Verification

```bash
uv run poe check

# Pipeline should produce no vector store writes
uv run python -m src.knowledge.pipeline

# Manually mark one article ready, then batch index
uv run python -c "
from src.knowledge.pipeline import set_article_vector_status
set_article_vector_status('https://medium.com/...', 'ready')
"
uv run python -m src.knowledge.pipeline index
```
