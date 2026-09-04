import json
from datetime import datetime, timezone
from pathlib import Path

from hsas.domain.courses.index_courses import (
    ArchiveIndex,
    ArchiveIndexError,
    iter_activities,
    iter_files,
)
from hsas.infrastructure.moodle.map_courses import build_course_archive
from hsas.domain.courses.define_courses import StoredFile
from hsas.domain.courses.calculate_statistics import refresh_archive_stats
import pytest


ROOT = Path(__file__).parents[1]


def test_archive_index_and_stats_are_shared_services(tmp_path: Path) -> None:
    state = json.loads((ROOT / "tests/fixtures/course_state.json").read_text())
    archive = build_course_archive(
        state,
        course_title="Demo Course",
        raw_state_path="courses/138907/raw/course-state.json",
    )
    syllabus_activity = archive.sections[0].activities[1]
    syllabus_activity.files.append(
        StoredFile(
            filename="syllabus.pdf",
            relative_path="courses/138907/files/syllabus.pdf",
            source_url="https://moodle.example.edu/pluginfile.php/syllabus.pdf",
            size_bytes=5,
            sha256="0" * 64,
            downloaded_at=datetime.now(timezone.utc),
        )
    )

    refresh_archive_stats(archive)
    json_path = tmp_path / "course.json"
    json_path.write_text(archive.model_dump_json(), encoding="utf-8")
    index = ArchiveIndex.from_json(json_path)

    assert len(list(iter_activities(archive))) == 3
    assert len(list(iter_files(archive))) == 1
    assert archive.stats.downloaded_file_count == 1
    assert archive.stats.downloaded_bytes == 5
    assert index.source_path == json_path
    assert index.archive.course.course_id == "138907"
    assert index.get_section("100").title == "General"
    assert index.get_activity("201").name == "Course Syllabus"
    assert index.get_activity_section_id("201") == "100"
    assert index.find_document(role="syllabus").stored_file.filename == "syllabus.pdf"
    assert index.get_file("courses/138907/files/syllabus.pdf").activity_id == "201"
    assert len(index.files_by_sha256["0" * 64]) == 1


def test_archive_index_rejects_duplicate_module_ids() -> None:
    state = json.loads((ROOT / "tests/fixtures/course_state.json").read_text())
    archive = build_course_archive(
        state,
        course_title="Demo Course",
        raw_state_path="courses/138907/raw/course-state.json",
    )
    archive.unassigned_activities.append(archive.sections[0].activities[0].model_copy())

    with pytest.raises(ArchiveIndexError, match="Duplicate module_id"):
        ArchiveIndex(archive)


def test_legacy_assessment_parser_output_is_ignored() -> None:
    state = json.loads((ROOT / "tests/fixtures/course_state.json").read_text())
    archive = build_course_archive(
        state,
        course_title="Demo Course",
        raw_state_path="courses/138907/raw/course-state.json",
    )
    payload = archive.model_dump(mode="json")
    payload["assessments"] = {"historical": "parser output"}

    loaded = type(archive).model_validate(payload)

    assert loaded.course.course_id == archive.course.course_id
    assert "assessments" not in loaded.model_dump(mode="json")
