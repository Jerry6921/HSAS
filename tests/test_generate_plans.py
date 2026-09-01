import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from hsas.domain.planning.validate_plan import validate_integrated_plan
from hsas.domain.planning.generate_plan import PlannerEngine
from hsas.domain.planning.define_execution import ExecutionLog, ExecutionRecord
from hsas.domain.planning.calculate_feedback import FeedbackIndex
from hsas.domain.planning.define_plan import Milestone
from hsas.domain.planning.define_profile import StudentProfile
from hsas.domain.courses.define_assessments import (
    AssessmentItem,
    AssessmentOverview,
    SourceReference,
)
from hsas.domain.courses.index_courses import ArchiveIndex
from hsas.infrastructure.moodle.map_courses import build_course_archive


ROOT = Path(__file__).parents[1]
ZONE = ZoneInfo("Asia/Hong_Kong")


def _archive() -> ArchiveIndex:
    state = json.loads((ROOT / "tests/fixtures/course_state.json").read_text())
    archive = build_course_archive(
        state,
        course_title="Demo Course, 2026",
        raw_state_path="courses/138907/raw/course-state.json",
    )
    archive.assessments = AssessmentOverview(
        parser_version="generic-v1",
        total_weight_percent=100,
        items=[
            AssessmentItem(
                assessment_id="essay-1",
                title="Essay 1",
                assessment_type="essay",
                weight_percent=40,
                word_limit=1000,
                due_at=datetime(2026, 9, 5, 17, 0, tzinfo=ZONE),
                status="confirmed",
                confidence=1,
                sources=[
                    SourceReference(
                        source_type="moodle_activity",
                        section_id="101",
                        activity_id="202",
                    )
                ],
            )
        ],
    )
    return ArchiveIndex(archive)


def _profile(*, with_commitment: bool = False) -> StudentProfile:
    commitments = []
    if with_commitment:
        commitments.append(
            {
                "title": "Class",
                "date": "2026-09-01",
                "start": "09:00",
                "end": "10:00",
            }
        )
    return StudentProfile.model_validate(
        {
            "profile_status": "active",
            "updated_at": "2026-09-01T07:00:00+08:00",
            "academic_goals": {
                "course_targets": [
                    {
                        "course_id": "138907",
                        "target_grade": "A",
                        "priority": "high",
                    }
                ]
            },
            "availability": {
                "weekly_pattern": [
                    {
                        "day_of_week": day,
                        "available_blocks": [
                            {"start": "09:00", "end": "12:00", "capacity": "high"}
                        ],
                    }
                    for day in [
                        "tuesday",
                        "wednesday",
                        "thursday",
                        "friday",
                        "saturday",
                    ]
                ],
                "fixed_commitments": commitments,
                "maximum_study_minutes_per_day": 180,
            },
            "study_capacity": {
                "preferred_session_minutes": 60,
                "preferred_break_minutes": 10,
                "writing_speed_words_per_hour": 250,
            },
            "planning_preferences": {
                "default_planning_horizon_days": 5,
                "deadline_buffer_hours": 12,
                "unscheduled_capacity_percent": 10,
            },
        }
    )


def test_engine_generates_valid_priority_backlog_without_timetable() -> None:
    archive = _archive()
    profile = _profile()
    now = datetime(2026, 9, 1, 8, 0, tzinfo=ZONE)

    plan = PlannerEngine().generate(
        profile,
        [archive],
        start_date=date(2026, 9, 1),
        now=now,
    )
    report = validate_integrated_plan(plan, profile, [archive])
    essay = next(item for item in plan.items if item.source_assessment_id == "essay-1")

    assert report.valid
    assert plan.plan_status == "active"
    assert essay.source_activity_id == "202"
    assert essay.academic_impact.importance_level == 5
    assert essay.effort.estimated_total_minutes == 600
    assert essay.priority.level in {"critical", "high"}
    assert plan.planning_mode == "priority_backlog"
    assert plan.timetable == []
    serialized = plan.model_dump(mode="json")
    assert "timetable" not in serialized
    assert "capacity_summary" not in serialized
    assert "review_points" not in serialized
    assert plan.workload_summary.key_item_count == len(plan.items)
    assert plan.workload_summary.total_remaining_minutes == sum(
        item.effort.remaining_minutes or 0 for item in plan.items
    )
    essay_milestones = [
        milestone
        for milestone in plan.milestones
        if milestone.plan_item_id == essay.plan_item_id
    ]
    assert [milestone.phase for milestone in essay_milestones] == [
        "requirements",
        "research-outline",
        "first-draft",
        "revision",
        "submission-ready",
    ]
    assert all(milestone.total_stages == 5 for milestone in essay_milestones)


def test_active_priority_backlog_does_not_require_availability_slots() -> None:
    profile = _profile()
    profile.availability.weekly_pattern = []
    profile.availability.fixed_commitments = []

    plan = PlannerEngine().generate(
        profile,
        [_archive()],
        start_date=date(2026, 9, 1),
        now=datetime(2026, 9, 1, 8, 0, tzinfo=ZONE),
    )

    assert plan.plan_status == "active"
    assert plan.planning_mode == "priority_backlog"
    assert plan.timetable == []


def test_engine_uses_type_specific_milestone_strategies() -> None:
    archive = _archive()
    due = datetime(2026, 9, 10, 17, 0, tzinfo=ZONE)
    archive.archive.assessments.items = [
        AssessmentItem(
            assessment_id=assessment_type,
            title=title,
            assessment_type=assessment_type,
            due_at=due,
            status="confirmed",
        )
        for assessment_type, title in [
            ("essay", "Research Essay"),
            ("report", "Research Report"),
            ("exam", "Final Exam"),
            ("project", "Group Project"),
            ("presentation", "Project Presentation"),
        ]
    ]

    plan = PlannerEngine().generate(
        _profile(),
        [archive],
        start_date=date(2026, 9, 1),
        now=datetime(2026, 9, 1, 8, 0, tzinfo=ZONE),
    )
    phases = {
        item.source_assessment_type: [
            milestone.phase
            for milestone in plan.milestones
            if milestone.plan_item_id == item.plan_item_id
        ]
        for item in plan.items
        if item.source_assessment_id
    }

    assert phases["essay"][-1] == "submission-ready"
    assert phases["report"][-1] == "submission-ready"
    assert "mock-exam" in phases["exam"]
    assert "prototype" in phases["project"]
    assert phases["presentation"] == [
        "message-outline",
        "draft-deck",
        "rehearsal",
        "delivery-ready",
    ]


def test_assessment_evidence_activity_is_not_mixed_with_assessment_section() -> None:
    archive = _archive()
    assessment = archive.archive.assessments.items[0]
    assessment.sources = [
        SourceReference(source_type="moodle_activity", activity_id="201"),
        SourceReference(source_type="moodle_section", section_id="101"),
    ]

    plan = PlannerEngine().generate(
        _profile(),
        [archive],
        start_date=date(2026, 9, 1),
        now=datetime(2026, 9, 1, 8, 0, tzinfo=ZONE),
    )
    item = next(value for value in plan.items if value.source_assessment_id == "essay-1")
    report = validate_integrated_plan(plan, _profile(), [archive])

    assert item.source_activity_id is None
    assert item.source_section_id == "101"
    assert report.valid


def test_engine_update_preserves_progress_without_creating_time_blocks() -> None:
    archive = _archive()
    profile = _profile()
    engine = PlannerEngine()
    first = engine.generate(
        profile,
        [archive],
        start_date=date(2026, 9, 1),
        now=datetime(2026, 9, 1, 8, 0, tzinfo=ZONE),
    )
    essay = next(item for item in first.items if item.source_assessment_id == "essay-1")
    essay.effort.completed_minutes = 60
    essay.effort.remaining_minutes = essay.effort.estimated_total_minutes - 60
    essay.status = "in_progress"
    first_milestone_targets = {
        milestone.milestone_id: milestone.target_at
        for milestone in first.milestones
        if milestone.plan_item_id == essay.plan_item_id
    }

    updated = engine.generate(
        profile,
        [archive],
        existing_plan=first,
        start_date=date(2026, 9, 1),
        now=datetime(2026, 9, 1, 8, 30, tzinfo=ZONE),
    )
    updated_essay = next(
        item for item in updated.items if item.source_assessment_id == "essay-1"
    )

    assert updated.generated_at == first.generated_at
    assert updated_essay.created_at == essay.created_at
    assert updated_essay.status == "in_progress"
    assert updated_essay.effort.completed_minutes == 60
    assert updated.timetable == []
    assert updated.workload_summary.total_remaining_minutes == sum(
        item.effort.remaining_minutes or 0 for item in updated.items
    )
    assert {
        milestone.milestone_id: milestone.target_at
        for milestone in updated.milestones
        if milestone.plan_item_id == essay.plan_item_id
    } == first_milestone_targets


def test_validator_detects_reference_and_workload_summary_conflicts() -> None:
    archive = _archive()
    profile = _profile(with_commitment=True)
    plan = PlannerEngine().generate(
        profile,
        [archive],
        start_date=date(2026, 9, 1),
        now=datetime(2026, 9, 1, 8, 0, tzinfo=ZONE),
    )
    # Break a source reference and a derived workload total.
    plan.items[0].source_section_id = "missing-section"
    plan.workload_summary.total_remaining_minutes += 1

    report = validate_integrated_plan(plan, profile, [archive])
    codes = {issue.code for issue in report.errors}

    assert not report.valid
    assert "reference.section_missing" in codes
    assert "workload.summary_mismatch" in codes


def test_execution_feedback_reestimates_effort_and_progress() -> None:
    archive = _archive()
    profile = _profile()
    records = ExecutionLog(
        updated_at=datetime(2026, 9, 1, 7, 30, tzinfo=ZONE),
        records=[
            ExecutionRecord(
                record_id="r1",
                plan_item_id="assessment:138907:essay-1",
                item_type="assessment",
                recorded_at=datetime(2026, 9, 1, 7, 0, tzinfo=ZONE),
                planned_minutes=60,
                actual_minutes=90,
                progress_minutes=60,
            ),
            ExecutionRecord(
                record_id="r2",
                plan_item_id="historical-item",
                item_type="assessment",
                recorded_at=datetime(2026, 8, 31, 7, 0, tzinfo=ZONE),
                planned_minutes=60,
                actual_minutes=90,
            ),
        ],
    )

    plan = PlannerEngine().generate(
        profile,
        [archive],
        execution_log=records,
        start_date=date(2026, 9, 1),
        now=datetime(2026, 9, 1, 8, 0, tzinfo=ZONE),
    )
    essay = next(item for item in plan.items if item.source_assessment_id == "essay-1")

    assert essay.effort.calibration_factor == 1.5
    assert essay.effort.estimated_total_minutes == 900
    assert essay.effort.completed_minutes == 60
    assert essay.effort.actual_minutes_spent == 90
    assert plan.feedback_summary.execution_record_count == 2


def test_feedback_extends_an_exhausted_but_incomplete_estimate() -> None:
    feedback = FeedbackIndex(ExecutionLog(records=[
        ExecutionRecord(
            record_id="r1",
            plan_item_id="reading-1",
            item_type="reading",
            recorded_at=datetime(2026, 9, 1, 7, 0, tzinfo=ZONE),
            planned_minutes=60,
            actual_minutes=95,
            progress_minutes=60,
            item_completed=False,
        )
    ]))

    total, factor, extended = feedback.estimate_for_item(
        "reading",
        "reading-1",
        60,
    )

    assert (total, factor, extended) == (75, 1.0, True)


def test_validator_handles_date_only_deadlines_without_allocating_capacity() -> None:
    archive = _archive()
    profile = _profile()
    profile.planning_preferences.default_planning_horizon_days = 1
    plan = PlannerEngine().generate(
        profile,
        [archive],
        start_date=date(2026, 9, 1),
        horizon_days=1,
        now=datetime(2026, 9, 1, 8, 0, tzinfo=ZONE),
    )
    essay = next(item for item in plan.items if item.source_assessment_id == "essay-1")
    essay.official_timing.due_at = None
    essay.official_timing.due_on = date(2026, 9, 5)
    plan.milestones = [
        Milestone(
            milestone_id="late",
            plan_item_id=essay.plan_item_id,
            title="Too late",
            target_at=datetime(2026, 9, 6, 12, 0, tzinfo=ZONE),
        )
    ]

    report = validate_integrated_plan(plan, profile, [archive])
    error_codes = {issue.code for issue in report.errors}
    assert "deadline.milestone_after_official_deadline" in error_codes
    assert plan.planning_mode == "priority_backlog"
    assert plan.timetable == []
    assert plan.capacity_summary.available_minutes is None
    assert plan.capacity_summary.over_capacity is False
