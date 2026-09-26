"""Local, provenance-preserving lexical retrieval over extracted course materials."""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import json
import math
from pathlib import Path
import re
import sqlite3
from typing import Any, Literal

from pydantic import Field

from hsas.domain.courses import (
    ArchiveIndex,
    StrictModel,
    activity_evidence_graph,
    linked_page_evidence_id,
    iter_activities,
    iter_files,
)
from hsas.application.material_index import (
    evidence_context,
    index_ready,
    mark_index_stale,
    remove_index_courses,
    replace_index,
    search_index,
    update_index_courses,
)


UNIT_MARKER = re.compile(
    r"^--- (Page|Slide|Speaker notes|Document part) (\d+) ---\s*$",
    re.MULTILINE,
)
WORD = re.compile(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*|[\u3400-\u9fff]+")


class MaterialHit(StrictModel):
    score: float = Field(ge=0)
    evidence_id: str
    course_id: str
    course_title: str
    activity_id: str
    activity_name: str
    source_kind: Literal["file", "moodle_activity"] = "file"
    filename: str
    relative_text_path: str
    page_start: int | None = None
    page_end: int | None = None
    source_unit_label: str | None = None
    source_unit_start: int | None = None
    source_unit_end: int | None = None
    chunk_index: int = Field(ge=0)
    text: str
    text_character_count: int = Field(ge=0)
    text_truncated: bool = False
    retrieval_hint: str | None = None
    content_tables: list[dict[str, Any]] = Field(default_factory=list)


class MaterialSearchResult(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    query: str
    course_ids: list[str] = Field(default_factory=list)
    indexed_document_count: int = Field(ge=0)
    indexed_chunk_count: int = Field(ge=0)
    skipped_document_count: int = Field(ge=0)
    hits: list[MaterialHit] = Field(default_factory=list)


class EvidenceContentChunk(StrictModel):
    course_id: str
    course_title: str
    activity_id: str
    activity_name: str
    source_kind: Literal["file", "moodle_activity"]
    filename: str
    relative_text_path: str
    page_start: int | None = None
    page_end: int | None = None
    source_unit_label: str | None = None
    source_unit_start: int | None = None
    source_unit_end: int | None = None
    chunk_index: int = Field(ge=0)
    text: str
    content_tables: list[dict[str, Any]] = Field(default_factory=list)


class EvidenceContentResult(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    status: Literal["found", "not_found"]
    evidence_id: str
    requested_chunk_index: int | None = None
    context_chunks: int = Field(default=1, ge=0, le=3)
    character_count: int = Field(default=0, ge=0)
    chunks: list[EvidenceContentChunk] = Field(default_factory=list)


def list_materials(
    resources_dir: Path,
    *,
    course_ids: set[str] | None = None,
) -> dict[str, object]:
    """Return a machine-readable manifest of locally downloaded materials."""
    selected = set(course_ids or [])
    documents: list[dict[str, object]] = []
    page_content: list[dict[str, object]] = []
    for archive_path in sorted((resources_dir / "courses").glob("*/course.json")):
        index = ArchiveIndex.from_json(archive_path)
        course_id = index.archive.course.course_id
        if selected and course_id not in selected:
            continue
        course_relative_path = archive_path.relative_to(resources_dir).as_posix()
        for activity in iter_activities(index.archive):
            content_text = activity.content_text
            if isinstance(content_text, str) and content_text.strip():
                page_content.append(
                    {
                        "course_id": course_id,
                        "course_title": index.archive.course.title,
                        "activity_id": activity.module_id,
                        "activity_name": activity.name,
                        "module": activity.module,
                        "relative_path": course_relative_path,
                        "content_text": content_text,
                        "content_tables": activity.content_tables,
                        "evidence_graph": activity_evidence_graph(activity).model_dump(mode="json"),
                    }
                )
            for page in activity.linked_pages:
                if not page.content_text.strip():
                    continue
                page_content.append(
                    {
                        "course_id": course_id,
                        "course_title": index.archive.course.title,
                        "activity_id": activity.module_id,
                        "activity_name": page.title or activity.name,
                        "module": "linked_page",
                        "relative_path": course_relative_path,
                        "content_text": page.content_text,
                        "content_tables": [],
                        "evidence_id": linked_page_evidence_id(activity.module_id, page),
                        "source_url": str(page.url),
                    }
                )
        for activity, stored_file in iter_files(index.archive):
            analysis = stored_file.analysis
            documents.append(
                {
                    "course_id": course_id,
                    "course_title": index.archive.course.title,
                    "activity_id": activity.module_id,
                    "activity_name": activity.name,
                    "filename": stored_file.filename,
                    "relative_path": stored_file.relative_path,
                    "local_path": str(
                        (resources_dir / stored_file.relative_path).resolve()
                    ),
                    "content_type": stored_file.content_type,
                    "size_bytes": stored_file.size_bytes,
                    "sha256": stored_file.sha256,
                    "downloaded_at": stored_file.downloaded_at.isoformat(),
                    "text_path": (
                        str((resources_dir / analysis.extracted_text_path).resolve())
                        if analysis and analysis.extracted_text_path
                        else None
                    ),
                    "analysis_status": analysis.status if analysis else None,
                    "analysis_warnings": analysis.warnings if analysis else [],
                }
            )
    return {
        "resources_dir": str(resources_dir.resolve()),
        "document_count": len(documents),
        "documents": documents,
        "page_content_count": len(page_content),
        "page_content": page_content,
    }


@dataclass(frozen=True, slots=True)
class _Chunk:
    evidence_id: str
    course_id: str
    course_title: str
    activity_id: str
    activity_name: str
    source_kind: Literal["file", "moodle_activity"]
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
    content_tables: list[dict[str, Any]]


def search_materials(
    resources_dir: Path,
    query: str,
    *,
    course_ids: set[str] | None = None,
    limit: int = 6,
    context_character_limit: int = 6_000,
    hit_character_limit: int = 1_200,
) -> MaterialSearchResult:
    """Retrieve relevant page-aware chunks without external services."""
    normalized_query = query.strip()
    query_tokens = _tokenize(normalized_query)
    if not query_tokens:
        raise ValueError("material query must contain searchable text")
    if limit < 1 or limit > 20:
        raise ValueError("material result limit must be between 1 and 20")
    if context_character_limit < 500 or context_character_limit > 50_000:
        raise ValueError("context character limit must be between 500 and 50000")
    if hit_character_limit < 200 or hit_character_limit > 10_000:
        raise ValueError("hit character limit must be between 200 and 10000")

    index_path = resources_dir / "index" / "materials.sqlite3"
    if not index_ready(index_path):
        _ensure_material_index(resources_dir)
    query_expression = " OR ".join(query_tokens)
    try:
        indexed = search_index(index_path, query_expression, course_ids, limit)
    except sqlite3.Error:
        _rebuild_material_index(resources_dir)
        try:
            indexed = search_index(index_path, query_expression, course_ids, limit)
        except sqlite3.Error as exc:
            raise OSError(f"material index search failed after recovery: {exc}") from exc
    return _result_from_index(
        normalized_query,
        course_ids,
        indexed,
        limit,
        context_character_limit=context_character_limit,
        hit_character_limit=hit_character_limit,
    )


def refresh_material_index(
    resources_dir: Path,
    course_ids: set[str] | None = None,
) -> dict[str, int]:
    """Build once or incrementally refresh synchronized course evidence."""
    index_path = resources_dir / "index" / "materials.sqlite3"
    try:
        with _material_index_lock(resources_dir):
            selected = course_ids if course_ids and index_ready(index_path) else None
            chunks, skipped_by_course = _collect_chunks(resources_dir, selected)
            if selected is None:
                return replace_index(
                    index_path,
                    chunks,
                    skipped_by_course=skipped_by_course,
                )
            return update_index_courses(
                index_path,
                chunks,
                course_ids=selected,
                skipped_by_course=skipped_by_course,
            )
    except sqlite3.Error as exc:
        raise OSError(f"material index refresh failed: {exc}") from exc


def _ensure_material_index(resources_dir: Path) -> None:
    index_path = resources_dir / "index" / "materials.sqlite3"
    try:
        with _material_index_lock(resources_dir):
            if index_ready(index_path):
                return
            chunks, skipped_by_course = _collect_chunks(resources_dir, None)
            replace_index(
                index_path,
                chunks,
                skipped_by_course=skipped_by_course,
            )
    except sqlite3.Error as exc:
        raise OSError(f"material index initialization failed: {exc}") from exc


def _rebuild_material_index(resources_dir: Path) -> dict[str, int]:
    """Replace a broken derived index once while serializing competing rebuilds."""
    index_path = resources_dir / "index" / "materials.sqlite3"
    try:
        with _material_index_lock(resources_dir):
            chunks, skipped_by_course = _collect_chunks(resources_dir, None)
            return replace_index(
                index_path,
                chunks,
                skipped_by_course=skipped_by_course,
            )
    except sqlite3.Error as exc:
        raise OSError(f"material index recovery failed: {exc}") from exc


@contextmanager
def _material_index_lock(resources_dir: Path):
    lock_path = resources_dir / "index" / "materials.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def remove_material_index_courses(
    resources_dir: Path,
    course_ids: set[str],
) -> dict[str, int]:
    try:
        with _material_index_lock(resources_dir):
            return remove_index_courses(
                resources_dir / "index" / "materials.sqlite3", course_ids
            )
    except sqlite3.Error as exc:
        raise OSError(f"material index removal failed: {exc}") from exc


def invalidate_material_index(resources_dir: Path) -> None:
    mark_index_stale(resources_dir / "index" / "materials.sqlite3")


def retrieve_evidence_context(
    resources_dir: Path,
    evidence_id: str,
    *,
    chunk_index: int | None = None,
    context_chunks: int = 1,
) -> list[dict[str, Any]]:
    index_path = resources_dir / "index" / "materials.sqlite3"
    if not index_ready(index_path):
        _ensure_material_index(resources_dir)
    try:
        return evidence_context(
            index_path,
            evidence_id,
            chunk_index=chunk_index,
            context_chunks=context_chunks,
        )
    except sqlite3.Error:
        _rebuild_material_index(resources_dir)
        try:
            return evidence_context(
                index_path,
                evidence_id,
                chunk_index=chunk_index,
                context_chunks=context_chunks,
            )
        except sqlite3.Error as exc:
            raise OSError(
                f"material evidence retrieval failed after recovery: {exc}"
            ) from exc


def _collect_chunks(
    resources_dir: Path,
    course_ids: set[str] | None,
) -> tuple[list[_Chunk], dict[str, int]]:
    chunks: list[_Chunk] = []
    skipped_by_course: dict[str, int] = {}
    courses_root = resources_dir / "courses"
    for archive_path in sorted(courses_root.glob("*/course.json")):
        index = ArchiveIndex.from_json(archive_path)
        course_id = index.archive.course.course_id
        if course_ids and course_id not in course_ids:
            continue
        skipped_by_course[course_id] = 0
        course_relative_path = archive_path.relative_to(resources_dir).as_posix()
        for activity in iter_activities(index.archive):
            content_text, content_tables = _activity_evidence(activity)
            if content_text:
                chunks.extend(
                    _chunk_document(
                        content_text,
                        course_id=course_id,
                        course_title=index.archive.course.title,
                        activity_id=activity.module_id,
                        activity_name=activity.name,
                        filename=f"Moodle activity · {activity.name}",
                        relative_text_path=course_relative_path,
                        default_unit_label="Moodle activity",
                        source_kind="moodle_activity",
                        content_tables=content_tables,
                        evidence_id=f"activity:{activity.module_id}",
                    )
                )
            for page_index, page in enumerate(activity.linked_pages):
                if not page.content_text.strip():
                    continue
                chunks.extend(
                    _chunk_document(
                        page.content_text,
                        course_id=course_id,
                        course_title=index.archive.course.title,
                        activity_id=activity.module_id,
                        activity_name=activity.name,
                        filename=page.title or f"Linked Moodle page {page_index + 1}",
                        relative_text_path=course_relative_path,
                        default_unit_label="Linked Moodle page",
                        source_kind="moodle_activity",
                        content_tables=[],
                        evidence_id=linked_page_evidence_id(activity.module_id, page),
                    )
                )
        for activity, stored_file in iter_files(index.archive):
            analysis = stored_file.analysis
            if analysis is None or not analysis.extracted_text_path:
                skipped_by_course[course_id] += 1
                continue
            text_path = resources_dir / analysis.extracted_text_path
            if not text_path.is_file():
                skipped_by_course[course_id] += 1
                continue
            text = text_path.read_text(encoding="utf-8")
            chunks.extend(
                _chunk_document(
                    text,
                    course_id=course_id,
                    course_title=index.archive.course.title,
                    activity_id=activity.module_id,
                    activity_name=activity.name,
                    filename=stored_file.filename,
                    relative_text_path=analysis.extracted_text_path,
                    evidence_id=f"text:{activity.module_id}:{analysis.extracted_text_path}",
                )
            )
    return chunks, skipped_by_course


def _result_from_index(
    query: str,
    course_ids: set[str] | None,
    indexed: dict[str, Any],
    limit: int,
    *,
    context_character_limit: int,
    hit_character_limit: int,
) -> MaterialSearchResult:
    hits = []
    remaining = context_character_limit
    for row in indexed["rows"][:limit]:
        score, *values = row
        tables = json.loads(values[-1])
        full_text = str(values[14])
        allowance = min(hit_character_limit, remaining)
        if allowance <= 0:
            break
        text = full_text
        truncated = len(full_text) > allowance
        if truncated:
            text = full_text[: allowance - 1].rstrip() + "…"
        remaining -= len(text)
        hits.append(MaterialHit(
            score=round(1.0 / (1.0 + abs(float(score))), 6),
            evidence_id=values[0], course_id=values[1], course_title=values[2], activity_id=values[3],
            activity_name=values[4], source_kind=values[5], filename=values[6],
            relative_text_path=values[7], page_start=values[8], page_end=values[9],
            source_unit_label=values[10], source_unit_start=values[11],
            source_unit_end=values[12], chunk_index=values[13], text=text,
            text_character_count=len(full_text), text_truncated=truncated,
            retrieval_hint=(
                "Call get_evidence_content with this evidence_id and chunk_index "
                "to retrieve the complete local context."
                if truncated else None
            ),
            content_tables=tables if isinstance(tables, list) else [],
        ))
    return MaterialSearchResult(
        query=query,
        course_ids=sorted(course_ids or {hit.course_id for hit in hits}),
        indexed_document_count=int(indexed["document_count"]),
        indexed_chunk_count=int(indexed["chunk_count"]),
        skipped_document_count=int(indexed["skipped"]),
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
    default_unit_label: str | None = None,
    source_kind: Literal["file", "moodle_activity"] = "file",
    content_tables: list[dict[str, Any]] | None = None,
    evidence_id: str,
) -> list[_Chunk]:
    units = _split_units(text)
    chunks: list[_Chunk] = []
    chunk_index = 0
    step = max(words_per_chunk - overlap_words, 1)
    for unit_label, unit_number, unit_text in units:
        effective_unit_label = unit_label or default_unit_label
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
                    evidence_id=evidence_id,
                    course_id=course_id,
                    course_title=course_title,
                    activity_id=activity_id,
                    activity_name=activity_name,
                    source_kind=source_kind,
                    filename=filename,
                    relative_text_path=relative_text_path,
                    page_start=unit_number if unit_label == "Page" else None,
                    page_end=unit_number if unit_label == "Page" else None,
                    source_unit_label=effective_unit_label,
                    source_unit_start=unit_number,
                    source_unit_end=unit_number,
                    chunk_index=chunk_index,
                    text=content,
                    tokens=tokens,
                    content_tables=content_tables or [],
                )
            )
            chunk_index += 1
            if start + words_per_chunk >= len(words):
                break
    return chunks


def _activity_evidence(
    activity: Any,
) -> tuple[str, list[dict[str, Any]]]:
    content_text = getattr(activity, "content_text", None)
    text = content_text.strip() if isinstance(content_text, str) else ""
    raw_tables = getattr(activity, "content_tables", None)
    tables = (
        [table for table in raw_tables if isinstance(table, dict)]
        if isinstance(raw_tables, list)
        else []
    )
    table_lines = []
    for table in tables:
        caption = table.get("caption")
        if isinstance(caption, str) and caption.strip():
            table_lines.append(caption.strip())
        rows = table.get("rows")
        if not isinstance(rows, list):
            continue
        for row in rows:
            cells = row.get("cells") if isinstance(row, dict) else None
            if not isinstance(cells, list):
                continue
            values = [
                str(cell.get("text") or "").strip()
                for cell in cells
                if isinstance(cell, dict)
            ]
            if any(values):
                table_lines.append(" | ".join(values))
    table_text = "\n".join(table_lines)
    return "\n".join(value for value in (text, table_text) if value), tables


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
