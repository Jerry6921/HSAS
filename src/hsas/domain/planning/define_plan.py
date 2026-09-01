from __future__ import annotations

from datetime import date as Date
from datetime import datetime
from datetime import time as Time
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator

from hsas.domain.courses import AssessmentType, StrictModel


PlanStatus = Literal["draft", "active", "completed"]
PlanningMode = Literal["priority_backlog", "legacy_timetable"]
ItemType = Literal[
    "assessment",
    "exam",
    "quiz",
    "reading",
    "lecture",
    "practice",
    "project",
    "review",
    "admin",
    "other",
]
ItemStatus = Literal[
    "not_started",
    "in_progress",
    "blocked",
    "completed",
    "cancelled",
]
Readiness = Literal[
    "ready",
    "not_open",
    "missing_material",
    "prerequisite_missing",
    "uncertain",
]
PriorityLevel = Literal["critical", "high", "medium", "planned"]
EffortBand = Literal["xs", "s", "m", "l", "xl"]


class PlanningWindow(StrictModel):
    start_date: Date
    end_date: Date

    @model_validator(mode="after")
    def ensure_order(self) -> "PlanningWindow":
        if self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date")
        return self


class CourseArchiveSnapshot(StrictModel):
    course_id: str
    path: str
    collected_at: datetime
    schema_version: str


class SourceSnapshot(StrictModel):
    student_profile_path: str = "student_profile.json"
    student_profile_updated_at: datetime | None = None
    course_archives: list[CourseArchiveSnapshot] = Field(default_factory=list)
    sync_report_path: str = "sync-report.json"
    execution_log_path: str = "execution_log.json"
    execution_log_updated_at: datetime | None = None
    warnings: list[str] = Field(default_factory=list)


class CapacitySummary(StrictModel):
    """Legacy timetable capacity fields retained for schema compatibility."""

    available_minutes: int | None = Field(default=None, ge=0)
    allocatable_minutes: int | None = Field(default=None, ge=0)
    required_minutes: int = Field(default=0, ge=0)
    scheduled_minutes: int = Field(default=0, ge=0)
    buffer_minutes: int = Field(default=0, ge=0)
    unscheduled_minutes: int | None = Field(default=None, ge=0)
    unscheduled_workload_minutes: int = Field(default=0, ge=0)
    over_capacity: bool = False


class WorkloadSummary(StrictModel):
    """Estimated effort for the key-priority backlog, without time-slot allocation."""

    key_item_count: int = Field(default=0, ge=0)
    estimated_item_count: int = Field(default=0, ge=0)
    unestimated_item_count: int = Field(default=0, ge=0)
    total_remaining_minutes: int = Field(default=0, ge=0)
    critical_minutes: int = Field(default=0, ge=0)
    high_priority_minutes: int = Field(default=0, ge=0)
    medium_priority_minutes: int = Field(default=0, ge=0)
    planned_minutes: int = Field(default=0, ge=0)


class FeedbackSummary(StrictModel):
    execution_record_count: int = Field(default=0, ge=0)
    total_actual_minutes: int = Field(default=0, ge=0)
    calibration_factors: dict[str, float] = Field(default_factory=dict)


class PlanSummary(StrictModel):
    critical_item_count: int = Field(default=0, ge=0)
    high_priority_item_count: int = Field(default=0, ge=0)
    overdue_item_count: int = Field(default=0, ge=0)
    blocked_item_count: int = Field(default=0, ge=0)
    items_missing_deadline: int = Field(default=0, ge=0)
    items_missing_effort_estimate: int = Field(default=0, ge=0)
    next_action_item_id: str | None = None
    summary: str | None = None


class OfficialTiming(StrictModel):
    opens_on: Date | None = None
    due_on: Date | None = None
    scheduled_on: Date | None = None
    opens_at: datetime | None = None
    due_at: datetime | None = None
    scheduled_at: datetime | None = None
    timezone: str = "Asia/Hong_Kong"
    is_confirmed: bool = False

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown IANA timezone: {value}") from exc
        return value

    @model_validator(mode="after")
    def ensure_timing_order(self) -> "OfficialTiming":
        if self.opens_at and self.due_at and self.opens_at > self.due_at:
            raise ValueError("opens_at must not be after due_at")
        if self.opens_on and self.due_on and self.opens_on > self.due_on:
            raise ValueError("opens_on must not be after due_on")
        return self


class AcademicImpact(StrictModel):
    weight_percent: float | None = Field(default=None, ge=0, le=100)
    assessment_group_id: str | None = None
    importance_level: int = Field(ge=1, le=5)
    importance_rationale: str


class LearningDemand(StrictModel):
    difficulty_level: int = Field(ge=1, le=5)
    difficulty_rationale: str
    prerequisite_item_ids: list[str] = Field(default_factory=list)
    weak_topic_match: bool | None = None


class EffortEstimate(StrictModel):
    estimated_total_minutes: int | None = Field(default=None, ge=0)
    completed_minutes: int = Field(default=0, ge=0)
    remaining_minutes: int | None = Field(default=None, ge=0)
    effort_band: EffortBand | None = None
    actual_minutes_spent: int = Field(default=0, ge=0)
    calibration_factor: float = Field(default=1.0, ge=0.5, le=2.0)
    estimation_basis: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def ensure_consistent_minutes(self) -> "EffortEstimate":
        if self.estimated_total_minutes is None:
            if self.remaining_minutes is not None:
                raise ValueError(
                    "remaining_minutes requires estimated_total_minutes"
                )
            return self
        expected = max(self.estimated_total_minutes - self.completed_minutes, 0)
        if self.remaining_minutes is None:
            self.remaining_minutes = expected
        elif self.remaining_minutes != expected:
            raise ValueError(
                "remaining_minutes must equal estimated_total_minutes - "
                "completed_minutes"
            )
        return self


class PriorityDecision(StrictModel):
    level: PriorityLevel
    rationale: str
    derived_from: list[str] = Field(default_factory=list)


class PlanSourceReference(StrictModel):
    source_type: Literal[
        "course_archive",
        "moodle_section",
        "moodle_activity",
        "syllabus",
        "student_profile",
        "ai_planner",
    ]
    relative_path: str | None = None
    section_id: str | None = None
    activity_id: str | None = None
    assessment_id: str | None = None
    page_numbers: list[int] = Field(default_factory=list)
    note: str | None = None


class PlanItem(StrictModel):
    plan_item_id: str
    course_id: str
    course_title: str
    source_section_id: str | None = None
    source_activity_id: str | None = None
    source_assessment_id: str | None = None
    source_assessment_type: AssessmentType | None = None
    item_type: ItemType
    title: str
    description: str | None = None
    official_timing: OfficialTiming = Field(default_factory=OfficialTiming)
    academic_impact: AcademicImpact
    learning_demand: LearningDemand
    effort: EffortEstimate
    priority: PriorityDecision
    status: ItemStatus = "not_started"
    readiness: Readiness = "ready"
    completion_criteria: list[str] = Field(default_factory=list)
    source_references: list[PlanSourceReference] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class TimetableBlock(StrictModel):
    block_id: str
    plan_item_id: str
    date: Date
    start_time: Time
    end_time: Time
    planned_minutes: int = Field(gt=0)
    block_type: Literal[
        "deep_work",
        "reading",
        "practice",
        "review",
        "admin",
        "buffer",
    ]
    location: str | None = None
    expected_output: str
    status: Literal["planned", "started", "completed", "missed", "rescheduled"] = (
        "planned"
    )
    actual_minutes: int | None = Field(default=None, ge=0)
    notes: str | None = None

    @model_validator(mode="after")
    def ensure_duration(self) -> "TimetableBlock":
        if self.start_time >= self.end_time:
            raise ValueError("start_time must be earlier than end_time")
        actual = int(
            (
                datetime.combine(self.date, self.end_time)
                - datetime.combine(self.date, self.start_time)
            ).total_seconds()
            // 60
        )
        if actual != self.planned_minutes:
            raise ValueError("planned_minutes must match start_time/end_time")
        return self


class Milestone(StrictModel):
    milestone_id: str
    plan_item_id: str
    title: str
    target_at: datetime
    phase: str | None = None
    sequence: int | None = Field(default=None, ge=1)
    total_stages: int | None = Field(default=None, ge=1)
    status: Literal["planned", "completed", "missed"] = "planned"
    is_ai_created: bool = True


class ReviewPoint(StrictModel):
    review_id: str
    scheduled_at: datetime
    scope: Literal["daily", "weekly", "assessment", "semester"]
    questions: list[str] = Field(default_factory=list)
    completed_at: datetime | None = None
    outcome: str | None = None


class ClassificationGuide(StrictModel):
    importance: dict[str, str] = Field(
        default_factory=lambda: {
            "1": "optional or minor enrichment",
            "2": "routine supporting or low-impact work",
            "3": "normal required work",
            "4": "high-impact, prerequisite, or strategically important work",
            "5": "major assessment or severe progression risk",
        }
    )
    difficulty: dict[str, str] = Field(
        default_factory=lambda: {
            "1": "very familiar or mechanical",
            "2": "mostly familiar",
            "3": "moderate conceptual or production challenge",
            "4": "complex or weak-topic work",
            "5": "very difficult, unfamiliar, or strongly blocked",
        }
    )
    effort_band: dict[str, str] = Field(
        default_factory=lambda: {
            "xs": "1-30 minutes",
            "s": "31-90 minutes",
            "m": "91-240 minutes",
            "l": "241-480 minutes",
            "xl": "more than 480 minutes",
        }
    )
    priority: dict[str, str] = Field(
        default_factory=lambda: {
            "critical": "overdue, due within 48 hours, or immediate severe risk",
            "high": "due within 7 days, blocked, or high-impact early work",
            "medium": "due within 14 days or normal required preparation",
            "planned": "later, recurring, optional, or not yet schedulable",
        }
    )
    rule: str = (
        "Priority is derived from urgency, importance, difficulty, remaining "
        "effort, readiness, and risk; it is not a Moodle field."
    )


class PlanWritePolicy(StrictModel):
    ai_may_read: bool = True
    ai_may_write: bool = False
    ai_must_preserve_official_deadlines: bool = True
    ai_must_label_created_milestones: bool = True
    ai_must_recalculate_after_profile_or_course_change: bool = True
    ai_must_not_copy_authentication_data: bool = True
    ai_must_not_treat_missing_values_as_zero: bool = True
    ai_must_not_double_count_assessment_groups: bool = True
    ai_must_not_assign_study_times_unless_requested: bool = True


class IntegratedPlan(StrictModel):
    schema_version: Literal["1.0", "1.1"] = "1.1"
    plan_id: str = "default"
    planning_mode: PlanningMode = "priority_backlog"
    generated_at: datetime | None = None
    updated_at: datetime | None = None
    timezone: str = "Asia/Hong_Kong"
    plan_status: PlanStatus = "draft"
    planning_window: PlanningWindow | None = None
    source_snapshot: SourceSnapshot = Field(default_factory=SourceSnapshot)
    # Accepted when reading v1.0 timetable plans, but deliberately omitted from
    # v1.1 output. Priority backlogs describe workload rather than allocating a
    # student's calendar capacity.
    capacity_summary: CapacitySummary = Field(
        default_factory=CapacitySummary,
        exclude=True,
    )
    workload_summary: WorkloadSummary = Field(default_factory=WorkloadSummary)
    feedback_summary: FeedbackSummary = Field(default_factory=FeedbackSummary)
    plan_summary: PlanSummary = Field(default_factory=PlanSummary)
    items: list[PlanItem] = Field(default_factory=list)
    timetable: list[TimetableBlock] = Field(default_factory=list, exclude=True)
    milestones: list[Milestone] = Field(default_factory=list)
    review_points: list[ReviewPoint] = Field(default_factory=list, exclude=True)
    plan_warnings: list[str] = Field(default_factory=list)
    classification_guide: ClassificationGuide = Field(
        default_factory=ClassificationGuide
    )
    write_policy: PlanWritePolicy = Field(default_factory=PlanWritePolicy)

    @model_validator(mode="before")
    @classmethod
    def recognize_legacy_timetable(cls, value):
        if isinstance(value, dict) and "planning_mode" not in value:
            value = dict(value)
            value["planning_mode"] = (
                "legacy_timetable" if value.get("timetable") else "priority_backlog"
            )
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown IANA timezone: {value}") from exc
        return value

    @model_validator(mode="after")
    def ensure_unique_identifiers(self) -> "IntegratedPlan":
        if self.plan_status != "draft" and (
            self.generated_at is None
            or self.updated_at is None
            or self.planning_window is None
        ):
            raise ValueError(
                "active/completed plans require timestamps and planning_window"
            )
        _ensure_unique([item.plan_item_id for item in self.items], "plan_item_id")
        _ensure_unique([block.block_id for block in self.timetable], "block_id")
        _ensure_unique(
            [milestone.milestone_id for milestone in self.milestones],
            "milestone_id",
        )
        _ensure_unique(
            [review.review_id for review in self.review_points],
            "review_id",
        )
        item_ids = {item.plan_item_id for item in self.items}
        for block in self.timetable:
            if block.plan_item_id not in item_ids:
                raise ValueError(
                    f"timetable block references unknown item: {block.plan_item_id}"
                )
        for milestone in self.milestones:
            if milestone.plan_item_id not in item_ids:
                raise ValueError(
                    "milestone references unknown item: "
                    f"{milestone.plan_item_id}"
                )
        if (
            self.plan_summary.next_action_item_id is not None
            and self.plan_summary.next_action_item_id not in item_ids
        ):
            raise ValueError("next_action_item_id references unknown item")
        if self.planning_mode == "priority_backlog" and self.timetable:
            raise ValueError("priority_backlog plans must not contain timetable blocks")
        return self


def _ensure_unique(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {label}")
