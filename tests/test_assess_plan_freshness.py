import json
from pathlib import Path

from hsas.application import (
    PlanGenerationRequest,
    assess_plan_freshness,
    generate_validated_plan,
)
from hsas.infrastructure.storage.persist_data import write_model
from hsas.domain.planning.define_profile import StudentProfile
from hsas.application.update_profile import apply_profile_patch
from hsas.infrastructure.moodle.record_sync import record_sync_operation
from hsas.infrastructure.moodle.map_courses import build_course_archive
from hsas.infrastructure.storage import JsonPlanningRepository


ROOT = Path(__file__).parents[1]
REPOSITORY = JsonPlanningRepository()


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

    generate_validated_plan(PlanGenerationRequest(resources_dir=resources), REPOSITORY)
    assert assess_plan_freshness(resources, REPOSITORY).current is True

    apply_profile_patch(
        profile_path,
        {"identity": {"preferred_name": "Jerry"}},
        confirmed=True,
        repository=REPOSITORY,
    )
    freshness = assess_plan_freshness(resources, REPOSITORY)

    assert freshness.current is False
    assert any("Profile changed" in reason for reason in freshness.reasons)
