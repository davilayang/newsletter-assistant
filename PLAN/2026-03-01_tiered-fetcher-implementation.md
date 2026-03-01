# Tiered Fetcher — Implementation Plan

## Context

The current pipeline opens one camoufox browser for up to 20 articles
sequentially — same fingerprint, same IP. Cloudflare blocks it. Failed fetches
silently fall back to email snippets stored permanently with no recovery path.

The agent's `read_article` tool also fetches live articles but throws the result
away — nothing is persisted, so the pipeline re-fetches the same URLs later.

This plan: a tiered fetcher in `src/knowledge/fetcher.py`, shared by both the
pipeline and the agent, that tries the cheapest approach first, persists every
successful fetch, and tracks failures for future retry.

---

## Tier Flow

```
Tier 1 — Jina Reader         plain HTTP GET, returns markdown, free 20 RPM
    ↓ empty / paywall / cloudflare marker
Tier 2 — mediumapi.com        RapidAPI, handles paywall, 150/month free
    ↓ quota ≤ 0 / ID not extractable / content invalid
Tier 3 — camoufox (batched)   local browser + auth, 3 URLs/session, 30–60s between batches
    ↓ all fail
         store snippet, scrape_status = 'snippet_only'
```

---

## Shared by agent and pipeline

`fetcher.py` lives in `src/knowledge/` — already importable by both
`pipeline.py` and `tools.py` (tools.py already imports raw_store, vector_store,
medium from `src/knowledge/`).

**Key principle:** any article fetched anywhere is immediately stored in
raw_store + vector_store. Neither the pipeline nor the agent will ever re-fetch
a URL that already has full content in the DB.

---

## Files to Create

### `src/knowledge/fetcher.py`

```python
def fetch_articles(urls: list[str]) -> dict[str, str]:
    """Tiered fetch for a batch of URLs. Returns url → markdown."""

def fetch_and_cache(
    url: str,
    title: str = "",
    author: str = "",
    newsletter_date: date | None = None,
) -> str:
    """Fetch one article, persist to raw_store + vector_store, return markdown.
    Used by agent's read_article so live fetches are not thrown away.
    Returns empty string if all tiers fail.
    """
```

Internal private functions:
- `_fetch_via_jina(url: str) -> str`
- `_fetch_via_mediumapi(url: str) -> str`  — skips if no `rapidapi_key` or ID unextractable
- `_fetch_via_camoufox_batched(urls: list[str]) -> dict[str, str]`  — calls `medium.fetch_articles_async(batch)` per chunk of 3

`fetch_articles()` internal flow:
```
for url in urls:        → try Jina       → ok: result[url]; fail: tier2_needed
for url in tier2_needed: → try mediumapi  → ok: result[url]; fail: tier3_needed
tier3_needed:            → camoufox batch → result.update(...)
```

Content validation with `medium._is_valid_content()` gates all three tiers.
HTTP errors (429, 4xx, 5xx, timeout) all skip the tier without retry.

---

## Files to Modify

### `src/knowledge/medium.py`

Add paywall markers to `_BLOCK_MARKERS`:
```python
_BLOCK_MARKERS = (
    "security verification",
    "performing security verification",
    "enable javascript and cookies",
    "ray id:",
    "cloudflare",
    # Medium paywall
    "this story is only available to medium members",
    "become a member to read this story",
    "read the rest of this story with a free account",
    "get access to this story",
)
```

No changes to `fetch_articles_async()` — calling it with a 3-URL list naturally
creates a new browser per batch.

### `src/knowledge/raw_store.py`

Add `scrape_status TEXT DEFAULT 'full'` column.

Values: `'full'` | `'snippet_only'`

Migration (safe, runs at module init):
```python
# In _init_db():
cols = {row[1] for row in conn.execute("PRAGMA table_info(articles)")}
if "scrape_status" not in cols:
    conn.execute("ALTER TABLE articles ADD COLUMN scrape_status TEXT DEFAULT 'full'")
```

Update `upsert_article()` signature to accept `scrape_status: str = "full"`.

Add:
```python
def get_articles_by_status(status: str, ...) -> list[ArticleRow]:
    """Return articles with given scrape_status. Enables retry runs."""
```

### `src/knowledge/pipeline.py`

- Call `medium.check_auth_state()` once before the email loop
- Append `newer_than:30d` to query
- Skip articles where `raw_store.get_article_by_url(url)` already has content ≥ 500 chars
- Cap articles per email: `cfg.get("max_articles", 5)`
- Replace `medium.fetch_articles()` with `fetcher.fetch_articles()`
- Pass `scrape_status='full'` or `'snippet_only'` to `raw_store.upsert_article()`
- Log explicitly when snippet fallback is used

### `src/agent/tools.py`

Replace `read_article` live-fetch with `fetcher.fetch_and_cache()`:
```python
# Before — fetches but discards:
results = await loop.run_in_executor(None, lambda: medium.fetch_articles([url]))
content = results.get(url, "")

# After — fetches and persists:
content = await loop.run_in_executor(None, fetcher.fetch_and_cache, url)
```

The raw_store cache-check at the top of `read_article` stays — `fetch_and_cache`
only fires when content isn't already in the DB.

### `src/core/config.py`

```python
jina_api_key: str = ""      # optional — unlocks higher RPM
rapidapi_key: str = ""      # required for Tier 2 (mediumapi.com)
```

### `config/newsletters.yaml`

Add `max_articles: 5` to the `medium` entry (the only `is_medium: true` entry).

---

## mediumapi.com Details

Article ID extraction (required for the API call):
```python
def _medium_article_id(url: str) -> str | None:
    m = re.search(r"-([a-f0-9]{8,12})$", url.rstrip("/").split("?")[0])
    return m.group(1) if m else None
```
Returns `None` for unusual URLs → Tier 2 skipped, goes straight to Tier 3.

Quota check from response headers — no custom counter needed:
```python
remaining = int(resp.headers.get("x-ratelimit-requests-remaining", 99))
if remaining == 0:
    return ""   # skip before calling
# After response:
if remaining <= 10:
    logger.warning("RapidAPI quota low: %d remaining this month", remaining)
```

Response format: JSON with `content` field (likely HTML). Apply
`medium._html_to_markdown()` if content starts with `<`, else use as-is.

---

## Documentation

Create `docs/article-fetching.md`:
- Three tiers explained, free tier limits, what each handles
- Required vs optional API keys
- Sign-up links (Jina: standard email; mediumapi.com: via rapidapi.com)
- How to refresh Medium auth cookies (`scripts/medium_login.py`)
- How `scrape_status` works and how to retry snippet-only articles

---

## Implementation Steps

| # | File | Change |
|---|---|---|
| 1 | `medium.py` | Add paywall markers to `_BLOCK_MARKERS` |
| 2 | `raw_store.py` | Add `scrape_status` column, migration, `get_articles_by_status()`, update `upsert_article()` |
| 3 | `config.py` | Add `jina_api_key`, `rapidapi_key` |
| 4 | `fetcher.py` | Create module with all tiers + `fetch_articles` + `fetch_and_cache` |
| 5 | `pipeline.py` | Use `fetcher.fetch_articles()`, all 4 pipeline fixes, `scrape_status` |
| 6 | `tools.py` | Update `read_article` to use `fetcher.fetch_and_cache()` |
| 7 | `newsletters.yaml` | Add `max_articles: 5` to medium entry |
| 8 | `.env.example` | Add `JINA_API_KEY`, `RAPIDAPI_KEY` |
| 9 | `tests/knowledge/test_fetcher.py` | Unit tests: each tier pass/fail, escalation, quota exhausted |
| 10 | `docs/article-fetching.md` | API and setup documentation |

---

## Verification

```bash
uv run poe check          # fmt + lint + mypy + tests must all pass

# Smoke test tiered fetch (Jina only, no API keys needed for public article)
uv run python -c "
from src.knowledge.fetcher import fetch_articles
r = fetch_articles(['https://towardsdatascience.com/<any-public-slug>'])
print(list(r.values())[0][:200])
"

# Verify pipeline runs without error
uv run poe pipeline
```
