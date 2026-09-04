"""Extract safe text sidecars from modern Word and PowerPoint files."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import math
from pathlib import Path
import re
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from hsas.domain.courses.calculate_statistics import refresh_archive_stats
from hsas.domain.courses.define_courses import CourseArchive
from hsas.domain.courses.define_documents import PdfAnalysis
from hsas.domain.courses.index_courses import iter_files
from hsas.infrastructure.documents.analyze_pdfs import (
    _extractive_summary,
    _keywords,
    _normalise_text,
    _tokens,
)
from hsas.infrastructure.storage.persist_data import safe_filename, write_text


def _natural_key(value: str) -> list[int | str]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", value)]


def _paragraph_text(xml: bytes) -> str:
    root = ElementTree.fromstring(xml)
    paragraphs: list[str] = []
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] != "p":
            continue
        parts = [
            child.text or ""
            for child in node.iter()
            if child.tag.rsplit("}", 1)[-1] == "t"
        ]
        text = "".join(parts).strip()
        if text:
            paragraphs.append(text)
    return _normalise_text("\n".join(paragraphs))


def _docx_units(archive: ZipFile) -> list[tuple[str, str]]:
    preferred = ["word/document.xml"]
    supporting = sorted(
        (
            name
            for name in archive.namelist()
            if re.fullmatch(
                r"word/(?:header|footer|footnotes|endnotes|comments)\d*\.xml",
                name,
            )
        ),
        key=_natural_key,
    )
    units = []
    for name in [*preferred, *supporting]:
        if name in archive.namelist():
            units.append((name, _paragraph_text(archive.read(name))))
    return units


def _pptx_units(archive: ZipFile) -> list[tuple[str, str]]:
    slide_names = sorted(
        (
            name
            for name in archive.namelist()
            if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
        ),
        key=_natural_key,
    )
    note_names = sorted(
        (
            name
            for name in archive.namelist()
            if re.fullmatch(r"ppt/notesSlides/notesSlide\d+\.xml", name)
        ),
        key=_natural_key,
    )
    units = [(name, _paragraph_text(archive.read(name))) for name in slide_names]
    units.extend((name, _paragraph_text(archive.read(name))) for name in note_names)
    return units


def analyze_office_document(
    document_path: Path,
    *,
    text_path: Path,
    storage_root: Path,
    reading_speed_wpm: int = 200,
) -> PdfAnalysis:
    """Extract DOCX/PPTX text without executing macros or embedded objects."""
    suffix = document_path.suffix.casefold()
    kind = "docx" if suffix == ".docx" else "pptx"
    method = "docx_xml" if kind == "docx" else "pptx_xml"
    unit_label = "document" if kind == "docx" else "slide"
    try:
        with ZipFile(document_path) as archive:
            units = _docx_units(archive) if kind == "docx" else _pptx_units(archive)
        rendered: list[str] = []
        text_units = 0
        for index, (name, value) in enumerate(units, start=1):
            if value:
                text_units += 1
            label = "Document part" if kind == "docx" else (
                "Speaker notes" if "notesSlides" in name else "Slide"
            )
            rendered.append(f"--- {label} {index} ---\n{value}")
        full_text = "\n\n".join(rendered).strip()
        write_text(text_path, full_text)
        words = len(_tokens(full_text))
        warnings: list[str] = []
        ocr_required = len(full_text) < 20
        if ocr_required:
            warnings.append("little_or_no_extractable_text; embedded images may require OCR")
        status = "partial" if warnings else "complete"
        encoded = full_text.encode("utf-8")
        return PdfAnalysis(
            status=status,
            extraction_method=method,
            document_kind=kind,
            unit_label=unit_label,
            analyzed_at=datetime.now(timezone.utc),
            page_count=len(units),
            pages_with_text=text_units,
            word_count=words,
            character_count=len(full_text),
            estimated_reading_minutes=math.ceil(words / reading_speed_wpm),
            estimation_basis_wpm=reading_speed_wpm,
            extracted_text_path=text_path.relative_to(storage_root).as_posix(),
            extracted_text_sha256=hashlib.sha256(encoded).hexdigest(),
            extractive_summary=_extractive_summary(full_text),
            keywords=_keywords(full_text),
            ocr_required=ocr_required,
            warnings=warnings,
        )
    except (BadZipFile, ElementTree.ParseError, KeyError, OSError) as exc:
        return PdfAnalysis(
            status="failed",
            extraction_method=method,
            document_kind=kind,
            unit_label=unit_label,
            analyzed_at=datetime.now(timezone.utc),
            page_count=0,
            pages_with_text=0,
            word_count=0,
            character_count=0,
            estimated_reading_minutes=0,
            warnings=[f"analysis_failed:{type(exc).__name__}:{str(exc)[:200]}"],
        )


def analyze_course_office_documents(
    archive: CourseArchive,
    *,
    storage_root: Path,
    course_root: Path,
) -> None:
    for activity, stored_file in iter_files(archive):
        suffix = Path(stored_file.filename).suffix.casefold()
        if suffix not in {".docx", ".pptx"}:
            continue
        if (
            stored_file.analysis
            and stored_file.analysis.extracted_text_path
            and (storage_root / stored_file.analysis.extracted_text_path).is_file()
        ):
            continue
        document_path = storage_root / stored_file.relative_path
        text_name = f"{activity.module_id}-{safe_filename(document_path.stem)}.txt"
        text_path = course_root / "analysis" / "text" / text_name
        stored_file.analysis = analyze_office_document(
            document_path,
            text_path=text_path,
            storage_root=storage_root,
        )
    refresh_archive_stats(archive)
