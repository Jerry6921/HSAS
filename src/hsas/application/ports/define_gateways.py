"""Contracts for course systems outside the application boundary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class SyncCourseResult:
    course_id: str
    course_title: str
    change_count: int
    output_path: Path


@dataclass(frozen=True, slots=True)
class SyncBatchResult:
    discovered_course_count: int
    succeeded_course_ids: tuple[str, ...]
    failures: tuple[dict[str, str], ...]
    report_path: Path


@dataclass(frozen=True, slots=True)
class MoodleSessionResult:
    status: str
    checked_at: str
    available_course_count: int
    error: str | None = None


@dataclass(frozen=True, slots=True)
class CourseCatalogEntry:
    course_id: str
    title: str
    url: str | None
    downloaded: bool


@dataclass(frozen=True, slots=True)
class CourseCatalogResult:
    login_status: str
    login_error: str | None
    available: tuple[CourseCatalogEntry, ...]
    downloaded: tuple[CourseCatalogEntry, ...]


class CourseGateway(Protocol):
    """Moodle operations required by HSAS use cases."""

    def login(self) -> None: ...

    def check_login_status(self) -> MoodleSessionResult: ...

    def login_until_ready(self, *, timeout_seconds: int = 300) -> MoodleSessionResult: ...

    def list_courses(self) -> CourseCatalogResult: ...

    def sync_course(self, course: str) -> SyncCourseResult: ...

    def sync_all(self) -> SyncBatchResult: ...
