"""Persist cleaned, source-faithful HKU SIS course-information pages."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from hashlib import sha256
from html import escape
from pathlib import Path
import re
from typing import Any, Callable

from hsas.application.ports.define_gateways import (
    SisCourseInfoSessionResult,
    SisCourseInfoSyncResult,
)
from hsas.domain.courses import ArchiveIndex
from hsas.infrastructure.storage.persist_data import read_json, write_json, write_text
from hsas.infrastructure.runtime import hku_portal_profile_dir

from .fetch_course_pages import (
    LOGIN_URL,
    SisCourseInfoAuthenticationError,
    capture_course_page,
    open_login_until_sis_ready,
    save_sis_session,
    sis_context,
)


SOURCE_NAME = "HKU SIS Course Information"
AUTHORITY = "highest"
COURSE_CODE_PATTERN = re.compile(r"(?<![A-Z0-9])([A-Z]{4})\s*[_-]?(\d{4})(?!\d)", re.I)


def course_identity(title: str) -> tuple[str, str, str] | None:
    match = COURSE_CODE_PATTERN.search(title.upper())
    if match is None:
        return None
    subject, catalogue = match.groups()
    return f"{subject}{catalogue}", subject, catalogue


def cleaned_visible_text(value: str) -> str:
    lines = []
    blank = False
    for raw_line in value.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        line = re.sub(r"[\t\u00a0 ]+", " ", raw_line).strip()
        if not line:
            if lines and not blank:
                lines.append("")
            blank = True
            continue
        blank = False
        lines.append(line)
    return "\n".join(lines).strip() + "\n"


def isolate_course_content(value: str, course_code: str) -> str:
    """Drop surrounding PeopleSoft navigation without interpreting course facts."""
    starts = [
        position
        for marker in (course_code, "Academic Year:", "Course Information")
        if (position := value.casefold().find(marker.casefold())) >= 0
    ]
    if starts:
        value = value[min(starts):]
    end = value.casefold().find("return to search")
    if end >= 0:
        value = value[:end]
    return value


def safe_rendered_html(*, course_code: str, text: str, source_url: str) -> str:
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>{escape(course_code)} · HKU SIS Course Information</title>"
        "<style>body{font:15px/1.55 system-ui,sans-serif;max-width:960px;"
        "margin:36px auto;padding:0 24px;color:#17211b}pre{white-space:pre-wrap;"
        "font:inherit}</style></head><body>"
        f"<h1>{escape(course_code)}</h1><p>Source: <a href='{escape(source_url)}'>"
        "HKU SIS Course Information</a></p>"
        f"<pre>{escape(text)}</pre></body></html>"
    )


def discover_moodle_course_codes(resources_dir: Path) -> tuple[list[dict[str, str]], list[str]]:
    courses: dict[str, dict[str, str]] = {}
    skipped: list[str] = []
    for path in sorted((resources_dir / "courses").glob("*/course.json")):
        try:
            archive = ArchiveIndex.from_json(path).archive
        except Exception:
            continue
        identity = course_identity(archive.course.title)
        if identity is None:
            skipped.append(archive.course.title)
            continue
        code, subject, catalogue = identity
        courses.setdefault(
            code,
            {
                "course_code": code,
                "subject_area": subject,
                "catalogue_number": catalogue,
                "moodle_course_id": archive.course.course_id,
                "moodle_title": archive.course.title,
            },
        )
    return [courses[key] for key in sorted(courses)], skipped


def sis_course_info_status(resources_dir: Path) -> dict[str, Any]:
    root = resources_dir / "sis-course-info"
    target = root / "latest.json"
    session = _read_session_status(root)
    if not target.is_file():
        return {
            "available": False,
            "synced_at": None,
            "course_count": 0,
            "changed_course_count": 0,
            "failure_count": 0,
            **session,
        }
    value = read_json(target)
    if not isinstance(value, dict) or not isinstance(value.get("courses"), list):
        raise ValueError("HKU SIS course-information manifest has an invalid shape")
    return {
        "available": True,
        "synced_at": value.get("synced_at"),
        "course_count": len(value["courses"]),
        "changed_course_count": len(value.get("changes") or []),
        "failure_count": len(value.get("failures") or []),
        "source": SOURCE_NAME,
        "authority": AUTHORITY,
        "courses": value["courses"],
        **session,
    }


class SisCourseInfoBrowserGateway:
    def __init__(self, resources_dir: Path, *, profile_dir: Path | None = None) -> None:
        self.resources_dir = resources_dir.expanduser().resolve()
        self.root = self.resources_dir / "sis-course-info"
        self.profile_dir = (
            profile_dir.expanduser().resolve()
            if profile_dir is not None
            else hku_portal_profile_dir(self.resources_dir)
        )
        self.session_state_path = self.profile_dir / "sis-session.json"

    def login_until_ready(
        self, *, timeout_seconds: int = 300
    ) -> SisCourseInfoSessionResult:
        async def run() -> SisCourseInfoSessionResult:
            async with sis_context(
                self.profile_dir,
                headless=False,
                session_state_path=self.session_state_path,
            ) as context:
                await open_login_until_sis_ready(
                    context,
                    login_url=LOGIN_URL,
                    timeout_seconds=timeout_seconds,
                )
                await save_sis_session(context, self.session_state_path)
                courses, _skipped = discover_moodle_course_codes(self.resources_dir)
                return SisCourseInfoSessionResult(
                    status="logged_in",
                    checked_at=datetime.now(timezone.utc).isoformat(),
                    available_course_count=len(courses),
                )

        try:
            result = asyncio.run(run())
        except Exception:
            self._write_session_status("login_required")
            raise
        self._write_session_status("logged_in")
        return result

    def sync(
        self,
        *,
        timeout_seconds: int = 90,
        selected_courses: list[dict[str, str]] | None = None,
        progress_callback: Callable[[dict[str, object]], None] | None = None,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> SisCourseInfoSyncResult:
        courses, skipped = (
            (selected_courses, [])
            if selected_courses is not None
            else discover_moodle_course_codes(self.resources_dir)
        )
        if not courses:
            raise ValueError("No Moodle course titles contain a Subject Area and Catalogue Number")

        async def run() -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
            records: list[dict[str, Any]] = []
            failures: list[dict[str, str]] = []
            async with sis_context(
                self.profile_dir,
                headless=True,
                session_state_path=self.session_state_path,
            ) as context:
                page = context.pages[0] if context.pages else await context.new_page()
                for index, course in enumerate(courses, start=1):
                    if cancel_requested is not None and cancel_requested():
                        break
                    if progress_callback is not None:
                        progress_callback(
                            {
                                "course_code": course["course_code"],
                                "completed": index - 1,
                                "total": len(courses),
                                "state": "running",
                            }
                        )
                    try:
                        _raw_html, visible_text, source_url = await capture_course_page(
                            page,
                            subject_area=course["subject_area"],
                            catalogue_number=course["catalogue_number"],
                            timeout_seconds=timeout_seconds,
                        )
                        records.append(self._persist_course(course, visible_text, source_url))
                    except SisCourseInfoAuthenticationError:
                        raise
                    except Exception as exc:
                        failures.append(
                            {
                                "course_code": course["course_code"],
                                "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                            }
                        )
                    finally:
                        if progress_callback is not None:
                            progress_callback(
                                {
                                    "course_code": course["course_code"],
                                    "completed": index,
                                    "total": len(courses),
                                    "state": "completed",
                                }
                            )
                if records:
                    await save_sis_session(context, self.session_state_path)
            return records, failures

        try:
            records, failures = asyncio.run(run())
        except SisCourseInfoAuthenticationError:
            self._write_session_status("expired")
            raise
        synced_at = datetime.now(timezone.utc).isoformat()
        previous = read_json(self.root / "latest.json") if (self.root / "latest.json").is_file() else {}
        previous_by_code = {
            value.get("course_code"): value
            for value in previous.get("courses", [])
            if isinstance(value, dict)
        }
        discovered_codes = {course["course_code"] for course in courses}
        successful_codes = {record["course_code"] for record in records}
        records.extend(
            value
            for code, value in previous_by_code.items()
            if code in discovered_codes and code not in successful_codes
        )
        records.sort(key=lambda value: value["course_code"])
        changes = []
        unchanged = []
        for record in records:
            if record["course_code"] not in successful_codes:
                continue
            old = previous_by_code.get(record["course_code"])
            if old is None:
                action = "added"
            elif old.get("content_sha256") != record["content_sha256"]:
                action = "modified"
            else:
                unchanged.append(record["course_code"])
                continue
            changes.append({"action": action, **record})
        changes.extend(
            {
                "action": "removed",
                **previous_by_code[code],
            }
            for code in sorted(set(previous_by_code) - discovered_codes)
        )
        envelope = {
            "schema_version": "1.0",
            "source": SOURCE_NAME,
            "authority": AUTHORITY,
            "synced_at": synced_at,
            "courses": records,
            "changes": changes,
            "skipped_moodle_titles": skipped,
            "failures": failures,
        }
        target = self.root / "latest.json"
        write_json(target, envelope).chmod(0o600)
        if changes:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            write_json(self.root / "history" / f"{stamp}.json", envelope).chmod(0o600)
        self._write_session_status("logged_in")
        return SisCourseInfoSyncResult(
            status="synced",
            synced_at=synced_at,
            discovered_course_count=len(courses),
            succeeded_course_codes=tuple(sorted(successful_codes)),
            unchanged_course_codes=tuple(unchanged),
            skipped_course_titles=tuple(skipped),
            failures=tuple(failures),
            output_path=target,
        )

    def _persist_course(
        self,
        course: dict[str, str],
        visible_text: str,
        source_url: str,
    ) -> dict[str, Any]:
        text = cleaned_visible_text(isolate_course_content(visible_text, course["course_code"]))
        digest = sha256(text.encode("utf-8")).hexdigest()
        code = course["course_code"]
        course_root = self.root / "courses" / code
        text_path = course_root / "latest.txt"
        html_path = course_root / "latest.html"
        write_text(text_path, text).chmod(0o600)
        write_text(
            html_path,
            safe_rendered_html(course_code=code, text=text, source_url=source_url),
        ).chmod(0o600)
        observed_at = datetime.now(timezone.utc).isoformat()
        return {
            **course,
            "source": SOURCE_NAME,
            "authority": AUTHORITY,
            "source_url": source_url,
            "observed_at": observed_at,
            "content_sha256": digest,
            "text_relative_path": text_path.relative_to(self.resources_dir).as_posix(),
            "html_relative_path": html_path.relative_to(self.resources_dir).as_posix(),
        }

    def _write_session_status(self, status: str) -> None:
        write_json(
            self.root / "session.json",
            {"status": status, "checked_at": datetime.now(timezone.utc).isoformat()},
        ).chmod(0o600)


def _read_session_status(root: Path) -> dict[str, Any]:
    path = root / "session.json"
    if not path.is_file():
        return {"login_status": "login_required", "login_checked_at": None}
    value = read_json(path)
    if not isinstance(value, dict):
        return {"login_status": "unknown", "login_checked_at": None}
    return {
        "login_status": value.get("status", "unknown"),
        "login_checked_at": value.get("checked_at"),
    }
