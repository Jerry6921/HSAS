"""Degraded reads must be reported instead of silently dropping canonical facts."""

from __future__ import annotations

import json
from pathlib import Path

from hsas.application.material_search import refresh_material_index, search_evidence
from hsas.infrastructure.moodle.course_mapper import build_course_archive
from hsas.infrastructure.moodle.gateway import _load_previous_archive
from hsas.infrastructure.sis.course_info.gateway import discover_moodle_course_codes
from hsas.infrastructure.storage.json_store import write_json, write_model

ROOT = Path(__file__).parents[1]


def _archive(title: str = "Neuroscience Demo"):
    state = json.loads((ROOT / "tests/fixtures/course_state.json").read_text())
    return build_course_archive(
        state,
        course_title=title,
        raw_state_path="courses/138907/raw/course-state.json",
    )


def _course_resources(tmp_path: Path) -> Path:
    resources = tmp_path / "resources"
    write_model(resources / "courses/138907/course.json", _archive())
    return resources


def test_search_reports_corrupt_canonical_store(tmp_path: Path) -> None:
    resources = _course_resources(tmp_path)
    (resources / "information.json").write_text("{not json", encoding="utf-8")

    result = search_evidence(resources, "moodle activity")

    assert any("information.json could not be read" in warning for warning in result.warnings)


def test_search_reports_missing_canonical_store(tmp_path: Path) -> None:
    resources = _course_resources(tmp_path)

    result = search_evidence(resources, "moodle activity")

    assert any("information.json is missing" in warning for warning in result.warnings)


def test_healthy_search_has_no_degradation_warning(tmp_path: Path) -> None:
    resources = _course_resources(tmp_path)
    write_json(resources / "information.json", {"courses": [], "items": []})

    result = search_evidence(resources, "moodle activity")

    assert result.warnings == []


def test_index_refresh_reports_corrupt_canonical_store(tmp_path: Path) -> None:
    resources = _course_resources(tmp_path)
    (resources / "information.json").write_text("{not json", encoding="utf-8")

    status = refresh_material_index(resources)

    assert any("information.json could not be read" in value for value in status["warnings"])


def test_corrupt_previous_snapshot_is_flagged(tmp_path: Path) -> None:
    course_path = tmp_path / "courses/138907/course.json"
    course_path.parent.mkdir(parents=True)
    course_path.write_text("{not json", encoding="utf-8")

    archive, corrupt = _load_previous_archive(course_path)

    assert archive is None
    assert corrupt is True


def test_readable_previous_snapshot_is_not_flagged(tmp_path: Path) -> None:
    course_path = tmp_path / "courses/138907/course.json"
    write_model(course_path, _archive())

    archive, corrupt = _load_previous_archive(course_path)

    assert archive is not None
    assert corrupt is False


def test_sis_discovery_counts_corrupt_snapshot(tmp_path: Path) -> None:
    resources = tmp_path / "resources"
    write_model(resources / "courses/138907/course.json", _archive())
    corrupt = resources / "courses/999/course.json"
    corrupt.parent.mkdir(parents=True)
    corrupt.write_text("{not json", encoding="utf-8")

    _courses, skipped = discover_moodle_course_codes(resources)

    assert any("999: unreadable course.json" in value for value in skipped)
