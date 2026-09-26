from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

from pypdf import PdfWriter

from hsas.infrastructure.documents.pdf import analyze_pdf
from hsas.infrastructure.documents.office import analyze_office_document
from hsas.infrastructure.documents.analysis_pipeline import analyze_course_documents
from hsas.domain.courses.models import StoredFile
from hsas.infrastructure.moodle.course_mapper import build_course_archive


ROOT = Path(__file__).parents[1]


def test_blank_pdf_is_marked_for_ocr(tmp_path: Path) -> None:
    pdf_path = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with pdf_path.open("wb") as stream:
        writer.write(stream)

    analysis = analyze_pdf(
        pdf_path,
        text_path=tmp_path / "output/text.txt",
        storage_root=tmp_path,
    )

    assert analysis.status == "partial"
    assert analysis.page_count == 1
    assert analysis.ocr_required is True
    assert analysis.extracted_text_path == "output/text.txt"


def test_docx_text_is_extracted_to_ai_readable_sidecar(tmp_path: Path) -> None:
    document = tmp_path / "brief.docx"
    with ZipFile(document, "w") as archive:
        archive.writestr(
            "word/document.xml",
            """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Assignment due Friday at 23:59.</w:t></w:r></w:p><w:p><w:r><w:t>Submit one report.</w:t></w:r></w:p></w:body></w:document>""",
        )

    analysis = analyze_office_document(
        document,
        text_path=tmp_path / "analysis/brief.txt",
        storage_root=tmp_path,
    )

    assert analysis.status == "complete"
    assert analysis.document_kind == "docx"
    assert analysis.extraction_method == "docx_xml"
    assert "Assignment due Friday" in (tmp_path / "analysis/brief.txt").read_text()


def test_pptx_slides_and_speaker_notes_are_extracted(tmp_path: Path) -> None:
    presentation = tmp_path / "lecture.pptx"
    with ZipFile(presentation, "w") as archive:
        archive.writestr(
            "ppt/slides/slide1.xml",
            """<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:p><a:r><a:t>Lecture topic</a:t></a:r></a:p></p:sld>""",
        )
        archive.writestr(
            "ppt/notesSlides/notesSlide1.xml",
            """<p:notes xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:p><a:r><a:t>Explain this example</a:t></a:r></a:p></p:notes>""",
        )

    analysis = analyze_office_document(
        presentation,
        text_path=tmp_path / "analysis/lecture.txt",
        storage_root=tmp_path,
    )
    text = (tmp_path / "analysis/lecture.txt").read_text()

    assert analysis.status == "complete"
    assert analysis.document_kind == "pptx"
    assert analysis.extraction_method == "pptx_xml"
    assert "--- Slide 1 ---" in text
    assert "--- Speaker notes 1 ---" in text
    assert "Lecture topic" in text
    assert "Explain this example" in text


def test_image_only_pptx_is_marked_for_ocr(tmp_path: Path) -> None:
    presentation = tmp_path / "scanned-slides.pptx"
    with ZipFile(presentation, "w") as archive:
        archive.writestr(
            "ppt/slides/slide1.xml",
            """<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" />""",
        )
        archive.writestr("ppt/media/image1.png", b"not-a-real-image")

    analysis = analyze_office_document(
        presentation,
        text_path=tmp_path / "analysis/scanned-slides.txt",
        storage_root=tmp_path,
    )

    assert analysis.status == "partial"
    assert analysis.ocr_required is True
    assert analysis.page_count == 1
    assert analysis.pages_with_text == 0


def test_analysis_pipeline_reuses_content_addressed_cache(tmp_path: Path) -> None:
    resources = tmp_path / "resources"
    state = json.loads((ROOT / "tests/fixtures/course_state.json").read_text())
    archive = build_course_archive(
        state,
        course_title="Demo",
        raw_state_path="courses/138907/raw/course-state.json",
    )
    activity = archive.sections[0].activities[0]
    document = resources / "courses/138907/files/brief.docx"
    document.parent.mkdir(parents=True)
    with ZipFile(document, "w") as source:
        source.writestr(
            "word/document.xml",
            """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Cached assignment instructions.</w:t></w:r></w:p></w:body></w:document>""",
        )
    digest = hashlib.sha256(document.read_bytes()).hexdigest()
    activity.files = [
        StoredFile(
            filename="brief.docx",
            relative_path="courses/138907/files/brief.docx",
            source_url="https://moodle.example.edu/pluginfile.php/brief.docx",
            content_type=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            size_bytes=document.stat().st_size,
            sha256=digest,
            downloaded_at=datetime.now(UTC),
        )
    ]
    course_root = resources / "courses/138907"
    cache_root = resources / "cache/document-analysis"

    first = analyze_course_documents(
        archive,
        storage_root=resources,
        course_root=course_root,
        cache_root=cache_root,
        max_workers=2,
    )
    text_path = resources / activity.files[0].analysis.extracted_text_path
    activity.files[0].analysis = None
    text_path.unlink()
    second = analyze_course_documents(
        archive,
        storage_root=resources,
        course_root=course_root,
        cache_root=cache_root,
        max_workers=2,
    )

    assert first.processed == 1
    assert first.cache_hits == 0
    assert second.processed == 0
    assert second.cache_hits == 1
    assert "Cached assignment instructions" in text_path.read_text(encoding="utf-8")
