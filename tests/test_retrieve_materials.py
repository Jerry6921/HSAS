import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from hsas.application.material_search import (
    list_materials,
    refresh_material_index,
    retrieve_evidence_context,
    search_materials,
)
from hsas.domain.courses.models import StoredFile
from hsas.domain.courses.documents import PdfAnalysis
from hsas.domain.courses.evidence import LinkedPageEvidence, linked_page_evidence_id
from hsas.infrastructure.moodle.course_mapper import build_course_archive
from hsas.infrastructure.storage.json_store import write_model, write_text


ROOT = Path(__file__).parents[1]
ZONE = ZoneInfo("Asia/Hong_Kong")


def test_local_search_returns_page_and_activity_provenance(tmp_path: Path) -> None:
    resources = tmp_path / "resources"
    state = json.loads((ROOT / "tests/fixtures/course_state.json").read_text())
    archive = build_course_archive(
        state, course_title="Neuroscience Demo", raw_state_path="courses/138907/raw/course-state.json"
    )
    activity = archive.sections[0].activities[0]
    activity.name = "Thalamic Bridge Reading"
    text_relative = "courses/138907/analysis/text/bridge.txt"
    stamp = datetime(2026, 9, 1, 8, 0, tzinfo=ZONE)
    activity.files.append(
        StoredFile(
            filename="bridge.pdf",
            relative_path="courses/138907/files/bridge.pdf",
            source_url="https://moodle.example.edu/pluginfile.php/bridge.pdf",
            content_type="application/pdf",
            size_bytes=100,
            sha256="0" * 64,
            downloaded_at=stamp,
            analysis=PdfAnalysis(
                status="complete",
                analyzed_at=stamp,
                page_count=2,
                pages_with_text=2,
                word_count=40,
                character_count=240,
                estimated_reading_minutes=1,
                extracted_text_path=text_relative,
                extracted_text_sha256="1" * 64,
            ),
        )
    )
    write_model(resources / "courses/138907/course.json", archive)
    write_text(
        resources / text_relative,
        "--- Page 1 ---\nOrdinary neural signalling.\n\n"
        "--- Page 2 ---\nA thalamic bridge may transmit sensory information.",
    )
    result = search_materials(resources, "thalamic bridge sensory", course_ids={"138907"})
    assert result.indexed_document_count == 1
    assert result.hits[0].activity_name == "Thalamic Bridge Reading"
    assert result.hits[0].evidence_id == f"text:{activity.module_id}:{text_relative}"
    assert result.hits[0].filename == "bridge.pdf"
    assert result.hits[0].page_start == 2
    assert result.hits[0].source_unit_label == "Page"
    assert result.hits[0].source_unit_start == 2


def test_local_search_returns_slide_provenance(tmp_path: Path) -> None:
    resources = tmp_path / "resources"
    state = json.loads((ROOT / "tests/fixtures/course_state.json").read_text())
    archive = build_course_archive(
        state, course_title="Neuroscience Demo", raw_state_path="courses/138907/raw/course-state.json"
    )
    activity = archive.sections[0].activities[0]
    text_relative = "courses/138907/analysis/text/lecture.txt"
    stamp = datetime(2026, 9, 1, 8, 0, tzinfo=ZONE)
    activity.files.append(
        StoredFile(
            filename="lecture.pptx",
            relative_path="courses/138907/files/lecture.pptx",
            source_url="https://moodle.example.edu/pluginfile.php/lecture.pptx",
            content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            size_bytes=100,
            sha256="2" * 64,
            downloaded_at=stamp,
            analysis=PdfAnalysis(
                status="complete",
                analyzed_at=stamp,
                page_count=2,
                pages_with_text=2,
                word_count=20,
                character_count=120,
                estimated_reading_minutes=1,
                extracted_text_path=text_relative,
                extracted_text_sha256="3" * 64,
            ),
        )
    )
    write_model(resources / "courses/138907/course.json", archive)
    write_text(
        resources / text_relative,
        "--- Slide 1 ---\nOrdinary introduction.\n\n"
        "--- Speaker notes 1 ---\nThalamic relay explanation.",
    )

    result = search_materials(resources, "thalamic relay", course_ids={"138907"})

    assert result.hits[0].filename == "lecture.pptx"
    assert result.hits[0].source_unit_label == "Speaker notes"
    assert result.hits[0].source_unit_start == 1
    assert result.hits[0].page_start is None


def test_local_search_indexes_rendered_moodle_activity_text(tmp_path: Path) -> None:
    resources = tmp_path / "resources"
    state = json.loads((ROOT / "tests/fixtures/course_state.json").read_text())
    archive = build_course_archive(
        state,
        course_title="Calculus Demo",
        raw_state_path="courses/138907/raw/course-state.json",
    )
    activity = archive.sections[0].activities[0]
    activity.name = "Timetable"
    activity.module = "label"
    activity.content_text = (
        "Timetable Tuesday 9:00-9:50 Tutorial MB167 Friday 10:00 Lecture A CYCC501"
    )
    activity.content_tables = [
        {
            "caption": "Timetable",
            "rows": [
                {
                    "cells": [
                        {"text": "9:00-9:50"},
                        {"text": ""},
                        {"text": "Tutorial (MB167)"},
                    ]
                }
            ],
        }
    ]
    write_model(resources / "courses/138907/course.json", archive)

    result = search_materials(
        resources,
        "Tuesday tutorial MB167",
        course_ids={"138907"},
    )
    manifest = list_materials(resources, course_ids={"138907"})

    assert result.indexed_document_count == 1
    assert result.hits[0].activity_id == activity.module_id
    assert result.hits[0].evidence_id == f"activity:{activity.module_id}"
    assert result.hits[0].source_kind == "moodle_activity"
    assert result.hits[0].filename == "Moodle activity · Timetable"
    assert result.hits[0].relative_text_path == "courses/138907/course.json"
    assert result.hits[0].source_unit_label == "Moodle activity"
    assert result.hits[0].content_tables[0]["caption"] == "Timetable"
    assert manifest["page_content_count"] == 1
    assert manifest["page_content"][0]["content_tables"][0]["caption"] == "Timetable"


def test_linked_page_search_hit_resolves_to_graph_node(tmp_path: Path) -> None:
    resources = tmp_path / "resources"
    state = json.loads((ROOT / "tests/fixtures/course_state.json").read_text())
    archive = build_course_archive(
        state, course_title="Calculus Demo", raw_state_path="courses/138907/raw/course-state.json"
    )
    activity = archive.sections[0].activities[0]
    activity.linked_pages.append(LinkedPageEvidence(
        url="https://moodle.example.edu/mod/page/view.php?id=22",
        depth=1,
        title="Tutorial registration",
        content_text="Register for the Tuesday tutorial in room MB167.",
    ))
    write_model(resources / "courses/138907/course.json", archive)

    result = search_materials(resources, "Tuesday tutorial MB167")

    assert result.hits[0].evidence_id == linked_page_evidence_id(
        activity.module_id, activity.linked_pages[0]
    )


def test_fts_refresh_preserves_unchanged_evidence_rows(tmp_path: Path) -> None:
    resources = tmp_path / "resources"
    state = json.loads((ROOT / "tests/fixtures/course_state.json").read_text())
    archive = build_course_archive(
        state, course_title="Calculus Demo", raw_state_path="courses/138907/raw/course-state.json"
    )
    first, second = archive.sections[0].activities[:2]
    first.content_text = "alpha calculus unchanged evidence"
    write_model(resources / "courses/138907/course.json", archive)
    search_materials(resources, "alpha calculus")
    index_path = resources / "index/materials.sqlite3"
    with sqlite3.connect(index_path) as connection:
        before = connection.execute(
            "SELECT rowid FROM chunks WHERE evidence_id = ?", (f"activity:{first.module_id}",)
        ).fetchone()[0]

    second.content_text = "beta differential equation new evidence"
    write_model(resources / "courses/138907/course.json", archive)
    refresh_material_index(resources, {"138907"})
    result = search_materials(resources, "beta differential")
    with sqlite3.connect(index_path) as connection:
        after = connection.execute(
            "SELECT rowid FROM chunks WHERE evidence_id = ?", (f"activity:{first.module_id}",)
        ).fetchone()[0]
        updated = connection.execute(
            "SELECT value FROM metadata WHERE key = 'updated_document_count'"
        ).fetchone()[0]

    assert after == before
    assert updated == "1"
    assert result.hits[0].evidence_id == f"activity:{second.module_id}"


def test_course_filters_do_not_rebuild_global_index(tmp_path: Path) -> None:
    resources = tmp_path / "resources"
    state = json.loads((ROOT / "tests/fixtures/course_state.json").read_text())
    archive = build_course_archive(
        state, course_title="Calculus Demo", raw_state_path="courses/138907/raw/course-state.json"
    )
    activity = archive.sections[0].activities[0]
    activity.content_text = "calculus derivative integral"
    write_model(resources / "courses/138907/course.json", archive)

    search_materials(resources, "calculus", course_ids={"138907"})
    index_path = resources / "index/materials.sqlite3"
    before = index_path.stat().st_mtime_ns

    assert search_materials(resources, "calculus", course_ids={"999999"}).hits == []
    assert search_materials(resources, "derivative", course_ids={"138907"}).hits
    assert index_path.stat().st_mtime_ns == before


def test_agent_packet_is_bounded_and_full_context_is_hydrated_on_demand(
    tmp_path: Path,
) -> None:
    resources = tmp_path / "resources"
    state = json.loads((ROOT / "tests/fixtures/course_state.json").read_text())
    archive = build_course_archive(
        state, course_title="Calculus Demo", raw_state_path="courses/138907/raw/course-state.json"
    )
    activity = archive.sections[0].activities[0]
    activity.content_text = "calculus " + "bounded-context-evidence " * 120
    write_model(resources / "courses/138907/course.json", archive)

    result = search_materials(
        resources,
        "calculus bounded context evidence",
        context_character_limit=500,
        hit_character_limit=300,
    )
    hit = result.hits[0]
    hydrated = retrieve_evidence_context(
        resources,
        hit.evidence_id,
        chunk_index=hit.chunk_index,
        context_chunks=1,
    )

    assert hit.text_truncated is True
    assert len(hit.text) <= 300
    assert hit.retrieval_hint is not None
    assert len(hydrated[0]["text"]) > len(hit.text)


def _write_search_archive(resources: Path, text: str = "alpha calculus evidence"):
    state = json.loads((ROOT / "tests/fixtures/course_state.json").read_text())
    archive = build_course_archive(
        state,
        course_title="Recovery Demo",
        raw_state_path="courses/138907/raw/course-state.json",
    )
    activity = archive.sections[0].activities[0]
    activity.content_text = text
    write_model(resources / "courses/138907/course.json", archive)
    return archive, activity


def test_v2_index_is_automatically_migrated_by_rebuild(tmp_path: Path) -> None:
    resources = tmp_path / "resources"
    _, activity = _write_search_archive(resources)
    index_path = resources / "index/materials.sqlite3"
    index_path.parent.mkdir(parents=True)
    with sqlite3.connect(index_path) as connection:
        connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO metadata VALUES ('index_version', '2')")
        connection.execute(
            "CREATE TABLE indexed_documents "
            "(evidence_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, chunk_count INTEGER NOT NULL)"
        )

    result = search_materials(resources, "alpha calculus")

    with sqlite3.connect(index_path) as connection:
        version = connection.execute(
            "SELECT value FROM metadata WHERE key = 'index_version'"
        ).fetchone()[0]
    assert version == "3"
    assert result.hits[0].evidence_id == f"activity:{activity.module_id}"


def test_corrupt_index_file_is_rebuilt_without_user_action(tmp_path: Path) -> None:
    resources = tmp_path / "resources"
    _write_search_archive(resources)
    assert search_materials(resources, "alpha").hits
    index_path = resources / "index/materials.sqlite3"
    index_path.write_bytes(b"not a sqlite database")

    recovered = search_materials(resources, "calculus")

    assert recovered.hits
    with sqlite3.connect(index_path) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_query_time_index_failure_is_recovered_once(tmp_path: Path) -> None:
    resources = tmp_path / "resources"
    _write_search_archive(resources)
    assert search_materials(resources, "alpha").hits
    index_path = resources / "index/materials.sqlite3"
    with sqlite3.connect(index_path) as connection:
        connection.execute("DROP TABLE chunks")

    recovered = search_materials(resources, "calculus")

    assert recovered.hits


def test_failed_incremental_update_rolls_back_to_previous_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hsas.application import material_index

    resources = tmp_path / "resources"
    archive, _ = _write_search_archive(resources)
    assert search_materials(resources, "alpha").hits
    archive.sections[0].activities[0].content_text = "beta replacement evidence"
    write_model(resources / "courses/138907/course.json", archive)

    def fail_insert(*_args, **_kwargs):
        raise RuntimeError("simulated interruption")

    monkeypatch.setattr(material_index, "_insert_documents", fail_insert)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        refresh_material_index(resources, {"138907"})

    assert search_materials(resources, "alpha").hits
    assert search_materials(resources, "beta").hits == []


def test_search_and_incremental_refresh_are_concurrency_safe(tmp_path: Path) -> None:
    resources = tmp_path / "resources"
    _write_search_archive(resources, "concurrent calculus evidence")
    assert search_materials(resources, "concurrent").hits

    def read_repeatedly() -> int:
        return sum(
            bool(search_materials(resources, "concurrent calculus").hits)
            for _ in range(15)
        )

    def refresh_repeatedly() -> int:
        for _ in range(8):
            refresh_material_index(resources, {"138907"})
        return 8

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(read_repeatedly) for _ in range(5)]
        futures.append(executor.submit(refresh_repeatedly))
        results = [future.result(timeout=20) for future in futures]

    assert results == [15, 15, 15, 15, 15, 8]
