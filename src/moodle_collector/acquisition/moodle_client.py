from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.async_api import BrowserContext, Page, async_playwright

from ..settings import SelectorConfig, Settings
from ..transformation.common.course_schema import CourseSummary


class MoodleAjaxError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CourseStateResult:
    """One course discovered from the dashboard and its optional AJAX state."""

    course: CourseSummary
    title: str
    state: dict[str, Any] | None = None
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.state is not None and self.error is None


CourseDiscoveryProgressCallback = Callable[[int, int, CourseSummary], None]


@asynccontextmanager
async def persistent_context(
    settings: Settings,
    *,
    headless: bool | None = None,
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


def _first_matching_nodes(soup: BeautifulSoup, selectors: list[str]):
    for selector in selectors:
        nodes = soup.select(selector)
        if nodes:
            return nodes
    return []


def parse_discovered_courses(
    html: str,
    page_url: str,
    selectors: SelectorConfig,
) -> list[CourseSummary]:
    """Parse and deduplicate course links from a Moodle dashboard."""
    soup = BeautifulSoup(html, "html.parser")
    courses: dict[str, CourseSummary] = {}
    for link in _first_matching_nodes(soup, selectors.course_links):
        href = link.get("href")
        title = " ".join(link.get_text(" ", strip=True).split())
        title = re.sub(r"^(?:course name|课程名称)\s+", "", title, flags=re.IGNORECASE)
        if not href or not title:
            continue
        url = urljoin(page_url, href)
        course_id = parse_qs(urlparse(url).query).get("id", [None])[0]
        courses[url] = CourseSummary(title=title, url=url, course_id=course_id)
    return list(courses.values())


def extract_course_title(
    html: str,
    selectors: SelectorConfig,
    *,
    fallback: str = "Untitled course",
) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for selector in selectors.course_title:
        node = soup.select_one(selector)
        if node:
            title = " ".join(node.get_text(" ", strip=True).split())
            if title:
                return title
    return fallback


async def discover_courses(
    page: Page,
    *,
    dashboard_url: str,
    selectors: SelectorConfig,
    wait_timeout_ms: int = 10_000,
) -> list[CourseSummary]:
    """Open Moodle's full course catalogue and wait for rendered course cards."""
    if page.url.rstrip("/") != dashboard_url.rstrip("/"):
        await page.goto(dashboard_url, wait_until="domcontentloaded")

    dashboard_html = await page.content()
    dashboard = BeautifulSoup(dashboard_html, "html.parser")
    catalogue_url: str | None = None
    for link in dashboard.select("a[href]"):
        candidate = urljoin(page.url, link.get("href"))
        if urlparse(candidate).path.rstrip("/") == "/my/courses.php":
            catalogue_url = candidate
            break
    if catalogue_url and page.url.rstrip("/") != catalogue_url.rstrip("/"):
        await page.goto(catalogue_url, wait_until="domcontentloaded")

    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait_timeout_ms / 1000
    while True:
        courses = parse_discovered_courses(
            await page.content(),
            page.url,
            selectors,
        )
        if courses or loop.time() >= deadline:
            return courses
        await asyncio.sleep(0.25)


def _decode_json_strings(value: Any) -> Any:
    """Decode Moodle methods that return JSON inside a JSON string."""
    for _ in range(3):
        if not isinstance(value, str):
            break
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            break
    return value


def decode_ajax_response(payload: Any) -> dict[str, Any]:
    """Unwrap service.php's list/result/data envelope and double-encoded data."""
    payload = _decode_json_strings(payload)
    if isinstance(payload, list):
        if not payload:
            raise MoodleAjaxError("Moodle returned an empty AJAX response")
        payload = payload[0]

    if isinstance(payload, dict) and payload.get("error"):
        exception = payload.get("exception") or {}
        message = exception.get("message") if isinstance(exception, dict) else None
        raise MoodleAjaxError(message or "Moodle AJAX method returned an error")

    if isinstance(payload, dict) and "data" in payload:
        payload = _decode_json_strings(payload["data"])

    if not isinstance(payload, dict):
        raise MoodleAjaxError("Unexpected Moodle AJAX response shape")
    if not {"course", "section", "cm"}.issubset(payload):
        raise MoodleAjaxError("Course state is missing course, section, or cm data")
    return payload


def enrich_course_state_from_html(
    state: dict[str, Any],
    html: str,
) -> dict[str, Any]:
    """Attach full rendered activity text omitted or truncated by state API.

    Moodle's course-format state commonly shortens label names with an
    ellipsis. The rendered page still contains the complete label, so retain
    its plain text as neutral activity metadata for generic parsers.
    """
    soup = BeautifulSoup(html, "html.parser")
    for activity in state.get("cm", []):
        module_id = str(activity.get("id") or "")
        if not module_id:
            continue
        node = soup.select_one(f'[id="module-{module_id}"]')
        if node is None:
            continue
        lines = [" ".join(line.split()) for line in node.get_text("\n").splitlines()]
        content_text = "\n".join(line for line in lines if line).strip()
        if content_text:
            activity["content_text"] = content_text[:20_000]
    return state


async def get_live_sesskey(page: Page) -> str:
    # Read the live value; never put sesskey in .env, source code, logs, or output.
    value = await page.evaluate(
        "() => (window.M && M.cfg && M.cfg.sesskey) ? M.cfg.sesskey : null"
    )
    if not isinstance(value, str) or not value:
        raise MoodleAjaxError(
            "Could not read M.cfg.sesskey. Confirm the course page is logged in."
        )
    return value


async def fetch_course_state(
    context: BrowserContext,
    page: Page,
    *,
    base_url: str,
    course_id: str,
) -> dict[str, Any]:
    sesskey = await get_live_sesskey(page)
    service_url = urljoin(base_url.rstrip("/") + "/", "lib/ajax/service.php")
    request_body = [
        {
            "index": 0,
            "methodname": "core_courseformat_get_state",
            "args": {"courseid": int(course_id)},
        }
    ]
    response = await context.request.post(
        service_url,
        params={
            "sesskey": sesskey,
            "info": "core_courseformat_get_state",
        },
        data=request_body,
        fail_on_status_code=False,
    )
    if not response.ok:
        raise MoodleAjaxError(
            f"Moodle AJAX request failed with HTTP {response.status}"
        )
    try:
        payload = await response.json()
    except Exception as exc:
        raise MoodleAjaxError("Moodle AJAX response was not JSON") from exc
    state = decode_ajax_response(payload)
    return enrich_course_state_from_html(state, await page.content())


async def discover_all_course_states(
    context: BrowserContext,
    page: Page,
    *,
    dashboard_url: str,
    base_url: str,
    selectors: SelectorConfig,
    progress_callback: CourseDiscoveryProgressCallback | None = None,
) -> list[CourseStateResult]:
    """Discover every dashboard course and fetch each course's AJAX state.

    A failure in one course is returned on that item rather than aborting the
    complete batch, allowing the orchestration layer to persist all successes.
    """
    courses = await discover_courses(
        page,
        dashboard_url=dashboard_url,
        selectors=selectors,
    )
    base_host = urlparse(base_url).netloc
    results: list[CourseStateResult] = []

    for index, course in enumerate(courses, start=1):
        if progress_callback:
            progress_callback(index, len(courses), course)
        course_id = course.course_id
        if not course_id or not course_id.isdigit():
            results.append(
                CourseStateResult(
                    course=course,
                    title=course.title,
                    error="Course URL has no numeric course ID",
                )
            )
            continue

        try:
            await page.goto(str(course.url), wait_until="domcontentloaded")
            if urlparse(page.url).netloc != base_host:
                raise MoodleAjaxError("Course navigation left the configured Moodle host")
            html = await page.content()
            title = extract_course_title(
                html,
                selectors,
                fallback=course.title,
            )
            state = await fetch_course_state(
                context,
                page,
                base_url=base_url,
                course_id=course_id,
            )
            results.append(CourseStateResult(course=course, title=title, state=state))
        except Exception as exc:
            results.append(
                CourseStateResult(
                    course=course,
                    title=course.title,
                    error=f"{type(exc).__name__}: {str(exc)[:300]}",
                )
            )

    return results
