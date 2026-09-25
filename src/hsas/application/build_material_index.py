"""Small local FTS5 index for fast, explainable material retrieval."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable


SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
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
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT value FROM metadata WHERE key = 'signature'"
        ).fetchone()
    return str(row[0]) if row else None


def write_index(path: Path, signature: str, chunks: Iterable[Any], document_count: int, skipped: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(SCHEMA)
        connection.execute("DELETE FROM chunks")
        connection.execute("DELETE FROM metadata")
        connection.executemany(
            """INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                (
                    chunk.course_id, chunk.course_title, chunk.activity_id,
                    chunk.activity_name, chunk.source_kind, chunk.filename,
                    chunk.relative_text_path, chunk.page_start, chunk.page_end,
                    chunk.source_unit_label, chunk.source_unit_start,
                    chunk.source_unit_end, chunk.chunk_index, chunk.text,
                    json.dumps(chunk.content_tables, ensure_ascii=False),
                )
                for chunk in chunks
            ),
        )
        connection.executemany(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            [("signature", signature), ("document_count", str(document_count)), ("skipped", str(skipped))],
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
            f"""SELECT bm25(chunks), course_id, course_title, activity_id,
                activity_name, source_kind, filename, relative_text_path,
                page_start, page_end, source_unit_label, source_unit_start,
                source_unit_end, chunk_index, content, content_tables
                FROM chunks WHERE {where} ORDER BY bm25(chunks) LIMIT ?""",
            [*params, limit],
        ).fetchall()
        document_count = connection.execute(
            f"""SELECT COUNT(DISTINCT course_id || ':' || activity_id || ':' || source_kind)
                FROM chunks WHERE {where}""",
            params,
        ).fetchone()[0]
        chunk_count = connection.execute(
            f"SELECT COUNT(*) FROM chunks WHERE {where}", params
        ).fetchone()[0]
        skipped = int(connection.execute(
            "SELECT value FROM metadata WHERE key = 'skipped'"
        ).fetchone()[0])
    return {
        "rows": rows,
        "document_count": document_count,
        "chunk_count": chunk_count,
        "skipped": skipped,
    }
