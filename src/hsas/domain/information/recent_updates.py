"""Validated, user-visible report of the most recently applied fact changes."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from hsas.domain.courses.base import StrictModel


class RecentUpdateChange(StrictModel):
    action: Literal["added", "modified", "removed"]
    kind: str
    title: str
    field: str | None = None
    before: Any = None
    after: Any = None
    relative_path: str | None = None
    source_url: str | None = None
    text_path: str | None = None


class RecentUpdateOutcome(StrictModel):
    """One user-meaningful result, aggregated above field-level audit changes."""

    record_id: str
    title: str
    kind: Literal["activity", "deadline", "material"]
    details: list[str] = Field(default_factory=list)
    relative_path: str | None = None
    source_url: str | None = None
    text_path: str | None = None


class RecentUpdateCourse(StrictModel):
    course_id: str
    course_title: str
    mode: Literal["completed"] = "completed"
    acknowledge_through: datetime
    changes: list[RecentUpdateChange] = Field(default_factory=list)
    files: list[dict[str, Any]] = Field(default_factory=list)
    activities_added: list[RecentUpdateOutcome] = Field(default_factory=list)
    activities_updated: list[RecentUpdateOutcome] = Field(default_factory=list)
    activities_confirmed: list[RecentUpdateOutcome] = Field(default_factory=list)
    materials_added: list[RecentUpdateOutcome] = Field(default_factory=list)
    materials_updated: list[RecentUpdateOutcome] = Field(default_factory=list)
    materials_removed: list[RecentUpdateOutcome] = Field(default_factory=list)


class RecentUpdateSummary(StrictModel):
    added: int = Field(ge=0)
    modified: int = Field(ge=0)
    removed: int = Field(ge=0)
    change_count: int = Field(ge=0)
    course_count: int = Field(ge=0)
    activities_added: int = Field(default=0, ge=0)
    activities_updated: int = Field(default=0, ge=0)
    activities_confirmed: int = Field(default=0, ge=0)
    materials_added: int = Field(default=0, ge=0)
    materials_updated: int = Field(default=0, ge=0)
    materials_removed: int = Field(default=0, ge=0)


class RecentInformationUpdate(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    applied_at: datetime
    updated_by: Literal["ai_agent", "import", "manual"]
    summary: RecentUpdateSummary
    courses: list[RecentUpdateCourse] = Field(default_factory=list)
