import json
from email.message import Message
from io import BytesIO
from datetime import datetime
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from hsas.domain.courses.define_courses import (
    CourseActivity,
    CourseArchive,
    CourseInfoV2,
    CourseSectionV2,
    StoredFile,
)
from hsas.domain.courses.define_documents import PdfAnalysis
from hsas.domain.planning.define_plan import (
    AcademicImpact,
    EffortEstimate,
    IntegratedPlan,
    LearningDemand,
    OfficialTiming,
    PlanItem,
    PriorityDecision,
    WorkloadSummary,
)
from hsas.infrastructure.storage.persist_data import write_model
from hsas.interfaces.run_dashboard import (
    ASSET_ROOT,
    DashboardError,
    DashboardRequestHandler,
    DashboardService,
    _load_dashboard_assets,
    _present_dashboard_warnings,
    build_dashboard_server,
)


ZONE = ZoneInfo("Asia/Hong_Kong")


def _write_plan(resources: Path) -> PlanItem:
    stamp = datetime(2026, 9, 1, 8, 0, tzinfo=ZONE)
    item = PlanItem(
        plan_item_id="assessment:1:essay",
        course_id="1",
        course_title="Demo Course",
        item_type="assessment",
        title="Essay",
        official_timing=OfficialTiming(due_on=stamp.date(), is_confirmed=True),
        academic_impact=AcademicImpact(
            importance_level=4,
            importance_rationale="Major work.",
        ),
        learning_demand=LearningDemand(
            difficulty_level=3,
            difficulty_rationale="Writing practice.",
        ),
        effort=EffortEstimate(
            estimated_total_minutes=180,
            completed_minutes=0,
            remaining_minutes=180,
            effort_band="m",
        ),
        priority=PriorityDecision(
            level="high",
            rationale="Due soon.",
            derived_from=["official_timing.due_on"],
        ),
        completion_criteria=["Draft reviewed"],
        created_at=stamp,
        updated_at=stamp,
    )
    write_model(
        resources / "integrated_plan.json",
        IntegratedPlan(
            items=[item],
            workload_summary=WorkloadSummary(
                key_item_count=1,
                total_remaining_minutes=180,
                high_priority_minutes=180,
            ),
        ),
    )
    return item


def _write_course_with_material(resources: Path) -> Path:
    stamp = datetime(2026, 9, 1, 8, 0, tzinfo=ZONE)
    relative_path = "courses/1/files/demo.pdf"
    file_path = resources / relative_path
    file_path.parent.mkdir(parents=True)
    file_path.write_bytes(b"%PDF-1.4\n% demo\n")
    stored_file = StoredFile(
        filename="Lecture 1.pdf",
        relative_path=relative_path,
        source_url="https://moodle.example.edu/pluginfile.php/1/demo.pdf",
        content_type="application/pdf",
        size_bytes=file_path.stat().st_size,
        sha256="0" * 64,
        downloaded_at=stamp,
        analysis=PdfAnalysis(
            status="complete",
            analyzed_at=stamp,
            page_count=2,
            pages_with_text=2,
            word_count=500,
            character_count=2400,
            estimated_reading_minutes=3,
        ),
    )
    archive = CourseArchive(
        collected_at=stamp,
        course=CourseInfoV2(
            course_id="1",
            title="Demo Course",
            url="https://moodle.example.edu/course/view.php?id=1",
            declared_section_count=1,
            returned_section_count=1,
        ),
        sections=[
            CourseSectionV2(
                section_id="10",
                number=1,
                title="Week 1",
                current=True,
                activities=[
                    CourseActivity(
                        module_id="100",
                        name="Lecture 1",
                        category="resource",
                        module="resource",
                        url="https://moodle.example.edu/mod/resource/view.php?id=100",
                        download_status="downloaded",
                        files=[stored_file],
                    )
                ],
            )
        ],
        raw_state_path="courses/1/raw/course-state.json",
    )
    write_model(resources / "courses/1/course.json", archive)
    return file_path


def test_dashboard_assets_are_present() -> None:
    assert (ASSET_ROOT / "index.html").is_file()
    assert (ASSET_ROOT / "styles.css").is_file()
    assert (ASSET_ROOT / "app.js").is_file()
    loaded = _load_dashboard_assets()
    assert b"HKU Study Assistant" in loaded["/"][0]
    assert "日期未确认".encode() in loaded["/"][0]
    assert b'data-info-tab="assessments"' in loaded["/"][0]
    assert b"/api/moodle/session" in loaded["/assets/app.js"][0]
    assert b"renderCourseInformationTab" in loaded["/assets/app.js"][0]
    assert b"courseColorClass" in loaded["/assets/app.js"][0]


def test_dashboard_warnings_explain_missing_status_and_removed_items() -> None:
    warnings = _present_dashboard_warnings(
        [
            "Course 1 has no synchronization status.",
            "Course 2 has no synchronization status.",
            "Items that are no longer key priorities were omitted during refresh: old:item",
        ]
    )

    assert len(warnings) == 2
    assert "2 门课程有本地归档" in warnings[0]
    assert "1、2" in warnings[0]
    assert "不代表事项已经完成" in warnings[1]


def test_moodle_session_actions_are_reported_and_login_requires_confirmation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    service = DashboardService(tmp_path, mutation_lock=Lock())
    session = SimpleNamespace(
        status="logged_out",
        checked_at="2026-09-01T15:00:00+00:00",
        available_course_count=0,
        error=None,
    )
    monkeypatch.setattr("hsas.interfaces.run_dashboard.check_login_status", lambda _: session)

    assert service.check_moodle_session()["status"] == "logged_out"
    with pytest.raises(DashboardError, match="Confirm before opening"):
        service.login_moodle({"confirmed": False})

    logged_in = SimpleNamespace(
        status="logged_in",
        checked_at="2026-09-01T15:01:00+00:00",
        available_course_count=5,
        error=None,
    )
    monkeypatch.setattr("hsas.interfaces.run_dashboard.login_until_ready", lambda _: logged_in)

    result = service.login_moodle({"confirmed": True})

    assert result["status"] == "logged_in"
    assert result["available_course_count"] == 5


def test_course_material_catalog_and_file_resolution_are_archive_scoped(
    tmp_path: Path,
) -> None:
    expected_path = _write_course_with_material(tmp_path)
    service = DashboardService(tmp_path, mutation_lock=Lock())

    catalog = service.course_materials("1")
    resolved_path, stored_file = service.resolve_material_file("1", "100", 0)

    assert catalog["course_title"] == "Demo Course"
    assert catalog["sections"][0]["activities"][0]["files"][0]["available"] is True
    assert catalog["sections"][0]["activities"][0]["files"][0]["analysis"]["page_count"] == 2
    assert resolved_path == expected_path
    assert stored_file.filename == "Lecture 1.pdf"

    with pytest.raises(DashboardError, match="Invalid Moodle course ID"):
        service.course_materials("../1")
    with pytest.raises(DashboardError, match="Unknown course file"):
        service.resolve_material_file("1", "100", 1)


def test_course_information_returns_complete_validated_archive(tmp_path: Path) -> None:
    _write_course_with_material(tmp_path)
    service = DashboardService(tmp_path, mutation_lock=Lock())

    information = service.course_information("1")

    assert information["course_id"] == "1"
    assert information["course_title"] == "Demo Course"
    assert information["course_json"]["schema_version"] == "2.2"
    assert information["course_json"]["sections"][0]["activities"][0]["files"][0][
        "filename"
    ] == "Lecture 1.pdf"


def test_dashboard_snapshot_presents_plan_without_editing_it(tmp_path: Path) -> None:
    _write_plan(tmp_path)
    before = (tmp_path / "integrated_plan.json").read_text(encoding="utf-8")
    service = DashboardService(tmp_path, mutation_lock=Lock())

    snapshot = service.snapshot()

    assert snapshot["summary"]["key_item_count"] == 1
    assert snapshot["summary"]["remaining_minutes"] == 180
    assert snapshot["items"][0]["plan_item_id"] == "assessment:1:essay"
    assert snapshot["items"][0]["due_confirmed"] is True
    assert (tmp_path / "integrated_plan.json").read_text(encoding="utf-8") == before


def test_execution_requires_confirmation_then_uses_validated_service(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_plan(tmp_path)
    service = DashboardService(tmp_path, mutation_lock=Lock())
    payload = {
        "plan_item_id": "assessment:1:essay",
        "record_id": "execution:web:test",
        "planned_minutes": 60,
        "actual_minutes": 75,
        "progress_minutes": 60,
        "completed": False,
        "notes": "Confirmed note",
        "confirmed": False,
    }

    with pytest.raises(DashboardError, match="Confirm the execution record"):
        service.record_execution(payload)
    assert not (tmp_path / "execution_log.json").exists()

    monkeypatch.setattr(
        "hsas.interfaces.run_dashboard.generate_validated_plan",
        lambda _request: object(),
    )
    payload["confirmed"] = True
    result = service.record_execution(payload)
    execution = json.loads((tmp_path / "execution_log.json").read_text(encoding="utf-8"))

    assert result["created"] is True
    assert result["plan_refreshed"] is True
    assert execution["records"][0]["actual_minutes"] == 75
    assert execution["records"][0]["progress_minutes"] == 60


def test_write_request_parser_requires_local_marker() -> None:
    handler = object.__new__(DashboardRequestHandler)
    handler.headers = Message()
    handler.headers["Content-Type"] = "application/json"
    handler.headers["Content-Length"] = "2"
    handler.rfile = BytesIO(b"{}")

    with pytest.raises(DashboardError, match="Missing local request marker"):
        handler._read_json()

    handler.headers["X-HSAS-Request"] = "1"
    assert handler._read_json() == {}


def test_request_host_must_match_loopback_server() -> None:
    handler = object.__new__(DashboardRequestHandler)
    handler.server = SimpleNamespace(server_address=("127.0.0.1", 8765))
    handler.headers = Message()
    handler.headers["Host"] = "malicious.example"

    assert handler._host_is_local() is False

    handler.headers.replace_header("Host", "127.0.0.1:8765")
    assert handler._host_is_local() is True


def test_server_rejects_non_loopback_binding(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="loopback"):
        build_dashboard_server(tmp_path, host="0.0.0.0")
