"""Define the Class Planner fields that can change timetable facts."""

from __future__ import annotations

from typing import Any


TIMETABLE_COURSE_FIELDS = {
    "STRM",
    "CRSE_ID",
    "CLASS_NBR",
    "COURSE_SUBCLASS",
    "COURSE_TITLE_LONG",
    "SUBJECT_AREA",
    "CATALOG_NBR",
    "DAYTIMEVENUE",
    "DAY_STR_SRCH",
    "INSTRUCTOR",
    "INSTRUCTOR_DISP",
    "CRSE_UNITS",
    "SIS_CP_SUB_CLS_TIME",
    "ENROLLMENT_REQUIREMENTS",
    "COURSE_DESCRIPTION",
}


def timetable_course_fields(course: dict[str, Any]) -> dict[str, Any]:
    """Exclude quotas, survey statistics and other volatile catalogue metadata."""
    return {
        key: value
        for key, value in course.items()
        if key.upper() in TIMETABLE_COURSE_FIELDS
    }


def timetable_record(record: dict[str, Any] | None) -> dict[str, Any] | None:
    if record is None:
        return None
    course = record.get("course")
    patterns = record.get("patterns")
    return {
        "course": timetable_course_fields(course if isinstance(course, dict) else {}),
        "patterns": patterns if isinstance(patterns, list) else [],
    }


def meaningful_detail(detail: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize a current or legacy detail and drop metadata-only modifications."""
    if detail.get("action") != "modified":
        return detail
    if not isinstance(detail.get("before"), dict) or not isinstance(
        detail.get("after"), dict
    ):
        return detail
    before = timetable_record(detail.get("before"))
    after = timetable_record(detail.get("after"))
    if before == after:
        return None
    fields = [
        field
        for field in ("course", "patterns")
        if (before or {}).get(field) != (after or {}).get(field)
    ]
    return {**detail, "fields": fields, "before": before, "after": after}
