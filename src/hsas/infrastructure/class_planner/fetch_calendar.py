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
PORTAL_LOGIN_PATH_MARKERS = ("login", "signin", "signon", "logout")


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


def _is_portal_resume_page(url: str) -> bool:
    """Return whether an HKU Portal page can hand control back to Class Planner.

    Depending on the current Portal deployment, a completed sign-in can stop on
    the AAD bridge, the Portal home page, or another authenticated Portal page.
    Explicit sign-in pages must remain open so the user can finish interacting
    with them.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc.lower() != PORTAL_HOST:
        return False
    path = parsed.path.lower()
    return not any(marker in path for marker in PORTAL_LOGIN_PATH_MARKERS)


async def _resume_after_portal_login(
    context: BrowserContext,
    payload_future: asyncio.Future[dict[str, Any]],
    *,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Return to Class Planner after HKU Portal finishes authentication.

    The official SPA may leave its only tab on the AAD bridge or another Portal
    page after sign-in. Re-opening `/app` lets MSAL use the shared browser
    session and issue the authenticated calendar request.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    portal_since: dict[int, float] = {}
    while loop.time() < deadline:
        if payload_future.done():
            return await payload_future
        pages = list(context.pages)
        active_portal_ids: set[int] = set()
        for page in pages:
            identity = id(page)
            if not _is_portal_resume_page(page.url):
                portal_since.pop(identity, None)
                continue
            active_portal_ids.add(identity)
            started = portal_since.setdefault(identity, loop.time())
            # A short stable period lets the Portal finish any automatic
            # redirect before control returns to Class Planner.
            if loop.time() - started >= 2:
                portal_since.pop(identity, None)
                await page.goto(APP_URL, wait_until="domcontentloaded")
                break
        portal_since = {
            identity: started
            for identity, started in portal_since.items()
            if identity in active_portal_ids
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
            return await _resume_after_portal_login(
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
