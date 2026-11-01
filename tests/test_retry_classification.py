"""Permanent source failures must be separated from transient ones."""

from __future__ import annotations

from pathlib import Path
from threading import Lock
from unittest.mock import Mock

import pytest

from hsas.core.ports import HIQSPortError
from hsas.core.services.information_snapshot import InformationSnapshotService
from hsas.core.sync.controller import CourseSyncController
from hsas.core.sync.workflow import (
    CourseSyncWorkflow,
    annotate_retry_tasks,
    classify_retry_task,
)
from hsas.domain.courses.change_queue import PendingChangeBatch
from hsas.domain.information import CourseRecord, InformationStore
from hsas.infrastructure.storage.json_store import write_json

_PERMANENT = {
    "source": "sis_course_info",
    "course_code": "BMED2206",
    "error": "SisCourseInfoLookupError: HKU SIS Course Information has no matching entry for BMED2206",
}
_TRANSIENT = {
    "source": "moodle",
    "course_code": "MATH1851",
    "error": "TimeoutError: navigation timeout while reading course",
}


def _workflow(resources: Path) -> CourseSyncWorkflow:
    return CourseSyncWorkflow(
        resources_dir=resources,
        mutation_lock=Lock(),
        controller=CourseSyncController(),
        review_service=Mock(),
        course_service_factory=Mock(),
        enrollment_gateway_factory=Mock(),
        unified_service_factory=Mock(),
    )


def _persist(resources: Path, tasks: list[dict]) -> None:
    write_json(
        resources / "sync-workflow" / "latest.json",
        {"schema_version": "1.0", "retry_tasks": tasks},
    )


def _snapshot(resources: Path, store: InformationStore, tasks: list[dict]):
    return InformationSnapshotService(
        resources_dir=resources,
        review_service=Mock(),
        personal_inbox_service=Mock(),
        sync_status_provider=lambda: {"result": {"retry_tasks": tasks}},
    )


def _complete_store() -> InformationStore:
    return InformationStore(
        courses=[CourseRecord(course_id="DEMO1001", code="DEMO1001", title="Demo")]
    )


def _empty_pending(resources: Path) -> PendingChangeBatch:
    return PendingChangeBatch(resources_dir=str(resources), courses=[])


def _complete_material_status() -> dict:
    return {"counts": {"ai_review": 0, "ocr": 0, "google_authorization": 0}}


def test_classifies_permanent_and_transient_errors() -> None:
    assert classify_retry_task(_PERMANENT) == "permanent"
    assert classify_retry_task({"error": "Moodle 中未找到与当前 enrolment 对应的课程"}) == "permanent"
    assert classify_retry_task(_TRANSIENT) == "transient"
    assert classify_retry_task({"error": ""}) == "transient"


def test_annotation_marks_retry_recommendation() -> None:
    annotated = annotate_retry_tasks([_PERMANENT, _TRANSIENT])

    assert [task["kind"] for task in annotated] == ["permanent", "transient"]
    assert [task["retry_recommended"] for task in annotated] == [False, True]


def test_retry_skips_permanent_failures(tmp_path: Path) -> None:
    _persist(tmp_path, [_PERMANENT, _TRANSIENT])
    workflow = _workflow(tmp_path)

    workflow.retry_failed_course_sync({"confirmed": True})
    assert workflow.controller.thread is not None
    workflow.controller.thread.join(timeout=5)
    result = workflow.controller.job.get("result") or {}

    assert [task["course_code"] for task in result.get("retry_tasks", [])] == ["MATH1851"]


def test_retry_refuses_when_only_permanent_failures_remain(tmp_path: Path) -> None:
    _persist(tmp_path, [_PERMANENT])
    workflow = _workflow(tmp_path)

    with pytest.raises(HIQSPortError, match="永久性"):
        workflow.retry_failed_course_sync({"confirmed": True})


def test_retry_can_include_permanent_failures_explicitly(tmp_path: Path) -> None:
    _persist(tmp_path, [_PERMANENT])
    workflow = _workflow(tmp_path)

    workflow.retry_failed_course_sync({"confirmed": True, "include_permanent": True})
    assert workflow.controller.thread is not None
    workflow.controller.thread.join(timeout=5)

    assert (workflow.controller.job.get("result") or {}).get("retry_tasks")


def test_review_closure_is_not_blocked_by_permanent_failures(tmp_path: Path) -> None:
    (tmp_path / "sis-enrollment").mkdir(parents=True)
    (tmp_path / "sis-enrollment/latest.json").write_text("{}", encoding="utf-8")
    service = _snapshot(tmp_path, _complete_store(), annotate_retry_tasks([_PERMANENT]))

    closure = service._review_closure(
        _complete_store(), _empty_pending(tmp_path), _complete_material_status()
    )

    assert closure["complete"] is True
    assert len(closure["permanent_failures"]) == 1
    assert closure["transient_failures"] == []


def test_review_closure_reports_transient_failures_as_incomplete(tmp_path: Path) -> None:
    (tmp_path / "sis-enrollment").mkdir(parents=True)
    (tmp_path / "sis-enrollment/latest.json").write_text("{}", encoding="utf-8")
    service = _snapshot(tmp_path, _complete_store(), annotate_retry_tasks([_TRANSIENT]))

    closure = service._review_closure(
        _complete_store(), _empty_pending(tmp_path), _complete_material_status()
    )

    assert closure["complete"] is False
    assert len(closure["transient_failures"]) == 1
