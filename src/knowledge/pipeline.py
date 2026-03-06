# src/knowledge/pipeline.py
# Daily scraping pipeline: Gmail → fetcher (tiered) → raw_store
# Entry point: `uv run python -m src.knowledge.pipeline`
#
# Vector store indexing is intentionally NOT done here — articles are stored
# with vector_status='pending' and indexed only after the user explicitly
# approves them (via the agent's index_article tool or index_ready() below).

from __future__ import annotations

import logging
import sys

from datetime import date
from pathlib import Path

import yaml

from src.core.gmail import ops as gmail_ops
from src.knowledge import fetcher, medium, raw_store, vector_store

logger = logging.getLogger(__name__)

_NEWSLETTERS_PATH = Path(__file__).parents[2] / "config" / "newsletters.yaml"
MAX_EMAILS = 10  # safety cap per run


def _medium_newsletters() -> list[tuple[str, dict]]:
    """Return (label, cfg) for every is_medium entry in newsletters.yaml."""
    with _NEWSLETTERS_PATH.open() as f:
        config: dict = yaml.safe_load(f)
    return [(cfg["label"], cfg) for cfg in config.values() if cfg.get("is_medium")]


def run(newsletter_date: date | None = None) -> None:
    """Idempotent pipeline run. Safe to call multiple times.

    Processes all newsletters marked is_medium: true in newsletters.yaml.

    Args:
        newsletter_date: Override the date recorded against articles (defaults to today).
    """
    if newsletter_date is None:
        newsletter_date = date.today()

    logger.info("Pipeline starting for date %s", newsletter_date)

    # Pre-flight: check Medium auth state once before any browser use
    medium.check_auth_state()

    newsletters = _medium_newsletters()
    if not newsletters:
        logger.warning("No is_medium newsletters found in newsletters.yaml. Done.")
        return

    for label, cfg in newsletters:
        logger.info("Querying Gmail for: %s", label)

        # Append newer_than to avoid pulling old emails on first run
        base_query = cfg["query"]
        query = f"{base_query} newer_than:30d"
        max_articles = cfg.get("max_articles", 5)

        emails = gmail_ops.list_messages(max_results=MAX_EMAILS, query=query)
        if not emails:
            logger.info("  No emails found for %s.", label)
            continue

        logger.info("  Found %d email(s) to process.", len(emails))

        for email_meta in emails:
            message_id = email_meta["id"]

            if raw_store.is_processed(message_id):
                logger.info("  Message %s already processed — skipping.", message_id)
                continue

            logger.info("  Processing message %s …", message_id)

            html = gmail_ops.get_message_html_body(message_id)
            if not html:
                logger.warning(
                    "  Message %s had no HTML body — marking processed anyway.",
                    message_id,
                )
                raw_store.mark_processed(message_id)
                continue

            articles = medium.parse_medium_newsletter(html)
            logger.info(
                "    Parsed %d article(s) from message %s.", len(articles), message_id
            )

            # Cap articles per email and skip URLs already stored with full content
            articles_to_fetch = []
            cached_count = 0
            for article in articles[:max_articles]:
                existing = raw_store.get_article_by_url(article.url)
                if existing and len(existing.raw_markdown) >= 500:
                    logger.info(
                        "    Cached:  %s (%d chars)",
                        article.url,
                        len(existing.raw_markdown),
                    )
                    cached_count += 1
                    continue
                logger.info("    Queued:  %s", article.url)
                articles_to_fetch.append(article)

            logger.info(
                "    → %d to fetch, %d already cached.",
                len(articles_to_fetch),
                cached_count,
            )

            urls_to_fetch = [a.url for a in articles_to_fetch]
            article_contents = (
                fetcher.fetch_articles(urls_to_fetch) if urls_to_fetch else {}
            )

            for article in articles[:max_articles]:
                content = article_contents.get(article.url, "")

                # Log and set status when falling back to snippet
                if not content:
                    existing = raw_store.get_article_by_url(article.url)
                    if existing and len(existing.raw_markdown) >= 500:
                        # Already stored with full content — skip upsert
                        continue
                    content = article.snippet
                    scrape_status = "snippet_only"
                    logger.warning(
                        "    Snippet-only: %s (%d chars) — all tiers failed",
                        article.url,
                        len(content),
                    )
                else:
                    scrape_status = "full"

                raw_store.upsert_article(
                    url=article.url,
                    title=article.title,
                    author=article.author,
                    newsletter_date=newsletter_date,
                    raw_markdown=content,
                    scrape_status=scrape_status,
                )

            raw_store.mark_processed(message_id)
            logger.info("    Message %s marked as processed.", message_id)

    logger.info("Pipeline complete.")


# ---------------------------------------------------------------------------
# Manual vector store controls
# ---------------------------------------------------------------------------


def set_article_vector_status(url: str, status: str) -> None:
    """Manually set vector_status for one article.

    status: 'pending' | 'ready' | 'indexed'

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
                if article.newsletter_date
                else "",
            },
        )
        raw_store.set_vector_status(article.url, "indexed")
        logger.info("  Indexed: %s", article.url)
    logger.info("Done.")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if len(sys.argv) > 1 and sys.argv[1] == "index":
        index_ready()
    else:
        run()
