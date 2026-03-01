# src/knowledge/medium.py
# Parse Medium newsletter HTML emails and fetch full article content via camoufox.

from __future__ import annotations

import asyncio
import logging
import random
import re

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import markdownify as md_lib

from bs4 import BeautifulSoup
from camoufox.async_api import AsyncCamoufox

logger = logging.getLogger(__name__)

# Known Medium-family domains (same as agent/tools.py)
_MEDIUM_DOMAINS = re.compile(
    r"^https?://(medium\.com|towardsdatascience\.com|betterprogramming\.pub"
    r"|levelup\.gitconnected\.com|pub\.towardsai\.net)"
)

_SKIP_FRAGMENTS = (
    "/m/signin",
    "/m/unsubscribe",
    "/m/global-identity",
    "medium.com/tag/",
    "medium.com/topic/",
    "medium.com/plans",
)

# Auth state
AUTH_STATE_PATH = Path("creds/medium_auth.json")
_AUTH_WARN_DAYS = 30  # warn if auth file is older than this

# Content validation: fewer chars than this is always a block/paywall page
_MIN_CONTENT_CHARS = 500
# Keywords that appear in Cloudflare challenge / Medium paywall pages
_BLOCK_MARKERS = (
    "security verification",
    "performing security verification",
    "enable javascript and cookies",
    "ray id:",
    "cloudflare",
)

# Retry / delay
_MAX_RETRIES = 2
_RETRY_BASE_DELAY = 2.0  # seconds; doubles each retry (2s, 4s)
_INTER_FETCH_DELAY = (1.0, 5.0)  # (min, max) random seconds between articles


class ScrapingError(RuntimeError):
    """Raised when valid article content could not be retrieved after all retries."""


@dataclass
class Article:
    url: str
    title: str
    author: str = ""
    snippet: str = ""
    # Extra metadata extracted from the email
    tags: list[str] = field(default_factory=list)


def parse_newsletter_email(html_body: str) -> list[Article]:
    """Extract article cards from a Medium newsletter HTML body.

    Returns deduplicated Article objects (URL is the dedup key), capped at 20.
    """
    soup = BeautifulSoup(html_body, "html.parser")
    articles: list[Article] = []
    seen: set[str] = set()

    for a_tag in soup.find_all("a", href=True):
        url: str = a_tag["href"]

        if not _MEDIUM_DOMAINS.match(url):
            continue
        if any(frag in url for frag in _SKIP_FRAGMENTS):
            continue

        clean_url = url.split("?")[0].rstrip("/")
        if clean_url in seen:
            continue
        seen.add(clean_url)

        # Derive title: prefer text of the link; walk up if too short
        title = a_tag.get_text(" ", strip=True)
        if len(title) < 12:
            for parent in a_tag.parents:
                candidate = parent.get_text(" ", strip=True)
                if 12 < len(candidate) < 250:
                    title = candidate
                    break

        # Try to find an author near the link (heuristic: next sibling text)
        author = ""
        parent = a_tag.find_parent()
        if parent:
            siblings = list(parent.next_siblings)
            for sib in siblings[:3]:
                text = (
                    sib.get_text(strip=True)
                    if hasattr(sib, "get_text")
                    else str(sib).strip()
                )
                if text and len(text) < 80:
                    author = text
                    break

        articles.append(Article(url=clean_url, title=title[:200], author=author[:100]))
        if len(articles) == 20:
            break

    return articles


def check_auth_state(path: Path = AUTH_STATE_PATH) -> None:
    """Log warnings if the auth state file is missing or getting stale."""
    if not path.exists():
        logger.warning(
            "Medium auth state not found at %s — fetching anonymously. "
            "Run scripts/medium_login.py to enable authenticated access.",
            path,
        )
        return

    age_days = (datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)).days
    if age_days > _AUTH_WARN_DAYS:
        logger.warning(
            "Medium auth state is %d days old (threshold: %d days). "
            "Consider re-running scripts/medium_login.py to refresh cookies.",
            age_days,
            _AUTH_WARN_DAYS,
        )


def _html_to_markdown(html: str) -> str:
    """Extract the article body from raw page HTML and convert to markdown."""
    soup = BeautifulSoup(html, "html.parser")
    article = soup.find("article")
    if not article:
        article = soup.find("main") or soup.find("section") or soup.body
    if not article:
        return ""
    for tag in article.find_all(["nav", "footer", "script", "style", "aside"]):
        tag.decompose()
    return md_lib.markdownify(str(article), heading_style="ATX", strip=["img"])


def _is_valid_content(md: str) -> bool:
    """Return True if markdown looks like a real article (not a Cloudflare or paywall block)."""
    if len(md.strip()) < _MIN_CONTENT_CHARS:
        return False
    lower = md.lower()
    return not any(marker in lower for marker in _BLOCK_MARKERS)


async def _fetch_one(page, url: str) -> str:
    """Fetch a single URL and return markdown, retrying with backoff on bad content.

    Raises ScrapingError if all attempts fail.
    """
    for attempt in range(_MAX_RETRIES + 1):
        if attempt > 0:
            delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
            logger.warning(
                "Retry %d/%d for %s (backoff %.1fs)", attempt, _MAX_RETRIES, url, delay
            )
            await asyncio.sleep(delay)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            try:
                await page.wait_for_selector("article", timeout=10_000)
            except Exception:
                pass  # continue with whatever is on the page

            md = _html_to_markdown(await page.content())
            if _is_valid_content(md):
                return md

            logger.warning(
                "Content validation failed for %s (attempt %d/%d): %d chars"
                " — likely Cloudflare challenge or paywall",
                url,
                attempt + 1,
                _MAX_RETRIES + 1,
                len(md.strip()),
            )
        except Exception as exc:
            logger.warning(
                "Fetch error for %s (attempt %d/%d): %s",
                url,
                attempt + 1,
                _MAX_RETRIES + 1,
                exc,
            )

    raise ScrapingError(
        f"Could not retrieve valid content from {url} after {_MAX_RETRIES + 1} attempts"
    )


async def fetch_articles_async(
    urls: list[str],
    auth_state: Path = AUTH_STATE_PATH,
) -> dict[str, str]:
    """Fetch multiple articles in a single browser session.

    Opens one camoufox browser, fetches each URL with a random human-like delay,
    retries with exponential backoff on validation failures.

    Returns a dict mapping url → markdown (empty string on unrecoverable failure).
    """
    check_auth_state(auth_state)
    ctx_kwargs: dict = {}
    if auth_state.exists():
        ctx_kwargs["storage_state"] = str(auth_state)

    results: dict[str, str] = {}

    async with AsyncCamoufox(headless=True) as browser:
        context = await browser.new_context(**ctx_kwargs)
        page = await context.new_page()

        for i, url in enumerate(urls):
            if i > 0:
                delay = random.uniform(*_INTER_FETCH_DELAY)
                logger.debug("Waiting %.1fs before next article", delay)
                await asyncio.sleep(delay)

            try:
                results[url] = await _fetch_one(page, url)
                logger.info("Fetched %s (%d chars)", url, len(results[url]))
            except ScrapingError as exc:
                logger.error("%s", exc)
                results[url] = ""

    return results


def fetch_articles(
    urls: list[str],
    auth_state: Path = AUTH_STATE_PATH,
) -> dict[str, str]:
    """Synchronous wrapper around fetch_articles_async.

    Safe to call from synchronous pipeline code.
    """
    return asyncio.run(fetch_articles_async(urls, auth_state))
