from pathlib import Path

import pytest
from typer.testing import CliRunner

from hsas.infrastructure.class_planner.manage_changes import (
    ClassPlannerReviewError,
    acknowledge_class_planner_changes,
    collect_class_planner_changes,
    validate_class_planner_batch,
)
from hsas.infrastructure.storage.persist_data import write_json
from hsas.interfaces.run_cli import app


def _snapshot(synced_at: str, course_key: str) -> dict:
    return {
        "synced_at": synced_at,
        "changes": {
            "changed": True,
            "added": [course_key],
            "modified": [],
            "removed": [],
            "details": [
                {"action": "added", "course_key": course_key, "fields": ["patterns"]}
            ],
        },
        "payload": {"mainTable": [], "patterns": []},
    }


def test_class_planner_queue_accumulates_history_and_advances_checkpoint(
    tmp_path: Path,
) -> None:
    root = tmp_path / "class-planner"
    first = _snapshot("2026-09-07T08:00:00+00:00", "course-1")
    second = _snapshot("2026-09-07T09:00:00+00:00", "course-2")
    write_json(root / "history" / "first.json", first)
    write_json(root / "latest.json", second)
    write_json(
        root / "review-checkpoint.json",
        {"acknowledged_through": "2026-09-07T07:00:00+00:00"},
    )

    batch = collect_class_planner_changes(tmp_path)
    assert batch["pending_snapshot_count"] == 2
    assert batch["pending_change_count"] == 2
    checkpoint = acknowledge_class_planner_changes(tmp_path, batch, confirmed=True)
    assert checkpoint["acknowledged_through"] == second["synced_at"]
    assert collect_class_planner_changes(tmp_path)["pending_change_count"] == 0


def test_class_planner_queue_rejects_stale_batch(tmp_path: Path) -> None:
    root = tmp_path / "class-planner"
    write_json(root / "latest.json", _snapshot("2026-09-07T08:00:00+00:00", "one"))
    batch = collect_class_planner_changes(tmp_path)
    write_json(root / "latest.json", _snapshot("2026-09-07T09:00:00+00:00", "two"))
    with pytest.raises(ClassPlannerReviewError, match="stale"):
        validate_class_planner_batch(tmp_path, batch)


def test_class_planner_queue_hides_metadata_only_legacy_modification(
    tmp_path: Path,
) -> None:
    root = tmp_path / "class-planner"
    snapshot = _snapshot("2026-09-07T08:00:00+00:00", "course-1")
    snapshot["changes"] = {
        "changed": True,
        "added": [],
        "modified": ["course-1"],
        "removed": [],
        "details": [
            {
                "action": "modified",
                "course_key": "course-1",
                "fields": ["course"],
                "before": {
                    "course": {
                        "STRM": "4261",
                        "CRSE_ID": "012345",
                        "APPROVED_HEAD_CNT": None,
                    },
                    "patterns": [],
                },
                "after": {
                    "course": {
                        "STRM": "4261",
                        "CRSE_ID": "012345",
                        "APPROVED_HEAD_CNT": 42,
                    },
                    "patterns": [],
                },
            }
        ],
    }
    write_json(root / "latest.json", snapshot)

    batch = collect_class_planner_changes(tmp_path)

    assert batch["pending_snapshot_count"] == 0
    assert batch["pending_change_count"] == 0
    assert batch["acknowledge_through"] == snapshot["synced_at"]


def test_information_apply_advances_matching_class_planner_batch(tmp_path: Path) -> None:
    resources = tmp_path / "resources"
    write_json(
        resources / "class-planner" / "latest.json",
        _snapshot("2026-09-07T08:00:00+00:00", "one"),
    )
    batch_path = tmp_path / "planner-changes.json"
    update_path = tmp_path / "information-update.json"
    write_json(batch_path, collect_class_planner_changes(resources))
    write_json(
        update_path,
        {"courses": [{"course_id": "1", "code": "DEMO1001", "title": "Demo"}]},
    )

    result = CliRunner().invoke(
        app,
        [
            "--resources",
            str(resources),
            "information",
            "apply",
            str(update_path),
            "--class-planner-changes",
            str(batch_path),
            "--confirmed",
        ],
    )

    assert result.exit_code == 0
    assert collect_class_planner_changes(resources)["pending_change_count"] == 0
