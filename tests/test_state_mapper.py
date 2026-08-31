import json
from pathlib import Path

from hku_moodle_collector.acquisition.downloader import sanitize_source_url
from hku_moodle_collector.transformation.state_mapper import build_course_archive


ROOT = Path(__file__).parents[1]


def test_build_course_archive_preserves_structure_and_types() -> None:
    state = json.loads((ROOT / "tests/fixtures/course_state.json").read_text())
    archive = build_course_archive(
        state,
        course_title="Demo Course",
        raw_state_path="courses/138907/raw/course-state.json",
    )

    assert archive.schema_version == "2.1"
    assert archive.course.returned_section_count == 2
    assert archive.sections[0].number == 0
    assert archive.sections[0].activities[0].category == "announcement"
    assert archive.sections[0].activities[1].download_status == "pending"
    assert archive.sections[1].activities[0].category == "assignment"
    assert archive.stats.activity_types == {"assign": 1, "forum": 1, "resource": 1}


def test_sensitive_query_values_are_not_persisted() -> None:
    result = sanitize_source_url(
        "https://moodle.example.edu/pluginfile.php/1/a.pdf?sesskey=secret&forcedownload=1"
    )
    assert "secret" not in result
    assert "sesskey" not in result
    assert "forcedownload=1" in result
