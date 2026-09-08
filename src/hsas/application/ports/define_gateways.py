"""Contracts for course systems outside the application boundary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol


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
    cancelled: bool = False


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

    def sync_all(
        self,
        *,
        progress_callback: Callable[[dict[str, object]], None] | None = None,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> SyncBatchResult: ...


@dataclass(frozen=True, slots=True)
class ClassPlannerSessionResult:
    status: str
    checked_at: str
    course_count: int
    term_ids: tuple[str, ...]
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ClassPlannerSyncResult:
    status: str
    synced_at: str
    course_count: int
    meeting_count: int
    term_ids: tuple[str, ...]
    changed: bool
    added_course_ids: tuple[str, ...]
    modified_course_ids: tuple[str, ...]
    removed_course_ids: tuple[str, ...]
    output_path: Path


class ClassPlannerGateway(Protocol):
    """Authenticated HKU Class Planner operations required by HIQS."""

    def login_until_ready(
        self, *, timeout_seconds: int = 300
    ) -> ClassPlannerSessionResult: ...

    def sync(self, *, timeout_seconds: int = 90) -> ClassPlannerSyncResult: ...


@dataclass(frozen=True, slots=True)
class SisCourseInfoSessionResult:
    status: str
    checked_at: str
    available_course_count: int
    error: str | None = None


@dataclass(frozen=True, slots=True)
class SisCourseInfoSyncResult:
    status: str
    synced_at: str
    discovered_course_count: int
    succeeded_course_codes: tuple[str, ...]
    unchanged_course_codes: tuple[str, ...]
    skipped_course_titles: tuple[str, ...]
    failures: tuple[dict[str, str], ...]
    output_path: Path


class SisCourseInfoGateway(Protocol):
    """Authenticated HKU SIS course-information collection operations."""

    def login_until_ready(
        self, *, timeout_seconds: int = 300
    ) -> SisCourseInfoSessionResult: ...

    def sync(
        self,
        *,
        timeout_seconds: int = 90,
        selected_courses: list[dict[str, str]] | None = None,
        progress_callback: Callable[[dict[str, object]], None] | None = None,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> SisCourseInfoSyncResult: ...
