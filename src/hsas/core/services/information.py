"""Information contract service used by the HIQS facade."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from hsas.application.information import (
    InformationServiceError,
    apply_information_update,
    load_information,
    validate_information_update,
    validate_material_coverage,
)
from hsas.application.material_search import (
    invalidate_material_index,
    refresh_material_index,
)
from hsas.domain.information import (
    CourseRecord,
    InformationItem,
    InformationStore,
    InformationUpdate,
    RecentInformationUpdate,
)
from hsas.infrastructure.storage import JsonInformationRepository
from hsas.infrastructure.storage.json_store import write_json


RECENT_UPDATE_PATH = Path("ai-state/recent-information-update.json")

_COURSE_FIELDS = (
    "code",
    "title",
    "semester",
    "starts_on",
    "ends_on",
    "overview",
    "objectives",
    "instructors",
    "links",
    "policies",
    "notes",
)
_ITEM_FIELDS = (
    "title",
    "category",
    "date_status",
    "opens_at",
    "starts_at",
    "ends_at",
    "due_at",
    "due_on",
    "scheduled_on",
    "recurrence",
    "all_day",
    "location",
    "description",
    "assessment_format",
    "submission_method",
    "weight_percent",
    "word_limit",
    "requirements",
    "policies",
    "links",
    "materials",
    "warnings",
)
_DEADLINE_CATEGORIES = {
    "assignment",
    "quiz",
    "exam",
    "presentation",
    "project",
    "report",
    "deadline",
}
_OUTCOME_FIELD_LABELS = {
    "date_status": "日期状态",
    "opens_at": "开放时间",
    "starts_at": "开始时间",
    "ends_at": "结束时间",
    "due_at": "截止时间",
    "due_on": "截止日期",
    "scheduled_on": "安排日期",
    "recurrence": "重复安排",
    "all_day": "全天",
    "location": "地点",
    "description": "说明",
    "assessment_format": "考核形式",
    "submission_method": "提交方式",
    "weight_percent": "占分",
    "word_limit": "字数限制",
    "requirements": "要求",
    "policies": "政策",
    "links": "链接",
    "materials": "相关资料",
    "warnings": "提示",
}
_OUTCOME_FIELD_ORDER = tuple(_OUTCOME_FIELD_LABELS)


class InformationContractService:
    """Own schema and validation concerns without performing writes."""

    def __init__(self, resources_dir: Path, repository: JsonInformationRepository) -> None:
        self.resources_dir = resources_dir
        self.repository = repository

    def schema(self) -> dict[str, Any]:
        return InformationUpdate.model_json_schema()

    def validate(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw_update = payload.get("update", payload)
        try:
            update = validate_information_update(raw_update)
            current = load_information(self.resources_dir / "information.json", self.repository)
            validate_material_coverage(self.resources_dir, current, update)
        except (ValueError, ValidationError, InformationServiceError) as exc:
            raise ValueError(str(exc)) from exc
        return {
            "valid": True,
            "course_count": len(update.courses),
            "item_count": len(update.items),
            "update": update.model_dump(mode="json"),
        }

    def apply(
        self, payload: dict[str, Any], review_service: Any, mutation_lock: Any
    ) -> dict[str, Any]:
        """Apply a validated update and acknowledge its reviewed source batches."""
        if payload.get("confirmed") is not True:
            raise ValueError("Information apply requires explicit confirmation.")
        raw_update = payload.get("update")
        if not isinstance(raw_update, dict):
            raise ValueError("update must be an InformationUpdate object.")
        review_batches = payload.get("review_batches", {})
        if not isinstance(review_batches, dict):
            raise ValueError("review_batches must be an object.")
        update = validate_information_update(raw_update)
        validated_batches = review_service.validate_review_batches(review_batches)
        if validated_batches and not update.courses and not update.items:
            raise ValueError(
                "An empty update cannot acknowledge review batches; use "
                "acknowledge_changes after confirming no fact change."
            )
        with mutation_lock:
            before = (
                self.repository.load(self.resources_dir / "information.json")
                if self.repository.exists(self.resources_dir / "information.json")
                else InformationStore()
            )
            result = apply_information_update(
                self.resources_dir / "information.json",
                update.model_dump(mode="json"),
                confirmed=True,
                repository=self.repository,
                resources_dir=self.resources_dir,
            )
            checkpoints = review_service.acknowledge_validated_batches(validated_batches)
            audit = _build_recent_update(before, result.store, update)
            audit_path = write_json(self.resources_dir / RECENT_UPDATE_PATH, audit)
            audit_path.chmod(0o600)
            affected_courses = {course.course_id for course in update.courses} | {
                item.course_id for item in update.items
            }
            try:
                index_status = {
                    "state": "ready",
                    **refresh_material_index(self.resources_dir, affected_courses),
                }
            except (OSError, ValueError) as exc:
                invalidate_material_index(self.resources_dir)
                index_status = {
                    "state": "stale",
                    "reason": type(exc).__name__,
                }
        return {
            "created_courses": result.created_courses,
            "updated_courses": result.updated_courses,
            "created_items": result.created_items,
            "updated_items": result.updated_items,
            "checkpoints": checkpoints,
            "recent_update": audit,
            "evidence_index": index_status,
        }


def _source(record: CourseRecord | InformationItem) -> dict[str, Any]:
    if not record.sources:
        return {}
    source = record.sources[0]
    return {
        "relative_path": source.relative_path,
        "source_url": source.url,
        "text_path": source.relative_path,
    }


def _material_identity(material: Any) -> str:
    return material.relative_path or material.url or f"title:{material.title.strip().casefold()}"


def _course_materials(course: CourseRecord) -> dict[str, tuple[Any, str]]:
    return {
        _material_identity(material): (material, section.title)
        for section in course.material_sections
        for material in section.materials
    }


def _outcome_source(record: CourseRecord | InformationItem | Any) -> dict[str, Any]:
    if isinstance(record, (CourseRecord, InformationItem)):
        return _source(record)
    return {
        "relative_path": record.relative_path,
        "source_url": record.url,
        "text_path": record.relative_path,
    }


def _display_outcome_value(field_name: str, value: Any) -> str:
    if field_name == "date_status":
        return {"confirmed": "已确认", "tentative": "暂定", "unknown": "未知"}.get(
            str(value), str(value)
        )
    if field_name == "weight_percent" and value is not None:
        return f"{value}%"
    if field_name == "all_day":
        return "是" if value else "否"
    if isinstance(value, list):
        if not value:
            return "已移除"
        return "；".join(str(entry) for entry in value[:3])
    if isinstance(value, dict):
        return "安排已更新"
    if value in (None, ""):
        return "已移除"
    return str(value)


def _item_outcome_details(
    previous: InformationItem | None, current: InformationItem
) -> list[str]:
    before = previous.model_dump(mode="json") if previous else {}
    after = current.model_dump(mode="json")
    details: list[str] = []
    for field_name in _OUTCOME_FIELD_ORDER:
        value = after[field_name]
        if previous is None:
            if value in (None, "", [], {}) or (
                field_name == "date_status" and value == "unknown"
            ):
                continue
        elif before[field_name] == value:
            continue
        details.append(
            f"{_OUTCOME_FIELD_LABELS[field_name]}："
            f"{_display_outcome_value(field_name, value)}"
        )
        if len(details) == 6:
            break
    return details


def _item_outcome(
    previous: InformationItem | None, current: InformationItem
) -> tuple[str, dict[str, Any]]:
    confirmed = (
        previous is not None
        and previous.date_status in {"unknown", "tentative"}
        and current.date_status == "confirmed"
    )
    group = (
        "activities_added"
        if previous is None
        else "activities_confirmed"
        if confirmed
        else "activities_updated"
    )
    kind = "deadline" if current.category in _DEADLINE_CATEGORIES else "activity"
    return group, {
        "record_id": current.item_id,
        "title": current.title,
        "kind": kind,
        "details": _item_outcome_details(previous, current),
        **_outcome_source(current),
    }


def _material_outcomes(
    previous: CourseRecord | None, current: CourseRecord
) -> dict[str, list[dict[str, Any]]]:
    outcomes: dict[str, list[dict[str, Any]]] = {
        "materials_added": [],
        "materials_updated": [],
        "materials_removed": [],
    }
    old_materials = _course_materials(previous) if previous else {}
    new_materials = _course_materials(current)
    for identity, (material, section) in new_materials.items():
        entry = {
            "record_id": identity,
            "title": material.title,
            "kind": "material",
            "details": [f"归类：{section}"],
            **_outcome_source(material),
        }
        if identity not in old_materials:
            outcomes["materials_added"].append(entry)
        elif (
            old_materials[identity][0].model_dump(mode="json")
            != material.model_dump(mode="json")
            or old_materials[identity][1] != section
        ):
            old_section = old_materials[identity][1]
            entry["details"] = (
                [f"归类：{old_section} → {section}"]
                if old_section != section
                else ["资料内容或来源已更新"]
            )
            outcomes["materials_updated"].append(entry)
    for identity, (material, section) in old_materials.items():
        if identity not in new_materials:
            outcomes["materials_removed"].append({
                "record_id": identity,
                "title": material.title,
                "kind": "material",
                "details": [f"原归类：{section}"],
                **_outcome_source(material),
            })
    return outcomes


def _change(
    action: str,
    kind: str,
    title: str,
    *,
    field: str | None = None,
    before: Any = None,
    after: Any = None,
    source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "action": action,
        "kind": kind,
        "title": title,
        "field": field,
        "before": before,
        "after": after,
        **(source or {}),
    }


def _course_changes(previous: CourseRecord | None, current: CourseRecord) -> list[dict[str, Any]]:
    source = _source(current)
    if previous is None:
        return [_change("added", "course", current.title, source=source)]
    changes: list[dict[str, Any]] = []
    before = previous.model_dump(mode="json")
    after = current.model_dump(mode="json")
    for field_name in _COURSE_FIELDS:
        if before[field_name] != after[field_name]:
            changes.append(
                _change(
                    "modified",
                    "course",
                    current.title,
                    field=field_name,
                    before=before[field_name],
                    after=after[field_name],
                    source=source,
                )
            )
    old_materials = _course_materials(previous)
    new_materials = _course_materials(current)
    for identity, (material, section) in new_materials.items():
        material_source = {
            "relative_path": material.relative_path,
            "source_url": material.url,
            "text_path": material.relative_path,
        }
        if identity not in old_materials:
            changes.append(
                _change("added", "material", material.title, after=section, source=material_source)
            )
        elif (
            old_materials[identity][0].model_dump(mode="json") != material.model_dump(mode="json")
            or old_materials[identity][1] != section
        ):
            changes.append(
                _change(
                    "modified",
                    "material",
                    material.title,
                    field="material",
                    before={
                        "section": old_materials[identity][1],
                        **old_materials[identity][0].model_dump(mode="json"),
                    },
                    after={"section": section, **material.model_dump(mode="json")},
                    source=material_source,
                )
            )
    for identity, (material, section) in old_materials.items():
        if identity not in new_materials:
            changes.append(_change("removed", "material", material.title, before=section))
    return changes


def _item_changes(
    previous: InformationItem | None, current: InformationItem
) -> list[dict[str, Any]]:
    kind = "deadline" if current.category in _DEADLINE_CATEGORIES else "activity"
    source = _source(current)
    if previous is None:
        return [_change("added", kind, current.title, source=source)]
    before = previous.model_dump(mode="json")
    after = current.model_dump(mode="json")
    return [
        _change(
            "modified",
            kind,
            current.title,
            field=field_name,
            before=before[field_name],
            after=after[field_name],
            source=source,
        )
        for field_name in _ITEM_FIELDS
        if before[field_name] != after[field_name]
    ]


def _build_recent_update(
    before: InformationStore,
    after: InformationStore,
    update: InformationUpdate,
) -> dict[str, Any]:
    old_courses = {course.course_id: course for course in before.courses}
    new_courses = {course.course_id: course for course in after.courses}
    old_items = {item.item_id: item for item in before.items}
    new_items = {item.item_id: item for item in after.items}
    courses: dict[str, dict[str, Any]] = {}

    def bucket(course_id: str) -> dict[str, Any]:
        course = new_courses.get(course_id) or old_courses.get(course_id)
        return courses.setdefault(
            course_id,
            {
                "course_id": course_id,
                "course_title": course.title if course else course_id,
                "mode": "completed",
                "acknowledge_through": after.updated_at.isoformat(),
                "changes": [],
                "files": [],
                "activities_added": [],
                "activities_updated": [],
                "activities_confirmed": [],
                "materials_added": [],
                "materials_updated": [],
                "materials_removed": [],
            },
        )

    for incoming in update.courses:
        previous = old_courses.get(incoming.course_id)
        current = new_courses[incoming.course_id]
        course_bucket = bucket(incoming.course_id)
        course_bucket["changes"].extend(_course_changes(previous, current))
        for group, entries in _material_outcomes(previous, current).items():
            course_bucket[group].extend(entries)
    for incoming in update.items:
        previous = old_items.get(incoming.item_id)
        current = new_items[incoming.item_id]
        course_bucket = bucket(incoming.course_id)
        item_changes = _item_changes(previous, current)
        course_bucket["changes"].extend(item_changes)
        if item_changes:
            group, outcome = _item_outcome(previous, current)
            course_bucket[group].append(outcome)
    outcome_groups = (
        "activities_added",
        "activities_updated",
        "activities_confirmed",
        "materials_added",
        "materials_updated",
        "materials_removed",
    )
    visible_courses = [
        value
        for value in courses.values()
        if value["changes"] or any(value[group] for group in outcome_groups)
    ]
    counts = {
        action: sum(
            change["action"] == action for course in visible_courses for change in course["changes"]
        )
        for action in ("added", "modified", "removed")
    }
    return RecentInformationUpdate.model_validate({
        "schema_version": "1.0",
        "applied_at": after.updated_at.isoformat(),
        "updated_by": after.updated_by,
        "summary": {
            **counts,
            "change_count": sum(counts.values()),
            "course_count": len(visible_courses),
            **{
                group: sum(len(course[group]) for course in visible_courses)
                for group in outcome_groups
            },
        },
        "courses": visible_courses,
    }).model_dump(mode="json")
