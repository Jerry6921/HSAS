"""Canonical, AI-authored course information models."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator

from hsas.domain.courses.define_models import StrictModel


SourceType = Literal[
    "syllabus",
    "moodle",
    "course_document",
    "announcement",
    "email",
    "manual",
    "other",
]
ItemCategory = Literal[
    "class",
    "tutorial",
    "lab",
    "office_hour",
    "assignment",
    "quiz",
    "exam",
    "presentation",
    "project",
    "report",
    "reading",
    "deadline",
    "other",
]
DateStatus = Literal["confirmed", "tentative", "unknown"]


class SourceReference(StrictModel):
    """Human-checkable evidence for one course fact."""

    source_type: SourceType
    title: str = Field(min_length=1)
    url: str | None = None
    relative_path: str | None = None
    page_numbers: list[int] = Field(default_factory=list)
    observed_at: datetime | None = None
    note: str | None = None

    @field_validator("observed_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("observed_at must include a UTC offset")
        return value

    @field_validator("page_numbers")
    @classmethod
    def validate_page_numbers(cls, value: list[int]) -> list[int]:
        if any(page < 1 for page in value):
            raise ValueError("page_numbers must use one-based positive integers")
        return list(dict.fromkeys(value))


class CourseLink(StrictModel):
    label: str = Field(min_length=1)
    url: str = Field(min_length=1)


class CourseRecord(StrictModel):
    """Queryable course identity and course-wide facts."""

    course_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    code: str = Field(min_length=1)
    title: str = Field(min_length=1)
    moodle_course_id: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    semester: str | None = None
    color: str = Field(default="#2563eb", pattern=r"^#[0-9A-Fa-f]{6}$")
    overview: str | None = Field(
        default=None,
        description="AI-authored, source-grounded overview of the course",
    )
    objectives: list[str] = Field(
        default_factory=list,
        description="AI-summarized course aims supported by course sources",
    )
    instructors: list[str] = Field(default_factory=list)
    links: list[CourseLink] = Field(default_factory=list)
    policies: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    sources: list[SourceReference] = Field(default_factory=list)


class WeeklyRecurrence(StrictModel):
    """A weekly timetable rule; weekdays use Monday=0 through Sunday=6."""

    weekdays: list[int] = Field(min_length=1)
    valid_from: date
    valid_until: date
    start_time: time
    end_time: time
    excluded_dates: list[date] = Field(default_factory=list)
    additional_dates: list[date] = Field(default_factory=list)

    @field_validator("weekdays")
    @classmethod
    def validate_weekdays(cls, value: list[int]) -> list[int]:
        if any(day < 0 or day > 6 for day in value):
            raise ValueError("weekdays must be between 0 (Monday) and 6 (Sunday)")
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def validate_range(self) -> "WeeklyRecurrence":
        if self.valid_until < self.valid_from:
            raise ValueError("valid_until must not be earlier than valid_from")
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be later than start_time")
        return self


class InformationItem(StrictModel):
    """One timetable, deadline, or assessment fact shown by the query UI."""

    item_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    course_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    title: str = Field(min_length=1)
    category: ItemCategory
    date_status: DateStatus = "unknown"
    opens_at: datetime | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    due_at: datetime | None = None
    due_on: date | None = None
    scheduled_on: date | None = None
    recurrence: WeeklyRecurrence | None = None
    all_day: bool = False
    location: str | None = None
    description: str | None = None
    assessment_format: str | None = None
    submission_method: str | None = None
    weight_percent: float | None = Field(default=None, ge=0, le=100)
    word_limit: int | None = Field(default=None, ge=0)
    requirements: list[str] = Field(default_factory=list)
    policies: list[str] = Field(default_factory=list)
    links: list[CourseLink] = Field(default_factory=list)
    sources: list[SourceReference] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    last_verified_at: datetime | None = None

    @field_validator(
        "opens_at",
        "starts_at",
        "ends_at",
        "due_at",
        "last_verified_at",
    )
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("datetime values must include a UTC offset")
        return value

    @model_validator(mode="after")
    def validate_timing(self) -> "InformationItem":
        has_timing = any(
            value is not None
            for value in (
                self.opens_at,
                self.starts_at,
                self.due_at,
                self.due_on,
                self.scheduled_on,
                self.recurrence,
            )
        )
        if self.date_status == "confirmed" and not has_timing:
            raise ValueError("confirmed items must include a date or recurrence")
        if self.ends_at is not None and self.starts_at is None:
            raise ValueError("ends_at requires starts_at")
        if (
            self.starts_at is not None
            and self.ends_at is not None
            and self.ends_at <= self.starts_at
        ):
            raise ValueError("ends_at must be later than starts_at")
        return self


class InformationStore(StrictModel):
    """Complete local information database consumed by the calendar."""

    schema_version: Literal["1.0"] = "1.0"
    timezone: str = "Asia/Hong_Kong"
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_by: Literal["ai_agent", "import", "manual"] = "ai_agent"
    courses: list[CourseRecord] = Field(default_factory=list)
    items: list[InformationItem] = Field(default_factory=list)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be an IANA timezone name") from exc
        return value

    @field_validator("updated_at")
    @classmethod
    def require_updated_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("updated_at must include a UTC offset")
        return value

    @model_validator(mode="after")
    def validate_identity_and_references(self) -> "InformationStore":
        course_ids = [course.course_id for course in self.courses]
        item_ids = [item.item_id for item in self.items]
        if len(course_ids) != len(set(course_ids)):
            raise ValueError("course_id values must be unique")
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("item_id values must be unique")
        missing = sorted({item.course_id for item in self.items} - set(course_ids))
        if missing:
            raise ValueError(f"items reference unknown course_id values: {', '.join(missing)}")
        return self


class InformationUpdate(StrictModel):
    """Validated upsert document prepared by an AI after reading source material."""

    schema_version: Literal["1.0"] = "1.0"
    timezone: str | None = None
    updated_by: Literal["ai_agent", "import", "manual"] = "ai_agent"
    courses: list[CourseRecord] = Field(default_factory=list)
    items: list[InformationItem] = Field(default_factory=list)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be an IANA timezone name") from exc
        return value

    @model_validator(mode="after")
    def validate_unique_update_ids(self) -> "InformationUpdate":
        course_ids = [course.course_id for course in self.courses]
        item_ids = [item.item_id for item in self.items]
        if len(course_ids) != len(set(course_ids)):
            raise ValueError("course_id values in one update must be unique")
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("item_id values in one update must be unique")
        return self
