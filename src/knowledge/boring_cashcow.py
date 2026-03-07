# src/knowledge/boring_cashcow.py
# Parser for "Boring Cash Cow" (David Maker / ConvertKit) newsletter emails.

from __future__ import annotations

import email
import re

from dataclasses import dataclass, field
from datetime import date
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup
from markdownify import markdownify


@dataclass
class CashCowSection:
    title: str  # email subject line
    content_md: str  # full body as markdown
    newsletter_date: date | None = field(default=None)


def _html_to_md(html: str) -> str:
    """Convert HTML fragment to clean markdown, preserving links."""
    md = markdownify(html, strip=["img"], newline_style="backslash")
    # Collapse excessive blank lines
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()


def parse_cashcow_html(html: str) -> str:
    """Parse Boring Cash Cow newsletter HTML and return cleaned markdown.

    Extracts the main content from the first ``ck-section`` div (excluding
    the ``ck-hide-in-public-posts`` footer), strips sign-off, greeting,
    DuckDuckGo banner, ConvertKit badge, and tracking images.
    """
    if not html or not html.strip():
        return ""

    soup = BeautifulSoup(html, "html.parser")

    # Remove DuckDuckGo email protection banner and preview div
    for tag in soup.find_all(
        attrs={"data-email-protection": "duckduckgo-email-protection-preview"}
    ):
        tag.decompose()
    for tag in soup.find_all(
        attrs={"data-email-protection": "duckduckgo-email-protection-banner"}
    ):
        tag.decompose()

    # Remove ck-hide-in-public-posts sections (Unsubscribe/Preferences footer)
    for tag in soup.find_all("div", class_="ck-hide-in-public-posts"):
        tag.decompose()

    # Remove "Built with ConvertKit" badge
    for tag in soup.find_all("a", href=re.compile(r"builtwith\.kit\.com")):
        parent = tag.parent
        if parent:
            parent.decompose()
        else:
            tag.decompose()

    # Remove tracking images (open.kit-mail3.com)
    for img in soup.find_all("img", src=re.compile(r"open\.kit-mail3\.com")):
        img.decompose()

    # Find main content: first ck-section div, then drill into ck-inner-section
    # to avoid table markup from outer layout wrappers.
    ck_section = soup.find("div", class_="ck-section")
    if ck_section is None:
        return ""

    inner = ck_section.find("div", class_="ck-inner-section")
    content_root = inner if inner is not None else ck_section
    md = _html_to_md(str(content_root))

    # Strip "Morning ," greeting line
    md = re.sub(r"^\s*Morning\s*,\s*\n?", "", md)

    # Strip sign-off: everything from "Cheers," onwards
    md = re.sub(r"\n\s*Cheers,.*", "", md, flags=re.DOTALL)

    # Remove zero-width spaces
    md = md.replace("\u200b", "")

    return md.strip()


def parse_cashcow_eml(raw_eml: str) -> CashCowSection | None:
    """Parse a raw .eml file for the Boring Cash Cow newsletter.

    Returns a ``CashCowSection`` or ``None`` if no content could be extracted.
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
            if part.get_content_type() == "text/html":
                payload = part.get_payload(decode=True)
                if isinstance(payload, bytes):
                    charset = part.get_content_charset() or "utf-8"
                    html_body = payload.decode(charset, errors="replace")
                    break
    else:
        if msg.get_content_type() == "text/html":
            payload = msg.get_payload(decode=True)
            if isinstance(payload, bytes):
                charset = msg.get_content_charset() or "utf-8"
                html_body = payload.decode(charset, errors="replace")

    content_md = parse_cashcow_html(html_body)
    if not content_md:
        return None

    return CashCowSection(
        title=subject,
        content_md=content_md,
        newsletter_date=newsletter_date,
    )
