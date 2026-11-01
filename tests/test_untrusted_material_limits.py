from pathlib import Path
from zipfile import ZipFile

import pytest

from hsas.domain.courses.models import CourseActivity
from hsas.infrastructure.documents import office, ocr
from hsas.infrastructure.documents.office import analyze_office_document
from hsas.infrastructure.moodle.activity_downloader import (
    _choose_filename,
    _is_storable,
)


class Response:
    def __init__(self, url: str, *, content_type: str = "application/pdf", disposition: str = ""):
        self.url = url
        self.headers = {
            "content-type": content_type,
            "content-disposition": disposition,
        }


def _activity() -> CourseActivity:
    return CourseActivity(
        module_id="10",
        name="Lecture slides",
        category="resource",
        module="resource",
    )


def test_docx_uncompressed_budget_rejects_over_limit_but_default_parses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = tmp_path / "brief.docx"
    xml = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>Assignment due Friday. "
        + "x" * 1200
        + "</w:t></w:r></w:p></w:body></w:document>"
    )
    with ZipFile(document, "w") as archive:
        archive.writestr("word/document.xml", xml)

    monkeypatch.setattr(office, "MAX_UNCOMPRESSED_BYTES", 1024)
    monkeypatch.setattr(office, "MAX_UNCOMPRESSED_ENTRY_BYTES", 1024)
    with pytest.raises(ValueError, match="uncompressed|budget"):
        analyze_office_document(
            document,
            text_path=tmp_path / "analysis/rejected.txt",
            storage_root=tmp_path,
        )

    monkeypatch.setattr(office, "MAX_UNCOMPRESSED_BYTES", 200 * 1024 * 1024)
    monkeypatch.setattr(office, "MAX_UNCOMPRESSED_ENTRY_BYTES", 50 * 1024 * 1024)
    analysis = analyze_office_document(
        document,
        text_path=tmp_path / "analysis/brief.txt",
        storage_root=tmp_path,
    )
    assert analysis.status == "complete"
    assert "Assignment due Friday" in (tmp_path / "analysis/brief.txt").read_text()


def test_pptx_ocr_image_extraction_uses_uncompressed_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    presentation = tmp_path / "slides.pptx"
    with ZipFile(presentation, "w") as archive:
        archive.writestr(
            "ppt/slides/slide1.xml",
            '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" />',
        )
        archive.writestr(
            "ppt/slides/_rels/slide1.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
            'Target="../media/image1.png" /></Relationships>',
        )
        archive.writestr("ppt/media/image1.png", b"image bytes")

    monkeypatch.setattr(ocr, "MAX_UNCOMPRESSED_BYTES", 1)
    monkeypatch.setattr(ocr, "MAX_UNCOMPRESSED_ENTRY_BYTES", 1)
    with pytest.raises(ValueError, match="uncompressed|budget"):
        ocr._extract_pptx_images(presentation, tmp_path / "rejected")

    monkeypatch.setattr(ocr, "MAX_UNCOMPRESSED_BYTES", 200 * 1024 * 1024)
    monkeypatch.setattr(ocr, "MAX_UNCOMPRESSED_ENTRY_BYTES", 50 * 1024 * 1024)
    destination = tmp_path / "images"
    destination.mkdir()
    extracted = ocr._extract_pptx_images(presentation, destination)
    assert [path.read_bytes() for path in extracted] == [b"image bytes"]


@pytest.mark.parametrize(
    "filename, expected_suffix",
    [
        ("lecture\u202e.exe", ".pdf"),
        ("lecture<x>.pdf", ".pdf"),
        ("lecture\x01.pdf", ".pdf"),
    ],
)
def test_choose_filename_sanitizes_name_and_validates_suffix(
    filename: str, expected_suffix: str
) -> None:
    response = Response(
        "https://moodle.example.edu/pluginfile.php/1/view.php",
        disposition=f'attachment; filename="{filename}"',
    )

    chosen = _choose_filename(response, _activity(), 1)

    assert chosen.endswith(expected_suffix)
    assert "\u202e" not in chosen
    assert "<" not in chosen and ">" not in chosen
    assert "\x01" not in chosen


@pytest.mark.parametrize(
    "url, disposition",
    [
        ("https://moodle.example.edu/files/tool.exe", "attachment; filename=notes.pdf"),
        ("https://moodle.example.edu/files/notes.pdf", "attachment; filename=run.command"),
    ],
)
def test_is_storable_rejects_executable_suffixes(url: str, disposition: str) -> None:
    assert _is_storable(Response(url, disposition=disposition)) is False


def test_is_storable_accepts_normal_pdf() -> None:
    assert _is_storable(Response("https://moodle.example.edu/files/notes.pdf")) is True
