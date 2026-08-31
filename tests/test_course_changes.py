import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from moodle_collector.transformation.assessment.schema import (
    AssessmentItem,
    AssessmentOverview,
)
from moodle_collector.transformation.common.course_changes import (
    compare_course_archives,
)
from moodle_collector.transformation.common.course_mapper import build_course_archive
from moodle_collector.transformation.common.course_schema import StoredFile


ROOT = Path(__file__).parents[1]


def test_change_set_detects_deadline_weight_and_material_changes() -> None:
    state = json.loads((ROOT / "tests/fixtures/course_state.json").read_text())
    previous = build_course_archive(
        state,
        course_title="Demo Course",
        raw_state_path="courses/138907/raw/course-state.json",
    )
    previous.assessments = AssessmentOverview(
        parser_version="generic-v1",
        items=[
            AssessmentItem(
                assessment_id="essay-1",
                title="Essay",
                assessment_type="essay",
                weight_percent=20,
                due_on="2026-09-10",
            )
        ],
    )
    previous.sections[0].activities[1].files = [
        StoredFile(
            filename="slides.pdf",
            relative_path="courses/138907/files/slides.pdf",
            source_url="https://moodle.example.edu/pluginfile.php/1/slides.pdf",
            content_type="application/pdf",
            size_bytes=10,
            sha256="a" * 64,
            downloaded_at=datetime.now(timezone.utc),
        )
    ]
    current = previous.model_copy(deep=True)
    current.collected_at = previous.collected_at + timedelta(hours=1)
    current.assessments.items[0].due_on = datetime(2026, 9, 17).date()
    current.assessments.items[0].weight_percent = 30
    current.sections[0].activities[1].files[0].sha256 = "b" * 64

    result = compare_course_archives(previous, current)
    keys = {(change.kind, change.field) for change in result.changes}

    assert result.initial_sync is False
    assert keys >= {
        ("deadline", "due_on"),
        ("weight", "weight_percent"),
        ("material", "sha256"),
    }
    assert result.summary == {"deadline": 1, "weight": 1, "material": 1}


def test_first_sync_creates_a_baseline_without_false_changes() -> None:
    state = json.loads((ROOT / "tests/fixtures/course_state.json").read_text())
    archive = build_course_archive(
        state,
        course_title="Demo Course",
        raw_state_path="courses/138907/raw/course-state.json",
    )

    result = compare_course_archives(None, archive)

    assert result.initial_sync is True
    assert result.changed is False
