"""Test Playwright-based Medium scrape using saved auth state.

Usage:
    uv run python scripts/test_scrape_playwright.py
"""

import asyncio

from pathlib import Path

import markdownify

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

AUTH_STATE = Path("creds/medium_auth.json")
TEST_URL = "https://pub.towardsai.net/how-i-scrape-and-search-my-medium-articles-by-keyword-5767ed7923ed"
OUTPUT = Path("scripts/scraped_article.md")


def html_to_markdown(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    # Medium's article body lives in <article>
    article = soup.find("article")
    if not article:
        # Fallback: grab the largest <section> or <main>
        article = soup.find("main") or soup.find("section") or soup.body

    if not article:
        return ""

    # Drop nav / footer / script / style noise
    for tag in article.find_all(["nav", "footer", "script", "style", "aside"]):
        tag.decompose()

    return markdownify.markdownify(str(article), heading_style="ATX", strip=["img"])


async def scrape(url: str) -> str:
    if not AUTH_STATE.exists():
        raise FileNotFoundError(
            f"{AUTH_STATE} not found. Run scripts/medium_login.py first."
        )

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(storage_state=str(AUTH_STATE))
        page = await context.new_page()

        await Stealth().apply_stealth_async(page)

        print(f"Fetching {url} ...")
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

        # Wait for article body to appear
        try:
            await page.wait_for_selector("article", timeout=10_000)
        except Exception:
            print("Warning: <article> not found within timeout, continuing anyway")

        html = await page.content()
        await browser.close()

    return html_to_markdown(html)


async def main() -> None:
    md = await scrape(TEST_URL)

    if not md.strip():
        print("ERROR: Got empty content — check auth state or selector")
        return

    OUTPUT.write_text(md, encoding="utf-8")
    print(f"Saved {len(md):,} chars to {OUTPUT}")
    print("\n--- First 1000 chars ---")
    print(md[:1000])


asyncio.run(main())
