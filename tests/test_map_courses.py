import json
from pathlib import Path

from hsas.infrastructure.moodle.download_files import sanitize_source_url
from hsas.infrastructure.moodle.map_courses import build_course_archive, map_activity


ROOT = Path(__file__).parents[1]


def test_build_course_archive_preserves_structure_and_types() -> None:
    state = json.loads((ROOT / "tests/fixtures/course_state.json").read_text())
    state["cm"][2]["duedate"] = 1794733200
    archive = build_course_archive(
        state,
        course_title="Demo Course",
        raw_state_path="courses/138907/raw/course-state.json",
    )

    assert archive.schema_version == "2.2"
    assert archive.course.returned_section_count == 2
    assert archive.sections[0].number == 0
    assert archive.sections[0].activities[0].category == "announcement"
    assert archive.sections[0].activities[1].download_status == "pending"
    assert archive.sections[1].activities[0].category == "assignment"
    assert archive.sections[1].activities[0].metadata["duedate"] == 1794733200
    assert archive.stats.activity_types == {"assign": 1, "forum": 1, "resource": 1}


def test_sensitive_query_values_are_not_persisted() -> None:
    result = sanitize_source_url(
        "https://moodle.example.edu/pluginfile.php/1/a.pdf?sesskey=secret&forcedownload=1"
    )
    assert "secret" not in result
    assert "sesskey" not in result
    assert "forcedownload=1" in result


def test_url_activities_are_inspected_for_downloadable_google_documents() -> None:
    activity = map_activity(
        {
            "id": 7,
            "module": "url",
            "name": "Shared brief",
            "url": "https://moodle.example.edu/mod/url/view.php?id=7",
        }
    )

    assert activity.category == "url"
    assert activity.download_status == "pending"
