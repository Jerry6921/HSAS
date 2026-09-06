"""Capture an authenticated HKU Class Planner calendar response in-browser."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator
from urllib.parse import urlparse

from playwright.async_api import BrowserContext, Response, async_playwright


APP_URL = "https://class-planner.hku.hk/app"
API_HOST = "class-planner.hku.hk"
API_PATH = "/api/calendar"
PORTAL_HOST = "hkuportal.hku.hk"
PORTAL_BRIDGE_PATH = "/cas/aad"


class ClassPlannerAuthenticationError(RuntimeError):
    """The user-managed Class Planner browser session is unavailable."""


@asynccontextmanager
async def class_planner_context(
    profile_dir: Path,
    *,
    headless: bool,
) -> AsyncIterator[BrowserContext]:
    profile_dir.mkdir(parents=True, exist_ok=True)
    profile_dir.chmod(0o700)
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=headless,
        )
        try:
            yield context
        finally:
            await context.close()


def _is_calendar_response(response: Response) -> bool:
    parsed = urlparse(response.url)
    return (
        parsed.scheme == "https"
        and parsed.netloc == API_HOST
        and parsed.path == API_PATH
        and response.status == 200
    )


def _is_portal_bridge(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.netloc == PORTAL_HOST and parsed.path == PORTAL_BRIDGE_PATH


async def _resume_after_portal_bridge(
    context: BrowserContext,
    payload_future: asyncio.Future[dict[str, Any]],
    *,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Return to Class Planner after HKU Portal finishes its AAD bridge.

    The official SPA leaves its only tab on the Portal bridge after the user
    completes sign-in. Re-opening `/app` lets MSAL use that new browser session
    and issue the authenticated calendar request.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    bridge_since: dict[int, float] = {}
    while loop.time() < deadline:
        if payload_future.done():
            return await payload_future
        pages = list(context.pages)
        active_bridge_ids: set[int] = set()
        for page in pages:
            identity = id(page)
            if not _is_portal_bridge(page.url):
                bridge_since.pop(identity, None)
                continue
            active_bridge_ids.add(identity)
            started = bridge_since.setdefault(identity, loop.time())
            # A short stable period distinguishes the completed bridge page
            # from its initial redirect into Microsoft sign-in.
            if loop.time() - started >= 5:
                bridge_since.pop(identity, None)
                await page.goto(APP_URL, wait_until="domcontentloaded")
                break
        bridge_since = {
            identity: started
            for identity, started in bridge_since.items()
            if identity in active_bridge_ids
        }
        await asyncio.sleep(0.5)
    raise TimeoutError


async def capture_calendar_response(
    profile_dir: Path,
    *,
    headless: bool,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Wait for the official SPA to make its own authenticated calendar call."""
    if timeout_seconds < 10 or timeout_seconds > 900:
        raise ValueError("Class Planner timeout must be between 10 and 900 seconds")

    async with class_planner_context(profile_dir, headless=headless) as context:
        loop = asyncio.get_running_loop()
        payload_future: asyncio.Future[dict[str, Any]] = loop.create_future()

        async def consume(response: Response) -> None:
            if payload_future.done() or not _is_calendar_response(response):
                return
            try:
                value = await response.json()
            except Exception:
                payload_future.set_exception(
                    ClassPlannerAuthenticationError(
                        "Class Planner calendar response was not valid JSON"
                    )
                )
                return
            if not isinstance(value, dict):
                payload_future.set_exception(
                    ClassPlannerAuthenticationError(
                        "Class Planner calendar response was not a JSON object"
                    )
                )
                return
            payload_future.set_result(value)

        def schedule(response: Response) -> None:
            asyncio.create_task(consume(response))

        context.on("response", schedule)
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(APP_URL, wait_until="domcontentloaded")
        try:
            if headless:
                return await asyncio.wait_for(payload_future, timeout=timeout_seconds)
            return await _resume_after_portal_bridge(
                context,
                payload_future,
                timeout_seconds=timeout_seconds,
            )
        except TimeoutError as exc:
            action = (
                "Complete HKU Portal sign-in in the opened browser"
                if not headless
                else "Run `hsas class-planner login` before syncing"
            )
            raise ClassPlannerAuthenticationError(
                f"No authenticated Class Planner calendar response was received. {action}."
            ) from exc
