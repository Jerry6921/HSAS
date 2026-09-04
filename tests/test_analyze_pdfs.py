from pathlib import Path
from zipfile import ZipFile

from pypdf import PdfWriter

from hsas.infrastructure.documents.analyze_pdfs import analyze_pdf
from hsas.infrastructure.documents.analyze_office_documents import analyze_office_document


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
