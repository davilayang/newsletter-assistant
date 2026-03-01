"""Run once interactively to save Medium auth state to creds/medium_auth.json.

Usage:
    uv run python scripts/medium_login.py
"""

import asyncio

from pathlib import Path

from playwright.async_api import async_playwright

AUTH_STATE = Path("creds/medium_auth.json")


async def main() -> None:
    AUTH_STATE.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        # Launch visible browser so you can log in manually
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        await page.goto("https://medium.com/m/signin")
        print("Log in to Medium in the browser window, then press Enter here...")
        input()

        await context.storage_state(path=str(AUTH_STATE))
        print(f"Auth state saved to {AUTH_STATE}")
        await browser.close()


asyncio.run(main())
