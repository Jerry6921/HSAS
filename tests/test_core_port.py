from datetime import UTC, datetime
import json
from pathlib import Path

import pytest

from hsas.core import (
    ApplicationLifecyclePort,
    CourseSyncPort,
    HIQSCore,
    HIQSPort,
    HIQSPortError,
    InformationCommandPort,
    InformationQueryPort,
    build_port,
)
from hsas.infrastructure.moodle.course_mapper import build_course_archive
from hsas.infrastructure.storage.json_store import write_model


ROOT = Path(__file__).parents[1]


def test_core_implements_public_port(tmp_path: Path) -> None:
    core = HIQSCore(resources_dir=tmp_path)

    assert isinstance(core, HIQSPort)
    assert isinstance(core, InformationQueryPort)
    assert isinstance(core, InformationCommandPort)
    assert isinstance(core, CourseSyncPort)
    assert isinstance(core, ApplicationLifecyclePort)
    assert core.resources_dir == tmp_path


def test_core_composes_capability_services_with_shared_state(tmp_path: Path) -> None:
    core = HIQSCore(resources_dir=tmp_path)

    assert core.record_service.resources_dir == tmp_path
    assert core.review_service.resources_dir == tmp_path
    assert core.personal_inbox_service.resources_dir == tmp_path
    assert core.material_query_service.resources_dir == tmp_path
    assert core.dashboard_projection_service.resources_dir == tmp_path
    assert core.sync_workflow.resources_dir == tmp_path
    assert core.record_service.mutation_lock is core.mutation_lock
    assert core.personal_inbox_service.mutation_lock is core.mutation_lock
    assert core.sync_workflow.mutation_lock is core.mutation_lock
    assert core.sync_workflow.controller is core.sync_controller


def test_build_port_uses_explicit_resources_directory(tmp_path: Path) -> None:
    port = build_port(tmp_path)

    assert isinstance(port, HIQSPort)
    assert port.resources_dir == tmp_path


def test_core_exposes_information_schema_and_empty_material_manifest(tmp_path: Path) -> None:
    core = HIQSCore(resources_dir=tmp_path)

    schema = core.information_update_schema()
    manifest = core.materials_manifest()

    assert schema["title"] == "InformationUpdate"
    assert manifest["document_count"] == 0
    assert manifest["documents"] == []


def test_core_exposes_attention_through_public_query_port(tmp_path: Path) -> None:
    now = datetime(2026, 9, 24, tzinfo=UTC)
    core = HIQSCore(resources_dir=tmp_path, clock=lambda: now)

    snapshot = core.attention_snapshot()

    assert snapshot["generated_at"] == "2026-09-24T00:00:00Z"
    assert snapshot["horizon_days"] == 14
    assert snapshot["items"][0]["reason_codes"] == ["LOGIN_REQUIRED"]


def test_core_rejects_string_as_course_id_list(tmp_path: Path) -> None:
    core = HIQSCore(resources_dir=tmp_path)

    with pytest.raises(HIQSPortError, match="list of strings"):
        core.search_materials({"query": "calculus", "course_ids": "142655"})


def test_core_resolves_stable_evidence_node(tmp_path: Path) -> None:
    state = json.loads((ROOT / "tests/fixtures/course_state.json").read_text())
    archive = build_course_archive(
        state, course_title="Demo", raw_state_path="courses/138907/raw/course-state.json"
    )
    activity = archive.sections[0].activities[0]
    write_model(tmp_path / "courses/138907/course.json", archive)
    core = HIQSCore(resources_dir=tmp_path)

    result = core.get_evidence(f"activity:{activity.module_id}")

    assert result["status"] == "found"
    assert result["node"]["evidence_id"] == f"activity:{activity.module_id}"
    assert result["course_id"] == "138907"
