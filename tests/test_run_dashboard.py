from email.message import Message
from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
import time

import pytest

from hsas.application.update_information import apply_information_update
from hsas.application.synchronize_unified_courses import UnifiedCourseSyncResult
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
    _load_dashboard_assets,
    build_dashboard_server,
)
from hsas.ui.run_dashboard import _material_content_security_policy


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
    assert b'id="week-view-button"' in loaded["/"][0]
    assert b'id="weekly-agenda"' in loaded["/"][0]
    assert b'id="add-event-button"' in loaded["/"][0]
    assert b'id="event-editor-dialog"' in loaded["/"][0]
    assert b'id="today-button"' in loaded["/"][0]
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
    assert b'id="show-reconciliation"' in loaded["/"][0]
    assert b'id="reconciliation-view"' in loaded["/"][0]
    assert b'id="copy-agent-prompt"' in loaded["/"][0]
    assert b'id="retry-failures"' in loaded["/"][0]
    assert b'id="updates-list"' in loaded["/"][0]
    assert b'id="source-preview"' in loaded["/"][0]
    assert b'id="item-detail-dialog"' in loaded["/"][0]
    assert b'id="close-item-detail"' in loaded["/"][0]
    assert b'id="canvas-effect-toggle"' in loaded["/"][0]
    assert b'id="app-update"' in loaded["/"][0]
    assert loaded["/"][0].index(b'id="app-update"') < loaded["/"][0].index(
        b'id="canvas-effect-toggle"'
    )
    assert b'id="canvas-ui-output"' in loaded["/"][0]
    assert b'id="next-up-card"' in loaded["/"][0]
    assert b'id="next-up-course"' in loaded["/"][0]
    assert 'target="_blank" rel="noopener noreferrer">打开 Moodle 来源'.encode() in loaded["/"][0]
    assert b'window.location.protocol === "file:"' in loaded["/assets/app.js"][0]
    assert b"/api/information" in loaded["/assets/app.js"][0]
    assert b"/api/source-preview" in loaded["/assets/app.js"][0]
    assert "PDF 预览为空？查看已提取文本".encode() in loaded["/assets/app.js"][0]
    assert b'"/api/sync/start"' in loaded["/assets/app.js"][0]
    assert b'"/api/sync/status"' in loaded["/assets/app.js"][0]
    assert b'"/api/sync/cancel"' in loaded["/assets/app.js"][0]
    assert b'"/api/sync/retry"' in loaded["/assets/app.js"][0]
    assert b'"/api/update/status"' in loaded["/assets/app.js"][0]
    assert b'"/api/update/apply"' in loaded["/assets/app.js"][0]
    assert b"target_commit: update.target_commit" in loaded["/assets/app.js"][0]
    assert b'panel.classList.toggle("hidden", !running)' in loaded["/assets/app.js"][0]
    assert b'panel.classList.toggle("cancelling", cancelling)' in loaded["/assets/app.js"][0]
    assert b'"/api/moodle/status"' not in loaded["/assets/app.js"][0]
    assert b'href="/api/calendar.ics"' in loaded["/"][0]
    assert b'"/api/ocr/run"' in loaded["/assets/app.js"][0]
    assert b'"/api/inbox/apply"' in loaded["/assets/app.js"][0]
    assert b'"/api/courses/add"' in loaded["/assets/app.js"][0]
    assert b'"/api/courses/delete"' in loaded["/assets/app.js"][0]
    assert b'"/api/courses/delete-many"' in loaded["/assets/app.js"][0]
    assert b'"/api/events/add"' in loaded["/assets/app.js"][0]
    assert b'"/api/events/delete"' in loaded["/assets/app.js"][0]
    assert b'id="course-manager-select-all"' in loaded["/"][0]
    assert b'id="delete-selected-courses"' in loaded["/"][0]
    assert b"overflow-y: auto" in loaded["/assets/styles.css"][0]
    assert "复制最近 Lecture 提示词".encode() in loaded["/assets/app.js"][0]
    assert "复制 AI 提示词".encode() in loaded["/assets/app.js"][0]
    assert b"materialPalettes" in loaded["/assets/app.js"][0]
    assert b'--material-color' in loaded["/assets/app.js"][0]
    assert b'class: "#a45e48"' in loaded["/assets/app.js"][0]
    assert b"Paper-card unification" in loaded["/assets/styles.css"][0]
    assert b"background: #fffaf3 !important" in loaded["/assets/styles.css"][0]
    assert b".unscheduled-item strong { color: #332d29; }" in loaded["/assets/styles.css"][0]
    assert b".course-item-group { animation: panel-settle" in loaded["/assets/styles.css"][0]
    assert b".material-subgroup-heading h3, .material-subgroup-heading h4" in loaded["/assets/styles.css"][0]
    assert b"font-weight: 760" in loaded["/assets/styles.css"][0]
    assert b"Unified warm hover feedback for every actionable button" in loaded["/assets/styles.css"][0]
    assert b"button:not(:disabled):hover, a.button:hover" in loaded["/assets/styles.css"][0]
    assert b"0 10px 24px rgba(111, 65, 47, .14)" in loaded["/assets/styles.css"][0]
    assert b"button:not(:disabled):not(.next-up-card):not(.material-card-main):hover" in loaded["/assets/styles.css"][0]
    assert b"button.material-card-main:hover" in loaded["/assets/styles.css"][0]
    assert b".detail-panel h2, .detail-facts dd" in loaded["/assets/styles.css"][0]
    assert b"@keyframes detail-geometry" in loaded["/assets/styles.css"][0]
    assert b"@keyframes shell-geometry" in loaded["/assets/styles.css"][0]
    assert b'id="query-controls" class="calendar-query-panel hidden"' in loaded["/"][0]
    assert b'view !== "calendar"' in loaded["/assets/app.js"][0]
    assert b".calendar-query-panel .search-field input:focus" in loaded["/assets/styles.css"][0]
    assert b'id="view-transition"' not in loaded["/"][0]
    assert b"playViewTransition" not in loaded["/assets/app.js"][0]
    assert b"@keyframes view-flow-left" not in loaded["/assets/styles.css"][0]
    assert b".motion-reveal.motion-visible { opacity: 1; transition: none; }" in loaded["/assets/styles.css"][0]
    assert "待 AI 分类".encode() in loaded["/assets/app.js"][0]
    assert b"renderDailyAgenda" in loaded["/assets/app.js"][0]
    assert b"renderWeeklyAgenda" in loaded["/assets/app.js"][0]
    assert b"openEventEditorFromGrid" in loaded["/assets/app.js"][0]
    assert "双击空白时段即可添加事件".encode() in loaded["/"][0]
    assert b".week-timeline" in loaded["/assets/styles.css"][0]
    assert b"closeItemDetail" in loaded["/assets/app.js"][0]
    assert b'window.open(url, "_blank", "noopener,noreferrer")' in loaded["/assets/app.js"][0]
    assert b'main.target = "_blank"' in loaded["/assets/app.js"][0]
    assert "本轮 ${changeCount} 项差异".encode() not in loaded["/assets/app.js"][0]
    assert b"createRipple" in loaded["/assets/ripple.js"][0]
    assert b"HIQSModernCalendar" in loaded["/assets/modern-ui.js"][0]
    assert b"--hiqs-rust" in loaded["/assets/modern-ui.css"][0]
    assert b'id="modern-calendar-root"' in loaded["/"][0]
    assert b'name="csp-nonce" content="hiqs-local-ui"' in loaded["/"][0]
    assert b'src="assets/modern-ui.js"' in loaded["/"][0]
    assert b"modernCalendar.mount" in loaded["/assets/app.js"][0]
    assert b"CanvasUIRipple" in loaded["/assets/ripple.js"][0]
    assert b"hiqs-canvas-effects" in loaded["/assets/canvas-effects.js"][0]
    assert b"motion-enabled" in loaded["/assets/canvas-effects.js"][0]
    assert b".motion-enabled .motion-surface:not(.agenda-item)" in loaded["/assets/styles.css"][0]
    assert b".motion-enabled .motion-surface { position: relative; }" not in loaded["/assets/styles.css"][0]
    assert b"IntersectionObserver" in loaded["/assets/canvas-effects.js"][0]
    assert b'".application-card"' in loaded["/assets/canvas-effects.js"][0]
    assert b'".calendar-card"' in loaded["/assets/canvas-effects.js"][0]
    assert b'".course-manager-row"' in loaded["/assets/canvas-effects.js"][0]
    assert b"align-items: flex-start" in loaded["/assets/styles.css"][0]
    assert b"flex-wrap: nowrap" in loaded["/assets/styles.css"][0]
    assert "相关学习材料".encode() in loaded["/assets/app.js"][0]
    assert "由 AI 根据已下载课程资料归纳".encode() in loaded["/assets/app.js"][0]
    assert b'courseContentMode: "materials"' in loaded["/assets/app.js"][0]
    assert '[["materials", "课件"], ["activities", "活动"]]'.encode() in loaded[
        "/assets/app.js"
    ][0]
    assert b"renderCourseItems" in loaded["/assets/app.js"][0]
    assert b"categoryColors" in loaded["/assets/app.js"][0]
    assert b".course-content-switch" in loaded["/assets/styles.css"][0]
    assert b".course-item-row" in loaded["/assets/styles.css"][0]
    assert b".material-card.course-item-row:focus-within" in loaded["/assets/styles.css"][0]
    assert b"border-color: color-mix(in srgb, var(--item-color) 66%, #d8c8be)" in loaded[
        "/assets/styles.css"
    ][0]
    assert "活动查询提示词已复制".encode() in loaded["/assets/app.js"][0]
    assert b".event-date-status.confirmed" in loaded["/assets/styles.css"][0]
    assert b'".course-item-row"' not in loaded["/assets/canvas-effects.js"][0]
    assert b"event-card-heading" in loaded["/assets/app.js"][0]
    assert b"event-date-status" in loaded["/assets/app.js"][0]
    assert b'titleLine.append(element("span", "material-type-badge"' not in loaded[
        "/assets/app.js"
    ][0]


def test_material_preview_csp_keeps_native_pdf_viewer_out_of_sandbox() -> None:
    pdf_policy = _material_content_security_policy("application/pdf")
    image_policy = _material_content_security_policy("image/png")
    document_policy = _material_content_security_policy(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

    assert "sandbox" not in pdf_policy
    assert "sandbox" not in image_policy
    assert document_policy.startswith("sandbox;")
    assert "frame-ancestors 'self'" in pdf_policy


def test_application_update_delegates_to_safe_update_service(tmp_path: Path) -> None:
    class FakeUpdateService:
        def status(self) -> dict[str, object]:
            return {
                "status": "current",
                "current_version": "2.7.0",
                "latest_version": "2.7.0",
            }

        def apply(self, *, confirmed: bool, target_commit: str) -> dict[str, object]:
            assert confirmed is True
            assert target_commit == "1" * 40
            return {"status": "updated", "current_version": "2.8.0"}

    service = DashboardService(tmp_path, update_service=FakeUpdateService())  # type: ignore[arg-type]

    assert service.application_update_status()["status"] == "current"
    assert service.apply_application_update(
        {"confirmed": True, "target_commit": "1" * 40}
    )["status"] == "updated"

    with pytest.raises(DashboardError, match="确认"):
        service.apply_application_update({"confirmed": False})


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
    assert snapshot["review_closure"]["agent_prompt"].startswith("请处理本机 HIQS")
    assert snapshot["course_reconciliation"]["counts"]["legacy"] == 1
    assert snapshot["course_reconciliation"]["source_order"][0] == "moodle"
    assert "Moodle" in snapshot["course_reconciliation"]["authority_note"]


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


def test_course_management_batch_deletes_selected_courses(tmp_path: Path) -> None:
    service = DashboardService(tmp_path)
    for index in (1, 2):
        service.add_course(
            {
                "confirmed": True,
                "course": {
                    "course_id": f"DEMO100{index}",
                    "code": f"DEMO100{index}",
                    "title": f"Demo Course {index}",
                    "moodle_course_id": str(12000 + index),
                },
            }
        )
        archive = tmp_path / "courses" / str(12000 + index)
        archive.mkdir(parents=True)
        (archive / "material.pdf").write_bytes(b"demo")

    apply_information_update(
        tmp_path / "information.json",
        {
            "items": [
                {
                    "item_id": f"demo-item-{index}",
                    "course_id": f"DEMO100{index}",
                    "title": f"Demo item {index}",
                    "category": "other",
                    "date_status": "unknown",
                }
                for index in (1, 2)
            ]
        },
        confirmed=True,
        repository=JsonInformationRepository(),
    )
    course_ids = ["DEMO1001", "DEMO1002"]

    with pytest.raises(DashboardError, match="确认"):
        service.delete_courses(
            {"confirmed": True, "confirmation": list(reversed(course_ids)), "course_ids": course_ids}
        )

    deleted = service.delete_courses(
        {"confirmed": True, "confirmation": course_ids, "course_ids": course_ids}
    )

    assert deleted["deleted_course_count"] == 2
    assert deleted["deleted_item_count"] == 2
    assert deleted["files_moved_to_trash"] == 2
    store = JsonInformationRepository().load(tmp_path / "information.json")
    assert store.courses == []
    assert store.items == []


def test_user_calendar_event_add_and_guarded_delete(tmp_path: Path) -> None:
    service = DashboardService(tmp_path)
    service.add_course(
        {
            "confirmed": True,
            "course": {
                "course_id": "DEMO1001",
                "code": "DEMO1001",
                "title": "Demo Course",
            },
        }
    )

    with pytest.raises(DashboardError, match="确认"):
        service.add_calendar_event({"confirmed": False, "event": {}})

    created = service.add_calendar_event(
        {
            "confirmed": True,
            "event": {
                "course_id": "DEMO1001",
                "title": "Study meeting",
                "category": "other",
                "starts_at": "2026-09-22T09:00:00+08:00",
                "ends_at": "2026-09-22T10:00:00+08:00",
                "location": "Library",
            },
        }
    )
    snapshot = service.information_snapshot()
    created_item = next(
        item for item in snapshot["items"] if item["item_id"] == created["item_id"]
    )
    assert created_item["user_created"] is True
    assert created_item["location"] == "Library"

    with pytest.raises(DashboardError, match="确认"):
        service.delete_calendar_event(
            {
                "confirmed": True,
                "confirmation": "wrong-item",
                "item_id": created["item_id"],
            }
        )

    deleted = service.delete_calendar_event(
        {
            "confirmed": True,
            "confirmation": created["item_id"],
            "item_id": created["item_id"],
        }
    )
    assert deleted["deleted"] is True
    assert (tmp_path / deleted["recoverable_from"]).is_file()
    assert JsonInformationRepository().load(tmp_path / "information.json").items == []

    apply_information_update(
        tmp_path / "information.json",
        {
            "items": [
                {
                    "item_id": "official-item",
                    "course_id": "DEMO1001",
                    "title": "Official event",
                    "category": "class",
                    "date_status": "unknown",
                    "sources": [{"source_type": "moodle", "title": "Moodle"}],
                }
            ]
        },
        confirmed=True,
        repository=JsonInformationRepository(),
    )
    with pytest.raises(DashboardError, match="只能删除"):
        service.delete_calendar_event(
            {
                "confirmed": True,
                "confirmation": "official-item",
                "item_id": "official-item",
            }
        )


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

    monkeypatch.setattr("hsas.core.implement_port.run_ocr_queue", run)
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
        "hsas.core.implement_port._course_service",
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
        "hsas.core.implement_port._class_planner_service",
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
        def sync(self, *, auto_login, **_kwargs):
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
        def login_until_ready(self, *, cancel_requested):
            while not cancel_requested():
                time.sleep(0.005)
            raise InterruptedError("cancelled")

    monkeypatch.setattr(
        "hsas.core.implement_port._sis_enrollment_gateway",
        lambda _resources: EnrollmentGateway(),
    )
    monkeypatch.setattr(
        "hsas.core.implement_port._class_planner_service",
        lambda _resources: PlannerService(),
    )
    service = DashboardService(tmp_path)
    started = service.start_course_sync({"confirmed": True})
    assert started["state"] == "running"
    cancelled_at = time.monotonic()
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
    assert time.monotonic() - cancelled_at < 0.5


def test_course_workflow_collects_authenticated_sources_concurrently(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class EnrollmentGateway:
        def sync(self, *, auto_login, **_kwargs):
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
        def check_login_status(self):
            return SimpleNamespace(status="logged_in")

    class PlannerService:
        def login_until_ready(self, **_kwargs):
            return SimpleNamespace(status="logged_in")

    class UnifiedService:
        async def synchronize(
            self,
            courses,
            *,
            progress_callback,
            cancel_requested,
        ):
            assert courses[0]["course_code"] == "BMED2206"
            assert cancel_requested() is False
            for stage, total in (("moodle", 1), ("sis_course_info", 1), ("timetable", 1)):
                progress_callback(
                    {
                        "stage": stage,
                        "processed": total,
                        "completed": total,
                        "failed": 0,
                        "total": total,
                        "detail": stage,
                    }
                )
            return UnifiedCourseSyncResult(
                {"completed": 1, "failures": []},
                SimpleNamespace(failures=()),
                SimpleNamespace(course_count=1),
            )

    monkeypatch.setattr(
        "hsas.core.implement_port._sis_enrollment_gateway",
        lambda _resources: EnrollmentGateway(),
    )
    monkeypatch.setattr(
        "hsas.core.implement_port._course_service",
        lambda _resources, *, profile_dir=None: MoodleService(),
    )
    monkeypatch.setattr(
        "hsas.core.implement_port._class_planner_service",
        lambda _resources, *, profile_dir=None: PlannerService(),
    )
    monkeypatch.setattr(
        "hsas.core.implement_port._unified_course_sync_service",
        lambda _resources: UnifiedService(),
    )

    service = DashboardService(tmp_path)
    service.start_course_sync({"confirmed": True})
    for _ in range(200):
        status = service.course_sync_status()
        if status["state"] != "running":
            break
        time.sleep(0.005)

    assert status["state"] == "completed"


def test_course_workflow_retries_only_failed_source_course(
    tmp_path: Path,
    monkeypatch,
) -> None:
    course = {
        "course_code": "BMED2206",
        "subject_area": "BMED",
        "catalogue_number": "2206",
        "title": "Engineering in Biology and Medicine",
    }

    class EnrollmentGateway:
        def status(self):
            return {"term": "2026-27 Semester 1", "courses": [course]}

    class MoodleService:
        def check_login_status(self):
            return SimpleNamespace(status="logged_in")

    class PlannerService:
        def login_until_ready(self, **_kwargs):
            return SimpleNamespace(status="logged_in")

    class UnifiedService:
        async def synchronize(self, courses, *, source_scopes, **_kwargs):
            assert courses == [course]
            assert source_scopes == {"sis_course_info": [course]}
            return UnifiedCourseSyncResult(
                None,
                SimpleNamespace(failures=()),
                None,
            )

    monkeypatch.setattr(
        "hsas.core.implement_port._sis_enrollment_gateway",
        lambda _resources: EnrollmentGateway(),
    )
    monkeypatch.setattr(
        "hsas.core.implement_port._course_service",
        lambda _resources, *, profile_dir=None: MoodleService(),
    )
    monkeypatch.setattr(
        "hsas.core.implement_port._class_planner_service",
        lambda _resources, *, profile_dir=None: PlannerService(),
    )
    monkeypatch.setattr(
        "hsas.core.implement_port._unified_course_sync_service",
        lambda _resources: UnifiedService(),
    )

    service = DashboardService(tmp_path)
    service.sync_job["result"] = {
        "retry_tasks": [
            {
                "source": "sis_course_info",
                "course_code": "BMED2206",
                "error": "timeout",
            }
        ]
    }
    service.retry_failed_course_sync({"confirmed": True})
    for _ in range(200):
        status = service.course_sync_status()
        if status["state"] != "running":
            break
        time.sleep(0.005)

    assert status["state"] == "completed"
    assert status["result"]["retry_mode"] is True
    assert status["result"]["retry_tasks"] == []
    assert status["detail"] == "同步完成"
    assert status["result"]["source_failures"] == []


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
        "hsas.core.implement_port._course_service",
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
    assert before_ai["courses"][0]["materials"]["unclassified"]
    assert (
        next(
            material
            for material in before_ai["courses"][0]["materials"]["unclassified"]
            if material["title"] == "lecture-1.pptx"
        )["change_action"]
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
                    "material_sections": [
                        {
                            "title": "Foundations and limit arguments",
                            "description": "Core concepts selected from this course.",
                            "materials": [
                                {
                                    "title": "lecture-1.pptx",
                                    "relative_path": stored_file.relative_path,
                                    "material_type": "Concept deck",
                                }
                            ],
                        }
                    ],
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
    activity = snapshot["items"][0]
    assert "hsas query" in activity["agent_prompt"]
    assert "demo-assignment" in activity["agent_prompt"]
    assert "最相关的课件/资料" in activity["agent_prompt"]
    assert course["materials"]["sections"][0]["title"] == "Foundations and limit arguments"
    classified = course["materials"]["sections"][0]["materials"][0]
    assert classified["title"] == "lecture-1.pptx"
    assert classified["material_type"] == "Concept deck"
    assert "定位并阅读这份课件" in classified["agent_prompt"]
    assert stored_file.relative_path in classified["agent_prompt"]
    assert "最近一次已经发生的 Lecture" in course["agent_prompts"]["recent_lecture_materials"]
    assert course["materials"]["unclassified"]
    assert service.material_file(stored_file.relative_path)[0] == material_path
    preview = service.source_preview(stored_file.relative_path, [2])
    assert preview["preview_kind"] == "text"
    assert "Sandwich theorem" in preview["text"]
    assert "Limits introduction" not in preview["text"]
    with pytest.raises(DashboardError, match="当前课程快照"):
        service.material_file("information.json")
    with pytest.raises(DashboardError, match="当前课程快照"):
        service.source_preview("information.json")
