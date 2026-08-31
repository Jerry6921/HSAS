from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from pypdf import PdfReader

from ...storage.local_store import safe_filename, write_text
from ..common.course_index import iter_files
from ..common.course_schema import CourseArchive
from ..common.course_stats import refresh_archive_stats
from .pdf_schema import PdfAnalysis, PdfMetadata


WORD_RE = re.compile(r"\b[^\W_]+(?:['’][^\W_]+)?\b", re.UNICODE)
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
STOPWORDS = {
    "about", "after", "again", "against", "also", "among", "and", "another",
    "are", "because", "been", "before", "being", "between", "both", "but",
    "can", "could", "did", "does", "doing", "during", "each", "from", "had",
    "has", "have", "having", "here", "how", "into", "its", "itself", "may",
    "more", "most", "must", "not", "only", "other", "our", "over", "same",
    "should", "some", "such", "than", "that", "the", "their", "them", "then",
    "there", "these", "they", "this", "those", "through", "under", "using",
    "very", "was", "were", "what", "when", "where", "which", "while", "who",
    "will", "with", "would", "you", "your",
}


def _normalise_text(value: str) -> str:
    value = value.replace("\x00", " ").replace("\u00a0", " ")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _tokens(text: str) -> list[str]:
    return [match.group(0).casefold() for match in WORD_RE.finditer(text)]


def _keywords(text: str, limit: int = 12) -> list[str]:
    counts = Counter(
        word for word in _tokens(text) if len(word) >= 4 and word not in STOPWORDS
    )
    return [word for word, _ in counts.most_common(limit)]


def _extractive_summary(text: str, limit: int = 5) -> str | None:
    compact = re.sub(r"\s+", " ", text).strip()
    sentences = [
        sentence.strip()
        for sentence in SENTENCE_RE.split(compact)
        if 50 <= len(sentence.strip()) <= 500
    ]
    if not sentences:
        return compact[:1200] or None
    frequencies = Counter(
        word for word in _tokens(compact) if len(word) >= 4 and word not in STOPWORDS
    )
    candidates: list[tuple[float, int, str]] = []
    for index, sentence in enumerate(sentences[:500]):
        words = [word for word in _tokens(sentence) if word in frequencies]
        if not words:
            continue
        score = sum(frequencies[word] for word in words) / math.sqrt(len(words))
        candidates.append((score, index, sentence))
    selected = sorted(candidates, reverse=True)[:limit]
    selected.sort(key=lambda item: item[1])
    summary = " ".join(item[2] for item in selected)
    return summary[:2000] or None


def _metadata(reader: PdfReader) -> PdfMetadata:
    raw = reader.metadata or {}

    def value(key: str) -> str | None:
        item = raw.get(key)
        return str(item).strip() if item else None

    return PdfMetadata(
        title=value("/Title"),
        author=value("/Author"),
        subject=value("/Subject"),
        creator=value("/Creator"),
        producer=value("/Producer"),
    )


def analyze_pdf(
    pdf_path: Path,
    *,
    text_path: Path,
    storage_root: Path,
    reading_speed_wpm: int = 200,
) -> PdfAnalysis:
    warnings: list[str] = []
    try:
        reader = PdfReader(pdf_path)
        page_texts: list[str] = []
        pages_with_text = 0
        for page_number, page in enumerate(reader.pages, start=1):
            try:
                text = _normalise_text(page.extract_text() or "")
            except Exception as exc:
                text = ""
                warnings.append(f"page_{page_number}_extraction_failed:{type(exc).__name__}")
            if text:
                pages_with_text += 1
            page_texts.append(text)

        full_text = "\n\n".join(
            f"--- Page {number} ---\n{text}"
            for number, text in enumerate(page_texts, start=1)
        ).strip()
        plain_text = "\n\n".join(page_texts).strip()
        write_text(text_path, full_text)
        text_bytes = full_text.encode("utf-8")
        word_count = len(_tokens(plain_text))
        page_count = len(reader.pages)
        ocr_required = len(plain_text) < 100 or pages_with_text < max(1, page_count // 2)
        if ocr_required:
            warnings.append("little_or_no_extractable_text; OCR may be required")
        status = "partial" if warnings or ocr_required else "complete"
        return PdfAnalysis(
            status=status,
            analyzed_at=datetime.now(timezone.utc),
            page_count=page_count,
            pages_with_text=pages_with_text,
            word_count=word_count,
            character_count=len(plain_text),
            estimated_reading_minutes=math.ceil(word_count / reading_speed_wpm),
            estimation_basis_wpm=reading_speed_wpm,
            extracted_text_path=text_path.relative_to(storage_root).as_posix(),
            extracted_text_sha256=hashlib.sha256(text_bytes).hexdigest(),
            extractive_summary=_extractive_summary(plain_text),
            keywords=_keywords(plain_text),
            ocr_required=ocr_required,
            metadata=_metadata(reader),
            warnings=warnings,
        )
    except Exception as exc:
        return PdfAnalysis(
            status="failed",
            analyzed_at=datetime.now(timezone.utc),
            page_count=0,
            pages_with_text=0,
            word_count=0,
            character_count=0,
            estimated_reading_minutes=0,
            ocr_required=False,
            warnings=[f"analysis_failed:{type(exc).__name__}:{str(exc)[:200]}"],
        )


def analyze_course_pdfs(
    archive: CourseArchive,
    *,
    storage_root: Path,
    course_root: Path,
) -> None:
    for activity, stored_file in iter_files(archive):
        if not (
            stored_file.content_type == "application/pdf"
            or stored_file.filename.casefold().endswith(".pdf")
        ):
            continue
        if (
            stored_file.analysis
            and stored_file.analysis.extracted_text_path
            and (storage_root / stored_file.analysis.extracted_text_path).exists()
        ):
            continue
        pdf_path = storage_root / stored_file.relative_path
        text_name = (
            f"{activity.module_id}-{safe_filename(Path(stored_file.filename).stem)}.txt"
        )
        text_path = course_root / "analysis" / "text" / text_name
        stored_file.analysis = analyze_pdf(
            pdf_path,
            text_path=text_path,
            storage_root=storage_root,
        )
    refresh_archive_stats(archive)
