import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from hsas.application.retrieve_materials import search_materials
from hsas.domain.courses.define_courses import StoredFile
from hsas.domain.courses.define_documents import PdfAnalysis
from hsas.infrastructure.moodle.map_courses import build_course_archive
from hsas.infrastructure.storage.persist_data import write_model, write_text


ROOT = Path(__file__).parents[1]
ZONE = ZoneInfo("Asia/Hong_Kong")


def test_local_search_returns_page_and_activity_provenance(tmp_path: Path) -> None:
    resources = tmp_path / "resources"
    state = json.loads((ROOT / "tests/fixtures/course_state.json").read_text())
    archive = build_course_archive(
        state, course_title="Neuroscience Demo", raw_state_path="courses/138907/raw/course-state.json"
    )
    activity = archive.sections[0].activities[0]
    activity.name = "Thalamic Bridge Reading"
    text_relative = "courses/138907/analysis/text/bridge.txt"
    stamp = datetime(2026, 9, 1, 8, 0, tzinfo=ZONE)
    activity.files.append(
        StoredFile(
            filename="bridge.pdf",
            relative_path="courses/138907/files/bridge.pdf",
            source_url="https://moodle.example.edu/pluginfile.php/bridge.pdf",
            content_type="application/pdf",
            size_bytes=100,
            sha256="0" * 64,
            downloaded_at=stamp,
            analysis=PdfAnalysis(
                status="complete",
                analyzed_at=stamp,
                page_count=2,
                pages_with_text=2,
                word_count=40,
                character_count=240,
                estimated_reading_minutes=1,
                extracted_text_path=text_relative,
                extracted_text_sha256="1" * 64,
            ),
        )
    )
    write_model(resources / "courses/138907/course.json", archive)
    write_text(
        resources / text_relative,
        "--- Page 1 ---\nOrdinary neural signalling.\n\n"
        "--- Page 2 ---\nA thalamic bridge may transmit sensory information.",
    )
    result = search_materials(resources, "thalamic bridge sensory", course_ids={"138907"})
    assert result.indexed_document_count == 1
    assert result.hits[0].activity_name == "Thalamic Bridge Reading"
    assert result.hits[0].filename == "bridge.pdf"
    assert result.hits[0].page_start == 2
