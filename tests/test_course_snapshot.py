import json
import os
from pathlib import Path

import pytest

from hsas_runtime.storage import write_json, write_model
from moodle_collector.storage.course_snapshot import (
    CourseSnapshotTransaction,
    _recover_interrupted_publish,
)
from moodle_collector.transformation.common.course_mapper import build_course_archive


ROOT = Path(__file__).parents[1]


def _archive(title: str):
    state = json.loads((ROOT / "tests/fixtures/course_state.json").read_text())
    return build_course_archive(
        state,
        course_title=title,
        raw_state_path="courses/138907/raw/course-state.json",
    )


def test_course_snapshot_publishes_complete_staged_directory(tmp_path: Path) -> None:
    resources = tmp_path / "resources"
    live = resources / "courses/138907"
    write_model(live / "course.json", _archive("Old"))
    (live / "files").mkdir()
    (live / "files/old.txt").write_text("old")

    with CourseSnapshotTransaction.prepare(resources, "138907") as transaction:
        write_model(transaction.staged_course_dir / "course.json", _archive("New"))
        (transaction.staged_course_dir / "files/new.txt").write_text("new")
        output = transaction.commit()

    assert output == live / "course.json"
    assert json.loads(output.read_text())["course"]["title"] == "New"
    assert (live / "files/new.txt").read_text() == "new"
    assert not list((resources / ".transactions").glob("*.journal.json"))


def test_course_snapshot_discards_staging_when_pipeline_fails(tmp_path: Path) -> None:
    resources = tmp_path / "resources"
    live = resources / "courses/138907"
    write_model(live / "course.json", _archive("Last known good"))

    with pytest.raises(RuntimeError, match="parser failed"):
        with CourseSnapshotTransaction.prepare(resources, "138907") as transaction:
            write_model(transaction.staged_course_dir / "course.json", _archive("Partial"))
            raise RuntimeError("parser failed")

    assert json.loads((live / "course.json").read_text())["course"]["title"] == "Last known good"


def test_recovery_restores_backup_after_interrupted_directory_swap(tmp_path: Path) -> None:
    resources = tmp_path / "resources"
    transactions = resources / ".transactions"
    root = transactions / "course-138907-interrupted"
    live = resources / "courses/138907"
    backup = root / "previous"
    write_model(live / "course.json", _archive("Old"))
    root.mkdir(parents=True, exist_ok=True)
    os.replace(live, backup)
    write_json(
        transactions / "course-138907.journal.json",
        {
            "transaction_root": str(root),
            "live_course_dir": str(live),
            "backup_dir": str(backup),
        },
    )

    _recover_interrupted_publish(resources, "138907")

    assert json.loads((live / "course.json").read_text())["course"]["title"] == "Old"
    assert not root.exists()
