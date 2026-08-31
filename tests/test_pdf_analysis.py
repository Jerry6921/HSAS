from pathlib import Path

from pypdf import PdfWriter

from hku_moodle_collector.transformation.pdf_analysis import analyze_pdf


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
