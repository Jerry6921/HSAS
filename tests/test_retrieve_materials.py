import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from hsas.application.retrieve_materials import list_materials, search_materials
from hsas.domain.courses.define_courses import StoredFile
from hsas.domain.courses.define_documents import PdfAnalysis
from hsas.infrastructure.moodle.map_courses import build_course_archive
from hsas.infrastructure.storage.persist_data import write_model, write_text


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
    activity.metadata["content_text"] = (
        "Timetable Tuesday 9:00-9:50 Tutorial MB167 Friday 10:00 Lecture A CYCC501"
    )
    activity.metadata["content_tables"] = [
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
