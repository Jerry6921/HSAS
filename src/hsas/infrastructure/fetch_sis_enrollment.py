"""Capture the current HKU SIS Student Center enrolment list."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from hsas.infrastructure.runtime import hku_portal_profile_dir
from hsas.infrastructure.storage.persist_data import read_json, write_json, write_text

from .sis_course_info.fetch_course_pages import (
    LOGIN_URL,
    SIS_HOST,
    open_login_until_authenticated,
    save_sis_session,
    sis_context,
)


STUDENT_CENTER_URL = (
    "https://sis-main.hku.hk/psc/sisprod/EMPLOYEE/SA/c/"
    "SA_LEARNER_SERVICES.SSS_STUDENT_CENTER.GBL"
)
COURSE_PATTERN = re.compile(
    r"(?<![A-Z0-9])([A-Z]{4})\s*[_-]?(\d{4})(?!\d)(?:\s*[-–—:]?\s*([^\n|]+))?",
    re.I,
)
TERM_PATTERNS = (
    re.compile(r"\b(20\d{2}[-/]\d{2}\s+(?:Semester|Term)\s+\d)\b", re.I),
    re.compile(r"\b((?:Fall|Spring|Summer|Winter)\s+20\d{2})\b", re.I),
    re.compile(r"\b(20\d{2}\s+(?:Semester|Term)\s+\d)\b", re.I),
)


class SisEnrollmentAuthenticationError(RuntimeError):
    """The Student Center session is unavailable."""


class SisEnrollmentParseError(RuntimeError):
    """The current enrolment list could not be identified."""


def parse_enrollment_text(text: str) -> tuple[str | None, list[dict[str, str]]]:
    """Extract current-page course identities while preserving source text separately."""
    term = next(
        (match.group(1).strip() for pattern in TERM_PATTERNS if (match := pattern.search(text))),
        None,
    )
    courses: dict[str, dict[str, str]] = {}
    for match in COURSE_PATTERN.finditer(text):
        subject, catalogue, raw_title = match.groups()
        code = f"{subject}{catalogue}".upper()
        title = (raw_title or code).strip(" -–—:\t")
        title = re.split(
            r"\s{2,}|\b(?:Units?|Credits?|Enrolled|Dropped|Waitlist(?:ed)?)\b",
            title,
            maxsplit=1,
            flags=re.I,
        )[0].strip()
        courses.setdefault(
            code,
            {
                "course_code": code,
                "subject_area": subject.upper(),
                "catalogue_number": catalogue,
                "title": title or code,
            },
        )
    if not courses:
        raise SisEnrollmentParseError("Student Center did not expose any current course codes")
    return term, [courses[code] for code in sorted(courses)]


async def _student_center_text(context, *, timeout_seconds: int) -> str:
    page = context.pages[0] if context.pages else await context.new_page()
    await page.goto(
        STUDENT_CENTER_URL,
        wait_until="domcontentloaded",
        timeout=timeout_seconds * 1000,
    )
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        best_match = ""
        for frame in page.frames:
            if urlparse(frame.url).netloc != SIS_HOST:
                continue
            try:
                text = await frame.locator("body").inner_text(timeout=1500)
            except Exception:
                continue
            if COURSE_PATTERN.search(text) and len(text) > len(best_match):
                best_match = text
        if best_match:
            return best_match
        await asyncio.sleep(0.5)
    raise SisEnrollmentAuthenticationError(
        "HKU SIS Student Center is unavailable or the session requires sign-in"
    )


class SisEnrollmentBrowserGateway:
    """Browser-backed Student Center acquisition using the shared HKU profile."""

    def __init__(self, resources_dir: Path) -> None:
        self.resources_dir = resources_dir.expanduser().resolve()
        self.root = self.resources_dir / "sis-enrollment"
        self.profile_dir = hku_portal_profile_dir(self.resources_dir)
        self.session_state_path = self.profile_dir / "sis-session.json"

    def sync(self, *, timeout_seconds: int = 90, auto_login: bool = True) -> dict[str, Any]:
        async def capture(
            headless: bool,
            target_url: str,
            *,
            capture_timeout_seconds: int,
        ) -> str:
            async with sis_context(
                self.profile_dir,
                headless=headless,
                session_state_path=self.session_state_path,
            ) as context:
                if target_url == LOGIN_URL:
                    await open_login_until_authenticated(
                        context,
                        login_url=LOGIN_URL,
                        timeout_seconds=capture_timeout_seconds,
                    )
                text = await _student_center_text(
                    context,
                    timeout_seconds=capture_timeout_seconds,
                )
                await save_sis_session(context, self.session_state_path)
                return text

        try:
            text = asyncio.run(
                capture(
                    True,
                    STUDENT_CENTER_URL,
                    capture_timeout_seconds=min(timeout_seconds, 5),
                )
            )
        except (SisEnrollmentAuthenticationError, PlaywrightTimeoutError):
            if not auto_login:
                self._write_status("expired")
                raise
            self._write_status("login_required")
            text = asyncio.run(
                capture(
                    False,
                    LOGIN_URL,
                    capture_timeout_seconds=timeout_seconds,
                )
            )
        observed_at = datetime.now(timezone.utc).isoformat()
        term, courses = parse_enrollment_text(text)
        cleaned = "\n".join(line.rstrip() for line in text.splitlines()).strip() + "\n"
        digest = sha256(cleaned.encode("utf-8")).hexdigest()
        text_path = self.root / "latest.txt"
        write_text(text_path, cleaned).chmod(0o600)
        previous = read_json(self.root / "latest.json") if (self.root / "latest.json").is_file() else {}
        changed = previous.get("content_sha256") != digest
        envelope = {
            "schema_version": "1.0",
            "source": "HKU SIS Student Center Enrollment Status",
            "source_url": STUDENT_CENTER_URL,
            "observed_at": observed_at,
            "term": term,
            "content_sha256": digest,
            "text_relative_path": text_path.relative_to(self.resources_dir).as_posix(),
            "courses": courses,
            "changed": changed,
        }
        write_json(self.root / "latest.json", envelope).chmod(0o600)
        if changed:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            write_json(self.root / "history" / f"{stamp}.json", envelope).chmod(0o600)
        self._write_status("logged_in")
        return envelope

    def status(self) -> dict[str, Any]:
        latest = self.root / "latest.json"
        session = self._read_status()
        if not latest.is_file():
            return {"available": False, "course_count": 0, "term": None, **session}
        value = read_json(latest)
        return {
            "available": True,
            "course_count": len(value.get("courses", [])),
            "term": value.get("term"),
            "observed_at": value.get("observed_at"),
            "courses": value.get("courses", []),
            **session,
        }

    def _write_status(self, status: str) -> None:
        write_json(
            self.root / "session.json",
            {"status": status, "checked_at": datetime.now(timezone.utc).isoformat()},
        ).chmod(0o600)

    def _read_status(self) -> dict[str, Any]:
        path = self.root / "session.json"
        if not path.is_file():
            return {"login_status": "login_required", "login_checked_at": None}
        value = read_json(path)
        return {
            "login_status": value.get("status", "unknown"),
            "login_checked_at": value.get("checked_at"),
        }
