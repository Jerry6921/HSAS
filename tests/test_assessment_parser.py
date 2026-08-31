import json
from datetime import datetime, timezone
from pathlib import Path

from hku_moodle_collector.transformation.assessment_parser import build_assessment_overview
from hku_moodle_collector.transformation.models import PdfAnalysis, StoredFile
from hku_moodle_collector.transformation.state_mapper import build_course_archive


ROOT = Path(__file__).parents[1]


def test_syllabus_confirms_and_enriches_assessment(tmp_path: Path) -> None:
    state = json.loads((ROOT / "tests/fixtures/course_state.json").read_text())
    state["section"].append(
        {
            "id": "102",
            "number": 2,
            "title": "Final Essay (Due 9 Dec 17:00)",
            "rawtitle": "Final Essay (Due 9 Dec 17:00)",
            "cmlist": [],
            "visible": False,
        }
    )
    archive = build_course_archive(
        state,
        course_title="Demo Course, 2026",
        raw_state_path="courses/138907/raw/course-state.json",
    )
    text_relative = "courses/138907/analysis/text/syllabus.txt"
    text_path = tmp_path / text_relative
    text_path.parent.mkdir(parents=True)
    text_path.write_text(
        "--- Page 1 ---\nAssessment (100% Coursework)\n"
        "Tutorial participation (15%)\nTutorial attendance is mandatory.\n\n"
        "--- Page 2 ---\nFinal Essay (25%)\n"
        "You will write one 1000 word final essay. Final essay due 9 December at 17:00.\n",
        encoding="utf-8",
    )
    syllabus_activity = archive.sections[0].activities[1]
    syllabus_activity.files.append(
        StoredFile(
            filename="syllabus.pdf",
            relative_path="courses/138907/files/syllabus.pdf",
            source_url="https://moodle.example.edu/pluginfile.php/syllabus.pdf",
            content_type="application/pdf",
            size_bytes=1,
            sha256="0" * 64,
            downloaded_at=datetime.now(timezone.utc),
            analysis=PdfAnalysis(
                status="complete",
                analyzed_at=datetime.now(timezone.utc),
                page_count=2,
                pages_with_text=2,
                word_count=20,
                character_count=100,
                estimated_reading_minutes=1,
                extracted_text_path=text_relative,
                extracted_text_sha256="1" * 64,
            ),
        )
    )

    overview = build_assessment_overview(archive, storage_root=tmp_path)
    final = next(item for item in overview.items if item.assessment_type == "essay")

    assert final.status == "confirmed"
    assert final.weight_percent == 25
    assert final.word_limit == 1000
    assert final.due_at == datetime(2026, 12, 9, 17, 0, tzinfo=final.due_at.tzinfo)
    assert overview.grading_basis == "100% Coursework"
