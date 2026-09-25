import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from hsas.domain.courses.models import StoredFile
from hsas.domain.courses.change_detection import compare_course_archives
from hsas.infrastructure.moodle.course_mapper import build_course_archive


ROOT = Path(__file__).parents[1]


def test_change_set_detects_moodle_date_and_material_changes() -> None:
    state = json.loads((ROOT / "tests/fixtures/course_state.json").read_text())
    previous = build_course_archive(
        state, course_title="Demo Course", raw_state_path="courses/138907/raw/course-state.json"
    )
    activity = previous.sections[0].activities[1]
    activity.metadata["duedate"] = 100
    activity.files = [
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
    current.sections[0].activities[1].metadata["duedate"] = 200
    current.sections[0].activities[1].files[0].sha256 = "b" * 64
    result = compare_course_archives(previous, current)
    keys = {(change.kind, change.field) for change in result.changes}
    assert keys == {("deadline", "metadata.duedate"), ("material", "sha256")}
    assert result.summary == {"deadline": 1, "material": 1}


def test_first_sync_is_a_quiet_baseline() -> None:
    state = json.loads((ROOT / "tests/fixtures/course_state.json").read_text())
    archive = build_course_archive(
        state, course_title="Demo Course", raw_state_path="courses/138907/raw/course-state.json"
    )
    result = compare_course_archives(None, archive)
    assert result.initial_sync is True
    assert result.changed is False


def test_change_set_detects_rendered_moodle_content_and_table_changes() -> None:
    state = json.loads((ROOT / "tests/fixtures/course_state.json").read_text())
    previous = build_course_archive(
        state,
        course_title="Demo Course",
        raw_state_path="courses/138907/raw/course-state.json",
    )
    activity = previous.sections[0].activities[0]
    activity.content_text = "Tuesday lecture at 10:00"
    activity.content_tables = [
        {"caption": "Timetable", "rows": [{"cells": [{"text": "10:00"}]}]}
    ]
    current = previous.model_copy(deep=True)
    current.collected_at = previous.collected_at + timedelta(hours=1)
    current_activity = current.sections[0].activities[0]
    current_activity.content_text = "Tuesday lecture at 11:00"
    current_activity.content_tables[0]["rows"][0]["cells"][0][
        "text"
    ] = "11:00"

    result = compare_course_archives(previous, current)

    assert {(change.kind, change.field) for change in result.changes} == {
        ("activity", "content_text"),
        ("activity", "content_tables"),
    }
    assert result.summary == {"activity": 2}
