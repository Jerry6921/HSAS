import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from integrated_planner.plan_validator import validate_integrated_plan
from integrated_planner.planner_engine import PlannerEngine
from integrated_planner.execution_schema import ExecutionLog, ExecutionRecord
from integrated_planner.feedback import FeedbackIndex
from integrated_planner.plan_schema import Milestone
from integrated_planner.profile_schema import StudentProfile
from moodle_collector.transformation.assessment.schema import (
    AssessmentItem,
    AssessmentOverview,
    SourceReference,
)
from moodle_collector.transformation.common.course_index import ArchiveIndex
from moodle_collector.transformation.common.course_mapper import build_course_archive


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


def test_engine_generates_valid_items_and_timetable() -> None:
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
    assert any(block.plan_item_id == essay.plan_item_id for block in plan.timetable)
    assert plan.capacity_summary.scheduled_minutes > 0
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


def test_engine_update_preserves_progress_and_completed_blocks() -> None:
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
    completed_block = next(
        block for block in first.timetable if block.plan_item_id == essay.plan_item_id
    )
    completed_block.status = "completed"
    completed_block.actual_minutes = completed_block.planned_minutes
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
    assert any(
        block.block_id == completed_block.block_id
        and block.status == "completed"
        for block in updated.timetable
    )
    assert {
        milestone.milestone_id: milestone.target_at
        for milestone in updated.milestones
        if milestone.plan_item_id == essay.plan_item_id
    } == first_milestone_targets


def test_validator_detects_reference_and_time_conflicts() -> None:
    archive = _archive()
    profile = _profile(with_commitment=True)
    plan = PlannerEngine().generate(
        profile,
        [archive],
        start_date=date(2026, 9, 1),
        now=datetime(2026, 9, 1, 8, 0, tzinfo=ZONE),
    )
    # The engine avoids commitments; move one generated block into the class time
    # and break one course reference to exercise external validation.
    block = plan.timetable[0]
    block.date = date(2026, 9, 1)
    block.start_time = datetime.strptime("09:00", "%H:%M").time()
    block.end_time = datetime.strptime("10:00", "%H:%M").time()
    block.planned_minutes = 60
    plan.items[0].source_section_id = "missing-section"

    report = validate_integrated_plan(plan, profile, [archive])
    codes = {issue.code for issue in report.errors}

    assert not report.valid
    assert "reference.section_missing" in codes
    assert "schedule.fixed_commitment_conflict" in codes


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


def test_validator_handles_date_only_deadlines_and_workload_overload() -> None:
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
    warning_codes = {issue.code for issue in report.warnings}

    assert "schedule.milestone_after_deadline" in error_codes
    assert plan.capacity_summary.over_capacity is True
    assert plan.capacity_summary.unscheduled_workload_minutes > 0
    assert "capacity.workload_exceeds_capacity" in warning_codes
