"""Validated contracts for incremental AI review of Moodle changes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import AwareDatetime, Field

from .define_models import StrictModel


class ReviewFile(StrictModel):
    filename: str
    relative_path: str
    local_path: str
    text_path: str | None = None
    exists: bool
    change_action: Literal["baseline", "added", "modified", "removed"]


class ChangeReference(StrictModel):
    change_set_id: str
    detected_at: AwareDatetime
    kind: Literal["deadline", "activity", "material"]
    action: Literal["added", "removed", "modified"]
    entity_id: str
    title: str
    field: str | None = None
    before: object | None = None
    after: object | None = None
    relative_path: str | None = None
    text_path: str | None = None
    source_url: str | None = None


class CourseReview(StrictModel):
    course_id: str
    course_title: str
    mode: Literal["full", "incremental"]
    acknowledge_through: AwareDatetime
    changes: list[ChangeReference] = Field(default_factory=list)
    files: list[ReviewFile] = Field(default_factory=list)
    affected_information_item_ids: list[str] = Field(default_factory=list)


class PendingChangeBatch(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    generated_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    resources_dir: str
    courses: list[CourseReview] = Field(default_factory=list)

    @property
    def pending_change_count(self) -> int:
        return sum(max(len(course.changes), 1) for course in self.courses)


class CourseChangeCheckpoint(StrictModel):
    processed_through: AwareDatetime
    acknowledged_at: AwareDatetime


class ChangeCheckpoint(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    updated_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    courses: dict[str, CourseChangeCheckpoint] = Field(default_factory=dict)
