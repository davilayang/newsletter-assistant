# src/knowledge/the_batch.py
# Parser for "The Batch" (DeepLearning.AI) newsletter emails.

from __future__ import annotations

import email
import re

from dataclasses import dataclass, field
from datetime import date
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup, Tag
from markdownify import markdownify

if TYPE_CHECKING:
    pass

_TRIVIAL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"^News$",
        r"^Subscribe$",
        r"Submit a tip",
        r"Work With Andrew Ng",
        r"Learn More About AI With Data Points",
        r"A MESSAGE FROM DEEPLEARNING\.AI",
        r"Unsubscribe",
        r"Manage preferences",
        r"Build and Train",
        r"Enroll now",
    ]
]


def _is_trivial(text: str) -> bool:
    """Return True if *text* matches a known trivial/promo pattern."""
    return any(pat.search(text) for pat in _TRIVIAL_PATTERNS)


@dataclass
class BatchArticle:
    title: str
    content_md: str  # markdown with hyperlinks preserved
    newsletter_date: date | None = field(default=None)


def _html_to_md(html: str) -> str:
    """Convert HTML fragment to clean markdown, preserving links."""
    md = markdownify(html, strip=["img"], newline_style="backslash")
    # Collapse excessive blank lines
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()


def _is_letter_stop(div: Tag) -> bool:
    """Return True if this div signals the end of Andrew's letter."""
    # Stop at h1 (news articles) or h2 "A MESSAGE FROM"
    if div.find("h1"):
        return True
    h2 = div.find("h2")
    if h2 and re.search(r"A MESSAGE FROM", h2.get_text(), re.IGNORECASE):
        return True
    return False


def _extract_andrew_letter(soup: BeautifulSoup) -> BatchArticle | None:
    """Extract Andrew Ng's letter (the content before the first <h1>)."""
    # The letter uses Georgia serif font and starts with "Dear friends"
    dear_tag = soup.find(string=re.compile(r"Dear friends", re.IGNORECASE))
    if dear_tag is None:
        return None

    # Walk up to the rich_text wrapper div
    letter_div = dear_tag.find_parent("div", class_="hs_cos_wrapper_type_rich_text")
    if letter_div is None:
        return None

    # Collect this div and any subsequent rich_text sibling divs that are part
    # of the letter (before we hit the promo or news section)
    parts: list[str] = [str(letter_div)]

    # Start from the first letter div's parent wrapper
    wrapper = letter_div.parent
    if wrapper is not None:
        current: Tag | None = wrapper.next_sibling  # type: ignore[assignment]
        while current is not None:
            if not isinstance(current, Tag):
                current = current.next_sibling  # type: ignore[assignment]
                continue

            rt = current.find("div", class_="hs_cos_wrapper_type_rich_text")
            if rt is not None:
                if _is_letter_stop(rt):
                    break
                parts.append(str(rt))

            # Also include image wrappers (part of the letter illustration)
            current = current.next_sibling  # type: ignore[assignment]

    combined_html = "\n".join(parts)
    md = _html_to_md(combined_html)

    # Remove lines containing Subscribe / Submit a tip (header navigation)
    md = re.sub(r"^.*Subscribe.*$\n?", "", md, flags=re.MULTILINE)
    md = re.sub(r"^.*Submit a tip.*$\n?", "", md, flags=re.MULTILINE)

    md = md.strip()
    if not md:
        return None

    return BatchArticle(title="Letter from Andrew Ng", content_md=md)


def parse_the_batch_html(html: str) -> list[BatchArticle]:
    """Parse The Batch newsletter HTML and return a list of articles.

    Each news article starts with an <h1> tag inside a rich_text wrapper div.
    Andrew's letter (if present) is extracted as the first article.
    Trivial sections (promos, job postings, footer) are filtered out.
    """
    if not html or not html.strip():
        return []

    soup = BeautifulSoup(html, "html.parser")
    articles: list[BatchArticle] = []

    # 1. Extract Andrew's letter
    letter = _extract_andrew_letter(soup)
    if letter is not None:
        articles.append(letter)

    # 2. Extract news articles (each starts with an <h1> in a rich_text div)
    h1_tags = soup.find_all("h1")
    for h1 in h1_tags:
        title = h1.get_text(strip=True)
        if not title or _is_trivial(title):
            continue

        # Find the enclosing rich_text div
        rich_div = h1.find_parent("div", class_="hs_cos_wrapper_type_rich_text")
        if rich_div is None:
            continue

        md = _html_to_md(str(rich_div))
        if not md:
            continue

        articles.append(BatchArticle(title=title, content_md=md))

    return articles


def parse_the_batch_eml(raw_eml: str) -> tuple[str, date | None, list[BatchArticle]]:
    """Parse a raw .eml file for The Batch newsletter.

    Returns (subject, date, articles).
    """
    msg = email.message_from_string(raw_eml)
    subject = msg.get("Subject", "")

    newsletter_date: date | None = None
    date_str = msg.get("Date")
    if date_str:
        try:
            newsletter_date = parsedate_to_datetime(date_str).date()
        except Exception:
            pass

    # Extract HTML body
    html_body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/html":
                payload = part.get_payload(decode=True)
                if isinstance(payload, bytes):
                    charset = part.get_content_charset() or "utf-8"
                    html_body = payload.decode(charset, errors="replace")
                    break
    else:
        ct = msg.get_content_type()
        if ct == "text/html":
            payload = msg.get_payload(decode=True)
            if isinstance(payload, bytes):
                charset = msg.get_content_charset() or "utf-8"
                html_body = payload.decode(charset, errors="replace")

    articles = parse_the_batch_html(html_body)

    # Stamp newsletter_date on each article
    for article in articles:
        article.newsletter_date = newsletter_date

    return subject, newsletter_date, articles
