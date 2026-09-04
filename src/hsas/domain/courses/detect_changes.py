"""Compare normalized Moodle archives without interpreting course content."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Literal

from pydantic import Field

from .define_courses import CourseArchive, StoredFile
from .define_models import StrictModel
from .index_courses import iter_activities, iter_files


ChangeKind = Literal["deadline", "activity", "material"]
ChangeAction = Literal["added", "removed", "modified"]


class CourseChange(StrictModel):
    kind: ChangeKind
    action: ChangeAction
    entity_id: str
    title: str
    field: str | None = None
    before: Any = None
    after: Any = None
    relative_path: str | None = None
    text_path: str | None = None
    source_url: str | None = None


class CourseChangeSet(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    course_id: str
    change_set_id: str | None = None
    detected_at: datetime
    initial_sync: bool = False
    changed: bool = False
    previous_collected_at: datetime | None = None
    current_collected_at: datetime
    changes: list[CourseChange] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict)


ACTIVITY_FIELDS = (
    "name",
    "category",
    "visible",
    "user_visible",
    "access_visible",
    "has_restrictions",
)
ACTIVITY_DATE_KEYS = (
    "opens_at",
    "allowsubmissionsfromdate",
    "timeopen",
    "due_at",
    "duedate",
    "timeclose",
    "scheduled_at",
)


def compare_course_archives(
    previous: CourseArchive | None,
    current: CourseArchive,
    *,
    detected_at: datetime | None = None,
) -> CourseChangeSet:
    """Report structural Moodle changes; the first sync establishes a baseline."""
    timestamp = detected_at or datetime.now(timezone.utc)
    if previous is None:
        return CourseChangeSet(
            course_id=current.course.course_id,
            detected_at=timestamp,
            initial_sync=True,
            current_collected_at=current.collected_at,
        )
    changes: list[CourseChange] = []
    _compare_activities(previous, current, changes)
    _compare_files(previous, current, changes)
    summary: dict[str, int] = {}
    for change in changes:
        summary[change.kind] = summary.get(change.kind, 0) + 1
    return CourseChangeSet(
        course_id=current.course.course_id,
        change_set_id=_change_set_id(current, changes),
        detected_at=timestamp,
        previous_collected_at=previous.collected_at,
        current_collected_at=current.collected_at,
        changed=bool(changes),
        changes=changes,
        summary=summary,
    )


def _compare_activities(
    previous: CourseArchive,
    current: CourseArchive,
    changes: list[CourseChange],
) -> None:
    old = {activity.module_id: activity for activity in iter_activities(previous)}
    new = {activity.module_id: activity for activity in iter_activities(current)}
    for activity_id in sorted(old.keys() | new.keys()):
        before, after = old.get(activity_id), new.get(activity_id)
        if before is None and after is not None:
            changes.append(
                CourseChange(
                    kind="activity",
                    action="added",
                    entity_id=activity_id,
                    title=after.name,
                    source_url=str(after.url) if after.url else None,
                )
            )
            continue
        if after is None and before is not None:
            changes.append(
                CourseChange(
                    kind="activity",
                    action="removed",
                    entity_id=activity_id,
                    title=before.name,
                    source_url=str(before.url) if before.url else None,
                )
            )
            continue
        assert before is not None and after is not None
        for field in ACTIVITY_FIELDS:
            old_value, new_value = getattr(before, field), getattr(after, field)
            if old_value != new_value:
                changes.append(
                    CourseChange(
                        kind="activity",
                        action="modified",
                        entity_id=activity_id,
                        title=after.name,
                        field=field,
                        before=old_value,
                        after=new_value,
                        source_url=str(after.url) if after.url else None,
                    )
                )
        for key in ACTIVITY_DATE_KEYS:
            old_value = _json_value(before.metadata.get(key))
            new_value = _json_value(after.metadata.get(key))
            if old_value != new_value:
                changes.append(
                    CourseChange(
                        kind="deadline",
                        action="modified",
                        entity_id=activity_id,
                        title=after.name,
                        field=f"metadata.{key}",
                        before=old_value,
                        after=new_value,
                        source_url=str(after.url) if after.url else None,
                    )
                )


def _compare_files(
    previous: CourseArchive,
    current: CourseArchive,
    changes: list[CourseChange],
) -> None:
    old = {
        _file_key(activity.module_id, str(stored_file.source_url)): stored_file
        for activity, stored_file in iter_files(previous)
    }
    new = {
        _file_key(activity.module_id, str(stored_file.source_url)): stored_file
        for activity, stored_file in iter_files(current)
    }
    for key in sorted(old.keys() | new.keys()):
        before, after = old.get(key), new.get(key)
        if before is None and after is not None:
            changes.append(
                CourseChange(
                    kind="material",
                    action="added",
                    entity_id=key,
                    title=after.filename,
                    after=after.sha256,
                    relative_path=after.relative_path,
                    text_path=_text_path(after),
                    source_url=str(after.source_url),
                )
            )
        elif after is None and before is not None:
            changes.append(
                CourseChange(
                    kind="material",
                    action="removed",
                    entity_id=key,
                    title=before.filename,
                    before=before.sha256,
                    relative_path=before.relative_path,
                    text_path=_text_path(before),
                    source_url=str(before.source_url),
                )
            )
        elif before is not None and after is not None and before.sha256 != after.sha256:
            changes.append(
                CourseChange(
                    kind="material",
                    action="modified",
                    entity_id=key,
                    title=after.filename,
                    field="sha256",
                    before=before.sha256,
                    after=after.sha256,
                    relative_path=after.relative_path,
                    text_path=_text_path(after),
                    source_url=str(after.source_url),
                )
            )


def _file_key(module_id: str, source_url: str) -> str:
    return f"{module_id}:{source_url}"


def _text_path(stored_file: StoredFile) -> str | None:
    analysis = stored_file.analysis
    return analysis.extracted_text_path if analysis else None


def _change_set_id(current: CourseArchive, changes: list[CourseChange]) -> str:
    payload = {
        "course_id": current.course.course_id,
        "current_collected_at": current.collected_at.isoformat(),
        "changes": [change.model_dump(mode="json") for change in changes],
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:20]
    return f"change:{current.course.course_id}:{digest}"


def _json_value(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
