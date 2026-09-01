import json
from pathlib import Path

from hsas_application import (
    PlanGenerationRequest,
    assess_plan_freshness,
    generate_validated_plan,
)
from hsas_runtime.storage import write_model
from integrated_planner.profile_schema import StudentProfile
from integrated_planner.profile_service import apply_profile_patch
from moodle_collector.sync_report import record_sync_operation
from moodle_collector.transformation.common.course_mapper import build_course_archive


ROOT = Path(__file__).parents[1]


def test_plan_freshness_detects_confirmed_input_change(tmp_path: Path) -> None:
    resources = tmp_path / "resources"
    state = json.loads((ROOT / "tests/fixtures/course_state.json").read_text())
    archive = build_course_archive(
        state,
        course_title="Demo",
        raw_state_path="courses/138907/raw/course-state.json",
    )
    write_model(resources / "courses/138907/course.json", archive)
    profile_path = resources / "student_profile.json"
    write_model(profile_path, StudentProfile())
    record_sync_operation(
        resources,
        scope="single",
        discovered_course_count=1,
        course_results=[
            {"course_id": "138907", "course": "Demo", "succeeded": True}
        ],
    )

    generate_validated_plan(PlanGenerationRequest(resources_dir=resources))
    assert assess_plan_freshness(resources).current is True

    apply_profile_patch(
        profile_path,
        {"identity": {"preferred_name": "Jerry"}},
        confirmed=True,
    )
    freshness = assess_plan_freshness(resources)

    assert freshness.current is False
    assert any("Profile changed" in reason for reason in freshness.reasons)
