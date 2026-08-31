"""Shared schemas used by acquisition, transformation, and storage stages."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, HttpUrl

from ..assessment.schema import AssessmentOverview
from ..course_materials.pdf_schema import PdfAnalysis
from .base_schema import StrictModel


class CourseSummary(StrictModel):
    title: str
    url: HttpUrl
    course_id: str | None = None


class Resource(StrictModel):
    kind: Literal["resource"] = "resource"
    title: str
    url: HttpUrl
    description: str | None = None
    resource_type: str | None = None


class Assignment(StrictModel):
    kind: Literal["assignment"] = "assignment"
    title: str
    url: HttpUrl
    description: str | None = None
    due_at: datetime | None = None


class Announcement(StrictModel):
    kind: Literal["announcement"] = "announcement"
    title: str
    url: HttpUrl
    description: str | None = None


class Section(StrictModel):
    title: str
    index: int = Field(ge=0)
    resources: list[Resource] = Field(default_factory=list)
    assignments: list[Assignment] = Field(default_factory=list)
    announcements: list[Announcement] = Field(default_factory=list)


class CourseSnapshot(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    source: Literal["hku_moodle"] = "hku_moodle"
    collected_at: datetime
    course: CourseSummary
    sections: list[Section]


# Version 2 models are API-first and preserve Moodle's stable IDs.  The v1
# models above remain available for the HTML fallback and existing consumers.
class StoredFile(StrictModel):
    filename: str
    relative_path: str
    source_url: HttpUrl
    content_type: str | None = None
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    downloaded_at: datetime
    etag: str | None = None
    last_modified: str | None = None
    validated_at: datetime | None = None
    analysis: "PdfAnalysis | None" = None


ActivityCategory = Literal[
    "resource", "assignment", "announcement", "forum", "quiz", "url", "other"
]
DownloadStatus = Literal[
    "not_applicable", "pending", "downloaded", "skipped", "failed", "external"
]


class CourseActivity(StrictModel):
    module_id: str
    name: str
    category: ActivityCategory
    module: str
    plugin: str | None = None
    module_name: str | None = None
    url: HttpUrl | None = None
    visible: bool = True
    user_visible: bool = True
    access_visible: bool = True
    stealth: bool = False
    has_restrictions: bool = False
    completion_state: int | None = None
    download_status: DownloadStatus = "not_applicable"
    download_error: str | None = None
    files: list[StoredFile] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CourseSectionV2(StrictModel):
    section_id: str
    number: int = Field(ge=0)
    title: str
    url: HttpUrl | None = None
    visible: bool = True
    current: bool = False
    activities: list[CourseActivity] = Field(default_factory=list)


class CourseInfoV2(StrictModel):
    course_id: str
    title: str
    url: HttpUrl
    declared_section_count: int = Field(ge=0)
    returned_section_count: int = Field(ge=0)
    max_upload_bytes: int | None = Field(default=None, ge=0)


class CollectionStats(StrictModel):
    section_count: int = Field(default=0, ge=0)
    activity_count: int = Field(default=0, ge=0)
    activity_types: dict[str, int] = Field(default_factory=dict)
    downloaded_file_count: int = Field(default=0, ge=0)
    downloaded_bytes: int = Field(default=0, ge=0)
    failed_download_count: int = Field(default=0, ge=0)
    analyzed_pdf_count: int = Field(default=0, ge=0)
    pdf_word_count: int = Field(default=0, ge=0)


class CourseArchive(StrictModel):
    schema_version: Literal["2.0", "2.1", "2.2"] = "2.2"
    source: Literal["hku_moodle_ajax"] = "hku_moodle_ajax"
    collected_at: datetime
    course: CourseInfoV2
    sections: list[CourseSectionV2]
    unassigned_activities: list[CourseActivity] = Field(default_factory=list)
    stats: CollectionStats = Field(default_factory=CollectionStats)
    raw_state_path: str
    assessments: AssessmentOverview = Field(default_factory=AssessmentOverview)
