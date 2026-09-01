from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal

from pydantic import Field, field_validator

from .define_models import StrictModel


class SourceReference(StrictModel):
    source_type: Literal["moodle_section", "syllabus", "moodle_activity"]
    relative_path: str | None = None
    section_id: str | None = None
    activity_id: str | None = None
    page_numbers: list[int] = Field(default_factory=list)
    note: str | None = None


AssessmentType = Literal[
    "participation",
    "lecture_response",
    "argument_analysis",
    "quiz",
    "news_report",
    "essay",
    "assignment",
    "exam",
    "presentation",
    "project",
    "report",
    "reflection",
    "lab",
    "other",
]

AssessmentExtractionMethod = Literal[
    "moodle_activity",
    "moodle_section",
    "syllabus_text",
]


def _migrate_extraction_methods(value: Any) -> Any:
    """Read old archives without retaining the removed course-plugin concept."""
    if not isinstance(value, list):
        return value
    migrated = [
        "syllabus_text" if method == "course_plugin" else method
        for method in value
    ]
    return list(dict.fromkeys(migrated))


class AssessmentGroup(StrictModel):
    group_id: str
    title: str
    weight_percent: float = Field(ge=0, le=100)
    description: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    extraction_methods: list[AssessmentExtractionMethod] = Field(default_factory=list)
    sources: list[SourceReference] = Field(default_factory=list)

    _migrate_legacy_methods = field_validator(
        "extraction_methods",
        mode="before",
    )(_migrate_extraction_methods)


class AssessmentItem(StrictModel):
    assessment_id: str
    group_id: str | None = None
    title: str
    assessment_type: AssessmentType
    weight_percent: float | None = Field(default=None, ge=0, le=100)
    bonus_percent: float | None = Field(default=None, ge=0, le=100)
    word_limit: int | None = Field(default=None, ge=0)
    opens_on: date | None = None
    due_on: date | None = None
    due_at: datetime | None = None
    scheduled_on: date | None = None
    timezone: str = "Asia/Hong_Kong"
    description: str | None = None
    requirements: list[str] = Field(default_factory=list)
    visible_in_course: bool = True
    status: Literal["confirmed", "tentative"] = "tentative"
    confidence: float | None = Field(default=None, ge=0, le=1)
    extraction_methods: list[AssessmentExtractionMethod] = Field(default_factory=list)
    sources: list[SourceReference] = Field(default_factory=list)

    _migrate_legacy_methods = field_validator(
        "extraction_methods",
        mode="before",
    )(_migrate_extraction_methods)


class AssessmentOverview(StrictModel):
    parser_version: Literal["generic-v1"] | None = None
    grading_basis: str | None = None
    total_weight_percent: float | None = Field(default=None, ge=0)
    groups: list[AssessmentGroup] = Field(default_factory=list)
    items: list[AssessmentItem] = Field(default_factory=list)
    policies: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AssessmentCandidate(StrictModel):
    """One extractor's evidence about a possible assessment item."""

    title: str
    assessment_type: AssessmentType
    group_id: str | None = None
    extraction_method: AssessmentExtractionMethod
    confidence: float = Field(ge=0, le=1)
    weight_percent: float | None = Field(default=None, ge=0, le=100)
    bonus_percent: float | None = Field(default=None, ge=0, le=100)
    word_limit: int | None = Field(default=None, ge=0)
    opens_on: date | None = None
    due_on: date | None = None
    due_at: datetime | None = None
    scheduled_on: date | None = None
    description: str | None = None
    requirements: list[str] = Field(default_factory=list)
    visible_in_course: bool | None = None
    sources: list[SourceReference] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SyllabusDocument:
    text: str
    pages: dict[int, str]
    relative_path: str


class AssessmentComponentHint(StrictModel):
    title: str | None = None
    weight_percent: float = Field(ge=0, le=100)


class AssessmentGroupCandidate(StrictModel):
    group_id: str
    title: str
    weight_percent: float = Field(ge=0, le=100)
    description: str | None = None
    confidence: float = Field(ge=0, le=1)
    components: list[AssessmentComponentHint] = Field(default_factory=list)
    sources: list[SourceReference] = Field(default_factory=list)
