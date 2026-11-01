"""Pin the MCP tool -> HIQSPort payload contract for command tools.

Regression guard for the review finding "4 MCP tools can never succeed": the
sync control tools omitted ``confirmed`` and ``delete_courses`` omitted
``confirmation``, so every call raised inside the port while the name-only tool
test stayed green. These tests exercise the tool bodies and the real service
gates instead of just comparing tool names.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from threading import Lock
from typing import Any
from unittest.mock import Mock

import pytest

from hsas.core import HIQSPort
from hsas.core.ports import HIQSPortError
from hsas.core.services.records import CourseRecordService
from hsas.core.sync.controller import CourseSyncController
from hsas.core.sync.workflow import CourseSyncWorkflow, courses_matching_scope
from hsas.mcp import build_mcp_server


def _build_server():
    port = Mock(spec=HIQSPort)
    return build_mcp_server(port), port


def _call(server, port: Mock, name: str, arguments: dict[str, Any]):
    getattr(port, name).return_value = {"status": "ok"}
    return asyncio.run(server.call_tool(name, arguments))


def _workflow() -> CourseSyncWorkflow:
    return CourseSyncWorkflow(
        resources_dir=Path("/tmp/hiqs-mcp-contract-test"),
        mutation_lock=Lock(),
        controller=CourseSyncController(),
        review_service=Mock(),
        course_service_factory=Mock(),
        enrollment_gateway_factory=Mock(),
        unified_service_factory=Mock(),
    )


def test_start_course_sync_forwards_confirmation_and_course_scope() -> None:
    server, port = _build_server()

    _call(server, port, "start_course_sync", {"course": "BMED2206", "confirmed": True})

    port.start_course_sync.assert_called_once_with(
        {"confirmed": True, "course": "BMED2206"}
    )


def test_start_course_sync_defaults_to_all_courses() -> None:
    server, port = _build_server()

    _call(server, port, "start_course_sync", {"confirmed": True})

    port.start_course_sync.assert_called_once_with({"confirmed": True})


@pytest.mark.parametrize("name", ["retry_failed_course_sync", "cancel_course_sync"])
def test_sync_control_tools_forward_confirmation(name: str) -> None:
    server, port = _build_server()

    _call(server, port, name, {"confirmed": True})

    getattr(port, name).assert_called_once_with({"confirmed": True})


def test_workflow_rejects_missing_confirmation_and_empty_course_scope() -> None:
    workflow = _workflow()

    with pytest.raises(HIQSPortError, match="确认"):
        workflow.start_course_sync({})
    with pytest.raises(HIQSPortError, match="课程代码"):
        workflow.start_course_sync({"confirmed": True, "course": "   "})


def test_workflow_threads_course_scope_into_run(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str | None] = []

    def fake_run(self, job_id, retry_tasks=None, *, course_scope=None):  # noqa: ANN001
        captured.append(course_scope)

    monkeypatch.setattr(CourseSyncWorkflow, "run", fake_run)
    workflow = _workflow()

    workflow.start_course_sync({"confirmed": True, "course": " bmed2206 "})
    assert workflow.controller.thread is not None
    workflow.controller.thread.join(timeout=5)

    assert captured == ["bmed2206"]


def test_courses_matching_scope_is_case_insensitive() -> None:
    courses = [
        {"course_code": "BMED2206", "title": "a"},
        {"course_code": "MATH1851", "title": "b"},
    ]

    assert courses_matching_scope(courses, " bmed2206 ") == [courses[0]]
    assert courses_matching_scope(courses, "missing") == []


def test_delete_courses_service_requires_matching_confirmation(tmp_path: Path) -> None:
    service = CourseRecordService(resources_dir=tmp_path, mutation_lock=Lock())

    with pytest.raises(HIQSPortError, match="确认"):
        service.delete_courses(
            {"course_ids": ["X"], "confirmation": ["X"], "confirmed": False}
        )

    # Both confirmations present: the request must reach the store and fail on
    # the unknown course, not on the confirmation gate.
    with pytest.raises(HIQSPortError) as excinfo:
        service.delete_courses(
            {"course_ids": ["X"], "confirmation": ["X"], "confirmed": True}
        )
    assert "确认" not in str(excinfo.value)


def test_export_notion_forwards_confirmation_without_path_bypass() -> None:
    server, port = _build_server()
    port.notion_export.return_value = {"status": "ok"}

    asyncio.run(server.call_tool("export_notion", {"confirmed": True}))

    port.notion_export.assert_called_once_with(
        {
            "destination": None,
            "include_files": True,
            "confirmed": True,
        }
    )
