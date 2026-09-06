"""Discover and process local documents that need OCR."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import hashlib
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from hsas.domain.courses import ArchiveIndex, iter_files
from hsas.domain.courses.calculate_statistics import refresh_archive_stats
from hsas.domain.courses.define_courses import StoredFile
from hsas.infrastructure.documents.analyze_pdfs import (
    _extractive_summary,
    _keywords,
    _tokens,
)
from hsas.infrastructure.storage.persist_data import write_model, write_text


Recognizer = Callable[[Path, str], tuple[str, str]]
VISION_SCRIPT = Path(__file__).with_name("vision_ocr.swift")
LEGACY_MACOS_SDK = Path("/Library/Developer/CommandLineTools/SDKs/MacOSX15.4.sdk")


class OcrError(RuntimeError):
    """A local OCR capability or processing failure."""


def ocr_capabilities() -> dict[str, object]:
    native = (
        sys.platform == "darwin"
        and Path("/usr/bin/swift").is_file()
        and VISION_SCRIPT.is_file()
    )
    tesseract = shutil.which("tesseract")
    pdftoppm = shutil.which("pdftoppm")
    available = native or bool(tesseract and pdftoppm)
    engine = "Apple Vision" if native else "Tesseract" if available else None
    return {
        "available": available,
        "engine": engine,
        "supports_pdf": native or bool(tesseract and pdftoppm),
        "supports_pptx": native or bool(tesseract),
    }


def collect_ocr_queue(resources_dir: Path) -> list[dict[str, object]]:
    queue: list[dict[str, object]] = []
    for index in _load_archives(resources_dir):
        for activity, stored_file in iter_files(index.archive):
            analysis = stored_file.analysis
            if analysis is None or not analysis.ocr_required:
                continue
            queue.append(
                {
                    "course_id": index.archive.course.course_id,
                    "course_title": index.archive.course.title,
                    "activity_id": activity.module_id,
                    "activity_name": activity.name,
                    "title": stored_file.filename,
                    "relative_path": stored_file.relative_path,
                    "document_kind": analysis.document_kind,
                    "page_count": analysis.page_count,
                    "character_count": analysis.character_count,
                    "warnings": analysis.warnings,
                }
            )
    return queue


def run_ocr_queue(
    resources_dir: Path,
    *,
    course_ids: set[str] | None = None,
    recognizer: Recognizer | None = None,
) -> dict[str, object]:
    """OCR every queued PDF/PPTX and atomically refresh each course archive."""
    resources = resources_dir.resolve()
    recognize = recognizer or _recognize_document
    processed: list[dict[str, str]] = []
    failures: list[dict[str, str]] = []
    for index in _load_archives(resources):
        course_id = index.archive.course.course_id
        if course_ids and course_id not in course_ids:
            continue
        archive_changed = False
        for _activity, stored_file in iter_files(index.archive):
            analysis = stored_file.analysis
            if analysis is None or not analysis.ocr_required:
                continue
            source = (resources / stored_file.relative_path).resolve()
            if not source.is_relative_to(resources) or not source.is_file():
                failures.append(
                    {"course_id": course_id, "title": stored_file.filename, "error": "source_missing"}
                )
                continue
            try:
                text, engine = recognize(source, analysis.document_kind)
                if not text.strip():
                    raise OcrError("OCR returned no text")
                _apply_ocr_text(resources, stored_file, text, engine)
                archive_changed = True
                processed.append(
                    {"course_id": course_id, "title": stored_file.filename, "engine": engine}
                )
            except (OcrError, OSError, subprocess.SubprocessError, BadZipFile) as exc:
                failures.append(
                    {
                        "course_id": course_id,
                        "title": stored_file.filename,
                        "error": f"{type(exc).__name__}: {str(exc)[:240]}",
                    }
                )
        if archive_changed:
            refresh_archive_stats(index.archive)
            archive_path = index.source_path or resources / "courses" / course_id / "course.json"
            write_model(archive_path, index.archive)
    return {
        "processed_count": len(processed),
        "failed_count": len(failures),
        "processed": processed,
        "failures": failures,
    }


def _load_archives(resources_dir: Path) -> list[ArchiveIndex]:
    return [
        ArchiveIndex.from_json(path)
        for path in sorted((resources_dir / "courses").glob("*/course.json"))
    ]


def _apply_ocr_text(
    resources: Path,
    stored_file: StoredFile,
    ocr_text: str,
    engine: str,
) -> None:
    analysis = stored_file.analysis
    assert analysis is not None
    if analysis.extracted_text_path:
        text_path = (resources / analysis.extracted_text_path).resolve()
    else:
        suffix = hashlib.sha256(stored_file.relative_path.encode()).hexdigest()[:12]
        text_path = resources / "analysis" / "ocr" / f"{suffix}.txt"
    if not text_path.is_relative_to(resources):
        raise OcrError("OCR text path escapes resources directory")
    existing = (
        text_path.read_text(encoding="utf-8", errors="replace").strip()
        if text_path.is_file()
        else ""
    )
    combined = "\n\n".join(value for value in (existing, ocr_text.strip()) if value)
    write_text(text_path, combined)
    encoded = combined.encode("utf-8")
    warnings = [
        warning
        for warning in analysis.warnings
        if "ocr" not in warning.casefold() and "little_or_no_extractable_text" not in warning
    ]
    words = len(_tokens(combined))
    method = "pypdf_ocr" if analysis.document_kind == "pdf" else "pptx_xml_ocr"
    stored_file.analysis = analysis.model_copy(
        update={
            "status": "partial" if warnings else "complete",
            "extraction_method": method,
            "analyzed_at": datetime.now(UTC),
            "word_count": words,
            "character_count": len(combined),
            "estimated_reading_minutes": math.ceil(words / analysis.estimation_basis_wpm),
            "extracted_text_path": text_path.relative_to(resources).as_posix(),
            "extracted_text_sha256": hashlib.sha256(encoded).hexdigest(),
            "extractive_summary": _extractive_summary(combined),
            "keywords": _keywords(combined),
            "ocr_required": False,
            "ocr_completed_at": datetime.now(UTC),
            "ocr_engine": engine,
            "warnings": warnings,
        }
    )


def _recognize_document(path: Path, document_kind: str) -> tuple[str, str]:
    capabilities = ocr_capabilities()
    if not capabilities["available"]:
        raise OcrError("No local OCR engine is available")
    if document_kind == "pptx":
        with TemporaryDirectory(prefix="hiqs-ocr-") as temporary:
            images = _extract_pptx_images(path, Path(temporary))
            if not images:
                raise OcrError("PPTX contains no slide images")
            return _recognize_images(images)
    if document_kind != "pdf":
        raise OcrError(f"Unsupported OCR document kind: {document_kind}")
    if capabilities["engine"] == "Apple Vision":
        return _run_apple_vision([path]), "Apple Vision"
    return _recognize_pdf_with_tesseract(path), "Tesseract"


def _recognize_images(paths: list[Path]) -> tuple[str, str]:
    if sys.platform == "darwin" and Path("/usr/bin/swift").is_file():
        return _run_apple_vision(paths), "Apple Vision"
    tesseract = shutil.which("tesseract")
    if not tesseract:
        raise OcrError("No local image OCR engine is available")
    sections = []
    for path in paths:
        result = _run_command([tesseract, str(path), "stdout"])
        sections.append(f"--- {_image_label(path)} ---\n{result.strip()}")
    return "\n\n".join(sections), "Tesseract"


def _run_apple_vision(paths: list[Path]) -> str:
    command = ["/usr/bin/swift"]
    if LEGACY_MACOS_SDK.is_dir():
        command.extend(["-sdk", str(LEGACY_MACOS_SDK)])
    command.extend([str(VISION_SCRIPT), *(str(path) for path in paths)])
    environment = os.environ.copy()
    environment["SWIFT_MODULECACHE_PATH"] = "/private/tmp/hiqs-swift-cache"
    environment["CLANG_MODULE_CACHE_PATH"] = "/private/tmp/hiqs-clang-cache"
    return _run_command(command, environment=environment)


def _recognize_pdf_with_tesseract(path: Path) -> str:
    pdftoppm = shutil.which("pdftoppm")
    tesseract = shutil.which("tesseract")
    if not pdftoppm or not tesseract:
        raise OcrError("Tesseract PDF OCR requires pdftoppm and tesseract")
    with TemporaryDirectory(prefix="hiqs-ocr-") as temporary:
        prefix = Path(temporary) / "page"
        _run_command([pdftoppm, "-png", "-r", "220", str(path), str(prefix)])
        images = sorted(prefix.parent.glob("page-*.png"), key=_natural_path_key)
        sections = []
        for page, image in enumerate(images, start=1):
            text = _run_command([tesseract, str(image), "stdout"])
            sections.append(f"--- Page {page} OCR ---\n{text.strip()}")
        return "\n\n".join(sections)


def _run_command(
    command: list[str],
    *,
    environment: dict[str, str] | None = None,
) -> str:
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
        env=environment,
    )
    if result.returncode != 0:
        raise OcrError(result.stderr.strip() or f"command exited with {result.returncode}")
    return result.stdout


def _extract_pptx_images(path: Path, destination: Path) -> list[Path]:
    extracted: list[Path] = []
    with ZipFile(path) as archive:
        slide_names = sorted(
            (name for name in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)),
            key=_natural_path_key,
        )
        for slide_name in slide_names:
            slide_number = int(re.search(r"(\d+)", PurePosixPath(slide_name).name).group(1))
            rel_name = f"ppt/slides/_rels/{PurePosixPath(slide_name).name}.rels"
            if rel_name not in archive.namelist():
                continue
            root = ElementTree.fromstring(archive.read(rel_name))
            targets = [
                node.attrib.get("Target", "")
                for node in root
                if node.attrib.get("Type", "").endswith("/image")
            ]
            for image_number, target in enumerate(targets, start=1):
                archive_name = str(PurePosixPath("ppt/slides", target))
                archive_name = str(PurePosixPath(archive_name.replace("ppt/slides/../", "ppt/")))
                if archive_name not in archive.namelist():
                    continue
                suffix = PurePosixPath(archive_name).suffix or ".png"
                output = destination / f"slide-{slide_number}-image-{image_number}{suffix}"
                output.write_bytes(archive.read(archive_name))
                extracted.append(output)
    return extracted


def _image_label(path: Path) -> str:
    match = re.match(r"slide-(\d+)-image-(\d+)", path.stem)
    return f"Slide {match.group(1)} OCR image {match.group(2)}" if match else f"Image {path.stem} OCR"


def _natural_path_key(value: str | Path) -> list[int | str]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", str(value))]
