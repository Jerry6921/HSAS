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
from hsas.application.update_information import apply_information_update
from hsas.domain.courses.define_courses import StoredFile
from hsas.domain.courses.detect_changes import compare_course_archives
from hsas.domain.information import InformationStore
from hsas.infrastructure.moodle.map_courses import build_course_archive
from hsas.infrastructure.storage import (
    JsonChangeQueueRepository,
    JsonInformationRepository,
)
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


def test_pending_review_maps_shared_moodle_archive_to_information_course(
    tmp_path: Path,
) -> None:
    resources = tmp_path / "resources"
    _archive(resources, datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc), "a")
    information = InformationStore.model_validate(
        {
            "courses": [
                {
                    "course_id": "MATH1851-S1",
                    "code": "MATH1851",
                    "title": "Calculus",
                    "moodle_course_id": "142655",
                    "additional_moodle_course_ids": ["138907"],
                }
            ],
            "items": [
                {
                    "item_id": "math-test",
                    "course_id": "MATH1851-S1",
                    "title": "Test",
                    "category": "exam",
                }
            ],
        }
    )

    review = collect_pending_changes(
        resources,
        REPOSITORY,
        information=information,
    ).courses[0]

    assert review.course_id == "138907"
    assert review.information_course_id == "MATH1851-S1"
    assert review.related_moodle_course_ids == ["142655", "138907"]
    assert review.affected_information_item_ids == ["math-test"]


def test_rendered_moodle_content_change_reaches_incremental_review(
    tmp_path: Path,
) -> None:
    resources = tmp_path / "resources"
    first_at = datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc)
    previous = _archive(resources, first_at, "a")
    previous.sections[0].activities[0].metadata["content_text"] = (
        "Tuesday lecture at 10:00"
    )
    write_model(resources / "courses/138907/course.json", previous)
    acknowledge_change_batch(
        resources,
        collect_pending_changes(resources, REPOSITORY),
        REPOSITORY,
        confirmed=True,
    )

    current = previous.model_copy(deep=True)
    current.collected_at = first_at + timedelta(hours=1)
    current.sections[0].activities[0].metadata["content_text"] = (
        "Tuesday lecture at 11:00"
    )
    write_model(resources / "courses/138907/course.json", current)
    write_model(
        resources / "courses/138907/changes/history/content.json",
        compare_course_archives(previous, current),
    )

    pending = collect_pending_changes(resources, REPOSITORY)

    assert pending.courses[0].mode == "incremental"
    assert [change.field for change in pending.courses[0].changes] == [
        "metadata.content_text"
    ]
    assert [(item.filename, item.change_action) for item in pending.courses[0].files] == [
        ("course.json", "modified")
    ]


def test_pending_review_hides_transient_remove_restore_of_identical_material(
    tmp_path: Path,
) -> None:
    resources = tmp_path / "resources"
    first_at = datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc)
    original = _archive(resources, first_at, "a")
    acknowledge_change_batch(
        resources,
        collect_pending_changes(resources, REPOSITORY),
        REPOSITORY,
        confirmed=True,
    )

    missing = original.model_copy(deep=True)
    missing.collected_at = first_at + timedelta(hours=1)
    missing.sections[0].activities[0].files = []
    write_model(
        resources / "courses/138907/changes/history/01-removed.json",
        compare_course_archives(original, missing),
    )

    restored = original.model_copy(deep=True)
    restored.collected_at = first_at + timedelta(hours=2)
    restored.sections[0].activities[0].files[0].filename = "brief-1.docx"
    restored.sections[0].activities[0].files[0].relative_path = (
        "courses/138907/files/brief-1.docx"
    )
    write_model(resources / "courses/138907/course.json", restored)
    write_model(
        resources / "courses/138907/changes/history/02-restored.json",
        compare_course_archives(missing, restored),
    )

    assert collect_pending_changes(resources, REPOSITORY).courses == []


def test_pending_review_compacts_material_flapping_to_one_net_change(
    tmp_path: Path,
) -> None:
    resources = tmp_path / "resources"
    first_at = datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc)
    original = _archive(resources, first_at, "a")
    acknowledge_change_batch(
        resources,
        collect_pending_changes(resources, REPOSITORY),
        REPOSITORY,
        confirmed=True,
    )

    missing = original.model_copy(deep=True)
    missing.collected_at = first_at + timedelta(hours=1)
    missing.sections[0].activities[0].files = []
    write_model(
        resources / "courses/138907/changes/history/01-removed.json",
        compare_course_archives(original, missing),
    )

    changed = original.model_copy(deep=True)
    changed.collected_at = first_at + timedelta(hours=2)
    changed.sections[0].activities[0].files[0].sha256 = "b" * 64
    write_model(resources / "courses/138907/course.json", changed)
    write_model(
        resources / "courses/138907/changes/history/02-restored.json",
        compare_course_archives(missing, changed),
    )

    pending = collect_pending_changes(resources, REPOSITORY)

    assert len(pending.courses) == 1
    assert len(pending.courses[0].changes) == 1
    assert pending.courses[0].changes[0].action == "modified"
    assert pending.courses[0].changes[0].before == "a" * 64
    assert pending.courses[0].changes[0].after == "b" * 64


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
        {
            "courses": [
                {
                    "course_id": "138907",
                    "code": "DEMO",
                    "title": "Demo",
                    "material_sections": [
                        {
                            "title": "Current materials",
                            "materials": [
                                {
                                    "title": "brief.docx",
                                    "relative_path": "courses/138907/files/brief.docx",
                                }
                            ],
                        }
                    ],
                }
            ]
        },
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


def test_information_apply_rejects_incomplete_live_material_manifest(
    tmp_path: Path,
) -> None:
    resources = tmp_path / "resources"
    _archive(resources, datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc), "a")
    update_path = tmp_path / "update.json"
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
            "--confirmed",
        ],
    )

    assert result.exit_code == 2
    assert "material coverage is incomplete" in result.output


def test_information_apply_rejects_dropping_a_live_linked_moodle_archive(
    tmp_path: Path,
) -> None:
    resources = tmp_path / "resources"
    _archive(resources, datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc), "a")
    information_path = resources / "information.json"
    apply_information_update(
        information_path,
        {
            "courses": [
                {
                    "course_id": "MATH1851",
                    "code": "MATH1851",
                    "title": "Calculus",
                    "moodle_course_id": "142655",
                    "additional_moodle_course_ids": ["138907"],
                    "material_sections": [
                        {
                            "title": "Shared materials",
                            "materials": [
                                {
                                    "title": "brief.docx",
                                    "relative_path": "courses/138907/files/brief.docx",
                                }
                            ],
                        }
                    ],
                }
            ]
        },
        confirmed=True,
        repository=JsonInformationRepository(),
    )
    update_path = tmp_path / "drop-linked-course.json"
    write_json(
        update_path,
        {
            "courses": [
                {
                    "course_id": "MATH1851",
                    "code": "MATH1851",
                    "title": "Calculus",
                    "moodle_course_id": "142655",
                }
            ]
        },
    )

    result = CliRunner().invoke(
        app,
        [
            "--resources",
            str(resources),
            "information",
            "apply",
            str(update_path),
            "--confirmed",
        ],
    )

    assert result.exit_code == 2
    assert "would drop linked Moodle archive(s): 138907" in result.output


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
