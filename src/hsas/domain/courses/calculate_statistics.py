from __future__ import annotations

from collections import Counter

from .index_courses import iter_activities
from .define_courses import CollectionStats, CourseArchive


def refresh_archive_stats(archive: CourseArchive) -> None:
    """Recompute derived archive statistics after any enrichment stage."""
    activities = list(iter_activities(archive))
    type_counts = Counter(activity.module for activity in activities)
    files = [stored_file for activity in activities for stored_file in activity.files]
    analyses = [stored_file.analysis for stored_file in files if stored_file.analysis]
    archive.stats = CollectionStats(
        section_count=len(archive.sections),
        activity_count=len(activities),
        activity_types=dict(sorted(type_counts.items())),
        downloaded_file_count=len(files),
        downloaded_bytes=sum(stored_file.size_bytes for stored_file in files),
        failed_download_count=sum(
            activity.download_status == "failed" for activity in activities
        ),
        analyzed_pdf_count=sum(
            analysis.status != "failed" and analysis.document_kind == "pdf"
            for analysis in analyses
        ),
        pdf_word_count=sum(
            analysis.word_count for analysis in analyses if analysis.document_kind == "pdf"
        ),
        analyzed_document_count=sum(analysis.status != "failed" for analysis in analyses),
        extracted_text_word_count=sum(analysis.word_count for analysis in analyses),
    )
