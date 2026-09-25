"""Validate and merge AI-authored course information updates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from pydantic import ValidationError

from hsas.application.ports.define_repositories import InformationRepository
from hsas.domain.courses import ArchiveIndex, iter_files
from hsas.domain.information import (
    CourseRecord,
    InformationItem,
    InformationStore,
    InformationUpdate,
    moodle_source_course_ids,
)


class InformationServiceError(ValueError):
    """A safe validation or authorization failure for information updates."""


@dataclass(frozen=True, slots=True)
class InformationApplyResult:
    store: InformationStore
    created_courses: int
    updated_courses: int
    created_items: int
    updated_items: int


Record = TypeVar("Record", CourseRecord, InformationItem)


def load_information(
    path: Path,
    repository: InformationRepository,
) -> InformationStore:
    if not repository.exists(path):
        return InformationStore()
    try:
        return repository.load(path)
    except (OSError, ValueError, ValidationError) as exc:
        raise InformationServiceError(
            f"Information database is invalid: {type(exc).__name__}: {exc}"
        ) from exc


def validate_information_update(payload: Any) -> InformationUpdate:
    try:
        return InformationUpdate.model_validate(payload)
    except ValidationError as exc:
        raise InformationServiceError(f"Information update is invalid: {exc}") from exc


def apply_information_update(
    path: Path,
    payload: Any,
    *,
    confirmed: bool,
    repository: InformationRepository,
    resources_dir: Path | None = None,
) -> InformationApplyResult:
    if not confirmed:
        raise InformationServiceError(
            "Refusing to write information without --confirmed. Review the AI-authored JSON first."
        )
    update = validate_information_update(payload)
    current = load_information(path, repository)
    if resources_dir is not None:
        validate_material_coverage(resources_dir, current, update)

    courses, created_courses, updated_courses = _upsert(
        current.courses,
        update.courses,
        key=lambda course: course.course_id,
    )
    items, created_items, updated_items = _upsert(
        current.items,
        update.items,
        key=lambda item: item.item_id,
    )
    try:
        store = InformationStore(
            timezone=update.timezone or current.timezone,
            updated_at=datetime.now(UTC),
            updated_by=update.updated_by,
            courses=courses,
            items=items,
        )
    except ValidationError as exc:
        raise InformationServiceError(
            f"Merged information database is invalid: {exc}"
        ) from exc
    repository.save(path, store)
    return InformationApplyResult(
        store=store,
        created_courses=created_courses,
        updated_courses=updated_courses,
        created_items=created_items,
        updated_items=updated_items,
    )


def validate_material_coverage(
    resources_dir: Path,
    current: InformationStore,
    update: InformationUpdate,
) -> None:
    """Reject course replacements that lose a live Moodle archive or its files."""
    current_by_id = {course.course_id: course for course in current.courses}
    for course in update.courses:
        source_ids = moodle_source_course_ids(course)
        previous = current_by_id.get(course.course_id)
        if previous is not None:
            previous_ids = moodle_source_course_ids(previous)
            dropped_ids = [value for value in previous_ids if value not in source_ids]
            live_dropped = [
                value
                for value in dropped_ids
                if (resources_dir / "courses" / value / "course.json").is_file()
            ]
            if live_dropped:
                raise InformationServiceError(
                    f"Course {course.course_id} would drop linked Moodle archive(s): "
                    f"{', '.join(live_dropped)}. Preserve them in "
                    "additional_moodle_course_ids and review their materials."
                )

        expected_paths: set[str] = set()
        missing_archives: list[str] = []
        for source_id in source_ids:
            archive_path = resources_dir / "courses" / source_id / "course.json"
            if not archive_path.is_file():
                if source_id in course.additional_moodle_course_ids:
                    missing_archives.append(source_id)
                continue
            archive = ArchiveIndex.from_json(archive_path).archive
            expected_paths.update(
                stored_file.relative_path
                for _activity, stored_file in iter_files(archive)
            )
        if missing_archives:
            raise InformationServiceError(
                f"Course {course.course_id} references missing linked Moodle archive(s): "
                f"{', '.join(missing_archives)}. Synchronize them before applying."
            )

        reviewed_paths = {
            material.relative_path
            for section in course.material_sections
            for material in section.materials
            if material.relative_path
        }
        missing_paths = sorted(expected_paths - reviewed_paths)
        if missing_paths:
            preview = ", ".join(missing_paths[:3])
            suffix = "" if len(missing_paths) <= 3 else f" and {len(missing_paths) - 3} more"
            raise InformationServiceError(
                f"Course {course.course_id} material coverage is incomplete: "
                f"{len(missing_paths)} current Moodle file(s) are missing from "
                f"material_sections ({preview}{suffix})."
            )


def build_information_template() -> InformationUpdate:
    """Return a schema-valid example that an AI can copy and replace."""
    return InformationUpdate.model_validate(
        {
            "schema_version": "1.0",
            "timezone": "Asia/Hong_Kong",
            "updated_by": "ai_agent",
            "courses": [
                {
                    "course_id": "MATH1851-2026-SEM1",
                    "code": "MATH1851",
                    "title": "Calculus and ordinary differential equations",
                    "moodle_course_id": None,
                    "additional_moodle_course_ids": [],
                    "semester": "2026-27 Semester 1",
                    "starts_on": "2026-09-01",
                    "ends_on": "2026-11-30",
                    "color": "#2563eb",
                    "overview": "To be replaced from an official course source",
                    "objectives": [],
                    "instructors": [],
                    "links": [],
                    "policies": [],
                    "notes": [],
                    "sources": [],
                    "material_sections": [
                        {
                            "title": "Replace with an evidence-derived section name",
                            "description": "AI chooses the grouping from this course's materials.",
                            "materials": [
                                {
                                    "title": "Replace with a downloaded course material",
                                    "relative_path": "courses/replace-with-downloaded-file.pdf",
                                }
                            ],
                        }
                    ],
                }
            ],
            "items": [
                {
                    "item_id": "MATH1851-tutorial-tue",
                    "course_id": "MATH1851-2026-SEM1",
                    "title": "Tutorial",
                    "category": "tutorial",
                    "date_status": "confirmed",
                    "recurrence": {
                        "weekdays": [1],
                        "valid_from": "2026-09-01",
                        "valid_until": "2026-11-30",
                        "start_time": "14:30:00",
                        "end_time": "15:20:00",
                        "excluded_dates": [],
                        "additional_dates": [],
                        "exceptions": [
                            {
                                "date": "2026-10-06",
                                "status": "cancelled",
                                "note": "Public holiday; replace from an official source",
                                "sources": [],
                            }
                        ],
                    },
                    "location": "To be replaced from the source",
                    "requirements": [],
                    "policies": [],
                    "links": [],
                    "materials": [
                        {
                            "title": "Tutorial 1 exercises",
                            "material_type": "exercises",
                            "relative_path": "courses/replace-with-downloaded-file.pdf",
                            "page_numbers": [1],
                            "note": "Replace only when the source explicitly supports this activity link",
                        }
                    ],
                    "sources": [],
                    "warnings": [],
                },
                {
                    "item_id": "MATH1851-assignment-1",
                    "course_id": "MATH1851-2026-SEM1",
                    "title": "Assignment 1",
                    "category": "assignment",
                    "date_status": "unknown",
                    "assessment_format": "To be replaced from the source",
                    "requirements": [],
                    "policies": [],
                    "links": [],
                    "materials": [],
                    "sources": [],
                    "warnings": ["Replace this example and verify the official deadline."],
                },
            ],
        }
    )


def _upsert(
    existing: list[Record],
    incoming: list[Record],
    *,
    key,
) -> tuple[list[Record], int, int]:
    incoming_by_id = {key(record): record for record in incoming}
    existing_ids = {key(record) for record in existing}
    merged = [incoming_by_id.get(key(record), record) for record in existing]
    merged.extend(record for record in incoming if key(record) not in existing_ids)
    created = sum(key(record) not in existing_ids for record in incoming)
    updated = len(incoming) - created
    return merged, created, updated
