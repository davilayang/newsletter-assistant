# src/agent/tools.py
# NewsletterAssistant Agent with function tools for Phase 1

import asyncio
import re

from textwrap import dedent

from bs4 import BeautifulSoup
from livekit.agents import Agent, RunContext, ToolError, function_tool

from src.core.gmail import ops as gmail_ops
from src.core.notes import save_note as _save_note

NEWSLETTER_QUERY = "from:noreply@medium.com is:unread"

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

        # Strip tracking query params
        clean_url = url.split("?")[0].rstrip("/")
        if clean_url in seen:
            continue
        seen.add(clean_url)

        # Title: prefer text of this link; walk up if too short
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


class NewsletterAssistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=dedent("""\
                You are a personal reading assistant for Medium newsletter articles.
                Each morning you help the user review what arrived in their newsletter.

                Style:
                - Speak naturally and conversationally. No markdown, bullet symbols,
                  asterisks, or emojis in your responses — you are speaking, not writing.
                - When summarising an article, give the key insight in 2 to 3 sentences,
                  then invite follow-up questions.
                - When saving a note, confirm exactly what was saved and to which file.
                - If the user wants to go deeper on any article, discuss it in detail.

                Start by greeting the user and offering to load their latest newsletter.
            """),
        )

    @function_tool()
    async def get_todays_newsletter(self, context: RunContext) -> str:
        """Fetch today's unread Medium newsletter emails from Gmail and return
        a structured list of articles with titles and URLs ready to discuss.

        Call this when the user asks what is in their newsletter, wants to
        review today's reading, or asks what arrived this morning.
        """
        loop = asyncio.get_event_loop()

        emails = await loop.run_in_executor(
            None,
            lambda: gmail_ops.list_messages(max_results=5, query=NEWSLETTER_QUERY),
        )

        if not emails:
            return "No unread Medium newsletter emails found in Gmail."

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
                "Found newsletter emails but could not extract any article links. "
                "The email format may have changed."
            )

        lines = [f"Found {len(all_articles)} articles in your Medium newsletter:\n"]
        for i, article in enumerate(all_articles, 1):
            lines.append(f"{i}. {article['title']}\n   {article['url']}")

        return "\n".join(lines)

    @function_tool()
    async def save_note(
        self,
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
