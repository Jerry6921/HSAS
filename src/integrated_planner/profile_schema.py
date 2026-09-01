from __future__ import annotations

from datetime import date as Date
from datetime import datetime
from datetime import time as Time
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator

from moodle_collector.transformation.common.base_schema import StrictModel


DayOfWeek = Literal[
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]
CapacityLevel = Literal["low", "medium", "high"]
CoursePriority = Literal["low", "medium", "high", "critical"]


class ClockBlock(StrictModel):
    start: Time
    end: Time
    capacity: CapacityLevel = "medium"

    @model_validator(mode="after")
    def ensure_positive_interval(self) -> "ClockBlock":
        if self.start >= self.end:
            raise ValueError("start must be earlier than end")
        return self


class WeeklyAvailability(StrictModel):
    day_of_week: DayOfWeek
    available_blocks: list[ClockBlock] = Field(default_factory=list)

    @model_validator(mode="after")
    def ensure_non_overlapping_blocks(self) -> "WeeklyAvailability":
        _ensure_non_overlapping(self.available_blocks, "available_blocks")
        return self


class DateException(StrictModel):
    date: Date
    available_blocks: list[ClockBlock] = Field(default_factory=list)
    reason: str | None = None

    @model_validator(mode="after")
    def ensure_non_overlapping_blocks(self) -> "DateException":
        _ensure_non_overlapping(self.available_blocks, "available_blocks")
        return self


class FixedCommitment(StrictModel):
    title: str
    day_of_week: DayOfWeek | None = None
    date: Date | None = None
    start: Time
    end: Time
    location: str | None = None

    @model_validator(mode="after")
    def validate_commitment(self) -> "FixedCommitment":
        if (self.day_of_week is None) == (self.date is None):
            raise ValueError("set exactly one of day_of_week or date")
        if self.start >= self.end:
            raise ValueError("start must be earlier than end")
        return self


class Availability(StrictModel):
    weekly_pattern: list[WeeklyAvailability] = Field(default_factory=list)
    date_exceptions: list[DateException] = Field(default_factory=list)
    fixed_commitments: list[FixedCommitment] = Field(default_factory=list)
    maximum_study_minutes_per_day: int | None = Field(default=None, ge=1)
    minimum_sleep_hours: float | None = Field(default=None, ge=0, le=24)

    @model_validator(mode="after")
    def ensure_unique_dates_and_days(self) -> "Availability":
        _ensure_unique(
            [entry.day_of_week for entry in self.weekly_pattern],
            "weekly_pattern day_of_week",
        )
        _ensure_unique(
            [entry.date for entry in self.date_exceptions],
            "date_exceptions date",
        )
        _ensure_commitments_do_not_overlap(self.fixed_commitments)
        return self


class Identity(StrictModel):
    preferred_name: str | None = None
    programme: str | None = None
    year_of_study: int | None = Field(default=None, ge=1)
    current_semester: str | None = None
    primary_language: str | None = None


class CourseTarget(StrictModel):
    course_id: str
    target_mark_percent: float | None = Field(default=None, ge=0, le=100)
    target_grade: str | None = None
    priority: CoursePriority = "medium"
    reason: str | None = None


class AcademicGoals(StrictModel):
    target_gpa: float | None = Field(default=None, ge=0)
    semester_goal: str | None = None
    course_targets: list[CourseTarget] = Field(default_factory=list)
    priority_course_ids: list[str] = Field(default_factory=list)
    mastery_goals: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def ensure_unique_courses(self) -> "AcademicGoals":
        _ensure_unique(
            [target.course_id for target in self.course_targets],
            "course_targets course_id",
        )
        _ensure_unique(self.priority_course_ids, "priority_course_ids")
        return self


class StudyCapacity(StrictModel):
    weekly_study_budget_minutes: int | None = Field(default=None, ge=1)
    preferred_session_minutes: int | None = Field(default=None, ge=15, le=240)
    preferred_break_minutes: int | None = Field(default=None, ge=0, le=120)
    maximum_deep_work_sessions_per_day: int | None = Field(default=None, ge=1)
    reading_speed_words_per_minute: int | None = Field(default=None, ge=1)
    writing_speed_words_per_hour: int | None = Field(default=None, ge=1)


class LearningPreferences(StrictModel):
    preferred_methods: list[str] = Field(default_factory=list)
    less_effective_methods: list[str] = Field(default_factory=list)
    preferred_plan_detail: Literal["daily", "weekly", "weekly_and_daily"] = (
        "weekly_and_daily"
    )
    preferred_explanation_style: str | None = None
    preferred_study_environment: str | None = None


class EnergyPeriod(StrictModel):
    day_of_week: DayOfWeek | None = None
    start: Time
    end: Time

    @model_validator(mode="after")
    def ensure_positive_interval(self) -> "EnergyPeriod":
        if self.start >= self.end:
            raise ValueError("start must be earlier than end")
        return self


class EnergyPattern(StrictModel):
    high_focus_periods: list[EnergyPeriod] = Field(default_factory=list)
    low_energy_periods: list[EnergyPeriod] = Field(default_factory=list)
    avoid_study_periods: list[EnergyPeriod] = Field(default_factory=list)


class Constraints(StrictModel):
    commute: str | None = None
    work_or_club_commitments: list[str] = Field(default_factory=list)
    accessibility_or_health_needs: list[str] = Field(default_factory=list)
    technology_constraints: list[str] = Field(default_factory=list)
    other: list[str] = Field(default_factory=list)


class KnownAssessmentResult(StrictModel):
    assessment_id: str
    score_percent: float | None = Field(default=None, ge=0, le=100)
    grade: str | None = None
    confirmed: bool = False
    source: Literal["user", "moodle", "official"] = "user"


class TopicConfidence(StrictModel):
    topic: str
    confidence_level: int = Field(ge=1, le=5)
    evidence: str | None = None


class CourseState(StrictModel):
    course_id: str
    self_reported_progress_percent: float | None = Field(
        default=None,
        ge=0,
        le=100,
    )
    completed_activity_ids: list[str] = Field(default_factory=list)
    known_assessment_results: list[KnownAssessmentResult] = Field(
        default_factory=list
    )
    topic_confidence: list[TopicConfidence] = Field(default_factory=list)
    current_difficulties: list[str] = Field(default_factory=list)
    updated_at: datetime | None = None

    @model_validator(mode="after")
    def ensure_unique_state_entries(self) -> "CourseState":
        _ensure_unique(self.completed_activity_ids, "completed_activity_ids")
        _ensure_unique(
            [result.assessment_id for result in self.known_assessment_results],
            "known_assessment_results assessment_id",
        )
        _ensure_unique(
            [topic.topic.casefold() for topic in self.topic_confidence],
            "topic_confidence topic",
        )
        return self


class PlanningPreferences(StrictModel):
    default_planning_horizon_days: int = Field(default=7, ge=1, le=365)
    deadline_buffer_hours: int = Field(default=24, ge=0, le=336)
    unscheduled_capacity_percent: int = Field(default=15, ge=0, le=80)
    allow_weekend_study: bool = True
    show_source_references: bool = True
    show_uncertainty_warnings: bool = True


class ProfileProvenance(StrictModel):
    last_confirmed_at: datetime | None = None
    confirmed_by_user: bool = False
    unconfirmed_fields: list[str] = Field(default_factory=list)
    source: Literal["user_profile"] = "user_profile"


class ProfileWritePolicy(StrictModel):
    owner: Literal["student"] = "student"
    ai_may_read: bool = True
    ai_may_propose_updates: bool = True
    ai_may_write_user_confirmed_data: bool = True
    ai_must_not_infer_sensitive_data: bool = True
    ai_must_not_store_authentication_data: bool = True
    never_store_fields: list[str] = Field(
        default_factory=lambda: [
            "password",
            "mfa_code",
            "sesskey",
            "cookie",
            "access_token",
        ]
    )


class StudentProfile(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    profile_id: str = "default"
    updated_at: datetime | None = None
    timezone: str = "Asia/Hong_Kong"
    profile_status: Literal["incomplete", "active"] = "incomplete"
    identity: Identity = Field(default_factory=Identity)
    academic_goals: AcademicGoals = Field(default_factory=AcademicGoals)
    availability: Availability = Field(default_factory=Availability)
    study_capacity: StudyCapacity = Field(default_factory=StudyCapacity)
    learning_preferences: LearningPreferences = Field(
        default_factory=LearningPreferences
    )
    energy_pattern: EnergyPattern = Field(default_factory=EnergyPattern)
    constraints: Constraints = Field(default_factory=Constraints)
    course_states: list[CourseState] = Field(default_factory=list)
    planning_preferences: PlanningPreferences = Field(
        default_factory=PlanningPreferences
    )
    profile_notes: list[str] = Field(default_factory=list)
    provenance: ProfileProvenance = Field(default_factory=ProfileProvenance)
    write_policy: ProfileWritePolicy = Field(default_factory=ProfileWritePolicy)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown IANA timezone: {value}") from exc
        return value

    @model_validator(mode="after")
    def ensure_unique_course_states(self) -> "StudentProfile":
        _ensure_unique(
            [state.course_id for state in self.course_states],
            "course_states course_id",
        )
        return self


def _ensure_unique(values: list[object], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {label}")


def _ensure_non_overlapping(blocks: list[ClockBlock], label: str) -> None:
    ordered = sorted(blocks, key=lambda block: block.start)
    for previous, current in zip(ordered, ordered[1:]):
        if current.start < previous.end:
            raise ValueError(f"overlapping {label}")


def _ensure_commitments_do_not_overlap(
    commitments: list[FixedCommitment],
) -> None:
    for index, left in enumerate(commitments):
        for right in commitments[index + 1:]:
            same_schedule = False
            if left.date is not None and right.date is not None:
                same_schedule = left.date == right.date
            elif left.day_of_week is not None and right.day_of_week is not None:
                same_schedule = left.day_of_week == right.day_of_week
            else:
                dated = left if left.date is not None else right
                recurring = right if left.date is not None else left
                same_schedule = (
                    dated.date is not None
                    and recurring.day_of_week
                    == dated.date.strftime("%A").casefold()
                )
            if (
                same_schedule
                and left.start < right.end
                and right.start < left.end
            ):
                raise ValueError(
                    f"fixed commitments overlap: {left.title} / {right.title}"
                )
