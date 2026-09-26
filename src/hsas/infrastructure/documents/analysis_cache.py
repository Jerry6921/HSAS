"""Content-addressed cache for deterministic document analysis artifacts."""

from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import ValidationError

from hsas.domain.courses.documents import PdfAnalysis
from hsas.infrastructure.storage.json_store import read_json, write_json, write_text


CACHE_VERSION = "1"


def restore_analysis(
    cache_root: Path,
    *,
    source_sha256: str,
    parser_id: str,
    text_path: Path,
    storage_root: Path,
) -> PdfAnalysis | None:
    """Restore a validated analysis and copy its text into the current snapshot."""
    metadata_path, cached_text_path = _cache_paths(cache_root, source_sha256, parser_id)
    if not metadata_path.is_file() or not cached_text_path.is_file():
        return None
    try:
        payload = read_json(metadata_path)
        if (
            payload.get("cache_version") != CACHE_VERSION
            or payload.get("source_sha256") != source_sha256
            or payload.get("parser_id") != parser_id
        ):
            return None
        text = cached_text_path.read_text(encoding="utf-8")
        expected_text_sha256 = payload.get("text_sha256")
        actual_text_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if expected_text_sha256 != actual_text_sha256:
            return None
        analysis = PdfAnalysis.model_validate(payload["analysis"])
    except (OSError, KeyError, TypeError, ValueError, ValidationError):
        return None
    write_text(text_path, text)
    return analysis.model_copy(
        update={
            "extracted_text_path": text_path.relative_to(storage_root).as_posix(),
            "extracted_text_sha256": actual_text_sha256,
        }
    )


def store_analysis(
    cache_root: Path,
    *,
    source_sha256: str,
    parser_id: str,
    analysis: PdfAnalysis,
    text_path: Path,
) -> bool:
    """Persist a successful analysis under its immutable content identity."""
    if analysis.status == "failed" or not analysis.extracted_text_path or not text_path.is_file():
        return False
    text = text_path.read_text(encoding="utf-8")
    text_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    metadata_path, cached_text_path = _cache_paths(cache_root, source_sha256, parser_id)
    write_text(cached_text_path, text)
    write_json(
        metadata_path,
        {
            "cache_version": CACHE_VERSION,
            "source_sha256": source_sha256,
            "parser_id": parser_id,
            "text_sha256": text_sha256,
            "analysis": analysis.model_dump(mode="json"),
        },
    )
    return True


def _cache_paths(cache_root: Path, source_sha256: str, parser_id: str) -> tuple[Path, Path]:
    identity = hashlib.sha256(
        f"{CACHE_VERSION}:{parser_id}:{source_sha256}".encode("utf-8")
    ).hexdigest()
    directory = cache_root / CACHE_VERSION / identity[:2]
    return directory / f"{identity}.json", directory / f"{identity}.txt"
