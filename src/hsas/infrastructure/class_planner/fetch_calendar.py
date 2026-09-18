"""Capture an authenticated HKU Class Planner calendar response in-browser."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Callable
from urllib.parse import urlparse

from playwright.async_api import BrowserContext, Response, async_playwright


APP_URL = "https://class-planner.hku.hk/app"
API_HOST = "class-planner.hku.hk"
API_PATH = "/api/calendar"
CURRENT_API_HOST = "api.hku.hk"
CURRENT_API_PATH = "/sis/app/cspa/calendar"
PORTAL_HOST = "hkuportal.hku.hk"
PORTAL_BRIDGE_PATH = "/cas/aad"
PORTAL_LOGIN_PATH_MARKERS = ("login", "signin", "signon", "logout")
PORTAL_AUTHENTICATED_TEXT_MARKERS = (
    "log out",
    "logout",
    "sign out",
    "my favourites",
    "my favorites",
    "you are signed in",
    "signed in successfully",
    "authentication successful",
    "close this window",
)
SSO_RETURN_HOSTS = (PORTAL_HOST, "adfs.connect.hku.hk", "login.microsoftonline.com")
APP_RETRY_DELAY_SECONDS = 1.5


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
            # Close every visible page first. A failed SSO flow can leave an
            # auxiliary page alive even after the original capture page closes.
            for page in list(context.pages):
                if page.is_closed():
                    continue
                try:
                    await page.close(run_before_unload=False)
                except Exception:
                    pass
            await context.close()


def _is_calendar_url(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    return (
        parsed.scheme == "https"
        and (
            (parsed.netloc == API_HOST and path == API_PATH)
            or (parsed.netloc == CURRENT_API_HOST and path == CURRENT_API_PATH)
        )
    )


def _is_calendar_response(response: Response) -> bool:
    return _is_calendar_url(response.url) and response.status == 200


def _is_portal_bridge(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.netloc == PORTAL_HOST and parsed.path == PORTAL_BRIDGE_PATH


def _is_class_planner_app(url: str) -> bool:
    """Return whether the browser has already reached the Class Planner SPA."""
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.netloc.lower() == API_HOST
        and (parsed.path == "/app" or parsed.path.startswith("/app/"))
    )


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


async def _is_authenticated_portal_page(page: Any) -> bool:
    """Recognize a completed HKU SSO landing page across Portal, ADFS and AAD."""
    parsed = urlparse(page.url)
    host = parsed.netloc.lower()
    if parsed.scheme != "https":
        return False
    if _is_class_planner_app(page.url):
        return True
    if host == PORTAL_HOST and _is_portal_resume_page(page.url):
        return True
    if host not in SSO_RETURN_HOSTS:
        return False
    try:
        if await page.locator("input[type='password']").count():
            return False
        text = (await page.locator("body").inner_text(timeout=1500)).casefold()
    except Exception:
        return False
    return any(marker in text for marker in PORTAL_AUTHENTICATED_TEXT_MARKERS)


async def _hku_session_fingerprint(context: BrowserContext) -> tuple[tuple[str, str, str], ...]:
    """Track HKU session advancement without exposing or persisting cookie values."""
    cookies = await context.cookies([APP_URL, f"https://{PORTAL_HOST}/"])
    return tuple(
        sorted(
            (
                str(cookie.get("domain", "")),
                str(cookie.get("name", "")),
                str(cookie.get("value", "")),
            )
            for cookie in cookies
            if str(cookie.get("domain", "")).lstrip(".").endswith("hku.hk")
        )
    )


async def _calendar_payload_from_app(page: Any) -> dict[str, Any] | None:
    """Recover calendar JSON from an already authenticated Class Planner SPA.

    The SPA can finish its first calendar request while the SSO navigation is
    settling. Resource Timing still retains the exact same-origin request URL,
    so repeat that request inside the authenticated page without exposing its
    query string (which contains the user's HKU email) to logs or local files.
    """
    if not _is_class_planner_app(page.url):
        return None
    try:
        value = await page.evaluate(
            """
            async () => {
              const target = performance.getEntriesByType("resource")
                .map((entry) => entry.name)
                .reverse()
                .find((value) => {
                  try {
                    const url = new URL(value, window.location.href);
                    return url.protocol === "https:"
                      && url.host === "class-planner.hku.hk"
                      && url.pathname.replace(/[/]$/, "") === "/api/calendar";
                  } catch (_error) {
                    return false;
                  }
                });
              if (!target) return null;
              const response = await fetch(target, {
                credentials: "include",
                cache: "no-store",
                headers: { Accept: "application/json" },
              });
              if (!response.ok) return null;
              return await response.json();
            }
            """
        )
    except Exception:
        return None
    return value if isinstance(value, dict) else None


async def _resume_after_portal_login(
    context: BrowserContext,
    payload_future: asyncio.Future[dict[str, Any]],
    *,
    timeout_seconds: int,
    cancel_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Return to Class Planner after HKU Portal finishes authentication.

    The official SPA may leave its only tab on the AAD bridge or another Portal
    page after sign-in. Re-opening `/app` lets MSAL use the shared browser
    session and issue the authenticated calendar request.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    portal_since: dict[int, float] = {}
    app_since: dict[int, float] = {}
    app_reload_attempted = False
    app_payload_attempts = 0
    last_probed_session = await _hku_session_fingerprint(context)
    while loop.time() < deadline:
        if cancel_requested is not None and cancel_requested():
            raise InterruptedError("Class Planner login was cancelled")
        if payload_future.done():
            return await payload_future
        pages = list(context.pages)
        has_class_planner_app = any(_is_class_planner_app(page.url) for page in pages)
        current_session = await _hku_session_fingerprint(context)
        if (
            not has_class_planner_app
            and current_session
            and current_session != last_probed_session
        ):
            probe = await context.new_page()
            try:
                try:
                    await probe.goto(
                        APP_URL,
                        wait_until="domcontentloaded",
                        timeout=5000,
                    )
                except Exception:
                    pass
            finally:
                if not probe.is_closed():
                    await probe.close()
            last_probed_session = current_session
            if payload_future.done():
                return await payload_future
        active_portal_ids: set[int] = set()
        active_app_ids: set[int] = set()
        for page in pages:
            identity = id(page)
            if _is_class_planner_app(page.url):
                active_app_ids.add(identity)
                portal_since.pop(identity, None)
                started = app_since.setdefault(identity, loop.time())
                if app_payload_attempts == 0:
                    app_payload_attempts += 1
                    recovered = await _calendar_payload_from_app(page)
                    if recovered is not None:
                        return recovered
                if (
                    not app_reload_attempted
                    and loop.time() - started >= APP_RETRY_DELAY_SECONDS
                ):
                    # The user may have completed SSO on a page whose first
                    # calendar response occurred before the capture settled.
                    # Reload exactly once to retrigger the SPA request, never
                    # every polling cycle.
                    app_reload_attempted = True
                    await page.reload(wait_until="domcontentloaded")
                    if payload_future.done():
                        return await payload_future
                    app_payload_attempts += 1
                    recovered = await _calendar_payload_from_app(page)
                    if recovered is not None:
                        return recovered
                continue
            if not await _is_authenticated_portal_page(page):
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
        app_since = {
            identity: started
            for identity, started in app_since.items()
            if identity in active_app_ids
        }
        await asyncio.sleep(0.5)
    raise TimeoutError


async def capture_calendar_response(
    profile_dir: Path,
    *,
    headless: bool,
    timeout_seconds: int,
    cancel_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Wait for the official SPA to make its own authenticated calendar call."""
    if timeout_seconds < 10 or timeout_seconds > 900:
        raise ValueError("Class Planner timeout must be between 10 and 900 seconds")

    async with class_planner_context(profile_dir, headless=headless) as context:
        return await capture_calendar_response_in_context(
            context,
            headless=headless,
            timeout_seconds=timeout_seconds,
            cancel_requested=cancel_requested,
        )


async def capture_calendar_response_in_context(
    context: BrowserContext,
    *,
    headless: bool = True,
    timeout_seconds: int,
    cancel_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Capture the calendar through a broker-owned browser context."""
    if timeout_seconds < 10 or timeout_seconds > 900:
        raise ValueError("Class Planner timeout must be between 10 and 900 seconds")
    page = await context.new_page()
    try:
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
        await page.goto(APP_URL, wait_until="domcontentloaded")
        try:
            if headless:
                deadline = loop.time() + timeout_seconds
                while not payload_future.done():
                    if cancel_requested is not None and cancel_requested():
                        raise InterruptedError("Class Planner synchronization was cancelled")
                    if loop.time() >= deadline:
                        raise TimeoutError
                    try:
                        return await asyncio.wait_for(asyncio.shield(payload_future), timeout=0.5)
                    except TimeoutError:
                        continue
                return await payload_future
            return await _resume_after_portal_login(
                context,
                payload_future,
                timeout_seconds=timeout_seconds,
                cancel_requested=cancel_requested,
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
        finally:
            context.remove_listener("response", schedule)
    finally:
        await page.close()
