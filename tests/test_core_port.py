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


def test_information_apply_keeps_a_user_visible_recent_change_audit(tmp_path: Path) -> None:
    core = HIQSCore(resources_dir=tmp_path)
    first = core.apply_information_update(
        {
            "confirmed": True,
            "update": {
                "courses": [
                    {
                        "course_id": "DEMO1001-2026-S1",
                        "code": "DEMO1001",
                        "title": "Demo Course",
                    }
                ],
                "items": [
                    {
                        "item_id": "demo-assignment",
                        "course_id": "DEMO1001-2026-S1",
                        "title": "Assignment",
                        "category": "assignment",
                    }
                ],
            },
        }
    )

    assert first["recent_update"]["summary"] == {
        "added": 2,
        "modified": 0,
        "removed": 0,
        "change_count": 2,
        "course_count": 1,
        "activities_added": 1,
        "activities_updated": 0,
        "activities_confirmed": 0,
        "materials_added": 0,
        "materials_updated": 0,
        "materials_removed": 0,
    }
    added_activity = first["recent_update"]["courses"][0]["activities_added"][0]
    assert added_activity["record_id"] == "demo-assignment"
    assert added_activity["title"] == "Assignment"
    audit_path = tmp_path / "ai-state/recent-information-update.json"
    assert audit_path.is_file()
    assert audit_path.stat().st_mode & 0o777 == 0o600

    second = core.apply_information_update(
        {
            "confirmed": True,
            "update": {
                "items": [
                    {
                        "item_id": "demo-assignment",
                        "course_id": "DEMO1001-2026-S1",
                        "title": "Assignment",
                        "category": "assignment",
                        "date_status": "confirmed",
                        "due_on": "2026-10-15",
                    }
                ]
            },
        }
    )

    recent = second["information"]["recent_update"]
    assert recent["summary"]["modified"] == 2
    assert recent["summary"]["course_count"] == 1
    assert recent["summary"]["activities_confirmed"] == 1
    assert recent["summary"]["activities_updated"] == 0
    changes = recent["courses"][0]["changes"]
    assert {change["field"] for change in changes} == {"date_status", "due_on"}
    due_change = next(change for change in changes if change["field"] == "due_on")
    assert due_change["before"] is None
    assert due_change["after"] == "2026-10-15"
    confirmed = recent["courses"][0]["activities_confirmed"][0]
    assert confirmed["record_id"] == "demo-assignment"
    assert confirmed["details"] == ["日期状态：已确认", "截止日期：2026-10-15"]

    third = core.apply_information_update(
        {
            "confirmed": True,
            "update": {
                "courses": [
                    {
                        "course_id": "DEMO1001-2026-S1",
                        "code": "DEMO1001",
                        "title": "Demo Course",
                        "material_sections": [
                            {
                                "title": "Lecture slides",
                                "materials": [
                                    {
                                        "title": "Week 1 slides",
                                        "url": "https://example.test/week-1.pdf",
                                    }
                                ],
                            }
                        ],
                    }
                ],
                "items": [
                    {
                        "item_id": "demo-assignment",
                        "course_id": "DEMO1001-2026-S1",
                        "title": "Assignment",
                        "category": "assignment",
                        "date_status": "confirmed",
                        "due_on": "2026-10-15",
                        "location": "Moodle",
                    }
                ],
            },
        }
    )
    recent = third["information"]["recent_update"]
    assert recent["summary"]["activities_confirmed"] == 0
    assert recent["summary"]["activities_updated"] == 1
    assert recent["summary"]["materials_added"] == 1
    assert recent["courses"][0]["activities_updated"][0]["details"] == ["地点：Moodle"]
    assert recent["courses"][0]["materials_added"][0]["details"] == [
        "归类：Lecture slides"
    ]


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


def test_core_hydrates_only_selected_evidence_context(tmp_path: Path) -> None:
    state = json.loads((ROOT / "tests/fixtures/course_state.json").read_text())
    archive = build_course_archive(
        state, course_title="Demo", raw_state_path="courses/138907/raw/course-state.json"
    )
    activity = archive.sections[0].activities[0]
    activity.content_text = "selected evidence context for the agent"
    write_model(tmp_path / "courses/138907/course.json", archive)
    core = HIQSCore(resources_dir=tmp_path)

    result = core.get_evidence_content(
        {
            "evidence_id": f"activity:{activity.module_id}",
            "chunk_index": 0,
            "context_chunks": 0,
        }
    )

    assert result["status"] == "found"
    assert result["chunks"][0]["text"] == "selected evidence context for the agent"


def test_core_explains_canonical_information_evidence(tmp_path: Path) -> None:
    core = HIQSCore(resources_dir=tmp_path)
    core.apply_information_update({
        "confirmed": True,
        "update": {
            "courses": [{"course_id": "DEMO1001", "code": "DEMO1001", "title": "Demo"}],
            "items": [{
                "item_id": "demo-deadline", "course_id": "DEMO1001",
                "title": "Report deadline", "category": "deadline",
                "date_status": "tentative", "due_on": "2026-10-20",
                "warnings": ["Date differs between two announcements"],
                "sources": [{"source_type": "announcement", "title": "Moodle news"}],
            }],
        },
    })

    result = core.explain_evidence("information:item:demo-deadline")

    assert result["status"] == "found"
    assert result["confirmation_status"] == "tentative"
    assert result["sources"][0]["title"] == "Moodle news"
    assert result["warnings"] == ["Date differs between two announcements"]
    assert "不得视为已确认日期" in result["limitations"][0]
