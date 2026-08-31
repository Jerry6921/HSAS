from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from integrated_planner.plan_schema import (
    AcademicImpact,
    EffortEstimate,
    IntegratedPlan,
    LearningDemand,
    OfficialTiming,
    PlanItem,
    PlanningWindow,
    PriorityDecision,
    TimetableBlock,
)
from integrated_planner.profile_schema import StudentProfile


ZONE = ZoneInfo("Asia/Hong_Kong")


def _item() -> PlanItem:
    stamp = datetime(2026, 9, 1, 8, 0, tzinfo=ZONE)
    return PlanItem(
        plan_item_id="assessment:1:essay",
        course_id="1",
        course_title="Demo",
        item_type="assessment",
        title="Essay",
        official_timing=OfficialTiming(
            due_at=datetime(2026, 9, 5, 17, 0, tzinfo=ZONE),
            is_confirmed=True,
        ),
        academic_impact=AcademicImpact(
            weight_percent=40,
            importance_level=5,
            importance_rationale="Major assessment.",
        ),
        learning_demand=LearningDemand(
            difficulty_level=4,
            difficulty_rationale="Long-form writing.",
        ),
        effort=EffortEstimate(
            estimated_total_minutes=300,
            completed_minutes=60,
            remaining_minutes=240,
            effort_band="l",
        ),
        priority=PriorityDecision(
            level="high",
            rationale="Due soon.",
        ),
        created_at=stamp,
        updated_at=stamp,
    )


def test_profile_rejects_overlapping_availability() -> None:
    with pytest.raises(ValidationError, match="overlapping available_blocks"):
        StudentProfile.model_validate(
            {
                "availability": {
                    "weekly_pattern": [
                        {
                            "day_of_week": "monday",
                            "available_blocks": [
                                {"start": "09:00", "end": "11:00"},
                                {"start": "10:00", "end": "12:00"},
                            ],
                        }
                    ]
                }
            }
        )


def test_profile_rejects_overlapping_fixed_commitments() -> None:
    with pytest.raises(ValidationError, match="fixed commitments overlap"):
        StudentProfile.model_validate(
            {
                "availability": {
                    "fixed_commitments": [
                        {
                            "title": "Lecture",
                            "day_of_week": "monday",
                            "start": "09:00",
                            "end": "11:00",
                        },
                        {
                            "title": "Tutorial",
                            "day_of_week": "monday",
                            "start": "10:30",
                            "end": "12:00",
                        },
                    ]
                }
            }
        )


def test_effort_requires_consistent_remaining_minutes() -> None:
    with pytest.raises(ValidationError, match="remaining_minutes must equal"):
        EffortEstimate(
            estimated_total_minutes=100,
            completed_minutes=20,
            remaining_minutes=70,
        )


def test_plan_rejects_unknown_internal_timetable_reference() -> None:
    item = _item()
    with pytest.raises(ValidationError, match="unknown item"):
        IntegratedPlan(
            generated_at=item.created_at,
            updated_at=item.updated_at,
            plan_status="active",
            planning_window=PlanningWindow(
                start_date=date(2026, 9, 1),
                end_date=date(2026, 9, 7),
            ),
            items=[item],
            timetable=[
                TimetableBlock(
                    block_id="block:missing",
                    plan_item_id="missing",
                    date=date(2026, 9, 1),
                    start_time=time(9, 0),
                    end_time=time(10, 0),
                    planned_minutes=60,
                    block_type="deep_work",
                    expected_output="Outline",
                )
            ],
        )


def test_timetable_duration_must_match_clock_range() -> None:
    with pytest.raises(ValidationError, match="planned_minutes must match"):
        TimetableBlock(
            block_id="block:bad-duration",
            plan_item_id="assessment:1:essay",
            date=date(2026, 9, 1),
            start_time=time(9, 0),
            end_time=time(10, 0),
            planned_minutes=30,
            block_type="deep_work",
            expected_output="Outline",
        )
