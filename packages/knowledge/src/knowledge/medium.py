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
from urllib.parse import urlparse

import markdownify as md_lib

from bs4 import BeautifulSoup
from camoufox.async_api import AsyncCamoufox

logger = logging.getLogger(__name__)

# Matches Medium article URLs: known domain + path ending with -<hex_id> (8–12 hex chars).
# Profile pages (/m/signin, /@user), publication homepages, and tag pages don't carry
# a hex suffix and are therefore excluded automatically.
_ARTICLE_URL_RE = re.compile(
    r"^https?://(?:medium\.com|towardsdatascience\.com|betterprogramming\.pub"
    r"|levelup\.gitconnected\.com|pub\.towardsai\.net)"
    r"/\S+-[a-f0-9]{8,12}$"
)
# Medium internal/editorial paths that match _ARTICLE_URL_RE but aren't user articles.
_EXCLUDED_PATH_PREFIXES = ("/jobs-at-medium/",)

# Auth state
AUTH_STATE_PATH = Path("creds/medium_auth.json")
_AUTH_WARN_DAYS = 30  # warn if auth file is older than this

# Content validation: fewer chars than this is always a block/paywall page
_MIN_CONTENT_CHARS = 500
# Keywords that appear in Cloudflare challenge or Medium paywall pages
_BLOCK_MARKERS = (
    "security verification",
    "performing security verification",
    "enable javascript and cookies",
    "ray id:",
    "cloudflare",
    # Medium paywall markers
    "this story is only available to medium members",
    "become a member to read this story",
    "read the rest of this story with a free account",
    "get access to this story",
    "create an account to read the full story",
)

# Warn if a newsletter email yields fewer than this many articles — likely
# indicates Medium changed their email format or _ARTICLE_URL_RE needs updating.
_MIN_EXPECTED_ARTICLES = 10

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


def parse_medium_newsletter(html_body: str) -> list[Article]:
    """Extract article cards from a Medium newsletter HTML body.

    Article URLs are identified by the hex article ID suffix (-[a-f0-9]{8,12}),
    which is present on every Medium article URL but absent on profile pages,
    publication homepages, sign-in links, and other non-article paths.

    Medium emails link to each article from multiple <a> tags (thumbnail image,
    title, and "Read more" button). We group all tags by URL and pick the one
    that contains an <h2> title — usually the second link in each card.

    Returns deduplicated Article objects (URL is the dedup key), capped at 20.
    """
    soup = BeautifulSoup(html_body, "html.parser")

    # Pass 1: collect all matching <a> tags grouped by clean URL, preserving order.
    url_order: list[str] = []
    url_tags: dict[str, list] = {}
    for a_tag in soup.find_all("a", href=True):
        raw_url: str = str(a_tag["href"])
        clean_url = raw_url.split("?")[0].rstrip("/")
        if not _ARTICLE_URL_RE.match(clean_url):
            continue
        # Skip Medium internal/editorial pages
        path = urlparse(clean_url).path
        if any(path.startswith(prefix) for prefix in _EXCLUDED_PATH_PREFIXES):
            continue
        if clean_url not in url_tags:
            url_order.append(clean_url)
            url_tags[clean_url] = []
        url_tags[clean_url].append(a_tag)

    # Pass 2: for each URL pick the <a> tag with the best title and extract author.
    articles: list[Article] = []
    for clean_url in url_order:
        title = ""
        snippet = ""
        author = ""
        for a_tag in url_tags[clean_url]:
            h2 = a_tag.find("h2")
            candidate = (
                h2.get_text(" ", strip=True) if h2 else a_tag.get_text(" ", strip=True)
            )
            if candidate:
                title = candidate
                h3 = a_tag.find("h3")
                snippet = h3.get_text(" ", strip=True) if h3 else ""
                break

        # Extract author from the card container that holds this article.
        # Walk up from the first <a> tag to find the enclosing card div,
        # then look for author profile links (href containing "/@").
        if not author and url_tags[clean_url]:
            card = url_tags[clean_url][0]
            for _ in range(10):  # walk up at most 10 levels
                card = card.parent
                if card is None:
                    break
                # Card containers have author profile links alongside article links
                # Match profile-only links: /@username followed by ? or end,
                # but NOT /@username/article-slug (which would be an article link).
                # Multiple <a> tags may link to the same profile (avatar img + name text);
                # pick the first one that has visible text.
                _profile_re = re.compile(r"https?://medium\.com/@[^/?]+(?:\?|$)")
                for author_link in card.find_all("a", href=_profile_re):
                    name = author_link.get_text(" ", strip=True).strip()
                    if name:
                        author = name
                        break
                if author:
                    break

        articles.append(
            Article(
                url=clean_url,
                title=title[:200],
                author=author[:100],
                snippet=snippet[:500],
            )
        )
        if len(articles) == 20:
            break

    if 0 < len(articles) < _MIN_EXPECTED_ARTICLES:
        logger.warning(
            "Only %d article(s) parsed from newsletter email (expected %d+). "
            "Medium may have changed their email format — check _ARTICLE_URL_RE.",
            len(articles),
            _MIN_EXPECTED_ARTICLES,
        )

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
        context = await browser.new_context(**ctx_kwargs)  # type: ignore[union-attr]
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
