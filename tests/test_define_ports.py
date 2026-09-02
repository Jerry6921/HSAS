from pathlib import Path

from hsas.application.ports import (
    CourseCatalogResult,
    MoodleSessionResult,
    SyncBatchResult,
    SyncCourseResult,
)
from hsas.application.synchronize_courses import CourseSynchronizationService


class FakeCourseGateway:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def login(self) -> None:
        self.calls.append("login")

    def check_login_status(self) -> MoodleSessionResult:
        self.calls.append("check")
        return MoodleSessionResult("logged_in", "2026-09-02T00:00:00+00:00", 2)

    def login_until_ready(self, *, timeout_seconds: int = 300) -> MoodleSessionResult:
        self.calls.append(f"wait:{timeout_seconds}")
        return MoodleSessionResult("logged_in", "2026-09-02T00:00:00+00:00", 2)

    def list_courses(self) -> CourseCatalogResult:
        self.calls.append("list")
        return CourseCatalogResult("logged in", None, (), ())

    def sync_course(self, course: str) -> SyncCourseResult:
        self.calls.append(f"course:{course}")
        return SyncCourseResult(course, "Demo", 1, Path("course.json"))

    def sync_all(self) -> SyncBatchResult:
        self.calls.append("all")
        return SyncBatchResult(2, ("1", "2"), (), Path("sync-report.json"))


def test_course_use_case_depends_only_on_gateway_contract() -> None:
    gateway = FakeCourseGateway()
    service = CourseSynchronizationService(gateway)

    service.login()
    assert service.check_login_status().status == "logged_in"
    assert service.login_until_ready(timeout_seconds=60).available_course_count == 2
    assert service.list_courses().login_error is None
    assert service.sync_course("1").change_count == 1
    assert service.sync_all().succeeded_course_ids == ("1", "2")
    assert gateway.calls == ["login", "check", "wait:60", "list", "course:1", "all"]
