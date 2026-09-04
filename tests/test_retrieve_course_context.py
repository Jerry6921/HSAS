import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from typer.testing import CliRunner

from hsas.application.retrieve_course_context import build_course_question_context
from hsas.domain.courses.define_courses import StoredFile
from hsas.domain.courses.define_documents import PdfAnalysis
from hsas.domain.information import InformationStore
from hsas.infrastructure.moodle.map_courses import build_course_archive
from hsas.infrastructure.storage.persist_data import write_model, write_text
from hsas.interfaces.run_cli import app


ROOT = Path(__file__).parents[1]
ZONE = ZoneInfo("Asia/Hong_Kong")


def _resources_with_evidence(tmp_path: Path) -> tuple[Path, InformationStore]:
    resources = tmp_path / "resources"
    state = json.loads((ROOT / "tests/fixtures/course_state.json").read_text())
    archive = build_course_archive(
        state,
        course_title="Calculus and Ordinary Differential Equations",
        raw_state_path="courses/138907/raw/course-state.json",
    )
    activity = archive.sections[0].activities[0]
    activity.name = "Part I assessment briefing"
    text_relative = "courses/138907/analysis/text/part-i.txt"
    stamp = datetime(2026, 9, 1, 8, 0, tzinfo=ZONE)
    activity.files.append(
        StoredFile(
            filename="part-i.pdf",
            relative_path="courses/138907/files/part-i.pdf",
            source_url="https://moodle.example.edu/pluginfile.php/part-i.pdf",
            content_type="application/pdf",
            size_bytes=100,
            sha256="0" * 64,
            downloaded_at=stamp,
            analysis=PdfAnalysis(
                status="complete",
                analyzed_at=stamp,
                page_count=2,
                pages_with_text=2,
                word_count=20,
                character_count=120,
                estimated_reading_minutes=1,
                extracted_text_path=text_relative,
                extracted_text_sha256="1" * 64,
            ),
        )
    )
    write_model(resources / "courses/138907/course.json", archive)
    write_text(
        resources / text_relative,
        "--- Page 1 ---\nGeneral introduction.\n\n"
        "--- Page 2 ---\nThe Part I test covers limits and continuity.",
    )
    information = InformationStore.model_validate(
        {
            "timezone": "Asia/Hong_Kong",
            "updated_at": "2026-09-04T14:00:00+08:00",
            "courses": [
                {
                    "course_id": "138907",
                    "code": "MATH1851",
                    "title": "Calculus and Ordinary Differential Equations",
                    "overview": "A first course in calculus and differential equations.",
                }
            ],
            "items": [
                {
                    "item_id": "math1851-part-i-test",
                    "course_id": "138907",
                    "title": "Part I test",
                    "category": "exam",
                    "date_status": "confirmed",
                    "scheduled_on": "2026-10-02",
                    "weight_percent": 15,
                    "sources": [
                        {
                            "source_type": "course_document",
                            "title": "Important Dates and Assessment labels",
                            "relative_path": "courses/138907/course.json",
                        }
                    ],
                }
            ],
        }
    )
    return resources, information


def test_context_combines_structured_facts_and_page_evidence(tmp_path: Path) -> None:
    resources, information = _resources_with_evidence(tmp_path)

    context = build_course_question_context(
        resources,
        "MATH1851 Part I test limits",
        information=information,
        course_ids={"138907"},
    )

    assert context.course_facts[0].course.code == "MATH1851"
    assert context.information_items[0].item.weight_percent == 15
    assert context.material_evidence.hits[0].filename == "part-i.pdf"
    assert context.material_evidence.hits[0].page_start == 2


def test_query_cli_returns_material_only_packet_when_information_is_missing(
    tmp_path: Path,
) -> None:
    resources, _information = _resources_with_evidence(tmp_path)

    result = CliRunner().invoke(
        app,
        ["--resources", str(resources), "query", "limits", "--course", "138907"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["information_updated_at"] is None
    assert payload["material_evidence"]["hits"][0]["page_start"] == 2
    assert "information.json is unavailable" in payload["warnings"][0]
