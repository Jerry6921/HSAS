"""Course synchronization use cases expressed through an application port."""

from __future__ import annotations

from dataclasses import dataclass

from hsas.application.ports.define_gateways import (
    CourseCatalogResult,
    CourseGateway,
    MoodleSessionResult,
    SyncBatchResult,
    SyncCourseResult,
)


@dataclass(frozen=True, slots=True)
class CourseSynchronizationService:
    gateway: CourseGateway

    def login(self) -> None:
        self.gateway.login()

    def check_login_status(self) -> MoodleSessionResult:
        return self.gateway.check_login_status()

    def login_until_ready(self, *, timeout_seconds: int = 300) -> MoodleSessionResult:
        return self.gateway.login_until_ready(timeout_seconds=timeout_seconds)

    def list_courses(self) -> CourseCatalogResult:
        return self.gateway.list_courses()

    def sync_course(self, course: str) -> SyncCourseResult:
        return self.gateway.sync_course(course)

    def sync_all(self) -> SyncBatchResult:
        return self.gateway.sync_all()


__all__ = [
    "CourseSynchronizationService",
    "MoodleSessionResult",
    "SyncBatchResult",
    "SyncCourseResult",
]
