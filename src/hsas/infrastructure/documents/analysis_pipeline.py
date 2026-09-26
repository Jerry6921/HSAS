"""Bounded parallel document analysis with content-addressed reuse."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Callable, Literal

from hsas.domain.courses.archive_index import iter_files
from hsas.domain.courses.documents import PdfAnalysis
from hsas.domain.courses.models import CourseArchive, StoredFile
from hsas.domain.courses.statistics import refresh_archive_stats
from hsas.infrastructure.documents.analysis_cache import restore_analysis, store_analysis
from hsas.infrastructure.documents.office import analyze_office_document
from hsas.infrastructure.documents.pdf import analyze_pdf
from hsas.infrastructure.storage.json_store import safe_filename


ParserKind = Literal["pdf", "docx", "pptx"]


@dataclass(frozen=True, slots=True)
class AnalysisStats:
    cache_hits: int
    processed: int
    failed: int


@dataclass(frozen=True, slots=True)
class _AnalysisJob:
    stored_file: StoredFile
    source_path: Path
    text_path: Path
    parser_kind: ParserKind
    parser_id: str


def analyze_course_documents(
    archive: CourseArchive,
    *,
    storage_root: Path,
    course_root: Path,
    cache_root: Path,
    max_workers: int | None = None,
) -> AnalysisStats:
    """Analyze all supported documents concurrently while preserving archive order."""
    jobs = _jobs(archive, storage_root=storage_root, course_root=course_root)
    pending: list[_AnalysisJob] = []
    cache_hits = 0
    for job in jobs:
        existing = job.stored_file.analysis
        if (
            existing is not None
            and existing.extracted_text_path
            and (storage_root / existing.extracted_text_path).is_file()
        ):
            continue
        restored = restore_analysis(
            cache_root,
            source_sha256=job.stored_file.sha256,
            parser_id=job.parser_id,
            text_path=job.text_path,
            storage_root=storage_root,
        )
        if restored is not None:
            job.stored_file.analysis = restored
            cache_hits += 1
        else:
            pending.append(job)

    processed = 0
    failed = 0
    if pending:
        worker_count = _worker_count(len(pending), max_workers)
        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="hiqs-document",
        ) as executor:
            futures: dict[Future[PdfAnalysis], _AnalysisJob] = {
                executor.submit(_analyze, job, storage_root): job for job in pending
            }
            for future in as_completed(futures):
                job = futures[future]
                try:
                    analysis = future.result()
                except Exception as exc:
                    analysis = _failed_analysis(job.parser_kind, exc)
                job.stored_file.analysis = analysis
                processed += 1
                if analysis.status == "failed":
                    failed += 1
                    continue
                store_analysis(
                    cache_root,
                    source_sha256=job.stored_file.sha256,
                    parser_id=job.parser_id,
                    analysis=analysis,
                    text_path=job.text_path,
                )
    refresh_archive_stats(archive)
    return AnalysisStats(cache_hits=cache_hits, processed=processed, failed=failed)


def _jobs(
    archive: CourseArchive,
    *,
    storage_root: Path,
    course_root: Path,
) -> list[_AnalysisJob]:
    jobs: list[_AnalysisJob] = []
    for activity, stored_file in iter_files(archive):
        suffix = Path(stored_file.filename).suffix.casefold()
        parser_kind: ParserKind | None = None
        if stored_file.content_type == "application/pdf" or suffix == ".pdf":
            parser_kind = "pdf"
        elif suffix == ".docx":
            parser_kind = "docx"
        elif suffix == ".pptx":
            parser_kind = "pptx"
        if parser_kind is None:
            continue
        text_name = (
            f"{activity.module_id}-{safe_filename(Path(stored_file.filename).stem)}.txt"
        )
        jobs.append(
            _AnalysisJob(
                stored_file=stored_file,
                source_path=storage_root / stored_file.relative_path,
                text_path=course_root / "analysis" / "text" / text_name,
                parser_kind=parser_kind,
                parser_id=f"{parser_kind}-extractor-v1",
            )
        )
    return jobs


def _analyze(job: _AnalysisJob, storage_root: Path) -> PdfAnalysis:
    analyzer: Callable[..., PdfAnalysis] = (
        analyze_pdf if job.parser_kind == "pdf" else analyze_office_document
    )
    return analyzer(
        job.source_path,
        text_path=job.text_path,
        storage_root=storage_root,
    )


def _worker_count(job_count: int, configured: int | None) -> int:
    available = max((os.cpu_count() or 2) - 1, 1)
    requested = configured if configured is not None else min(available, 4)
    return max(1, min(requested, job_count, 8))


def _failed_analysis(kind: ParserKind, exc: Exception) -> PdfAnalysis:
    from datetime import UTC, datetime

    method = "pypdf" if kind == "pdf" else f"{kind}_xml"
    unit_label = "page" if kind == "pdf" else "document" if kind == "docx" else "slide"
    return PdfAnalysis(
        status="failed",
        extraction_method=method,
        document_kind=kind,
        unit_label=unit_label,
        analyzed_at=datetime.now(UTC),
        page_count=0,
        pages_with_text=0,
        word_count=0,
        character_count=0,
        estimated_reading_minutes=0,
        warnings=[f"analysis_failed:{type(exc).__name__}:{str(exc)[:200]}"],
    )
