from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from hsas.infrastructure.sis.enrollment.client import (
    SisEnrollmentBrowserGateway,
    SisEnrollmentParseError,
    parse_enrollment_text,
)
from hsas.infrastructure.sis.enrollment.review import (
    SisEnrollmentReviewError,
    acknowledge_sis_enrollment_changes,
    collect_sis_enrollment_changes,
    validate_sis_enrollment_batch,
)


def test_parse_enrollment_text_extracts_unique_current_courses() -> None:
    term, courses = parse_enrollment_text(
        """
        Enrollment Status
        2026-27 Semester 1
        BMED 2206 - Engineering in Biology and Medicine    Enrolled
        ENGG1300 Computer Programming I    Enrolled
        BMED2206 - Engineering in Biology and Medicine
        """
    )

    assert term == "2026-27 Semester 1"
    assert courses == [
        {
            "course_code": "BMED2206",
            "subject_area": "BMED",
            "catalogue_number": "2206",
            "title": "Engineering in Biology and Medicine",
        },
        {
            "course_code": "ENGG1300",
            "subject_area": "ENGG",
            "catalogue_number": "1300",
            "title": "Computer Programming I",
        },
    ]


def test_parse_enrollment_text_prefers_current_schedule_over_enrollment_history() -> None:
    term, courses = parse_enrollment_text(
        """
        This Week's Schedule
        Class Schedule
        BMED 2206-1A
        LEC (3159)
        CCHU 9051-1A
        LEC (2691)

        Student Enrollment
        Term Class Schedule Action
        Row
        1
        2026-27 Sem 1
        BMED 2206-1A LEC (3159)
        Approved
        Row
        2
        2026-27 Sem 1
        CCHU 9045-1A LEC (2577)
        Not Approved
        Row
        3
        2026-27 Sem 1
        CCHU 9022-1A LEC (1732)
        Dropped
        Row
        4
        2026-27 Sem 2
        CHEM 1011-2A LEC (4801)
        Approved
        Weekly Schedule
        """
    )

    assert term == "2026-27 Sem 1"
    assert [course["course_code"] for course in courses] == ["BMED2206", "CCHU9051"]
    assert all(course["title"] == course["course_code"] for course in courses)


def test_parse_enrollment_text_fallback_filters_status_and_term() -> None:
    term, courses = parse_enrollment_text(
        """
        Student Enrollment
        Row
        1
        2026-27 Semester 1
        BMED 2206 - Engineering in Biology and Medicine
        Approved
        Row
        2
        2026-27 Semester 1
        CCHU 9045 - The Last Course
        Not Approved
        Row
        3
        2026-27 Semester 1
        CCHU 9022 - Humanity
        Dropped
        Row
        4
        2026-27 Semester 2
        CHEM 1011 - Foundations of Chemistry
        Approved
        Weekly Schedule
        """
    )

    assert term == "2026-27 Semester 1"
    assert courses == [
        {
            "course_code": "BMED2206",
            "subject_area": "BMED",
            "catalogue_number": "2206",
            "title": "Engineering in Biology and Medicine",
        }
    ]


def test_parse_enrollment_text_requires_course_codes() -> None:
    with pytest.raises(SisEnrollmentParseError):
        parse_enrollment_text("Enrollment Status: no rows")


def test_enrollment_status_reads_latest_snapshot(tmp_path: Path) -> None:
    root = tmp_path / "sis-enrollment"
    root.mkdir()
    (root / "latest.json").write_text(
        '{"term":"4261","observed_at":"2026-09-08T00:00:00Z",'
        '"courses":[{"course_code":"BMED2206"}]}',
        encoding="utf-8",
    )

    status = SisEnrollmentBrowserGateway(tmp_path).status()

    assert status["available"] is True
    assert status["course_count"] == 1
    assert status["term"] == "4261"
    assert status["login_status"] == "login_required"


def test_enrollment_review_checkpoint_tracks_course_list(tmp_path: Path) -> None:
    root = tmp_path / "sis-enrollment"
    root.mkdir()
    (root / "latest.json").write_text(
        '{"content_sha256":"abc","term":"4261",'
        '"observed_at":"2026-09-08T00:00:00Z",'
        '"courses":[{"course_code":"BMED2206","subject_area":"BMED",'
        '"catalogue_number":"2206","title":"Engineering in Biology"}]}',
        encoding="utf-8",
    )

    batch = collect_sis_enrollment_changes(tmp_path)
    assert batch["pending_change_count"] == 1
    assert batch["changes"][0]["kind"] == "added"

    checkpoint = acknowledge_sis_enrollment_changes(
        tmp_path, batch, confirmed=True
    )
    assert checkpoint["content_sha256"] == "abc"
    assert collect_sis_enrollment_changes(tmp_path)["pending_change_count"] == 0


def test_enrollment_review_rejects_stale_batch(tmp_path: Path) -> None:
    root = tmp_path / "sis-enrollment"
    root.mkdir()
    latest = root / "latest.json"
    latest.write_text(
        '{"content_sha256":"abc","courses":[{"course_code":"BMED2206"}]}',
        encoding="utf-8",
    )
    batch = collect_sis_enrollment_changes(tmp_path)
    latest.write_text(
        '{"content_sha256":"def","courses":[{"course_code":"ENGG1300"}]}',
        encoding="utf-8",
    )

    with pytest.raises(SisEnrollmentReviewError):
        validate_sis_enrollment_batch(tmp_path, batch)


def test_enrollment_sync_opens_shared_sis_login_after_short_probe(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import hsas.infrastructure.sis.enrollment.client as module

    headless_modes = []
    timeouts = []
    calls = []

    class Page:
        async def goto(self, url, **_kwargs):
            calls.append(("goto", url))

    class Context:
        pages = [Page()]

    @asynccontextmanager
    async def fake_context(_profile_dir, *, headless, session_state_path):
        assert session_state_path.name == "sis-session.json"
        headless_modes.append(headless)
        yield Context()

    async def fake_student_center_text(_context, *, timeout_seconds):
        calls.append(("student_center", timeout_seconds))
        timeouts.append(timeout_seconds)
        if len(timeouts) == 1:
            raise module.SisEnrollmentAuthenticationError("login required")
        return (
            "Enrollment Status\n2026-27 Semester 1\n"
            "BMED2206 Engineering in Biology    Enrolled"
        )

    async def fake_save(_context, path):
        assert path.name == "sis-session.json"

    async def fake_login(_context, *, login_url, timeout_seconds):
        calls.append(("login", login_url, timeout_seconds))
        return Page()

    monkeypatch.setattr(module, "sis_context", fake_context)
    monkeypatch.setattr(module, "_student_center_text", fake_student_center_text)
    monkeypatch.setattr(module, "save_sis_session", fake_save)
    monkeypatch.setattr(module, "open_login_until_authenticated", fake_login)

    result = SisEnrollmentBrowserGateway(tmp_path).sync(timeout_seconds=90)

    assert headless_modes == [True, False]
    assert timeouts == [5, 90]
    assert calls == [
        ("login", module.LOGIN_URL, 5),
        ("student_center", 5),
        ("login", module.LOGIN_URL, 90),
        ("student_center", 90),
    ]
    assert result["courses"][0]["course_code"] == "BMED2206"


@pytest.mark.parametrize("verification_required", [False, True])
def test_enrollment_waits_for_sis_login_and_uses_authenticated_page(
    tmp_path: Path, monkeypatch, verification_required: bool,
) -> None:
    import hsas.infrastructure.sis.enrollment.client as module

    modes = []
    calls = []

    class Frame:
        url = module.STUDENT_CENTER_URL

        def locator(self, selector):
            assert selector == "body"
            return self

        async def inner_text(self, **_kwargs):
            return "2026-27 Semester 1\nBMED2206 Engineering    Enrolled"

    class Page:
        frames = [Frame()]

        async def goto(self, url, **_kwargs):
            calls.append(("goto", url))

    page = Page()

    @asynccontextmanager
    async def fake_context(_profile, *, headless, **_kwargs):
        modes.append(headless)
        yield object()

    async def fake_login(_context, **_kwargs):
        calls.append(("login", modes[-1]))
        if verification_required and modes[-1]:
            raise module.SisCourseInfoAuthenticationError("SIS verification required")
        return page

    async def fake_save(_context, _path):
        calls.append(("save",))

    monkeypatch.setattr(module, "sis_context", fake_context)
    monkeypatch.setattr(module, "open_login_until_authenticated", fake_login)
    monkeypatch.setattr(module, "save_sis_session", fake_save)

    result = SisEnrollmentBrowserGateway(tmp_path).sync()

    assert modes == ([True, False] if verification_required else [True])
    assert calls == [("login", True)] + (
        [("login", False)] if verification_required else []
    ) + [
        ("goto", module.STUDENT_CENTER_URL), ("save",),
    ]
    assert result["courses"][0]["course_code"] == "BMED2206"
    assert SisEnrollmentBrowserGateway(tmp_path).status()["login_status"] == "logged_in"


@pytest.mark.parametrize(
    "auto_login,interactive_login", [(False, True), (True, False)]
)
def test_enrollment_noninteractive_failure_preserves_snapshot(
    tmp_path: Path, monkeypatch, auto_login: bool, interactive_login: bool,
) -> None:
    import hsas.infrastructure.sis.enrollment.client as module

    root = tmp_path / "sis-enrollment"
    root.mkdir()
    snapshot = '{"term":"previous","courses":[{"course_code":"BMED2206"}]}'
    (root / "latest.json").write_text(snapshot)
    modes = []

    @asynccontextmanager
    async def fake_context(_profile, *, headless, **_kwargs):
        modes.append(headless)
        yield object()

    async def fake_login(_context, **_kwargs):
        raise module.SisCourseInfoAuthenticationError("verification required")

    monkeypatch.setattr(module, "sis_context", fake_context)
    monkeypatch.setattr(module, "open_login_until_authenticated", fake_login)

    with pytest.raises(module.SisEnrollmentAuthenticationError, match="sign-in"):
        SisEnrollmentBrowserGateway(tmp_path).sync(
            auto_login=auto_login, interactive_login=interactive_login,
        )

    assert modes == [True]
    assert (root / "latest.json").read_text() == snapshot
    assert SisEnrollmentBrowserGateway(tmp_path).status()["login_status"] == "expired"


def test_enrollment_cancel_does_not_open_recovery_browser(tmp_path: Path, monkeypatch) -> None:
    import hsas.infrastructure.sis.enrollment.client as module

    modes = []
    cancelled = False

    @asynccontextmanager
    async def fake_context(_profile, *, headless, **_kwargs):
        modes.append(headless)
        yield object()

    async def fake_login(_context, **_kwargs):
        nonlocal cancelled
        cancelled = True
        raise module.SisCourseInfoAuthenticationError("verification required")

    monkeypatch.setattr(module, "sis_context", fake_context)
    monkeypatch.setattr(module, "open_login_until_authenticated", fake_login)

    with pytest.raises(InterruptedError, match="cancelled"):
        SisEnrollmentBrowserGateway(tmp_path).sync(cancel_requested=lambda: cancelled)

    assert modes == [True]
    assert not (tmp_path / "sis-enrollment" / "latest.json").exists()
