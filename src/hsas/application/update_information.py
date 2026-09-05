"""Validate and merge AI-authored course information updates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from pydantic import ValidationError

from hsas.application.ports.define_repositories import InformationRepository
from hsas.domain.information import (
    CourseRecord,
    InformationItem,
    InformationStore,
    InformationUpdate,
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
) -> InformationApplyResult:
    if not confirmed:
        raise InformationServiceError(
            "Refusing to write information without --confirmed. Review the AI-authored JSON first."
        )
    update = validate_information_update(payload)
    current = load_information(path, repository)

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
