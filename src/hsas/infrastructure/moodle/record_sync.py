"""Backward-compatible, per-course synchronization status records."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hsas.infrastructure.storage.persist_data import read_json, write_json


def record_sync_operation(
    resources_dir: Path,
    *,
    scope: str,
    discovered_course_count: int,
    course_results: list[dict[str, Any]],
) -> Path:
    """Merge one sync operation into durable per-course status."""
    path = resources_dir / "sync-report.json"
    previous: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = read_json(path)
            if isinstance(loaded, dict):
                previous = loaded
        except (OSError, ValueError):
            previous = {}
    courses = previous.get("courses")
    if not isinstance(courses, dict):
        courses = {}
    attempted_at = datetime.now(timezone.utc).isoformat()
    succeeded: list[str] = []
    failures: list[dict[str, str]] = []
    change_counts: dict[str, int] = {}
    for result in course_results:
        course_id = str(result.get("course_id") or "")
        title = str(result.get("course") or result.get("title") or course_id)
        success = bool(result.get("succeeded"))
        error = str(result.get("error") or "")
        changes = int(result.get("change_count") or 0)
        record = {
            "course_id": course_id,
            "course": title,
            "attempted_at": attempted_at,
            "succeeded": success,
            "change_count": changes,
            "error": error or None,
        }
        if course_id:
            courses[course_id] = record
        if success and course_id:
            succeeded.append(course_id)
            change_counts[course_id] = changes
        elif not success:
            failures.append(
                {"course": title, "course_id": course_id, "error": error or "unknown error"}
            )
    value = {
        "schema_version": "2.0",
        "updated_at": attempted_at,
        "last_scope": scope,
        "discovered_course_count": discovered_course_count,
        "succeeded_course_ids": succeeded,
        "change_counts": change_counts,
        "failures": failures,
        "courses": courses,
    }
    return write_json(path, value)


def sync_warnings(resources_dir: Path, course_ids: set[str]) -> list[str]:
    """Return current, course-specific failures without treating missing status as success."""
    path = resources_dir / "sync-report.json"
    if not path.is_file():
        return ["Synchronization status is unavailable; course freshness is unverified."]
    try:
        value = read_json(path)
    except (OSError, ValueError):
        return ["Synchronization status is invalid; course freshness is unverified."]
    courses = value.get("courses") if isinstance(value, dict) else None
    warnings: list[str] = []
    if isinstance(courses, dict):
        for course_id in sorted(course_ids):
            status = courses.get(course_id)
            if not isinstance(status, dict):
                warnings.append(f"Course {course_id} has no synchronization status.")
            elif not status.get("succeeded"):
                error = status.get("error") or "unknown error"
                warnings.append(f"Course {course_id} last synchronization failed: {error}")
        return warnings
    failures = value.get("failures", []) if isinstance(value, dict) else []
    succeeded = {
        str(course_id)
        for course_id in (value.get("succeeded_course_ids", []) if isinstance(value, dict) else [])
    }
    failed_ids: set[str] = set()
    for failure in failures if isinstance(failures, list) else []:
        if not isinstance(failure, dict):
            continue
        course_id = str(failure.get("course_id") or "")
        if course_id:
            failed_ids.add(course_id)
        if not course_ids or course_id in course_ids:
            warnings.append(
                f"Course {course_id or failure.get('course', 'unknown')} synchronization failed: "
                f"{failure.get('error') or 'unknown error'}"
            )
    for course_id in sorted(course_ids - succeeded - failed_ids):
        warnings.append(f"Course {course_id} has no synchronization status.")
    return warnings
