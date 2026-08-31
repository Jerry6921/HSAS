from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from playwright.async_api import BrowserContext, Page, async_playwright

from ..config import Settings


@asynccontextmanager
async def persistent_context(
    settings: Settings, *, headless: bool | None = None
) -> AsyncIterator[BrowserContext]:
    """Reuse a local Chromium profile so Moodle cookies survive between runs."""
    settings.profile_dir.mkdir(parents=True, exist_ok=True)
    storage_state_path = settings.profile_dir / "storage-state.json"
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(settings.profile_dir),
            headless=settings.headless if headless is None else headless,
        )
        # Chromium may discard session-only cookies when it closes. Persist and
        # re-inject them explicitly so Moodle SSO survives between CLI commands.
        if storage_state_path.exists():
            state = json.loads(storage_state_path.read_text(encoding="utf-8"))
            cookies = state.get("cookies", [])
            if cookies:
                await context.add_cookies(cookies)
        context.set_default_timeout(settings.navigation_timeout_ms)
        try:
            yield context
        finally:
            await context.storage_state(path=str(storage_state_path))
            storage_state_path.chmod(0o600)
            await context.close()


async def open_page(context: BrowserContext, url: str) -> Page:
    page = context.pages[0] if context.pages else await context.new_page()
    await page.goto(url, wait_until="domcontentloaded")
    return page


async def save_html(page: Page, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(await page.content(), encoding="utf-8")
