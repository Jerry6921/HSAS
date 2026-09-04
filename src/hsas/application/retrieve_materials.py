"""Local, provenance-preserving lexical retrieval over extracted course materials."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
from pathlib import Path
import re

from pydantic import Field

from hsas.domain.courses import ArchiveIndex, StrictModel, iter_files


UNIT_MARKER = re.compile(
    r"^--- (Page|Slide|Speaker notes|Document part) (\d+) ---\s*$",
    re.MULTILINE,
)
WORD = re.compile(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*|[\u3400-\u9fff]+")


class MaterialHit(StrictModel):
    score: float = Field(ge=0)
    course_id: str
    course_title: str
    activity_id: str
    activity_name: str
    filename: str
    relative_text_path: str
    page_start: int | None = None
    page_end: int | None = None
    source_unit_label: str | None = None
    source_unit_start: int | None = None
    source_unit_end: int | None = None
    chunk_index: int = Field(ge=0)
    text: str


class MaterialSearchResult(StrictModel):
    query: str
    course_ids: list[str] = Field(default_factory=list)
    indexed_document_count: int = Field(ge=0)
    indexed_chunk_count: int = Field(ge=0)
    skipped_document_count: int = Field(ge=0)
    hits: list[MaterialHit] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _Chunk:
    course_id: str
    course_title: str
    activity_id: str
    activity_name: str
    filename: str
    relative_text_path: str
    page_start: int | None
    page_end: int | None
    source_unit_label: str | None
    source_unit_start: int | None
    source_unit_end: int | None
    chunk_index: int
    text: str
    tokens: tuple[str, ...]


def search_materials(
    resources_dir: Path,
    query: str,
    *,
    course_ids: set[str] | None = None,
    limit: int = 6,
) -> MaterialSearchResult:
    """Retrieve relevant page-aware chunks without external services."""
    normalized_query = query.strip()
    query_tokens = _tokenize(normalized_query)
    if not query_tokens:
        raise ValueError("material query must contain searchable text")
    if limit < 1 or limit > 20:
        raise ValueError("material result limit must be between 1 and 20")

    chunks: list[_Chunk] = []
    document_count = 0
    skipped = 0
    courses_root = resources_dir / "courses"
    for archive_path in sorted(courses_root.glob("*/course.json")):
        index = ArchiveIndex.from_json(archive_path)
        course_id = index.archive.course.course_id
        if course_ids and course_id not in course_ids:
            continue
        for activity, stored_file in iter_files(index.archive):
            analysis = stored_file.analysis
            if analysis is None or not analysis.extracted_text_path:
                skipped += 1
                continue
            text_path = resources_dir / analysis.extracted_text_path
            if not text_path.is_file():
                skipped += 1
                continue
            text = text_path.read_text(encoding="utf-8")
            document_count += 1
            chunks.extend(
                _chunk_document(
                    text,
                    course_id=course_id,
                    course_title=index.archive.course.title,
                    activity_id=activity.module_id,
                    activity_name=activity.name,
                    filename=stored_file.filename,
                    relative_text_path=analysis.extracted_text_path,
                )
            )

    scored = _rank(chunks, query_tokens, normalized_query)
    hits = [
        MaterialHit(
            score=round(score, 6),
            course_id=chunk.course_id,
            course_title=chunk.course_title,
            activity_id=chunk.activity_id,
            activity_name=chunk.activity_name,
            filename=chunk.filename,
            relative_text_path=chunk.relative_text_path,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            source_unit_label=chunk.source_unit_label,
            source_unit_start=chunk.source_unit_start,
            source_unit_end=chunk.source_unit_end,
            chunk_index=chunk.chunk_index,
            text=chunk.text,
        )
        for score, chunk in scored[:limit]
    ]
    return MaterialSearchResult(
        query=normalized_query,
        course_ids=sorted(course_ids or {chunk.course_id for chunk in chunks}),
        indexed_document_count=document_count,
        indexed_chunk_count=len(chunks),
        skipped_document_count=skipped,
        hits=hits,
    )


def _chunk_document(
    text: str,
    *,
    course_id: str,
    course_title: str,
    activity_id: str,
    activity_name: str,
    filename: str,
    relative_text_path: str,
    words_per_chunk: int = 260,
    overlap_words: int = 40,
) -> list[_Chunk]:
    units = _split_units(text)
    chunks: list[_Chunk] = []
    chunk_index = 0
    step = max(words_per_chunk - overlap_words, 1)
    for unit_label, unit_number, unit_text in units:
        words = unit_text.split()
        for start in range(0, len(words), step):
            selected = words[start : start + words_per_chunk]
            if not selected:
                continue
            content = " ".join(selected).strip()
            tokens = tuple(
                _tokenize(
                    " ".join(
                        [course_title, activity_name, filename, content]
                    )
                )
            )
            if not tokens:
                continue
            chunks.append(
                _Chunk(
                    course_id=course_id,
                    course_title=course_title,
                    activity_id=activity_id,
                    activity_name=activity_name,
                    filename=filename,
                    relative_text_path=relative_text_path,
                    page_start=unit_number if unit_label == "Page" else None,
                    page_end=unit_number if unit_label == "Page" else None,
                    source_unit_label=unit_label,
                    source_unit_start=unit_number,
                    source_unit_end=unit_number,
                    chunk_index=chunk_index,
                    text=content,
                    tokens=tokens,
                )
            )
            chunk_index += 1
            if start + words_per_chunk >= len(words):
                break
    return chunks


def _split_units(text: str) -> list[tuple[str | None, int | None, str]]:
    matches = list(UNIT_MARKER.finditer(text))
    if not matches:
        return [(None, None, text.strip())]
    units: list[tuple[str | None, int | None, str]] = []
    prefix = text[: matches[0].start()].strip()
    if prefix:
        units.append((None, None, prefix))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        units.append(
            (match.group(1), int(match.group(2)), text[match.end() : end].strip())
        )
    return units


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for match in WORD.findall(text.casefold()):
        if re.fullmatch(r"[\u3400-\u9fff]+", match):
            tokens.extend(
                match[index : index + 2]
                for index in range(max(len(match) - 1, 1))
            )
        elif len(match) > 1 or match.isdigit():
            tokens.append(match)
    return tokens


def _rank(
    chunks: list[_Chunk],
    query_tokens: list[str],
    raw_query: str,
) -> list[tuple[float, _Chunk]]:
    if not chunks:
        return []
    document_frequency: Counter[str] = Counter()
    for chunk in chunks:
        document_frequency.update(set(chunk.tokens))
    average_length = sum(len(chunk.tokens) for chunk in chunks) / len(chunks)
    query_counts = Counter(query_tokens)
    ranked: list[tuple[float, _Chunk]] = []
    for chunk in chunks:
        frequencies = Counter(chunk.tokens)
        length = len(chunk.tokens)
        score = 0.0
        for term, query_weight in query_counts.items():
            frequency = frequencies.get(term, 0)
            if not frequency:
                continue
            frequency_count = document_frequency[term]
            inverse_frequency = math.log(
                1 + (len(chunks) - frequency_count + 0.5) / (frequency_count + 0.5)
            )
            normalized = frequency * 2.2 / (
                frequency + 1.2 * (0.25 + 0.75 * length / average_length)
            )
            score += inverse_frequency * normalized * query_weight
        if raw_query.casefold() in chunk.text.casefold():
            score += 2.0
        if score > 0:
            ranked.append((score, chunk))
    return sorted(
        ranked,
        key=lambda value: (
            -value[0],
            value[1].course_id,
            value[1].relative_text_path,
            value[1].chunk_index,
        ),
    )
