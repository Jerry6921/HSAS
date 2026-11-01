"""Durability: an atomic write must flush the parent directory after rename."""

from __future__ import annotations

import json
from pathlib import Path

from hsas.infrastructure.moodle.course_mapper import build_course_archive
from hsas.infrastructure.storage import course_publisher, json_store
from hsas.infrastructure.storage.course_publisher import CourseSnapshotTransaction
from hsas.infrastructure.storage.json_store import atomic_write, fsync_directory, write_model

ROOT = Path(__file__).parents[1]


def _archive(title: str):
    state = json.loads((ROOT / "tests/fixtures/course_state.json").read_text())
    return build_course_archive(
        state,
        course_title=title,
        raw_state_path="courses/138907/raw/course-state.json",
    )


def test_atomic_write_fsyncs_parent_directory(tmp_path: Path, monkeypatch) -> None:
    calls: list[Path] = []
    monkeypatch.setattr(json_store, "fsync_directory", calls.append)

    target = tmp_path / "state" / "information.json"
    atomic_write(target, "{}")

    assert calls == [target.parent]


def test_atomic_write_leaves_no_temporary_files(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    atomic_write(target, "a")
    atomic_write(target, "b")

    assert target.read_text() == "b"
    assert [path.name for path in tmp_path.iterdir()] == ["state.json"]


def test_fsync_directory_tolerates_missing_directory(tmp_path: Path) -> None:
    fsync_directory(tmp_path / "missing")


def test_publish_fsyncs_live_parent_and_transactions(tmp_path: Path, monkeypatch) -> None:
    calls: list[Path] = []
    monkeypatch.setattr(course_publisher, "fsync_directory", calls.append)

    resources = tmp_path / "resources"
    live = resources / "courses/138907"
    write_model(live / "course.json", _archive("Old"))

    with CourseSnapshotTransaction.prepare(resources, "138907") as transaction:
        write_model(transaction.staged_course_dir / "course.json", _archive("New"))
        transaction.commit()

    transactions = resources / ".transactions"
    # Two directory renames (live -> backup, staged -> live) then journal cleanup.
    assert calls.count(live.parent) == 2
    assert calls[-1] == transactions
