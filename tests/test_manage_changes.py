import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hsas.application.manage_changes import (
    ChangeQueueError,
    acknowledge_change_batch,
    collect_pending_changes,
)
from hsas.domain.courses.define_courses import StoredFile
from hsas.domain.courses.detect_changes import compare_course_archives
from hsas.domain.information import InformationStore
from hsas.infrastructure.moodle.map_courses import build_course_archive
from hsas.infrastructure.storage import JsonChangeQueueRepository
from hsas.infrastructure.storage.persist_data import write_json, write_model
from hsas.interfaces.run_cli import app


ROOT = Path(__file__).parents[1]
REPOSITORY = JsonChangeQueueRepository()


def _archive(resources: Path, collected_at: datetime, digest: str):
    state = json.loads((ROOT / "tests/fixtures/course_state.json").read_text())
    archive = build_course_archive(
        state,
        course_title="Demo Course",
        raw_state_path="courses/138907/raw/course-state.json",
    )
    archive.collected_at = collected_at
    stored_file = StoredFile(
        filename="brief.docx",
        relative_path="courses/138907/files/brief.docx",
        source_url="https://moodle.example.edu/pluginfile.php/brief.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size_bytes=10,
        sha256=digest * 64,
        downloaded_at=collected_at,
    )
    archive.sections[0].activities[0].files = [stored_file]
    path = resources / "courses/138907/course.json"
    write_model(path, archive)
    file_path = resources / stored_file.relative_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(digest.encode())
    return archive


def test_first_review_is_full_then_only_changed_files_are_pending(tmp_path: Path) -> None:
    resources = tmp_path / "resources"
    first_at = datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc)
    previous = _archive(resources, first_at, "a")
    first = collect_pending_changes(resources, REPOSITORY)

    assert first.courses[0].mode == "full"
    assert {item.filename for item in first.courses[0].files} == {
        "course.json",
        "brief.docx",
    }
    acknowledge_change_batch(resources, first, REPOSITORY, confirmed=True)
    assert collect_pending_changes(resources, REPOSITORY).courses == []

    current = previous.model_copy(deep=True)
    current.collected_at = first_at + timedelta(days=1)
    current.sections[0].activities[0].files[0].sha256 = "b" * 64
    write_model(resources / "courses/138907/course.json", current)
    change_set = compare_course_archives(previous, current)
    write_model(
        resources / "courses/138907/changes/history/change.json",
        change_set,
    )

    information = InformationStore.model_validate(
        {
            "courses": [{"course_id": "138907", "code": "DEMO", "title": "Demo"}],
            "items": [
                {
                    "item_id": "assignment-1",
                    "course_id": "138907",
                    "title": "Assignment",
                    "category": "assignment",
                    "sources": [
                        {
                            "source_type": "course_document",
                            "title": "Brief",
                            "relative_path": "courses/138907/files/brief.docx",
                        }
                    ],
                }
            ],
        }
    )
    pending = collect_pending_changes(resources, REPOSITORY, information=information)

    assert pending.courses[0].mode == "incremental"
    assert pending.courses[0].changes[0].change_set_id.startswith("change:138907:")
    assert pending.courses[0].affected_information_item_ids == ["assignment-1"]
    assert {item.change_action for item in pending.courses[0].files} == {
        "modified"
    }


def test_processed_legacy_assessment_history_does_not_break_change_listing(
    tmp_path: Path,
) -> None:
    resources = tmp_path / "resources"
    collected_at = datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc)
    _archive(resources, collected_at, "a")
    batch = collect_pending_changes(resources, REPOSITORY)
    acknowledge_change_batch(resources, batch, REPOSITORY, confirmed=True)
    write_json(
        resources / "courses/138907/changes/history/legacy.json",
        {
            "schema_version": "1.0",
            "course_id": "138907",
            "detected_at": "2026-08-31T08:30:00Z",
            "initial_sync": False,
            "changed": True,
            "previous_collected_at": "2026-08-31T08:00:00Z",
            "current_collected_at": "2026-08-31T08:20:00Z",
            "changes": [
                {
                    "kind": "assessment",
                    "action": "modified",
                    "entity_id": "quiz-1",
                    "title": "Quiz 1",
                    "field": "status",
                    "before": "tentative",
                    "after": "confirmed",
                },
                {
                    "kind": "weight",
                    "action": "modified",
                    "entity_id": "quiz-1",
                    "title": "Quiz 1",
                    "field": "weight_percent",
                    "before": None,
                    "after": 15,
                },
            ],
            "summary": {"assessment": 1, "weight": 1},
        },
    )

    assert collect_pending_changes(resources, REPOSITORY).courses == []


def test_unprocessed_legacy_change_kinds_are_adapted_to_activity(
    tmp_path: Path,
) -> None:
    resources = tmp_path / "resources"
    first_at = datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc)
    previous = _archive(resources, first_at, "a")
    first = collect_pending_changes(resources, REPOSITORY)
    acknowledge_change_batch(resources, first, REPOSITORY, confirmed=True)
    current_at = first_at + timedelta(days=1)
    current = previous.model_copy(deep=True)
    current.collected_at = current_at
    write_model(resources / "courses/138907/course.json", current)
    write_json(
        resources / "courses/138907/changes/history/legacy-new.json",
        {
            "schema_version": "1.0",
            "course_id": "138907",
            "detected_at": current_at.isoformat(),
            "initial_sync": False,
            "changed": True,
            "previous_collected_at": first_at.isoformat(),
            "current_collected_at": current_at.isoformat(),
            "changes": [
                {
                    "kind": "assessment",
                    "action": "modified",
                    "entity_id": "quiz-1",
                    "title": "Quiz 1",
                    "field": "requirements",
                    "before": [],
                    "after": ["Chapters 1–3"],
                },
                {
                    "kind": "weight",
                    "action": "modified",
                    "entity_id": "quiz-1",
                    "title": "Quiz 1",
                    "field": "weight_percent",
                    "before": None,
                    "after": 15,
                },
            ],
            "summary": {"assessment": 1, "weight": 1},
        },
    )

    pending = collect_pending_changes(resources, REPOSITORY)

    assert [change.kind for change in pending.courses[0].changes] == [
        "activity",
        "activity",
    ]
    assert [change.field for change in pending.courses[0].changes] == [
        "requirements",
        "weight_percent",
    ]


def test_stale_batch_cannot_advance_checkpoint(tmp_path: Path) -> None:
    resources = tmp_path / "resources"
    collected_at = datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc)
    _archive(resources, collected_at, "a")
    batch = collect_pending_changes(resources, REPOSITORY)
    _archive(resources, collected_at + timedelta(minutes=1), "a")

    with pytest.raises(ChangeQueueError, match="changed after"):
        acknowledge_change_batch(resources, batch, REPOSITORY, confirmed=True)


def test_information_apply_can_acknowledge_exact_review_batch(tmp_path: Path) -> None:
    resources = tmp_path / "resources"
    _archive(resources, datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc), "a")
    batch = collect_pending_changes(resources, REPOSITORY)
    batch_path = tmp_path / "changes.json"
    update_path = tmp_path / "update.json"
    write_json(batch_path, batch.model_dump(mode="json"))
    write_json(
        update_path,
        {"courses": [{"course_id": "138907", "code": "DEMO", "title": "Demo"}]},
    )

    result = CliRunner().invoke(
        app,
        [
            "--resources",
            str(resources),
            "information",
            "apply",
            str(update_path),
            "--changes",
            str(batch_path),
            "--confirmed",
        ],
    )

    assert result.exit_code == 0
    assert "acknowledged" in result.stdout
    assert collect_pending_changes(resources, REPOSITORY).courses == []


def test_no_information_change_requires_explicit_acknowledgement(tmp_path: Path) -> None:
    resources = tmp_path / "resources"
    _archive(resources, datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc), "a")
    batch = collect_pending_changes(resources, REPOSITORY)
    batch_path = tmp_path / "changes.json"
    write_json(batch_path, batch.model_dump(mode="json"))

    refused = CliRunner().invoke(
        app,
        [
            "--resources",
            str(resources),
            "changes",
            "acknowledge",
            str(batch_path),
            "--confirmed",
        ],
    )
    accepted = CliRunner().invoke(
        app,
        [
            "--resources",
            str(resources),
            "changes",
            "acknowledge",
            str(batch_path),
            "--confirmed",
            "--reviewed-no-information-change",
        ],
    )

    assert refused.exit_code != 0
    assert accepted.exit_code == 0
    assert collect_pending_changes(resources, REPOSITORY).courses == []


def test_review_batch_rejects_resource_paths_outside_root(tmp_path: Path) -> None:
    resources = tmp_path / "resources"
    archive = _archive(
        resources,
        datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc),
        "a",
    )
    archive.sections[0].activities[0].files[0].relative_path = "../escape.docx"
    write_model(resources / "courses/138907/course.json", archive)

    with pytest.raises(ChangeQueueError, match="unsafe course resource path"):
        collect_pending_changes(resources, REPOSITORY)
