# Tiered Article Fetcher — Plan

## Problem recap

Current pipeline calls `medium.fetch_articles(all_urls)` which opens one
camoufox browser session and fetches up to 20 articles sequentially — same
fingerprint, same IP, many requests. Cloudflare recognises this pattern and
blocks the session, storing only email snippets (1–2 sentences) instead of
full article content.

---

## All approaches considered

| Approach | Type | Free limit | Handles paywall | Browser |
|---|---|---|---|---|
| Jina Reader | HTTP API | 20 RPM | ✗ (no auth) | No |
| Jina + Medium cookie forwarded | HTTP API | 20 RPM | Maybe | No |
| Wayback Machine | HTTP | Unlimited | Sometimes | No |
| Diffbot | HTTP API | 10,000/month | Yes (own infra) | No |
| Firecrawl | HTTP API | 500 one-time | Yes | No |
| Medium GraphQL API (internal) | HTTP | Unlimited* | Yes (with auth) | No |
| mediumapi.com (RapidAPI) | HTTP API | 150/month | Yes | No |
| Steel.dev / Browserless | Remote browser | 10 hr/month | Yes (with cookies) | Remote |
| camoufox local (batched) | Local browser | Unlimited | Yes (with cookies) | Local |
| RSS feed | HTTP | Unlimited | ✗ (truncated) | No |
| Trafilatura | Python library | N/A | N/A (extraction only) | No |

**Not carried forward:**
- **RSS** — Medium RSS is always truncated for member articles, same as Jina without auth.
- **Wayback Machine** — low hit rate (~20-30%), stale content, unreliable as a tier.
- **Medium GraphQL API** — undocumented, could break at any deploy, arguably ToS-violating.
- **Firecrawl** — 500 one-time credits (not monthly), burns out quickly in a daily pipeline.
- **Steel.dev / Browserless** — adds remote dependency; local camoufox already works when not rate-limited, and is simpler.

**mediumapi.com — reconsidered as Tier 2 alternative to Diffbot:**
150/month looks weak in isolation, but Tier 2 only fires on articles Jina
fails (paywalled). If Jina handles ~50% of articles (public ones), mediumapi.com
only sees ~75 calls/month — well within the free tier. Additionally, RapidAPI
returns quota headers on every response (`x-ratelimit-requests-remaining`),
eliminating the need for a custom budget counter. No work email required for
signup. See Tier 2 section for both options.

**Trafilatura** is worth adopting regardless of fetch tier — it replaces the
current `BeautifulSoup + markdownify` extraction in `_html_to_markdown()` with
a more accurate article body detector.

---

## Proposed solution: three-tier fetcher

```
Tier 1 — Jina Reader           fast, no browser, free (20 RPM)
    ↓ fails (short/paywalled)
Tier 2 — mediumapi.com          no browser, handles paywall, 150/month free
       or Diffbot               no browser, handles paywall, 10k/month (work email required)
    ↓ fails or quota exhausted
Tier 3 — camoufox               local browser, uses saved auth cookies, batched (3/session)
```

The key shift: camoufox moves from primary to last resort. Most public articles
are handled by Jina. Paywalled articles go to Tier 2 (mediumapi.com or Diffbot)
before touching a browser.

**Tier 2 recommendation:** mediumapi.com (RapidAPI) unless you have a work email
for Diffbot. The 150/month limit is workable given Tier 1 handles public articles
first, and RapidAPI's built-in quota headers (`x-ratelimit-requests-remaining`)
mean no custom budget tracking code is needed.

---

## Comments on each tier

### Tier 1 — Jina Reader (`https://r.jina.ai/<url>`)

**How it works:** `GET https://r.jina.ai/https://medium.com/...` returns the
page as clean markdown. Internally Jina runs a headless browser with its own
bot-bypass, but that's their problem, not ours. We just make an HTTP call.

**Free tier:** 20 RPM — more than enough for a daily newsletter pipeline that
processes ~20 articles/day total (much less than 1/min average).

**Authentication:** An API key (`Authorization: Bearer <token>`) unlocks higher
rate limits and better content quality. Not required for the free tier.

**Paywall concern:** Jina doesn't have your Medium cookies. Member-only articles
return the same truncated preview a logged-out reader would see. This will fail
`_is_valid_content()` if the preview is short, but some previews are long enough
to pass the length check while still missing the article body.

**Fix:** Extend `_is_valid_content()` to detect Medium's paywall strings:
```python
_PAYWALL_MARKERS = (
    "this story is only available to medium members",
    "become a member to read this story",
    "read the rest of this story with a free account",
)
```

**Jina-specific headers worth setting:**
- `X-Return-Format: markdown` — explicitly request markdown output
- `X-Timeout: 20` — don't wait forever

---

### Tier 2 — mediumapi.com (RapidAPI) *(recommended for personal use)*

**How it works:** Unofficial scraping API on RapidAPI. Handles Medium member
auth internally — returns full article content for paywalled posts.

```
GET https://medium2.p.rapidapi.com/article/{article_id}/content
Headers: X-RapidAPI-Key: <key>
```

**Free tier:** 150 requests/month. Workable because Tier 1 (Jina) handles all
public articles first — Tier 2 only fires for paywalled ones. At 5 articles/day
with ~50% paywalled, that's ~75 calls/month.

**Budget tracking — built in via RapidAPI headers:**
Every response includes quota headers — no custom counter needed:
```python
remaining = int(resp.headers.get("x-ratelimit-requests-remaining", 0))
if remaining < 10:
    logger.warning("RapidAPI quota low (%d left) — falling to camoufox", remaining)
    return ""
```

**Signup:** Standard email, no work email required.

**Extracting article ID from URL:**
```python
import re
def _medium_article_id(url: str) -> str | None:
    m = re.search(r"-([a-f0-9]{8,12})$", url.rstrip("/").split("?")[0])
    return m.group(1) if m else None
```

---

### Tier 2 alternative — Diffbot (`https://api.diffbot.com/v3/article`)

**How it works:** Structured article extraction API with its own crawling
infrastructure. Has been handling paywalls reliably since 2012.

```
GET https://api.diffbot.com/v3/article?url=<url>&token=<key>
```

Returns `text` (plain text) and `html` fields — requires a conversion step to
markdown (Trafilatura or markdownify).

**Free tier:** 10,000 requests/month — far more headroom than mediumapi.com.

**Budget tracking:** Requires a custom `data/api_usage.json` counter (no
equivalent of RapidAPI's response headers).

**⚠ Signup requires a work/organisation email.** Not suitable for personal
use without one. Prefer mediumapi.com unless you have access.

---

### Tier 3 — camoufox (batched)

Moves from primary to fallback — only fires when both Jina and Medium API fail.
In practice this will be: articles where Medium API budget is exhausted, or
unusual domains (betterprogramming.pub, levelup.gitconnected.com) that the API
doesn't handle.

**Key change from current:** fetch in batches of 3 articles per browser
instance, with a 30–60s gap between browser restarts. This limits fingerprint
correlation.

```
[browser A] → article 1, 2, 3 → close
  sleep 30–60s (randomised)
[browser B] → article 4, 5, 6 → close
  ...
```

Config: `CAMOUFOX_BATCH_SIZE = 3`, `CAMOUFOX_INTER_BATCH_DELAY = (30, 60)`.

---

## Other pipeline fixes (from previous review)

These apply regardless of which fetch tier is used:

### Cap articles per email

Don't process all 20 articles from one email. Add `max_articles_per_email` to
`newsletters.yaml` per newsletter (default: 5). The agent can always call
`read_article` on-demand for the rest.

```yaml
medium:
  label: Medium Daily Digest
  query: 'from:noreply@medium.com "Medium Daily Digest"'
  is_medium: true
  max_articles: 5      # new field
```

### Skip articles already in raw_store

Before fetching, check if a full-content version already exists:
```python
urls_to_fetch = [
    a.url for a in articles
    if not raw_store.get_article_by_url(a.url)
]
```

### Log snippet fallbacks explicitly

```python
if not content or len(content) < 500:
    logger.warning("Stored snippet-only for %s (%d chars)", article.url, len(content))
```

### Pre-flight auth check

Call `medium.check_auth_state()` once before the email loop, not buried inside
the browser session.

### Add `newer_than` to pipeline query

Prevent pulling old emails on first run. Default: `newer_than:30d`.

---

## New module: `src/knowledge/fetcher.py`

Extract the tiered fetch logic out of `pipeline.py` and `medium.py` into a
dedicated module. This keeps each file focused:

| File | Responsibility |
|---|---|
| `fetcher.py` | Tier orchestration: Jina → mediumapi.com → camoufox |
| `medium.py` | camoufox browser implementation (Tier 3 only) |
| `pipeline.py` | Email loop, dedup, storage — calls `fetcher.fetch_article()` |

### Public interface

```python
# src/knowledge/fetcher.py

def fetch_article(url: str) -> str:
    """Fetch full article markdown using the cheapest available tier.

    Returns empty string if all tiers fail.
    Tiers: Jina Reader → mediumapi.com (RapidAPI) → camoufox (batched fallback).
    """
```

The pipeline calls this once per article:
```python
for article in articles[:max_articles]:
    if raw_store.get_article_by_url(article.url):
        continue  # already have full content
    content = fetcher.fetch_article(article.url) or article.snippet
    ...
```

### Extraction: swap `markdownify` for `trafilatura`

Regardless of which fetch tier returns the HTML, replace the current
`_html_to_markdown()` with Trafilatura for better article body detection:

```python
import trafilatura

def _html_to_markdown(html: str) -> str:
    result = trafilatura.extract(html, output_format="markdown", include_comments=False)
    return result or ""
```

Trafilatura is more accurate at stripping nav/footer/ads and isolating the
main article body compared to the current BeautifulSoup heuristic. Add to
`pyproject.toml` dependencies.

---

## Config additions

`config/newsletters.yaml` — add `max_articles` per newsletter.

`.env` / `src/core/config.py` — add:
```python
jina_api_key: str = ""               # optional, unlocks higher RPM
rapidapi_key: str = ""               # required for mediumapi.com (Tier 2)
# No custom budget counter needed — read x-ratelimit-requests-remaining header
```

If using Diffbot instead, replace `rapidapi_key` with:
```python
diffbot_api_key: str = ""
# Also add data/api_usage.json counter (RapidAPI headers not available)
```

---

## Implementation steps

| Step | Task | Effort |
|---|---|---|
| 1 | Add `trafilatura` dep; swap `_html_to_markdown()` in `medium.py` | 30 min |
| 2 | Extend `_is_valid_content()` with paywall markers | 15 min |
| 3 | Write `_fetch_via_jina(url)` in `fetcher.py` | 1 hr |
| 4 | Write `_fetch_via_mediumapi(url)` — read quota from response headers | 1 hr |
| 5 | Refactor camoufox into `_fetch_via_camoufox(urls)` with batch-restart | 1 hr |
| 6 | Wire tiers into `fetcher.fetch_article()` | 30 min |
| 7 | Update `pipeline.py`: cap, skip-if-exists, pre-flight auth, newer_than | 1 hr |
| 8 | Add config fields to `config.py` and `.env.example` | 15 min |
| 9 | Update `newsletters.yaml` with `max_articles` field | 15 min |
| 10 | Write tests for each tier (mock HTTP/browser) | 2 hr |

**Total: ~8 hours.**

---

## Open questions

1. **Jina + Medium cookie forwarding?** Jina supports a `Cookie` request header.
   Forwarding the Medium session cookie from `medium_auth.json` might make Jina
   work for member-only articles, potentially eliminating the need for Tier 2
   entirely. Worth a quick manual test before building the full Diffbot tier.

2. **Jina API key?** A free Jina account unlocks higher rate limits. Worth
   registering before the first production run.

3. **Diffbot paywall coverage?** Diffbot handles many paywalled sites but Medium
   member content is not guaranteed. Validate on a known paywalled article
   before relying on it as Tier 2.

4. **Trafilatura vs markdownify quality?** Run both on a sample article and
   compare output — trafilatura is generally better at body isolation but
   markdownify preserves more formatting structure. Choose based on what produces
   better semantic search embeddings.
