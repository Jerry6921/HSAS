"""Thin CLI adapters still need one cheap test each.

They carry no business rules, but they are the surface a human (and sometimes an
agent without MCP) actually types. A typo in an option or an output format that
lies about what happened is invisible to the service tests.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

from typer.testing import CliRunner

from hsas.cli.app import app


def _resource_args(tmp_path: Path) -> list[str]:
    return ["--resources", str(tmp_path)]


def test_sync_courses_cancel_stops_instead_of_collecting(tmp_path: Path, monkeypatch) -> None:
    port = Mock()
    port.cancel_course_sync.return_value = {"state": "cancelled"}
    monkeypatch.setattr("hsas.core.build_port", lambda _resources: port)

    result = CliRunner().invoke(
        app, [*_resource_args(tmp_path), "sync-courses", "--cancel"]
    )

    assert result.exit_code == 0, result.output
    port.cancel_course_sync.assert_called_once_with({"confirmed": True})
    assert "cancelled" in result.output
    port.synchronize_courses.assert_not_called()


def test_enrolment_status_reports_the_snapshot_and_review_queue(
    tmp_path: Path, monkeypatch,
) -> None:
    gateway = Mock()
    gateway.return_value.status.return_value = {"course_count": 6, "term": "2026-27 Sem 1"}
    monkeypatch.setattr(
        "hsas.infrastructure.sis.enrollment.client.SisEnrollmentBrowserGateway", gateway
    )
    monkeypatch.setattr(
        "hsas.infrastructure.sis.enrollment.review.collect_sis_enrollment_changes",
        lambda _resources: {"pending_change_count": 3},
    )

    result = CliRunner().invoke(app, [*_resource_args(tmp_path), "sis-enrollment", "status"])

    assert result.exit_code == 0, result.output
    assert "6 course(s)" in result.output
    assert "2026-27 Sem 1" in result.output
    assert "pending review=3" in result.output


def test_enrolment_changes_can_be_written_to_a_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "hsas.infrastructure.sis.enrollment.review.collect_sis_enrollment_changes",
        lambda _resources: {"pending_change_count": 2, "courses": []},
    )
    output = tmp_path / "batch.json"

    result = CliRunner().invoke(
        app,
        [
            *_resource_args(tmp_path),
            "sis-enrollment",
            "changes",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(output.read_text())["pending_change_count"] == 2
    assert "2 change(s)" in result.output


def test_enrolment_acknowledge_advances_only_with_a_valid_batch(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setattr(
        "hsas.infrastructure.sis.enrollment.review.acknowledge_sis_enrollment_changes",
        lambda _resources, batch, confirmed: {
            "content_sha256": "a" * 64,
            "confirmed": confirmed,
        },
    )
    batch = tmp_path / "batch.json"
    batch.write_text(json.dumps({"pending_change_count": 0}), encoding="utf-8")

    accepted = CliRunner().invoke(
        app,
        [*_resource_args(tmp_path), "sis-enrollment", "acknowledge", str(batch), "--confirmed"],
    )
    assert accepted.exit_code == 0, accepted.output
    assert "a" * 64 in accepted.output

    broken = tmp_path / "broken.json"
    broken.write_text("[]", encoding="utf-8")
    rejected = CliRunner().invoke(
        app, [*_resource_args(tmp_path), "sis-enrollment", "acknowledge", str(broken)]
    )
    assert rejected.exit_code != 0
    assert "JSON object" in rejected.output


def test_notion_status_prints_the_packet_as_json(tmp_path: Path, monkeypatch) -> None:
    port = Mock()
    port.notion_status = Mock(return_value={"connected": False, "data_sources": {}})
    monkeypatch.setattr("hsas.core.build_port", lambda _resources: port)

    result = CliRunner().invoke(app, [*_resource_args(tmp_path), "notion", "status"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["connected"] is False


def test_notion_status_reports_a_failure_as_a_usage_error(tmp_path: Path, monkeypatch) -> None:
    from hsas.core import HIQSPortError

    port = Mock()
    port.notion_status = Mock(side_effect=HIQSPortError("Notion 尚未配置"))
    monkeypatch.setattr("hsas.core.build_port", lambda _resources: port)

    result = CliRunner().invoke(app, [*_resource_args(tmp_path), "notion", "status"])

    assert result.exit_code != 0
    assert "尚未配置" in result.output
