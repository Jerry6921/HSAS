"""Open authenticated HKU SIS course-information pages in a private browser."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import re
from typing import Any, AsyncIterator
from urllib.parse import urlencode, urlparse

from playwright.async_api import BrowserContext, Frame, Page, async_playwright

from hsas.infrastructure.storage.persist_data import read_json, write_json


SEARCH_URL = (
    "https://sis-main.hku.hk/psc/sisprod/EMPLOYEE/PSFT_CS/c/"
    "SA_LEARNER_SERVICES.Z_STDT_CSE_LAYOUT.GBL"
)
LOGIN_URL = "https://sis-main.hku.hk/sisprod/z_signon.jsp"
DETAIL_URL = SEARCH_URL.replace("/psc/", "/psp/")
SIS_HOST = "sis-main.hku.hk"


class SisCourseInfoAuthenticationError(RuntimeError):
    """The user-managed HKU SIS session is unavailable."""


class SisCourseInfoLookupError(RuntimeError):
    """A course page could not be resolved from the SIS component."""


@asynccontextmanager
async def sis_context(
    profile_dir: Path,
    *,
    headless: bool,
    session_state_path: Path | None = None,
) -> AsyncIterator[BrowserContext]:
    profile_dir.mkdir(parents=True, exist_ok=True)
    profile_dir.chmod(0o700)
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=headless,
        )
        try:
            if session_state_path is not None:
                await restore_sis_session(context, session_state_path)
            yield context
        finally:
            await context.close()


async def restore_sis_session(context: BrowserContext, path: Path) -> None:
    """Restore private SIS session cookies omitted by a clean browser shutdown."""
    if not path.is_file():
        return
    value = read_json(path)
    cookies = value.get("cookies", []) if isinstance(value, dict) else []
    if not isinstance(cookies, list):
        return
    safe_cookies = [
        cookie
        for cookie in cookies
        if isinstance(cookie, dict)
        and str(cookie.get("domain", "")).lstrip(".").endswith("hku.hk")
    ]
    if safe_cookies:
        await context.add_cookies(safe_cookies)


async def save_sis_session(context: BrowserContext, path: Path) -> None:
    """Persist only HKU cookies inside the shared private browser profile."""
    cookies: list[dict[str, Any]] = await context.cookies(
        [LOGIN_URL, SEARCH_URL]
    )
    cookies = [
        cookie
        for cookie in cookies
        if str(cookie.get("domain", "")).lstrip(".").endswith("hku.hk")
    ]
    write_json(path, {"schema_version": "1.0", "cookies": cookies}).chmod(0o600)


def course_detail_url(subject_area: str, catalogue_number: str) -> str:
    query = urlencode(
        {
            "ACAD_PLAN_TYPE": "CUR",
            "SUBJECT": subject_area,
            "Z_CATALOG_NBR": catalogue_number,
        }
    )
    return f"{DETAIL_URL}?{query}"


async def wait_until_sis_ready(
    context: BrowserContext,
    *,
    timeout_seconds: int,
) -> tuple[Page, Frame]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    while loop.time() < deadline:
        for page in context.pages:
            for frame in page.frames:
                if urlparse(frame.url).netloc != SIS_HOST:
                    continue
                text = await _body_text(frame)
                if _looks_like_search_or_detail(text):
                    return page, frame
        await asyncio.sleep(0.5)
    raise SisCourseInfoAuthenticationError(
        "No authenticated HKU SIS course-information page appeared. "
        "Complete HKU Portal sign-in in the opened browser."
    )


async def open_login_until_sis_ready(
    context: BrowserContext,
    *,
    login_url: str = LOGIN_URL,
    timeout_seconds: int,
) -> tuple[Page, Frame]:
    """Open SIS sign-on and continue after user-completed CAPTCHA and SSO."""
    await open_login_until_authenticated(
        context,
        login_url=login_url,
        timeout_seconds=timeout_seconds,
    )
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    search_opened = False
    while loop.time() < deadline:
        for candidate in context.pages:
            for frame in candidate.frames:
                if urlparse(frame.url).netloc != SIS_HOST:
                    continue
                text = await _body_text(frame)
                if _looks_like_search_or_detail(text):
                    return candidate, frame
            if search_opened or not _looks_authenticated_sis_page(candidate):
                continue
            await candidate.goto(SEARCH_URL, wait_until="domcontentloaded")
            search_opened = True
            break
        await asyncio.sleep(0.5)
    raise SisCourseInfoAuthenticationError(
        "HKU SIS sign-in did not reach the course-information search page. "
        "Complete HKU Portal sign-in and any SIS image verification in the opened browser."
    )


async def open_login_until_authenticated(
    context: BrowserContext,
    *,
    login_url: str = LOGIN_URL,
    timeout_seconds: int,
) -> Page:
    """Stay on SIS sign-on until the user-managed login has completed."""
    page = context.pages[0] if context.pages else await context.new_page()
    previous_token = await _sis_token(context)
    await page.goto(login_url, wait_until="domcontentloaded")
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    while loop.time() < deadline:
        for candidate in context.pages:
            if _looks_authenticated_sis_page(candidate):
                return candidate
        current_token = await _sis_token(context)
        if current_token and current_token != previous_token:
            return page
        await asyncio.sleep(0.5)
    raise SisCourseInfoAuthenticationError(
        "HKU SIS sign-in is still waiting for SSO, MFA, or image verification"
    )


async def _sis_token(context: BrowserContext) -> str | None:
    """Return the active PeopleSoft token without exposing it outside the browser boundary."""
    cookies = await context.cookies([LOGIN_URL])
    return next(
        (
            str(cookie.get("value"))
            for cookie in cookies
            if str(cookie.get("name", "")).upper() == "PS_TOKEN"
            and cookie.get("value")
        ),
        None,
    )


async def capture_course_page(
    page: Page,
    *,
    subject_area: str,
    catalogue_number: str,
    timeout_seconds: int,
) -> tuple[str, str, str]:
    """Return rendered HTML, visible text, and a secret-free source URL."""
    code = f"{subject_area}{catalogue_number}".upper()
    target = course_detail_url(subject_area, catalogue_number)
    await page.goto(target, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
    frame, text = await _wait_for_course_frame(page, code, timeout_seconds=3)
    if frame is None:
        await _submit_search(
            page,
            subject_area=subject_area,
            catalogue_number=catalogue_number,
            timeout_seconds=timeout_seconds,
        )
        frame, text = await _wait_for_course_frame(
            page,
            code,
            timeout_seconds=min(timeout_seconds, 20),
        )
    if frame is None:
        raise SisCourseInfoLookupError(
            f"HKU SIS did not return a detail page for {code}"
        )
    return await frame.content(), text, target


async def _submit_search(
    page: Page,
    *,
    subject_area: str,
    catalogue_number: str,
    timeout_seconds: int,
) -> None:
    await page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
    await page.wait_for_timeout(600)
    frame = await _find_search_frame(page)
    if frame is None:
        raise SisCourseInfoAuthenticationError(
            "HKU SIS search form is unavailable; the saved session may have expired"
        )
    subject = await _matching_input(frame, required=("subject",), excluded=("catalog",))
    catalogue = await _matching_input(frame, required=("catalog",), excluded=())
    if subject is None or catalogue is None:
        raise SisCourseInfoLookupError(
            "HKU SIS search fields could not be identified"
        )
    await subject.fill(subject_area)
    await catalogue.fill(catalogue_number)
    submitted = False
    for locator in (
        frame.get_by_role("button", name=re.compile(r"^search$", re.I)),
        frame.locator("input[type='submit'][value*='Search' i]"),
        frame.locator("input[type='button'][value*='Search' i]"),
        frame.locator("a").filter(has_text=re.compile(r"^Search$", re.I)),
    ):
        if await locator.count():
            await locator.first.click()
            submitted = True
            break
    if not submitted:
        raise SisCourseInfoLookupError("HKU SIS Search action could not be identified")
    code = f"{subject_area}{catalogue_number}"
    frame, _text = await _wait_for_course_frame(page, code, timeout_seconds=8)
    if frame is not None:
        return
    if await _has_no_matching_results(page):
        raise SisCourseInfoLookupError(
            f"HKU SIS Course Information has no matching entry for {code}"
        )
    for candidate in page.frames:
        link = candidate.get_by_text(re.compile(re.escape(code), re.I))
        if await link.count():
            await link.first.click()
            await _wait_for_course_frame(page, code, timeout_seconds=8)
            return


async def _matching_input(frame: Frame, *, required: tuple[str, ...], excluded: tuple[str, ...]):
    label = "Subject Area" if required == ("subject",) else "Catalogue Number"
    labelled = frame.get_by_label(re.compile(label, re.I))
    if await labelled.count():
        return labelled.first
    inputs = frame.locator("input:not([type='hidden'])")
    for index in range(await inputs.count()):
        candidate = inputs.nth(index)
        attributes = " ".join(
            (await candidate.get_attribute(name)) or ""
            for name in ("id", "name", "aria-label", "title", "placeholder")
        ).casefold()
        if all(value in attributes for value in required) and not any(
            value in attributes for value in excluded
        ):
            return candidate
    return None


async def _find_search_frame(page: Page) -> Frame | None:
    for frame in page.frames:
        text = (await _body_text(frame)).casefold()
        if "subject area" in text and "catalogue number" in text:
            return frame
    return None


async def _find_course_frame(page: Page, course_code: str) -> tuple[Frame | None, str]:
    compact_code = re.sub(r"\W+", "", course_code).casefold()
    for frame in page.frames:
        if urlparse(frame.url).netloc != SIS_HOST:
            continue
        text = await _body_text(frame)
        compact_text = re.sub(r"\W+", "", text).casefold()
        if compact_code in compact_text and any(
            marker in text.casefold()
            for marker in ("approved syllabus", "course learning outcomes", "course grade")
        ):
            return frame, text
    return None, ""


async def _wait_for_course_frame(
    page: Page,
    course_code: str,
    *,
    timeout_seconds: int,
) -> tuple[Frame | None, str]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    while loop.time() < deadline:
        frame, text = await _find_course_frame(page, course_code)
        if frame is not None:
            return frame, text
        if await _has_no_matching_results(page):
            return None, ""
        await asyncio.sleep(0.25)
    return None, ""


async def _has_no_matching_results(page: Page) -> bool:
    for frame in page.frames:
        result = frame.locator("[id*='SEARCHRESULT']")
        if await result.count():
            text = " ".join(await result.all_text_contents()).casefold()
            if "no matching values were found" in text:
                return True
    return False


async def _body_text(frame: Frame) -> str:
    try:
        return await frame.locator("body").inner_text(timeout=1500)
    except Exception:
        return ""


def _looks_like_search_or_detail(text: str) -> bool:
    lowered = text.casefold()
    return (
        "subject area" in lowered and "catalogue number" in lowered
    ) or "approved syllabus" in lowered


def _looks_authenticated_sis_page(page: Page) -> bool:
    parsed = urlparse(page.url)
    path = parsed.path.casefold()
    if parsed.netloc != SIS_HOST or path.endswith("/z_signon.jsp"):
        return False
    return not any(marker in path for marker in ("login", "signon", "signin"))
