# src/knowledge/pipeline.py
# Daily scraping pipeline: Gmail → medium.py → raw_store → vector_store
# Entry point: `uv run python -m src.knowledge.pipeline`

from __future__ import annotations

import logging

from datetime import date
from pathlib import Path

import yaml

from src.core.gmail import ops as gmail_ops
from src.knowledge import medium, raw_store, vector_store

logger = logging.getLogger(__name__)

_NEWSLETTERS_PATH = Path(__file__).parents[2] / "newsletters.yaml"
MAX_EMAILS = 10  # safety cap per run


def _medium_newsletters() -> list[tuple[str, str]]:
    """Return (label, query) for every is_medium entry in newsletters.yaml."""
    with _NEWSLETTERS_PATH.open() as f:
        config: dict = yaml.safe_load(f)
    return [
        (cfg["label"], cfg["query"])
        for cfg in config.values()
        if cfg.get("is_medium")
    ]


def run(newsletter_date: date | None = None) -> None:
    """Idempotent pipeline run. Safe to call multiple times.

    Processes all newsletters marked is_medium: true in newsletters.yaml.

    Args:
        newsletter_date: Override the date recorded against articles (defaults to today).
    """
    if newsletter_date is None:
        newsletter_date = date.today()

    logger.info("Pipeline starting for date %s", newsletter_date)

    newsletters = _medium_newsletters()
    if not newsletters:
        logger.warning("No is_medium newsletters found in newsletters.yaml. Done.")
        return

    for label, query in newsletters:
        logger.info("Querying Gmail for: %s", label)

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

            articles = medium.parse_newsletter_email(html)
            logger.info(
                "    Parsed %d article(s) from message %s.", len(articles), message_id
            )

            article_contents = medium.fetch_articles([a.url for a in articles])

            for article in articles:
                content = article_contents.get(article.url) or article.snippet

                raw_store.upsert_article(
                    url=article.url,
                    title=article.title,
                    author=article.author,
                    newsletter_date=newsletter_date,
                    raw_markdown=content,
                )

                vector_store.upsert_article(
                    url=article.url,
                    raw_markdown=content,
                    metadata={
                        "title": article.title,
                        "author": article.author,
                        "newsletter_date": newsletter_date.isoformat(),
                    },
                )

            raw_store.mark_processed(message_id)
            logger.info("    Message %s marked as processed.", message_id)

    logger.info("Pipeline complete.")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    run()
