from email.message import Message
from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hsas.application.update_information import apply_information_update
from hsas.domain.courses.define_courses import StoredFile
from hsas.infrastructure.moodle.map_courses import build_course_archive
from hsas.infrastructure.storage import JsonInformationRepository
from hsas.infrastructure.storage.persist_data import write_model
from hsas.interfaces.run_dashboard import (
    ASSET_ROOT,
    DashboardError,
    DashboardRequestHandler,
    DashboardService,
    _material_type,
    _load_dashboard_assets,
    build_dashboard_server,
)


def test_dashboard_assets_are_calendar_only() -> None:
    assert (ASSET_ROOT / "index.html").is_file()
    assert (ASSET_ROOT / "styles.css").is_file()
    assert (ASSET_ROOT / "app.js").is_file()
    loaded = _load_dashboard_assets()
    assert b"HKU Information Query System" in loaded["/"][0]
    assert b'id="calendar-grid"' in loaded["/"][0]
    assert b'id="login-moodle"' in loaded["/"][0]
    assert b'id="sync-courses"' in loaded["/"][0]
    assert b'id="metric-pending"' in loaded["/"][0]
    assert b'id="course-overview-view"' in loaded["/"][0]
    assert b'id="course-navigation"' in loaded["/"][0]
    assert b"/api/information" in loaded["/assets/app.js"][0]
    assert b"/api/moodle/login" in loaded["/assets/app.js"][0]
    assert b'"/api/sync"' in loaded["/assets/app.js"][0]
    assert b"materialTypeLabels" in loaded["/assets/app.js"][0]
    assert "由 AI 根据已下载课程资料归纳".encode() in loaded["/assets/app.js"][0]


def test_information_snapshot_handles_missing_and_valid_database(tmp_path: Path) -> None:
    service = DashboardService(tmp_path)
    assert service.information_snapshot()["available"] is False
    apply_information_update(
        tmp_path / "information.json",
        {
            "courses": [{"course_id": "1", "code": "DEMO1001", "title": "Demo"}],
            "items": [
                {
                    "item_id": "demo-deadline",
                    "course_id": "1",
                    "title": "Demo deadline",
                    "category": "deadline",
                    "date_status": "unknown",
                }
            ],
        },
        confirmed=True,
        repository=JsonInformationRepository(),
    )
    snapshot = service.information_snapshot()
    assert snapshot["available"] is True
    assert snapshot["summary"] == {
        "course_count": 1,
        "item_count": 1,
        "calendar_item_count": 0,
        "unknown_date_count": 1,
    }


def test_request_host_must_match_loopback_server() -> None:
    handler = object.__new__(DashboardRequestHandler)
    handler.server = SimpleNamespace(server_address=("127.0.0.1", 8765))
    handler.headers = Message()
    handler.headers["Host"] = "malicious.example"
    assert handler._host_is_local() is False
    handler.headers.replace_header("Host", "127.0.0.1:8765")
    assert handler._host_is_local() is True


def test_moodle_actions_require_confirmation_and_report_results(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[str] = []

    class Service:
        def login_until_ready(self):
            calls.append("login")
            return SimpleNamespace(
                status="logged_in",
                checked_at="2026-09-04T12:00:00+00:00",
                available_course_count=3,
                error=None,
            )

        def sync_all(self):
            calls.append("sync")
            return SimpleNamespace(
                discovered_course_count=3,
                succeeded_course_ids=("1", "2"),
                failures=({"course_id": "3", "error": "denied"},),
                report_path=tmp_path / "sync-report.json",
            )

    monkeypatch.setattr(
        "hsas.interfaces.run_dashboard._course_service",
        lambda _resources: Service(),
    )
    service = DashboardService(tmp_path)

    with pytest.raises(DashboardError, match="确认"):
        service.login_moodle({"confirmed": False})
    with pytest.raises(DashboardError, match="确认"):
        service.synchronize_courses({"confirmed": False})

    login = service.login_moodle({"confirmed": True})
    sync = service.synchronize_courses({"confirmed": True})

    assert login["available_course_count"] == 3
    assert sync["succeeded_course_count"] == 2
    assert sync["failed_course_count"] == 1
    assert calls == ["login", "sync"]


def test_write_request_requires_local_marker() -> None:
    handler = object.__new__(DashboardRequestHandler)
    handler.headers = Message()
    handler.headers["Content-Type"] = "application/json"
    body = b'{"confirmed":true}'
    handler.headers["Content-Length"] = str(len(body))
    handler.rfile = BytesIO(body)

    with pytest.raises(DashboardError, match="本地请求标记"):
        handler._read_json()

    handler.headers["X-HIQS-Request"] = "1"
    assert handler._read_json() == {"confirmed": True}


def test_server_rejects_non_loopback_binding(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="loopback"):
        build_dashboard_server(tmp_path, host="0.0.0.0")


def test_course_overview_combines_ai_facts_and_local_moodle_materials(
    tmp_path: Path,
) -> None:
    state = json.loads(
        (Path(__file__).parent / "fixtures/course_state.json").read_text()
    )
    archive = build_course_archive(
        state,
        course_title="DEMO1001 Demo Course",
        raw_state_path="courses/138907/raw/course-state.json",
    )
    archive.collected_at = datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc)
    activity = archive.sections[0].activities[1]
    activity.name = "Lecture 1 slides"
    stored_file = StoredFile(
        filename="lecture-1.pptx",
        relative_path="courses/138907/files/lecture-1.pptx",
        source_url="https://moodle.example.edu/pluginfile.php/lecture-1.pptx",
        content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        size_bytes=5,
        sha256="a" * 64,
        downloaded_at=archive.collected_at,
    )
    activity.files = [stored_file]
    material_path = tmp_path / stored_file.relative_path
    material_path.parent.mkdir(parents=True)
    material_path.write_bytes(b"slides")
    write_model(tmp_path / "courses/138907/course.json", archive)
    before_ai = DashboardService(tmp_path).information_snapshot()
    assert before_ai["available"] is False
    assert before_ai["courses"][0]["moodle_course_id"] == "138907"
    assert before_ai["courses"][0]["materials"]["learning"]
    assert (
        before_ai["courses"][0]["materials"]["learning"][0]["change_action"]
        == "baseline"
    )
    apply_information_update(
        tmp_path / "information.json",
        {
            "courses": [
                {
                    "course_id": "DEMO1001-2026-S1",
                    "moodle_course_id": "138907",
                    "code": "DEMO1001",
                    "title": "Demo Course",
                    "overview": "A concise official overview.",
                    "objectives": ["Understand the core methods"],
                }
            ],
            "items": [
                {
                    "item_id": "demo-assignment",
                    "course_id": "DEMO1001-2026-S1",
                    "title": "Assignment",
                    "category": "assignment",
                    "weight_percent": 30,
                }
            ],
        },
        confirmed=True,
        repository=JsonInformationRepository(),
    )

    service = DashboardService(tmp_path)
    snapshot = service.information_snapshot()
    course = snapshot["courses"][0]

    assert len(snapshot["courses"]) == 1
    assert course["course_id"] == "DEMO1001-2026-S1"
    assert course["moodle_course_id"] == "138907"
    assert course["overview"] == "A concise official overview."
    assert course["objectives"] == ["Understand the core methods"]
    assert course["grade_distribution"][0]["item_id"] == "demo-assignment"
    assert course["materials"]["learning"][0]["title"] == "lecture-1.pptx"
    assert course["materials"]["learning"][0]["material_type"] == "lecture"
    assert course["materials"]["information"]
    assert service.material_file(stored_file.relative_path)[0] == material_path
    with pytest.raises(DashboardError, match="当前课程快照"):
        service.material_file("information.json")


@pytest.mark.parametrize(
    ("activity_name", "filename", "category", "section", "expected"),
    [
        ("Lecture 3", "slides.pdf", "resource", "Week 3", "lecture"),
        ("Tutorial 2", "tutorial.pdf", "resource", "Week 2", "tutorial"),
        ("Week 4 notes", "notes.docx", "resource", "Week 4", "notes"),
        ("Problem Set 1", "questions.pdf", "resource", "Practice", "exercises"),
        ("Course syllabus", "syllabus.pdf", "resource", "General", "course_information"),
        ("Assignment 1", "brief.pdf", "assignment", "Assessment", "assessment"),
        ("Research paper", "reading.pdf", "assignment", "Week 5", "assessment"),
    ],
)
def test_material_type_uses_moodle_context(
    activity_name: str,
    filename: str,
    category: str,
    section: str,
    expected: str,
) -> None:
    assert _material_type(activity_name, filename, category, section) == expected
