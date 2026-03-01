"""Test camoufox-based Medium scrape (Firefox, anti-Cloudflare).

Usage:
    uv run python scripts/test_scrape_camoufox.py
"""

import asyncio

from pathlib import Path

import markdownify

from bs4 import BeautifulSoup
from camoufox.async_api import AsyncCamoufox

AUTH_STATE = Path("creds/medium_auth.json")
TEST_URL = "https://pub.towardsai.net/how-i-scrape-and-search-my-medium-articles-by-keyword-5767ed7923ed"
OUTPUT = Path("scripts/scraped_article_camoufox.md")


def html_to_markdown(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    article = soup.find("article")
    if not article:
        article = soup.find("main") or soup.find("section") or soup.body
    if not article:
        return ""
    for tag in article.find_all(["nav", "footer", "script", "style", "aside"]):
        tag.decompose()
    return markdownify.markdownify(str(article), heading_style="ATX", strip=["img"])


async def scrape(url: str) -> str:
    storage_state = str(AUTH_STATE) if AUTH_STATE.exists() else None
    if not storage_state:
        print("Warning: no auth state found, fetching as anonymous user")

    async with AsyncCamoufox(headless=True) as browser:
        ctx_kwargs = {"storage_state": storage_state} if storage_state else {}
        context = await browser.new_context(**ctx_kwargs)
        page = await context.new_page()

        print(f"Fetching {url} ...")
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

        try:
            await page.wait_for_selector("article", timeout=10_000)
        except Exception:
            print("Warning: <article> not found within timeout, continuing anyway")

        html = await page.content()

    return html_to_markdown(html)


async def main() -> None:
    md = await scrape(TEST_URL)

    if not md.strip():
        print("ERROR: Got empty content")
        return

    OUTPUT.write_text(md, encoding="utf-8")
    print(f"Saved {len(md):,} chars to {OUTPUT}")
    print("\n--- First 1000 chars ---")
    print(md[:1000])


asyncio.run(main())
