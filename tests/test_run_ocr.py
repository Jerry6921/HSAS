import json
from datetime import datetime, timezone
from pathlib import Path

from hsas.application.material_search import search_materials
from hsas.domain.courses.models import StoredFile
from hsas.domain.courses.documents import PdfAnalysis
from hsas.infrastructure.documents.ocr import collect_ocr_queue, run_ocr_queue
from hsas.infrastructure.moodle.course_mapper import build_course_archive
from hsas.infrastructure.storage.json_store import write_model


def test_batch_ocr_updates_sidecar_and_archive_atomically(tmp_path: Path) -> None:
    state = json.loads(
        (Path(__file__).parent / "fixtures/course_state.json").read_text(encoding="utf-8")
    )
    archive = build_course_archive(
        state,
        course_title="DEMO1001 Demo Course",
        raw_state_path="courses/138907/raw/course-state.json",
    )
    activity = archive.sections[0].activities[0]
    relative_path = "courses/138907/files/scanned.pdf"
    text_relative_path = "courses/138907/analysis/text/scanned.txt"
    activity.files = [
        StoredFile(
            filename="scanned.pdf",
            relative_path=relative_path,
            source_url="https://moodle.example.edu/pluginfile.php/scanned.pdf",
            content_type="application/pdf",
            size_bytes=7,
            sha256="a" * 64,
            downloaded_at=datetime(2026, 9, 6, tzinfo=timezone.utc),
            analysis=PdfAnalysis(
                status="partial",
                analyzed_at=datetime(2026, 9, 6, tzinfo=timezone.utc),
                page_count=1,
                pages_with_text=0,
                word_count=0,
                character_count=0,
                estimated_reading_minutes=0,
                extracted_text_path=text_relative_path,
                ocr_required=True,
                warnings=["little_or_no_extractable_text; OCR may be required"],
            ),
        )
    ]
    source = tmp_path / relative_path
    source.parent.mkdir(parents=True)
    source.write_bytes(b"%PDF-1")
    sidecar = tmp_path / text_relative_path
    sidecar.parent.mkdir(parents=True)
    sidecar.write_text("--- Page 1 ---", encoding="utf-8")
    archive_path = tmp_path / "courses/138907/course.json"
    write_model(archive_path, archive)

    assert len(collect_ocr_queue(tmp_path)) == 1
    result = run_ocr_queue(
        tmp_path,
        recognizer=lambda _path, _kind: ("--- Page 1 OCR ---\nForce equals mass times acceleration", "Test OCR"),
    )

    assert result["processed_count"] == 1
    assert result["failed_count"] == 0
    assert collect_ocr_queue(tmp_path) == []
    updated = json.loads(archive_path.read_text(encoding="utf-8"))
    analysis = updated["sections"][0]["activities"][0]["files"][0]["analysis"]
    assert analysis["ocr_required"] is False
    assert analysis["ocr_engine"] == "Test OCR"
    assert analysis["extraction_method"] == "pypdf_ocr"
    assert "Force equals mass" in sidecar.read_text(encoding="utf-8")
    indexed = search_materials(tmp_path, "force mass acceleration", course_ids={"138907"})
    assert indexed.hits[0].evidence_id.startswith("text:")
