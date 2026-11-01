"""The set of tools and the shape of a tool is what an agent can rely on.

The SIS course-information gateway is the only path from a Moodle archive title to
an official catalogue page, so its skip and failure reporting is the difference
between "this course has no SIS page" and "the sync silently dropped it".
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hsas.infrastructure.sis.course_info import gateway as gateway_module
from hsas.infrastructure.sis.course_info.client import SisCourseInfoAuthenticationError
from hsas.infrastructure.sis.course_info.gateway import (
    SisCourseInfoBrowserGateway,
    discover_moodle_course_codes,
    sis_course_info_status,
)


class _FakeArchiveIndex:
    """Stand-in for the Moodle archive reader; discovery logic is what is tested."""

    @staticmethod
    def from_json(path: Path):
        name = path.parent.name
        if name == "corrupt":
            raise ValueError("truncated snapshot")
        if name == "noidentity":
            return SimpleNamespace(
                archive=SimpleNamespace(
                    course=SimpleNamespace(
                        title="AASO_FORUM Academic Advising", course_id="9001"
                    )
                )
            )
        return SimpleNamespace(
            archive=SimpleNamespace(
                course=SimpleNamespace(
                    title=f"{name} Engineering in Biology", course_id=f"moodle-{name}"
                )
            )
        )


def _write_course(resources: Path, directory: str) -> None:
    path = resources / "courses" / directory / "course.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")


def test_discovery_reports_corrupt_and_unnumbered_courses_instead_of_dropping_them(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setattr(gateway_module, "ArchiveIndex", _FakeArchiveIndex)
    for directory in ("BMED2206", "MATH1851", "corrupt", "noidentity"):
        _write_course(tmp_path, directory)

    courses, skipped = discover_moodle_course_codes(tmp_path)

    assert [course["course_code"] for course in courses] == ["BMED2206", "MATH1851"]
    assert [course["moodle_course_id"] for course in courses] == [
        "moodle-BMED2206",
        "moodle-MATH1851",
    ]
    assert any("corrupt: unreadable course.json (ValueError)" == entry for entry in skipped)
    assert "AASO_FORUM Academic Advising" in skipped


def test_discovery_keeps_one_entry_per_course_code(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setattr(gateway_module, "ArchiveIndex", _FakeArchiveIndex)
    for directory in ("BMED2206", "BMED2206_1AB"):
        _write_course(tmp_path, directory)

    courses, skipped = discover_moodle_course_codes(tmp_path)

    assert [course["course_code"] for course in courses] == ["BMED2206"]
    assert skipped == []


class _Page:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _Context:
    def __init__(self) -> None:
        self.pages: list[_Page] = []

    async def new_page(self) -> _Page:
        page = _Page()
        self.pages.append(page)
        return page


_TWO_COURSES = [
    {
        "course_code": "BMED2206",
        "subject_area": "BMED",
        "catalogue_number": "2206",
        "moodle_course_id": "moodle-BMED2206",
        "moodle_title": "BMED2206 Engineering in Biology",
    },
    {
        "course_code": "MATH1851",
        "subject_area": "MATH",
        "catalogue_number": "1851",
        "moodle_course_id": "moodle-MATH1851",
        "moodle_title": "MATH1851 Calculus",
    },
]


def _gateway_with_recording_capture(tmp_path: Path, monkeypatch, capture):
    saved: list[object] = []

    async def fake_save(_context, path):
        saved.append(path)

    monkeypatch.setattr(gateway_module, "capture_course_page", capture)
    monkeypatch.setattr(gateway_module, "save_sis_session", fake_save)
    return SisCourseInfoBrowserGateway(tmp_path), saved


def test_sync_persists_each_course_and_reports_progress(
    tmp_path: Path, monkeypatch,
) -> None:
    async def capture(page, *, subject_area, catalogue_number, timeout_seconds):
        return "<html/>", f"{subject_area}{catalogue_number} official page", (
            f"https://example.test/{subject_area}{catalogue_number}"
        )

    gateway, saved = _gateway_with_recording_capture(tmp_path, monkeypatch, capture)
    context = _Context()
    progress: list[dict[str, object]] = []

    result = asyncio.run(
        gateway.sync_in_context(
            context,
            selected_courses=_TWO_COURSES,
            progress_callback=progress.append,
        )
    )

    assert result.status == "synced"
    assert result.succeeded_course_codes == ("BMED2206", "MATH1851")
    assert result.failures == ()
    assert context.pages[0].closed is True
    assert [entry["state"] for entry in progress] == [
        "running", "completed", "running", "completed",
    ]
    manifest = json.loads((tmp_path / "sis-course-info/latest.json").read_text())
    assert [course["course_code"] for course in manifest["courses"]] == [
        "BMED2206",
        "MATH1851",
    ]
    assert all(len(course["content_sha256"]) == 64 for course in manifest["courses"])
    assert saved, "the refreshed session was not persisted after a successful sync"


def test_one_failing_course_does_not_fail_the_whole_sync(
    tmp_path: Path, monkeypatch,
) -> None:
    async def capture(page, *, subject_area, catalogue_number, timeout_seconds):
        if catalogue_number == "1851":
            raise RuntimeError("navigation timeout")
        return "<html/>", "BMED2206 official page", "https://example.test/BMED2206"

    gateway, _ = _gateway_with_recording_capture(tmp_path, monkeypatch, capture)

    result = asyncio.run(
        gateway.sync_in_context(_Context(), selected_courses=_TWO_COURSES)
    )

    assert result.succeeded_course_codes == ("BMED2206",)
    assert [failure["course_code"] for failure in result.failures] == ["MATH1851"]
    assert result.failures[0]["error"].startswith("RuntimeError: navigation timeout")
    assert result.status == "synced"


def test_an_expired_session_is_recorded_before_the_error_propagates(
    tmp_path: Path, monkeypatch,
) -> None:
    async def capture(page, *, subject_area, catalogue_number, timeout_seconds):
        raise SisCourseInfoAuthenticationError("people soft token changed")

    gateway, saved = _gateway_with_recording_capture(tmp_path, monkeypatch, capture)

    with pytest.raises(SisCourseInfoAuthenticationError):
        asyncio.run(gateway.sync_in_context(_Context(), selected_courses=_TWO_COURSES))

    assert saved == [], "a failed session must not be persisted as usable"
    session = json.loads((tmp_path / "sis-course-info/session.json").read_text())
    assert session["status"] == "expired"
    assert sis_course_info_status(tmp_path)["login_status"] == "expired"


def test_cancellation_stops_after_the_current_course_and_closes_the_page(
    tmp_path: Path, monkeypatch,
) -> None:
    async def capture(page, *, subject_area, catalogue_number, timeout_seconds):
        return "<html/>", "official page", "https://example.test/page"

    gateway, saved = _gateway_with_recording_capture(tmp_path, monkeypatch, capture)
    context = _Context()

    result = asyncio.run(
        gateway.sync_in_context(
            context,
            selected_courses=_TWO_COURSES,
            cancel_requested=lambda: True,
        )
    )

    assert result.succeeded_course_codes == ()
    assert context.pages[0].closed is True
    assert saved == [], "a cancelled run must not persist a session hand-off"


def test_sync_refuses_to_guess_when_no_course_code_can_be_derived(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setattr(
        gateway_module, "discover_moodle_course_codes", lambda _resources: ([], [])
    )
    gateway = SisCourseInfoBrowserGateway(tmp_path)

    with pytest.raises(ValueError, match="Subject Area and Catalogue Number"):
        asyncio.run(gateway.sync_in_context(_Context()))


def test_status_is_explicit_about_missing_and_corrupt_state(tmp_path: Path) -> None:
    empty = sis_course_info_status(tmp_path)
    assert empty["available"] is False
    assert empty["login_status"] == "login_required"

    root = tmp_path / "sis-course-info"
    root.mkdir()
    (root / "latest.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid shape"):
        sis_course_info_status(tmp_path)

    (root / "latest.json").write_text(
        json.dumps({"synced_at": "2026-11-02T00:00:00+00:00", "courses": [{"course_code": "BMED2206"}]}),
        encoding="utf-8",
    )
    (root / "session.json").write_text("[]", encoding="utf-8")
    status = sis_course_info_status(tmp_path)
    assert status["available"] is True
    assert status["course_count"] == 1
    assert status["login_status"] == "unknown"
