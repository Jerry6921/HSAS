from email.message import Message
from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
import time

import pytest

from hsas.application.update_information import apply_information_update
from hsas.domain.courses.define_courses import StoredFile
from hsas.domain.courses.define_documents import PdfAnalysis
from hsas.infrastructure.moodle.map_courses import build_course_archive
from hsas.infrastructure.moodle.record_session import record_moodle_session_status
from hsas.infrastructure.storage import JsonInformationRepository
from hsas.infrastructure.storage.persist_data import write_model
from hsas.interfaces.run_dashboard import (
    ASSET_ROOT,
    DashboardError,
    DashboardRequestHandler,
    DashboardService,
    _copy_authenticated_profile,
    _material_type,
    _load_dashboard_assets,
    build_dashboard_server,
)


def test_authenticated_profile_snapshot_excludes_browser_process_locks(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source-profile"
    (source / "Default").mkdir(parents=True)
    (source / "Default" / "Cookies").write_text("session", encoding="utf-8")
    (source / "SingletonLock").write_text("active", encoding="utf-8")

    target = _copy_authenticated_profile(source, tmp_path / "snapshot")

    assert (target / "Default" / "Cookies").read_text(encoding="utf-8") == "session"
    assert not (target / "SingletonLock").exists()
    assert target.stat().st_mode & 0o777 == 0o700


def test_dashboard_assets_include_application_calendar_and_source_preview() -> None:
    assert (ASSET_ROOT / "index.html").is_file()
    assert (ASSET_ROOT / "styles.css").is_file()
    assert (ASSET_ROOT / "app.js").is_file()
    assert (ASSET_ROOT / "ripple.js").is_file()
    assert (ASSET_ROOT / "canvas-effects.js").is_file()
    loaded = _load_dashboard_assets()
    assert b"HKU Information Query System" in loaded["/"][0]
    assert b'id="calendar-grid"' in loaded["/"][0]
    assert b'id="daily-agenda"' in loaded["/"][0]
    assert b'id="day-view-button"' in loaded["/"][0]
    assert b'id="today-button"' not in loaded["/"][0]
    assert b'id="start-workflow"' in loaded["/"][0]
    assert b'id="moodle-login-state"' not in loaded["/"][0]
    assert b'id="enrollment-login-state"' not in loaded["/"][0]
    assert b'id="sis-course-info-login-state"' not in loaded["/"][0]
    assert b'id="class-planner-login-state"' not in loaded["/"][0]
    assert b'id="workflow-cards"' not in loaded["/"][0]
    assert b'id="workflow-summaries"' not in loaded["/"][0]
    assert b'class="loading-spinner"' in loaded["/"][0]
    assert loaded["/"][0].count(b'id="reload-data"') == 1
    assert b'id="sync-courses"' not in loaded["/"][0]
    assert b'id="login-all-sources"' not in loaded["/"][0]
    assert b'id="sync-all-sources"' not in loaded["/"][0]
    assert b'id="course-manager-dialog"' in loaded["/"][0]
    assert b'id="metric-pending"' in loaded["/"][0]
    assert b'id="status-title"' in loaded["/"][0]
    assert b'id="run-ocr"' in loaded["/"][0]
    assert b'id="inbox-list"' in loaded["/"][0]
    assert b'id="course-overview-view"' in loaded["/"][0]
    assert b'id="course-navigation"' in loaded["/"][0]
    assert b'id="show-home"' in loaded["/"][0]
    assert b'id="updates-list"' in loaded["/"][0]
    assert b'id="source-preview"' in loaded["/"][0]
    assert b'id="item-detail-dialog"' in loaded["/"][0]
    assert b'id="close-item-detail"' in loaded["/"][0]
    assert b'id="canvas-effect-toggle"' in loaded["/"][0]
    assert b'id="canvas-ui-output"' in loaded["/"][0]
    assert b'id="next-up-card"' in loaded["/"][0]
    assert b'id="next-up-course"' in loaded["/"][0]
    assert 'target="_blank" rel="noopener noreferrer">打开 Moodle 来源'.encode() in loaded["/"][0]
    assert b'window.location.protocol === "file:"' in loaded["/assets/app.js"][0]
    assert b"/api/information" in loaded["/assets/app.js"][0]
    assert b"/api/source-preview" in loaded["/assets/app.js"][0]
    assert b'"/api/sync/start"' in loaded["/assets/app.js"][0]
    assert b'"/api/sync/status"' in loaded["/assets/app.js"][0]
    assert b'"/api/sync/cancel"' in loaded["/assets/app.js"][0]
    assert b'panel.classList.toggle("hidden", !running)' in loaded["/assets/app.js"][0]
    assert b'panel.classList.toggle("cancelling", cancelling)' in loaded["/assets/app.js"][0]
    assert b'"/api/moodle/status"' not in loaded["/assets/app.js"][0]
    assert b'href="/api/calendar.ics"' in loaded["/"][0]
    assert b'"/api/ocr/run"' in loaded["/assets/app.js"][0]
    assert b'"/api/inbox/apply"' in loaded["/assets/app.js"][0]
    assert b'"/api/courses/add"' in loaded["/assets/app.js"][0]
    assert b'"/api/courses/delete"' in loaded["/assets/app.js"][0]
    assert b"materialTypeLabels" in loaded["/assets/app.js"][0]
    assert b"renderDailyAgenda" in loaded["/assets/app.js"][0]
    assert b"closeItemDetail" in loaded["/assets/app.js"][0]
    assert b'window.open(url, "_blank", "noopener,noreferrer")' in loaded["/assets/app.js"][0]
    assert b'card.target = "_blank"' in loaded["/assets/app.js"][0]
    assert "本轮 ${changeCount} 项差异".encode() not in loaded["/assets/app.js"][0]
    assert b"createRipple" in loaded["/assets/ripple.js"][0]
    assert b"CanvasUIRipple" in loaded["/assets/ripple.js"][0]
    assert b"hiqs-canvas-effects" in loaded["/assets/canvas-effects.js"][0]
    assert b"motion-enabled" in loaded["/assets/canvas-effects.js"][0]
    assert b"IntersectionObserver" in loaded["/assets/canvas-effects.js"][0]
    assert b'".application-card"' in loaded["/assets/canvas-effects.js"][0]
    assert b'".calendar-card"' in loaded["/assets/canvas-effects.js"][0]
    assert b'".course-manager-row"' in loaded["/assets/canvas-effects.js"][0]
    assert b"align-items: flex-start" in loaded["/assets/styles.css"][0]
    assert b"flex-wrap: nowrap" in loaded["/assets/styles.css"][0]
    assert "相关学习材料".encode() in loaded["/assets/app.js"][0]
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
    assert snapshot["material_status"]["counts"]["date_unknown"] == 1
    assert snapshot["personal_inbox"]["pending_count"] == 0
    assert snapshot["class_planner"]["available"] is False
    assert snapshot["moodle_session"]["login_status"] == "login_required"


def test_course_management_adds_and_deletes_canonical_course_data(tmp_path: Path) -> None:
    service = DashboardService(tmp_path)

    with pytest.raises(DashboardError, match="确认"):
        service.add_course({"confirmed": False, "course": {}})

    created = service.add_course(
        {
            "confirmed": True,
            "course": {
                "course_id": "DEMO1001-2026-S1",
                "code": "DEMO1001",
                "title": "Demo Course",
                "moodle_course_id": "12345",
            },
        }
    )
    assert created == {"course_id": "DEMO1001-2026-S1", "created": True}
    apply_information_update(
        tmp_path / "information.json",
        {
            "items": [
                {
                    "item_id": "demo-item",
                    "course_id": "DEMO1001-2026-S1",
                    "title": "Demo item",
                    "category": "other",
                    "date_status": "unknown",
                }
            ]
        },
        confirmed=True,
        repository=JsonInformationRepository(),
    )
    archive = tmp_path / "courses" / "12345"
    archive.mkdir(parents=True)
    (archive / "material.pdf").write_bytes(b"demo")

    with pytest.raises(DashboardError, match="确认"):
        service.delete_course(
            {
                "confirmed": True,
                "confirmation": "wrong-course",
                "course_id": "DEMO1001-2026-S1",
            }
        )

    deleted = service.delete_course(
        {
            "confirmed": True,
            "confirmation": "DEMO1001-2026-S1",
            "course_id": "DEMO1001-2026-S1",
        }
    )
    assert deleted["deleted_item_count"] == 1
    assert deleted["files_moved_to_trash"] is True
    store = JsonInformationRepository().load(tmp_path / "information.json")
    assert store.courses == []
    assert store.items == []
    assert not archive.exists()
    assert list((tmp_path / ".trash" / "courses").glob("*-12345/material.pdf"))


def test_ocr_action_requires_confirmation_and_reports_results(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[Path] = []

    def run(resources: Path):
        calls.append(resources)
        return {
            "processed_count": 2,
            "failed_count": 1,
            "processed": [],
            "failures": [],
        }

    monkeypatch.setattr("hsas.interfaces.run_dashboard.run_ocr_queue", run)
    service = DashboardService(tmp_path)

    with pytest.raises(DashboardError, match="确认"):
        service.process_ocr_queue({"confirmed": False})

    result = service.process_ocr_queue({"confirmed": True})

    assert result["processed_count"] == 2
    assert result["failed_count"] == 1
    assert calls == [tmp_path]


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


def test_class_planner_actions_require_confirmation_and_report_differences(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[str] = []

    class Service:
        def login_until_ready(self):
            calls.append("login")
            return SimpleNamespace(
                status="logged_in",
                checked_at="2026-09-06T12:00:00+00:00",
                course_count=5,
                term_ids=("4261",),
                error=None,
            )

        def sync(self):
            calls.append("sync")
            return SimpleNamespace(
                status="synced",
                synced_at="2026-09-06T12:01:00+00:00",
                course_count=5,
                meeting_count=8,
                term_ids=("4261",),
                changed=True,
                added_course_ids=("new",),
                modified_course_ids=("changed",),
                removed_course_ids=(),
            )

    monkeypatch.setattr(
        "hsas.interfaces.run_dashboard._class_planner_service",
        lambda _resources: Service(),
    )
    service = DashboardService(tmp_path)

    with pytest.raises(DashboardError, match="确认"):
        service.login_class_planner({"confirmed": False})
    with pytest.raises(DashboardError, match="确认"):
        service.synchronize_class_planner({"confirmed": False})

    login = service.login_class_planner({"confirmed": True})
    sync = service.synchronize_class_planner({"confirmed": True})

    assert login["course_count"] == 5
    assert sync["meeting_count"] == 8
    assert sync["added_course_count"] == 1
    assert sync["modified_course_count"] == 1
    assert calls == ["login", "sync"]


def test_course_workflow_reports_progress_and_can_cancel(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class EnrollmentGateway:
        def sync(self, *, auto_login):
            time.sleep(0.02)
            return {
                "term": "2026-27 Semester 1",
                "courses": [
                    {
                        "course_code": "BMED2206",
                        "subject_area": "BMED",
                        "catalogue_number": "2206",
                        "title": "Engineering in Biology and Medicine",
                    }
                ],
            }

    class PlannerService:
        def login_until_ready(self):
            time.sleep(0.02)

    monkeypatch.setattr(
        "hsas.interfaces.run_dashboard._sis_enrollment_gateway",
        lambda _resources: EnrollmentGateway(),
    )
    monkeypatch.setattr(
        "hsas.interfaces.run_dashboard._class_planner_service",
        lambda _resources: PlannerService(),
    )
    service = DashboardService(tmp_path)
    started = service.start_course_sync({"confirmed": True})
    assert started["state"] == "running"
    cancelled = service.cancel_course_sync({"confirmed": True})
    assert cancelled["cancel_requested"] is True
    assert cancelled["detail"] == "正在取消"
    for _ in range(100):
        status = service.course_sync_status()
        if status["state"] != "running":
            break
        time.sleep(0.005)
    assert status["state"] == "cancelled"
    assert status["detail"] == "同步已取消"
    assert status["cards"] == []


def test_course_workflow_collects_authenticated_sources_concurrently(
    tmp_path: Path,
    monkeypatch,
) -> None:
    rendezvous = Barrier(3)
    source_profiles: dict[str, Path] = {}

    class EnrollmentGateway:
        def sync(self, *, auto_login):
            assert auto_login is True
            return {
                "term": "2026-27 Semester 1",
                "courses": [
                    {
                        "course_code": "BMED2206",
                        "subject_area": "BMED",
                        "catalogue_number": "2206",
                        "title": "Engineering in Biology and Medicine",
                    }
                ],
            }

    class MoodleService:
        def __init__(self, profile_dir):
            if profile_dir is not None:
                source_profiles["moodle"] = profile_dir

        def check_login_status(self):
            return SimpleNamespace(status="logged_in")

        def list_courses(self):
            return SimpleNamespace(
                available=(
                    SimpleNamespace(
                        title="BMED2206 Engineering in Biology and Medicine",
                        course_id="138096",
                    ),
                )
            )

        def sync_course(self, _course_id):
            rendezvous.wait(timeout=1)
            return SimpleNamespace()

    class SisService:
        def __init__(self, profile_dir):
            source_profiles["sis"] = profile_dir

        def sync(
            self,
            *,
            selected_courses,
            progress_callback,
            timeout_seconds,
            cancel_requested,
        ):
            assert selected_courses[0]["course_code"] == "BMED2206"
            assert timeout_seconds == 30
            assert cancel_requested() is False
            rendezvous.wait(timeout=1)
            progress_callback(
                {"course_code": "BMED2206", "completed": 1, "total": 1}
            )
            return SimpleNamespace(failures=())

    class PlannerService:
        def __init__(self, profile_dir):
            if profile_dir is not None:
                source_profiles["class-planner"] = profile_dir

        def login_until_ready(self):
            return SimpleNamespace(status="logged_in")

        def sync(self):
            rendezvous.wait(timeout=1)
            return SimpleNamespace(course_count=1)

    def copy_profile(_source, target):
        target.mkdir(parents=True)
        return target

    monkeypatch.setattr(
        "hsas.interfaces.run_dashboard.hku_portal_profile_dir",
        lambda _resources: tmp_path / "browser-profile",
    )
    monkeypatch.setattr(
        "hsas.interfaces.run_dashboard._copy_authenticated_profile",
        copy_profile,
    )
    monkeypatch.setattr(
        "hsas.interfaces.run_dashboard._sis_enrollment_gateway",
        lambda _resources: EnrollmentGateway(),
    )
    monkeypatch.setattr(
        "hsas.interfaces.run_dashboard._course_service",
        lambda _resources, *, profile_dir=None: MoodleService(profile_dir),
    )
    monkeypatch.setattr(
        "hsas.interfaces.run_dashboard._sis_course_info_service",
        lambda _resources, *, profile_dir=None: SisService(profile_dir),
    )
    monkeypatch.setattr(
        "hsas.interfaces.run_dashboard._class_planner_service",
        lambda _resources, *, profile_dir=None: PlannerService(profile_dir),
    )

    service = DashboardService(tmp_path)
    service.start_course_sync({"confirmed": True})
    for _ in range(200):
        status = service.course_sync_status()
        if status["state"] != "running":
            break
        time.sleep(0.005)

    assert status["state"] == "completed"
    assert status["detail"] == "同步完成"
    assert status["result"]["source_failures"] == []
    assert set(source_profiles) == {"moodle", "sis", "class-planner"}
    assert len(set(source_profiles.values())) == 3


def test_moodle_session_verification_replaces_stale_logged_in_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    record_moodle_session_status(tmp_path, "logged_in", available_course_count=8)

    class Service:
        def check_login_status(self):
            record_moodle_session_status(tmp_path, "expired")
            return SimpleNamespace(status="logged_out", error=None)

    monkeypatch.setattr(
        "hsas.interfaces.run_dashboard._course_service",
        lambda _resources: Service(),
    )

    status = DashboardService(tmp_path).verify_moodle_session()

    assert status["login_status"] == "expired"
    assert status["available_course_count"] == 0
    assert status["verification_deferred"] is False


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
        analysis=PdfAnalysis(
            status="complete",
            extraction_method="pptx_xml",
            document_kind="pptx",
            unit_label="slide",
            analyzed_at=archive.collected_at,
            page_count=2,
            pages_with_text=2,
            word_count=6,
            character_count=42,
            estimated_reading_minutes=1,
            extracted_text_path="courses/138907/analysis/lecture-1.txt",
        ),
    )
    activity.files = [stored_file]
    material_path = tmp_path / stored_file.relative_path
    material_path.parent.mkdir(parents=True)
    material_path.write_bytes(b"slides")
    text_path = tmp_path / "courses/138907/analysis/lecture-1.txt"
    text_path.parent.mkdir(parents=True)
    text_path.write_text(
        "--- Slide 1 ---\nLimits introduction\n\n--- Slide 2 ---\nSandwich theorem",
        encoding="utf-8",
    )
    write_model(tmp_path / "courses/138907/course.json", archive)
    before_ai = DashboardService(tmp_path).information_snapshot()
    assert before_ai["available"] is False
    assert before_ai["courses"][0]["moodle_course_id"] == "138907"
    assert before_ai["courses"][0]["materials"]["learning"]
    assert (
        before_ai["courses"][0]["materials"]["learning"][0]["change_action"]
        == "baseline"
    )
    assert before_ai["updates"]["courses"][0]["mode"] == "full"
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
    preview = service.source_preview(stored_file.relative_path, [2])
    assert preview["preview_kind"] == "text"
    assert "Sandwich theorem" in preview["text"]
    assert "Limits introduction" not in preview["text"]
    with pytest.raises(DashboardError, match="当前课程快照"):
        service.material_file("information.json")
    with pytest.raises(DashboardError, match="当前课程快照"):
        service.source_preview("information.json")


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
