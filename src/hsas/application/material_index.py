"""Persistent FTS5 storage for incrementally indexed course evidence."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Any, Iterable


INDEX_VERSION = "3"
SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS indexed_courses (
    course_id TEXT PRIMARY KEY,
    skipped_document_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS indexed_documents (
    evidence_id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    chunk_count INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS indexed_documents_course
    ON indexed_documents(course_id);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
    evidence_id UNINDEXED,
    course_id UNINDEXED, course_title UNINDEXED, activity_id UNINDEXED,
    activity_name UNINDEXED, source_kind UNINDEXED, filename UNINDEXED,
    relative_text_path UNINDEXED, page_start UNINDEXED, page_end UNINDEXED,
    source_unit_label UNINDEXED, source_unit_start UNINDEXED,
    source_unit_end UNINDEXED, chunk_index UNINDEXED,
    content, content_tables UNINDEXED,
    tokenize = 'unicode61'
);
"""


def index_ready(path: Path) -> bool:
    """Return whether a compatible, fully initialized index is available."""
    if not path.is_file():
        return False
    try:
        with _connect(path, writable=False) as connection:
            version = connection.execute(
                "SELECT value FROM metadata WHERE key = 'index_version'"
            ).fetchone()
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(indexed_documents)")
            }
    except sqlite3.Error:
        return False
    return version is not None and version[0] == INDEX_VERSION and "course_id" in columns


def replace_index(
    path: Path,
    chunks: Iterable[Any],
    *,
    skipped_by_course: dict[str, int],
) -> dict[str, int]:
    """Atomically replace an incompatible or explicitly rebuilt global index."""
    materialized = list(chunks)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        with _connect(temporary_path, use_wal=False) as connection:
            connection.executescript(SCHEMA)
            grouped = _group_chunks(materialized)
            _insert_documents(connection, grouped)
            connection.executemany(
                "INSERT INTO indexed_courses(course_id, skipped_document_count) VALUES (?, ?)",
                sorted(skipped_by_course.items()),
            )
            stats = _write_metadata(connection, updated=len(grouped), removed=0)
            connection.commit()
        _remove_sqlite_sidecars(path)
        os.replace(temporary_path, path)
        return stats
    finally:
        temporary_path.unlink(missing_ok=True)
        _remove_sqlite_sidecars(temporary_path)


def update_index_courses(
    path: Path,
    chunks: Iterable[Any],
    *,
    course_ids: set[str],
    skipped_by_course: dict[str, int],
) -> dict[str, int]:
    """Upsert only changed courses while preserving every unaffected FTS row."""
    if not course_ids:
        return index_statistics(path)
    materialized = list(chunks)
    grouped = _group_chunks(materialized)
    unexpected = {values[0].course_id for values in grouped.values()} - course_ids
    if unexpected:
        raise ValueError(f"chunks contain courses outside update scope: {sorted(unexpected)}")

    path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(path) as connection:
        _prepare_schema(connection)
        placeholders = ",".join("?" for _ in course_ids)
        previous = dict(
            connection.execute(
                f"SELECT evidence_id, fingerprint FROM indexed_documents "
                f"WHERE course_id IN ({placeholders})",
                sorted(course_ids),
            ).fetchall()
        )
        fingerprints = {
            evidence_id: _document_fingerprint(values)
            for evidence_id, values in grouped.items()
        }
        removed = set(previous) - set(fingerprints)
        changed = {
            evidence_id
            for evidence_id, fingerprint in fingerprints.items()
            if previous.get(evidence_id) != fingerprint
        }
        for evidence_id in sorted(removed | changed):
            connection.execute("DELETE FROM chunks WHERE evidence_id = ?", (evidence_id,))
            connection.execute(
                "DELETE FROM indexed_documents WHERE evidence_id = ?", (evidence_id,)
            )
        _insert_documents(
            connection,
            {evidence_id: grouped[evidence_id] for evidence_id in changed},
        )
        connection.executemany(
            """INSERT INTO indexed_courses(course_id, skipped_document_count)
               VALUES (?, ?)
               ON CONFLICT(course_id) DO UPDATE SET
                   skipped_document_count = excluded.skipped_document_count""",
            (
                (course_id, int(skipped_by_course.get(course_id, 0)))
                for course_id in sorted(course_ids)
            ),
        )
        stats = _write_metadata(connection, updated=len(changed), removed=len(removed))
        connection.commit()
    return stats


def remove_index_courses(path: Path, course_ids: set[str]) -> dict[str, int]:
    """Remove deleted course evidence without rebuilding unrelated courses."""
    if not course_ids or not index_ready(path):
        return index_statistics(path)
    with _connect(path) as connection:
        placeholders = ",".join("?" for _ in course_ids)
        evidence_ids = [
            row[0]
            for row in connection.execute(
                f"SELECT evidence_id FROM indexed_documents "
                f"WHERE course_id IN ({placeholders})",
                sorted(course_ids),
            )
        ]
        for evidence_id in evidence_ids:
            connection.execute("DELETE FROM chunks WHERE evidence_id = ?", (evidence_id,))
        connection.execute(
            f"DELETE FROM indexed_documents WHERE course_id IN ({placeholders})",
            sorted(course_ids),
        )
        connection.execute(
            f"DELETE FROM indexed_courses WHERE course_id IN ({placeholders})",
            sorted(course_ids),
        )
        stats = _write_metadata(connection, updated=0, removed=len(evidence_ids))
        connection.commit()
    return stats


def search_index(
    path: Path,
    query: str,
    course_ids: set[str] | None,
    limit: int,
) -> dict[str, Any]:
    clauses = ["chunks MATCH ?"]
    params: list[Any] = [query]
    if course_ids:
        placeholders = ",".join("?" for _ in course_ids)
        clauses.append(f"course_id IN ({placeholders})")
        params.extend(sorted(course_ids))
    where = " AND ".join(clauses)
    with _connect(path, writable=False) as connection:
        rows = connection.execute(
            f"""SELECT bm25(chunks), evidence_id, course_id, course_title, activity_id,
                activity_name, source_kind, filename, relative_text_path,
                page_start, page_end, source_unit_label, source_unit_start,
                source_unit_end, chunk_index, content, content_tables
                FROM chunks WHERE {where} ORDER BY bm25(chunks) LIMIT ?""",
            [*params, limit],
        ).fetchall()
        stats = _statistics(connection)
    return {"rows": rows, **stats}


def evidence_context(
    path: Path,
    evidence_id: str,
    *,
    chunk_index: int | None = None,
    context_chunks: int = 1,
) -> list[dict[str, Any]]:
    """Read one indexed evidence document or a bounded chunk neighborhood."""
    if context_chunks < 0 or context_chunks > 3:
        raise ValueError("context_chunks must be between 0 and 3")
    clauses = ["evidence_id = ?"]
    params: list[Any] = [evidence_id]
    if chunk_index is not None:
        clauses.append("chunk_index BETWEEN ? AND ?")
        params.extend([max(0, chunk_index - context_chunks), chunk_index + context_chunks])
    with _connect(path, writable=False) as connection:
        rows = connection.execute(
            f"""SELECT course_id, course_title, activity_id, activity_name, source_kind,
                filename, relative_text_path, page_start, page_end, source_unit_label,
                source_unit_start, source_unit_end, chunk_index, content, content_tables
                FROM chunks WHERE {' AND '.join(clauses)} ORDER BY chunk_index""",
            params,
        ).fetchall()
    keys = (
        "course_id", "course_title", "activity_id", "activity_name", "source_kind",
        "filename", "relative_text_path", "page_start", "page_end", "source_unit_label",
        "source_unit_start", "source_unit_end", "chunk_index", "text", "content_tables",
    )
    return [
        {**dict(zip(keys, row, strict=True)), "content_tables": json.loads(row[-1])}
        for row in rows
    ]


def index_statistics(path: Path) -> dict[str, int]:
    if not index_ready(path):
        return {"document_count": 0, "chunk_count": 0, "skipped": 0}
    with _connect(path, writable=False) as connection:
        return _statistics(connection)


def mark_index_stale(path: Path) -> None:
    """Invalidate a derived index so the next read safely performs one rebuild."""
    if not path.is_file():
        return
    try:
        with _connect(path) as connection:
            connection.execute("DELETE FROM metadata WHERE key = 'index_version'")
            connection.commit()
    except sqlite3.Error:
        return


def _connect(
    path: Path,
    *,
    writable: bool = True,
    use_wal: bool = True,
) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA busy_timeout = 5000")
    if writable and use_wal:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
    return connection


def _remove_sqlite_sidecars(path: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        path.with_name(path.name + suffix).unlink(missing_ok=True)


def _prepare_schema(connection: sqlite3.Connection) -> None:
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(indexed_documents)")
    }
    if columns and not {"course_id", "fingerprint", "chunk_count"}.issubset(columns):
        _reset_schema(connection)
    connection.executescript(SCHEMA)


def _reset_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        DROP TABLE IF EXISTS chunks;
        DROP TABLE IF EXISTS indexed_documents;
        DROP TABLE IF EXISTS indexed_courses;
        DROP TABLE IF EXISTS metadata;
        """
    )


def _group_chunks(chunks: list[Any]) -> dict[str, list[Any]]:
    grouped: dict[str, list[Any]] = {}
    for chunk in chunks:
        grouped.setdefault(chunk.evidence_id, []).append(chunk)
    return grouped


def _insert_documents(
    connection: sqlite3.Connection,
    grouped: dict[str, list[Any]],
) -> None:
    for evidence_id, values in sorted(grouped.items()):
        if not values:
            continue
        connection.executemany(
            "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (_chunk_row(chunk) for chunk in values),
        )
        connection.execute(
            """INSERT INTO indexed_documents(evidence_id, course_id, fingerprint, chunk_count)
               VALUES (?, ?, ?, ?)""",
            (
                evidence_id,
                values[0].course_id,
                _document_fingerprint(values),
                len(values),
            ),
        )


def _chunk_row(chunk: Any) -> tuple[Any, ...]:
    return (
        chunk.evidence_id,
        chunk.course_id,
        chunk.course_title,
        chunk.activity_id,
        chunk.activity_name,
        chunk.source_kind,
        chunk.filename,
        chunk.relative_text_path,
        chunk.page_start,
        chunk.page_end,
        chunk.source_unit_label,
        chunk.source_unit_start,
        chunk.source_unit_end,
        chunk.chunk_index,
        chunk.text,
        json.dumps(chunk.content_tables, ensure_ascii=False),
    )


def _write_metadata(
    connection: sqlite3.Connection,
    *,
    updated: int,
    removed: int,
) -> dict[str, int]:
    stats = _statistics(connection)
    values = {
        "index_version": INDEX_VERSION,
        "document_count": str(stats["document_count"]),
        "indexed_chunk_count": str(stats["chunk_count"]),
        "skipped": str(stats["skipped"]),
        "updated_document_count": str(updated),
        "removed_document_count": str(removed),
    }
    connection.execute("DELETE FROM metadata")
    connection.executemany(
        "INSERT INTO metadata(key, value) VALUES (?, ?)", sorted(values.items())
    )
    return stats


def _statistics(connection: sqlite3.Connection) -> dict[str, int]:
    document_count = int(
        connection.execute("SELECT COUNT(*) FROM indexed_documents").fetchone()[0]
    )
    chunk_count = int(connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
    skipped = int(
        connection.execute(
            "SELECT COALESCE(SUM(skipped_document_count), 0) FROM indexed_courses"
        ).fetchone()[0]
    )
    return {
        "document_count": document_count,
        "chunk_count": chunk_count,
        "skipped": skipped,
    }


def _document_fingerprint(chunks: list[Any]) -> str:
    payload = [
        {
            "chunk_index": chunk.chunk_index,
            "text": chunk.text,
            "path": chunk.relative_text_path,
            "tables": chunk.content_tables,
        }
        for chunk in chunks
    ]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
