"""Compare two normalized course archives and report plan-relevant changes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import Field

from .define_models import StrictModel
from .index_courses import iter_activities, iter_files
from .define_courses import CourseArchive


ChangeKind = Literal["assessment", "deadline", "weight", "activity", "material"]
ChangeAction = Literal["added", "removed", "modified"]


class CourseChange(StrictModel):
    kind: ChangeKind
    action: ChangeAction
    entity_id: str
    title: str
    field: str | None = None
    before: Any = None
    after: Any = None


class CourseChangeSet(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    course_id: str
    detected_at: datetime
    initial_sync: bool = False
    changed: bool = False
    previous_collected_at: datetime | None = None
    current_collected_at: datetime
    changes: list[CourseChange] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict)

ASSESSMENT_FIELDS: dict[str, ChangeKind] = {
    "opens_on": "deadline",
    "due_on": "deadline",
    "due_at": "deadline",
    "scheduled_on": "deadline",
    "weight_percent": "weight",
    "bonus_percent": "weight",
    "word_limit": "assessment",
    "requirements": "assessment",
    "status": "assessment",
}
ACTIVITY_FIELDS = (
    "name",
    "category",
    "visible",
    "user_visible",
    "access_visible",
    "has_restrictions",
)
ACTIVITY_DEADLINE_KEYS = (
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
    """Return a compact field-level diff; the first sync establishes a baseline."""
    if previous is None:
        return CourseChangeSet(
            course_id=current.course.course_id,
            detected_at=detected_at or datetime.now(timezone.utc),
            initial_sync=True,
            current_collected_at=current.collected_at,
        )

    changes: list[CourseChange] = []
    _compare_assessments(previous, current, changes)
    _compare_assessment_groups(previous, current, changes)
    _compare_activities(previous, current, changes)
    _compare_files(previous, current, changes)
    summary: dict[str, int] = {}
    for change in changes:
        summary[change.kind] = summary.get(change.kind, 0) + 1
    return CourseChangeSet(
        course_id=current.course.course_id,
        detected_at=detected_at or datetime.now(timezone.utc),
        previous_collected_at=previous.collected_at,
        current_collected_at=current.collected_at,
        changed=bool(changes),
        changes=changes,
        summary=summary,
    )


def _compare_assessments(
    previous: CourseArchive,
    current: CourseArchive,
    changes: list[CourseChange],
) -> None:
    old = {item.assessment_id: item for item in previous.assessments.items}
    new = {item.assessment_id: item for item in current.assessments.items}
    for assessment_id in sorted(old.keys() | new.keys()):
        before, after = old.get(assessment_id), new.get(assessment_id)
        if before is None and after is not None:
            changes.append(CourseChange(
                kind="assessment", action="added", entity_id=assessment_id,
                title=after.title, after=after.model_dump(mode="json"),
            ))
            continue
        if after is None and before is not None:
            changes.append(CourseChange(
                kind="assessment", action="removed", entity_id=assessment_id,
                title=before.title, before=before.model_dump(mode="json"),
            ))
            continue
        assert before is not None and after is not None
        for field, kind in ASSESSMENT_FIELDS.items():
            old_value = _json_value(getattr(before, field))
            new_value = _json_value(getattr(after, field))
            if old_value != new_value:
                changes.append(CourseChange(
                    kind=kind, action="modified", entity_id=assessment_id,
                    title=after.title, field=field, before=old_value, after=new_value,
                ))


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
            changes.append(CourseChange(
                kind="activity", action="added", entity_id=activity_id,
                title=after.name,
            ))
            continue
        if after is None and before is not None:
            changes.append(CourseChange(
                kind="activity", action="removed", entity_id=activity_id,
                title=before.name,
            ))
            continue
        assert before is not None and after is not None
        for field in ACTIVITY_FIELDS:
            old_value, new_value = getattr(before, field), getattr(after, field)
            if old_value != new_value:
                changes.append(CourseChange(
                    kind="activity", action="modified", entity_id=activity_id,
                    title=after.name, field=field, before=old_value, after=new_value,
                ))
        for key in ACTIVITY_DEADLINE_KEYS:
            old_value = _json_value(before.metadata.get(key))
            new_value = _json_value(after.metadata.get(key))
            if old_value != new_value:
                changes.append(CourseChange(
                    kind="deadline", action="modified", entity_id=activity_id,
                    title=after.name, field=f"metadata.{key}",
                    before=old_value, after=new_value,
                ))


def _compare_assessment_groups(
    previous: CourseArchive,
    current: CourseArchive,
    changes: list[CourseChange],
) -> None:
    old = {group.group_id: group for group in previous.assessments.groups}
    new = {group.group_id: group for group in current.assessments.groups}
    for group_id in sorted(old.keys() & new.keys()):
        before, after = old[group_id], new[group_id]
        if before.weight_percent != after.weight_percent:
            changes.append(CourseChange(
                kind="weight", action="modified", entity_id=group_id,
                title=after.title, field="group.weight_percent",
                before=before.weight_percent, after=after.weight_percent,
            ))


def _compare_files(
    previous: CourseArchive,
    current: CourseArchive,
    changes: list[CourseChange],
) -> None:
    old = {_file_key(activity.module_id, str(file.source_url)): file
           for activity, file in iter_files(previous)}
    new = {_file_key(activity.module_id, str(file.source_url)): file
           for activity, file in iter_files(current)}
    for key in sorted(old.keys() | new.keys()):
        before, after = old.get(key), new.get(key)
        entity_id = key
        if before is None and after is not None:
            changes.append(CourseChange(
                kind="material", action="added", entity_id=entity_id,
                title=after.filename, after=after.sha256,
            ))
        elif after is None and before is not None:
            changes.append(CourseChange(
                kind="material", action="removed", entity_id=entity_id,
                title=before.filename, before=before.sha256,
            ))
        elif before is not None and after is not None and before.sha256 != after.sha256:
            changes.append(CourseChange(
                kind="material", action="modified", entity_id=entity_id,
                title=after.filename, field="sha256",
                before=before.sha256, after=after.sha256,
            ))


def _file_key(activity_id: str, source_url: str) -> str:
    return f"{activity_id}:{source_url}"


def _json_value(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
