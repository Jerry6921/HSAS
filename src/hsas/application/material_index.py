"""Small local FTS5 index for fast, explainable material retrieval."""

from __future__ import annotations

import json
import hashlib
import sqlite3
from pathlib import Path
from typing import Any, Iterable


SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS indexed_documents (
    evidence_id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL
);
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


def read_signature(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        with sqlite3.connect(path) as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(chunks)")}
            version = connection.execute(
                "SELECT value FROM metadata WHERE key = 'index_version'"
            ).fetchone()
            chunk_count = connection.execute(
                "SELECT value FROM metadata WHERE key = 'indexed_chunk_count'"
            ).fetchone()
            if (
                "evidence_id" not in columns
                or version is None
                or version[0] != "2"
                or chunk_count is None
            ):
                return None
            row = connection.execute(
                "SELECT value FROM metadata WHERE key = 'signature'"
            ).fetchone()
    except sqlite3.Error:
        return None
    return str(row[0]) if row else None


def write_index(path: Path, signature: str, chunks: Iterable[Any], document_count: int, skipped: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    materialized = list(chunks)
    grouped: dict[str, list[Any]] = {}
    for chunk in materialized:
        grouped.setdefault(chunk.evidence_id, []).append(chunk)
    fingerprints = {
        evidence_id: _document_fingerprint(values)
        for evidence_id, values in grouped.items()
    }
    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(chunks)")}
        if columns and "evidence_id" not in columns:
            connection.execute("DROP TABLE chunks")
        connection.executescript(SCHEMA)
        previous = dict(connection.execute(
            "SELECT evidence_id, fingerprint FROM indexed_documents"
        ).fetchall())
        chunk_evidence_ids = {
            str(row[0])
            for row in connection.execute("SELECT DISTINCT evidence_id FROM chunks")
        }
        for evidence_id in sorted(chunk_evidence_ids - set(previous)):
            connection.execute("DELETE FROM chunks WHERE evidence_id = ?", (evidence_id,))
        removed = set(previous) - set(fingerprints)
        changed = {
            evidence_id for evidence_id, fingerprint in fingerprints.items()
            if previous.get(evidence_id) != fingerprint
        }
        for evidence_id in sorted(removed | changed):
            connection.execute("DELETE FROM chunks WHERE evidence_id = ?", (evidence_id,))
            connection.execute("DELETE FROM indexed_documents WHERE evidence_id = ?", (evidence_id,))
        changed_chunks = [
            chunk for evidence_id in changed for chunk in grouped[evidence_id]
        ]
        connection.execute("DELETE FROM metadata")
        connection.executemany(
            """INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                (
                    chunk.evidence_id, chunk.course_id, chunk.course_title, chunk.activity_id,
                    chunk.activity_name, chunk.source_kind, chunk.filename,
                    chunk.relative_text_path, chunk.page_start, chunk.page_end,
                    chunk.source_unit_label, chunk.source_unit_start,
                    chunk.source_unit_end, chunk.chunk_index, chunk.text,
                    json.dumps(chunk.content_tables, ensure_ascii=False),
                )
                for chunk in changed_chunks
            ),
        )
        connection.executemany(
            "INSERT INTO indexed_documents(evidence_id, fingerprint) VALUES (?, ?)",
            ((evidence_id, fingerprints[evidence_id]) for evidence_id in sorted(changed)),
        )
        connection.executemany(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            [
                ("signature", signature),
                ("document_count", str(document_count)),
                ("indexed_chunk_count", str(len(materialized))),
                ("skipped", str(skipped)),
                ("index_version", "2"),
                ("updated_document_count", str(len(changed))),
                ("removed_document_count", str(len(removed))),
            ],
        )
        connection.commit()


def search_index(path: Path, query: str, course_ids: set[str] | None, limit: int) -> dict[str, Any]:
    clauses = ["chunks MATCH ?"]
    params: list[Any] = [query]
    if course_ids:
        placeholders = ",".join("?" for _ in course_ids)
        clauses.append(f"course_id IN ({placeholders})")
        params.extend(sorted(course_ids))
    where = " AND ".join(clauses)
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            f"""SELECT bm25(chunks), evidence_id, course_id, course_title, activity_id,
                activity_name, source_kind, filename, relative_text_path,
                page_start, page_end, source_unit_label, source_unit_start,
                source_unit_end, chunk_index, content, content_tables
                FROM chunks WHERE {where} ORDER BY bm25(chunks) LIMIT ?""",
            [*params, limit],
        ).fetchall()
        document_count = int(connection.execute(
            "SELECT value FROM metadata WHERE key = 'document_count'"
        ).fetchone()[0])
        chunk_count = int(connection.execute(
            "SELECT value FROM metadata WHERE key = 'indexed_chunk_count'"
        ).fetchone()[0])
        skipped = int(connection.execute(
            "SELECT value FROM metadata WHERE key = 'skipped'"
        ).fetchone()[0])
    return {
        "rows": rows,
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
