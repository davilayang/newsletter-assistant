# src/knowledge/fetcher.py
# Tiered article fetcher: Jina Reader → mediumapi.com → camoufox (batched).
#
# Shared by both the pipeline and the agent so every successful fetch is
# persisted to raw_store + vector_store immediately, avoiding duplicate work.

from __future__ import annotations

import logging
import re

from datetime import date

import httpx

from src.core.config import settings
from src.knowledge import medium, raw_store, vector_store

logger = logging.getLogger(__name__)

# Camoufox batch configuration
_CAMOUFOX_BATCH_SIZE = 3

# Jina Reader base URL, see https://jina.ai/reader/
_JINA_BASE = "https://r.jina.ai/"

# mediumapi.com markdown endpoint — returns {"id": "...", "markdown": "..."}
# see https://rapidapi.com/nishujain199719-vgIfuFHZxVZ/api/medium2
_MEDIUMAPI_URL = "https://medium2.p.rapidapi.com/article/{article_id}/markdown"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _medium_article_id(url: str) -> str | None:
    """Extract the hex article ID from a Medium URL.

    Works for URLs ending in '-<hex_id>' (8–12 hex chars).
    Returns None for unusual URL formats — Tier 2 is skipped in that case.
    """
    clean = url.rstrip("/").split("?")[0]
    m = re.search(r"-([a-f0-9]{8,12})$", clean)
    return m.group(1) if m else None


def _fetch_via_jina(url: str) -> str:
    """Tier 1: fetch via Jina Reader (plain HTTP, returns markdown).
    Reference:
      - https://jina.ai/reader/
      - https://github.com/jina-ai/reader

    Returns empty string on any error or invalid content.
    """
    headers: dict[str, str] = {
        "X-Return-Format": "markdown",
        "X-Timeout": "20",
    }
    if settings.jina_api_key:
        headers["Authorization"] = f"Bearer {settings.jina_api_key}"

    try:
        resp = httpx.get(
            f"{_JINA_BASE}{url}",
            headers=headers,
            timeout=25,
            follow_redirects=True,
        )
        if resp.status_code == 429:
            logger.warning("Jina rate-limited (429) for %s — skipping tier", url)
            return ""
        if resp.status_code >= 400:
            logger.warning("Jina HTTP %d for %s — skipping tier", resp.status_code, url)
            return ""
        content = resp.text
        if medium._is_valid_content(content):
            return content
        logger.debug(
            "Jina content invalid for %s (%d chars)", url, len(content.strip())
        )
        return ""
    except httpx.TimeoutException:
        logger.warning("Jina timeout for %s — skipping Tier 1", url)
        return ""
    except Exception as exc:
        logger.warning("Jina error for %s: %s", url, exc)
        return ""


def _fetch_via_mediumapi(url: str) -> str:
    """Tier 2: fetch via mediumapi.com (RapidAPI), handles Medium paywall.
    Reference:
      - https://mediumapi.com/
      - https://rapidapi.com/nishujain199719-vgIfuFHZxVZ/api/medium2

    Skipped if:
    - Article ID cannot be extracted from URL
    - Quota is exhausted (x-ratelimit-requests-remaining == 0)

    Returns empty string on any error or invalid content.
    """
    if not settings.rapidapi_key:
        raise ValueError("RAPIDAPI_KEY is not configured")

    article_id = _medium_article_id(url)
    if article_id is None:
        logger.debug("Cannot extract article ID from %s — skipping Tier 2", url)
        return ""

    endpoint = _MEDIUMAPI_URL.format(article_id=article_id)
    headers = {
        "X-RapidAPI-Key": settings.rapidapi_key,
        "X-RapidAPI-Host": "medium2.p.rapidapi.com",
    }

    try:
        resp = httpx.get(endpoint, headers=headers, timeout=20)

        # Check quota from response headers (works even on error responses)
        remaining = int(resp.headers.get("x-ratelimit-requests-remaining", 99))
        if remaining <= 10:
            logger.warning(
                "RapidAPI quota low: %d requests remaining this month", remaining
            )
        if remaining == 0:
            logger.warning("RapidAPI quota exhausted — skipping Tier 2 for %s", url)
            return ""

        if resp.status_code == 429:
            logger.warning("mediumapi rate-limited (429) for %s — skipping tier", url)
            return ""
        if resp.status_code >= 400:
            logger.warning(
                "mediumapi HTTP %d for %s — skipping tier", resp.status_code, url
            )
            return ""

        data = resp.json()
        content: str = data.get("markdown") or ""
        if not content:
            logger.debug("mediumapi returned empty markdown for %s", url)
            return ""

        if medium._is_valid_content(content):
            return content
        logger.debug(
            "mediumapi content invalid for %s (%d chars)", url, len(content.strip())
        )
        return ""
    except httpx.TimeoutException:
        logger.warning("mediumapi timeout for %s — skipping tier", url)
        return ""
    except Exception as exc:
        logger.warning("mediumapi error for %s: %s", url, exc)
        return ""


def _fetch_via_camoufox_batched(urls: list[str]) -> dict[str, str]:
    """Tier 3: fetch via camoufox in batches of _CAMOUFOX_BATCH_SIZE.

    Each batch opens a new browser instance (natural fingerprint rotation).
    Returns url → markdown (empty string for failed URLs).
    """
    results: dict[str, str] = {}
    batches = [
        urls[i : i + _CAMOUFOX_BATCH_SIZE]
        for i in range(0, len(urls), _CAMOUFOX_BATCH_SIZE)
    ]
    for batch in batches:
        logger.info("camoufox: fetching batch of %d URL(s)", len(batch))
        batch_results = medium.fetch_articles(batch)
        results.update(batch_results)
    return results


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


def fetch_articles(urls: list[str]) -> dict[str, str]:
    """Tiered fetch for a batch of URLs. Returns url → markdown.

    Tries tiers in order: Jina Reader → mediumapi.com → camoufox (batched).
    Empty string is returned for any URL where all tiers fail.
    """
    results: dict[str, str] = {}
    tier2_needed: list[str] = []

    # Tier 1: Jina
    for url in urls:
        content = _fetch_via_jina(url)
        if content:
            logger.info("Tier 1 (Jina) success: %s (%d chars)", url, len(content))
            results[url] = content
        else:
            tier2_needed.append(url)

    # Tier 2: mediumapi.com
    tier3_needed: list[str] = []
    for url in tier2_needed:
        content = _fetch_via_mediumapi(url)
        if content:
            logger.info("Tier 2 (mediumapi) success: %s (%d chars)", url, len(content))
            results[url] = content
        else:
            tier3_needed.append(url)

    # Tier 3: camoufox batched
    if tier3_needed:
        logger.info("Tier 3 (camoufox): %d URL(s) remaining", len(tier3_needed))
        camoufox_results = _fetch_via_camoufox_batched(tier3_needed)
        results.update(camoufox_results)

    return results


def fetch_and_cache(
    url: str,
    title: str = "",
    author: str = "",
    newsletter_date: date | None = None,
) -> str:
    """Fetch one article, persist to raw_store + vector_store, return markdown.

    Used by the agent's read_article tool so live fetches are not thrown away.
    Returns empty string if all tiers fail.
    """
    content_map = fetch_articles([url])
    content = content_map.get(url, "")

    if content:
        scrape_status = "full"
    else:
        logger.warning("All tiers failed for %s — content unavailable", url)
        scrape_status = "snippet_only"

    raw_store.upsert_article(
        url=url,
        title=title,
        author=author,
        newsletter_date=newsletter_date,
        raw_markdown=content,
        scrape_status=scrape_status,
    )

    if content:
        vector_store.upsert_article(
            url=url,
            raw_markdown=content,
            metadata={
                "title": title,
                "author": author,
                "newsletter_date": newsletter_date.isoformat()
                if newsletter_date
                else "",
            },
        )

    return content
