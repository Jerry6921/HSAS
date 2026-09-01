from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from .define_assessments import AssessmentGroup, AssessmentItem
from .define_courses import CourseActivity, CourseArchive, CourseSectionV2, StoredFile


class ArchiveIndexError(ValueError):
    """Raised when an archive cannot form an unambiguous in-memory index."""


@dataclass(frozen=True, slots=True)
class FileLocation:
    section_id: str | None
    activity_id: str
    activity: CourseActivity
    stored_file: StoredFile


def iter_activities(archive: CourseArchive) -> Iterator[CourseActivity]:
    """Iterate all assigned and unassigned activities exactly once."""
    for section in archive.sections:
        yield from section.activities
    yield from archive.unassigned_activities


def iter_files(archive: CourseArchive) -> Iterator[tuple[CourseActivity, StoredFile]]:
    """Iterate files together with their owning activity."""
    for activity in iter_activities(archive):
        for stored_file in activity.files:
            yield activity, stored_file


class ArchiveIndex:
    """Strongly typed CourseArchive plus fast indexes over its nested objects.

    The underlying Pydantic models remain mutable. Call ``rebuild()`` after
    adding/removing sections, activities, files, or assessments through another
    service so every lookup reflects the latest archive state.
    """

    def __init__(
        self,
        archive: CourseArchive,
        *,
        source_path: Path | None = None,
    ) -> None:
        self.archive = archive
        self.source_path = source_path
        self.rebuild()

    @classmethod
    def from_json(cls, path: str | Path) -> "ArchiveIndex":
        source_path = Path(path)
        archive = CourseArchive.model_validate_json(
            source_path.read_text(encoding="utf-8")
        )
        return cls(archive, source_path=source_path)

    @classmethod
    def from_json_text(cls, text: str) -> "ArchiveIndex":
        return cls(CourseArchive.model_validate_json(text))

    def rebuild(self) -> None:
        sections: dict[str, CourseSectionV2] = {}
        activities: dict[str, CourseActivity] = {}
        activity_section_ids: dict[str, str | None] = {}
        files_by_path: dict[str, FileLocation] = {}
        files_by_sha256: dict[str, list[FileLocation]] = {}
        assessments: dict[str, AssessmentItem] = {}
        groups: dict[str, AssessmentGroup] = {}

        for section in self.archive.sections:
            self._add_unique(sections, section.section_id, section, "section_id")
            for activity in section.activities:
                self._index_activity(
                    activity,
                    section_id=section.section_id,
                    activities=activities,
                    activity_section_ids=activity_section_ids,
                    files_by_path=files_by_path,
                    files_by_sha256=files_by_sha256,
                )
        for activity in self.archive.unassigned_activities:
            self._index_activity(
                activity,
                section_id=None,
                activities=activities,
                activity_section_ids=activity_section_ids,
                files_by_path=files_by_path,
                files_by_sha256=files_by_sha256,
            )
        for assessment in self.archive.assessments.items:
            self._add_unique(
                assessments,
                assessment.assessment_id,
                assessment,
                "assessment_id",
            )
        for group in self.archive.assessments.groups:
            self._add_unique(groups, group.group_id, group, "group_id")

        self._sections_by_id = sections
        self._activities_by_id = activities
        self._activity_section_ids = activity_section_ids
        self._files_by_path = files_by_path
        self._files_by_sha256 = {
            digest: tuple(locations) for digest, locations in files_by_sha256.items()
        }
        self._assessments_by_id = assessments
        self._groups_by_id = groups

    @staticmethod
    def _add_unique(target: dict, key: str, value: object, label: str) -> None:
        if not key:
            raise ArchiveIndexError(f"Cannot index an empty {label}")
        if key in target:
            raise ArchiveIndexError(f"Duplicate {label}: {key}")
        target[key] = value

    def _index_activity(
        self,
        activity: CourseActivity,
        *,
        section_id: str | None,
        activities: dict[str, CourseActivity],
        activity_section_ids: dict[str, str | None],
        files_by_path: dict[str, FileLocation],
        files_by_sha256: dict[str, list[FileLocation]],
    ) -> None:
        self._add_unique(activities, activity.module_id, activity, "module_id")
        activity_section_ids[activity.module_id] = section_id
        for stored_file in activity.files:
            location = FileLocation(
                section_id=section_id,
                activity_id=activity.module_id,
                activity=activity,
                stored_file=stored_file,
            )
            self._add_unique(
                files_by_path,
                stored_file.relative_path,
                location,
                "relative_path",
            )
            files_by_sha256.setdefault(stored_file.sha256, []).append(location)

    @property
    def sections_by_id(self) -> Mapping[str, CourseSectionV2]:
        return MappingProxyType(self._sections_by_id)

    @property
    def activities_by_id(self) -> Mapping[str, CourseActivity]:
        return MappingProxyType(self._activities_by_id)

    @property
    def files_by_path(self) -> Mapping[str, FileLocation]:
        return MappingProxyType(self._files_by_path)

    @property
    def files_by_sha256(self) -> Mapping[str, tuple[FileLocation, ...]]:
        return MappingProxyType(self._files_by_sha256)

    @property
    def assessments_by_id(self) -> Mapping[str, AssessmentItem]:
        return MappingProxyType(self._assessments_by_id)

    @property
    def groups_by_id(self) -> Mapping[str, AssessmentGroup]:
        return MappingProxyType(self._groups_by_id)

    def get_section(self, section_id: str) -> CourseSectionV2 | None:
        return self._sections_by_id.get(section_id)

    def get_activity(self, module_id: str) -> CourseActivity | None:
        return self._activities_by_id.get(module_id)

    def get_activity_section_id(self, module_id: str) -> str | None:
        return self._activity_section_ids.get(module_id)

    def get_file(self, relative_path: str) -> FileLocation | None:
        return self._files_by_path.get(relative_path)

    def get_assessment(self, assessment_id: str) -> AssessmentItem | None:
        return self._assessments_by_id.get(assessment_id)

    def get_group(self, group_id: str) -> AssessmentGroup | None:
        return self._groups_by_id.get(group_id)

    def find_document(self, *, role: str) -> FileLocation | None:
        marker = role.casefold().strip()
        for location in self._files_by_path.values():
            if (
                marker in location.activity.name.casefold()
                or marker in location.stored_file.filename.casefold()
            ):
                return location
        return None
