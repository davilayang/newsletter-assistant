# src/agent/tools.py
# Function tool definitions for the NewsletterAssistant agent.

import asyncio
import re

from pathlib import Path

import yaml

from bs4 import BeautifulSoup
from livekit.agents import RunContext, ToolError, function_tool

from src.core.gmail import ops as gmail_ops
from src.core.notes import save_note as _save_note
from src.knowledge import medium, raw_store, vector_store

# Truncate fetched article content to this length before passing to the LLM,
# to keep context usage predictable.
_MAX_ARTICLE_CHARS = 12_000

_NEWSLETTERS_PATH = Path(__file__).parents[2] / "newsletters.yaml"


def _load_newsletters() -> dict[str, dict]:
    """Load newsletter registry from newsletters.yaml."""
    with _NEWSLETTERS_PATH.open() as f:
        return yaml.safe_load(f)


_NEWSLETTERS: dict[str, dict] = _load_newsletters()
_NEWSLETTER_NAMES = ", ".join(f'"{k}"' for k in _NEWSLETTERS)

# Known Medium-family domains
_MEDIUM_DOMAINS = re.compile(
    r"^https?://(medium\.com|towardsdatascience\.com|betterprogramming\.pub"
    r"|levelup\.gitconnected\.com|pub\.towardsai\.net)"
)

# URL fragments that indicate non-article links
_SKIP_FRAGMENTS = (
    "/m/signin",
    "/m/unsubscribe",
    "/m/global-identity",
    "medium.com/tag/",
    "medium.com/topic/",
    "medium.com/plans",
)


def _parse_articles(html: str) -> list[dict[str, str]]:
    """Extract article cards from a Medium newsletter HTML body.

    Returns a list of {title, url} dicts, capped at 10.
    """
    soup = BeautifulSoup(html, "html.parser")
    articles: list[dict[str, str]] = []
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

        title = a_tag.get_text(" ", strip=True)
        if len(title) < 12:
            for parent in a_tag.parents:
                candidate = parent.get_text(" ", strip=True)
                if 12 < len(candidate) < 250:
                    title = candidate
                    break

        articles.append({"title": title[:200], "url": clean_url})
        if len(articles) == 10:
            break

    return articles


def _resolve_newsletter(name: str) -> dict | None:
    """Return the newsletter config for a given name, using fuzzy matching."""
    key = name.lower().strip()
    if key in _NEWSLETTERS:
        return _NEWSLETTERS[key]
    for canonical, cfg in _NEWSLETTERS.items():
        if key in canonical or canonical in key:
            return cfg
    return None


@function_tool()
async def get_todays_newsletter(
    context: RunContext, newsletter: str = "medium"
) -> str:
    """Fetch unread newsletter emails from Gmail.

    For Medium, returns a numbered list of article titles and URLs.
    For other newsletters, returns the email body as plain text for discussion.

    Call this when the user asks what is in their newsletter, wants to review
    today's reading, or asks what arrived. If the user names a specific newsletter
    (e.g. "The Batch", "Boring Cash Cow", "North London"), pass that name.

    Args:
        newsletter: Which newsletter to load. One of: "medium" (default),
            "boring cash cow", "the batch", "north london".
    """
    cfg = _resolve_newsletter(newsletter)
    if cfg is None:
        return (
            f'Unknown newsletter "{newsletter}". '
            f"Available options are: {_NEWSLETTER_NAMES}."
        )

    loop = asyncio.get_event_loop()
    emails = await loop.run_in_executor(
        None,
        lambda: gmail_ops.list_messages(max_results=5, query=cfg["query"]),
    )

    if not emails:
        return f"No unread {cfg['label']} emails found in Gmail."

    if cfg["is_medium"]:
        all_articles: list[dict[str, str]] = []
        for meta in emails[:3]:
            html = await loop.run_in_executor(
                None,
                lambda m=meta: gmail_ops.get_message_html_body(m["id"]),
            )
            if html:
                all_articles.extend(_parse_articles(html))

        if not all_articles:
            raise ToolError(
                f"Found {cfg['label']} emails but could not extract article links. "
                "The email format may have changed."
            )

        lines = [f"Found {len(all_articles)} articles in your {cfg['label']}:\n"]
        for i, article in enumerate(all_articles, 1):
            lines.append(f"{i}. {article['title']}\n   {article['url']}")
        return "\n".join(lines)

    else:
        parts: list[str] = []
        for meta in emails[:2]:
            html = await loop.run_in_executor(
                None,
                lambda m=meta: gmail_ops.get_message_html_body(m["id"]),
            )
            if html:
                soup = BeautifulSoup(html, "html.parser")
                for tag in soup.find_all(["script", "style", "nav", "footer"]):
                    tag.decompose()
                parts.append(soup.get_text(" ", strip=True)[:4_000])

        if not parts:
            raise ToolError(
                f"Found {cfg['label']} emails but could not extract content."
            )

        return (
            f"Here is your latest {cfg['label']} newsletter:\n\n"
            + "\n\n---\n\n".join(parts)
        )


@function_tool()
async def save_note(
    context: RunContext,
    content: str,
    article_title: str,
    article_url: str,
) -> str:
    """Save a note about an article to today's local markdown notes file.

    Call this when the user asks to take a note, write something down,
    remember something, or save a thought about an article.

    Args:
        content: The note content to save.
        article_title: Title of the article the note is about.
        article_url: URL of the article the note is about.
    """
    loop = asyncio.get_event_loop()
    path = await loop.run_in_executor(
        None,
        lambda: _save_note(content, article_title, article_url),
    )
    return f"Note saved to {path}."


@function_tool()
async def read_article(context: RunContext, url: str) -> str:
    """Fetch and return the full text of a Medium article.

    First checks the local knowledge base (fast); if not found, fetches
    live from the web using the saved Medium auth credentials.

    Call this when the user wants to read an article in depth, asks for a
    detailed summary, or asks a specific question about a particular article.

    Args:
        url: The article URL, exactly as shown in the newsletter listing.
    """
    loop = asyncio.get_event_loop()

    cached = await loop.run_in_executor(
        None, lambda: raw_store.get_article_by_url(url)
    )
    if cached and cached.raw_markdown:
        content = cached.raw_markdown
    else:
        results = await loop.run_in_executor(
            None, lambda: medium.fetch_articles([url])
        )
        content = results.get(url, "")

    if not content:
        raise ToolError(
            f"Could not retrieve content for {url}. "
            "The article may be blocked or the auth state may need refreshing."
        )

    return content[:_MAX_ARTICLE_CHARS]


@function_tool()
async def search_knowledge(context: RunContext, query: str) -> str:
    """Search the accumulated knowledge base of past newsletter articles.

    Call this when the user asks what they have read about a topic, wants
    to recall a past article, or asks a question that might be answered by
    previously scraped content.

    Args:
        query: A natural-language description of what to search for.
    """
    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(
        None,
        lambda: vector_store.search(query, n_results=5),
    )

    if not results:
        return (
            "The knowledge base is empty or no relevant articles were found. "
            "Try running the pipeline first: uv run python -m src.knowledge.pipeline"
        )

    lines = [f"Found {len(results)} relevant passage(s) from past articles:\n"]
    for i, r in enumerate(results, 1):
        lines.append(
            f"{i}. [{r.title or 'Untitled'}]({r.url})"
            + (f" — {r.author}" if r.author else "")
        )
        lines.append(f"   {r.chunk[:300].strip()}…\n")

    return "\n".join(lines)
