"""Information contract service used by the HIQS facade."""

from __future__ import annotations

from datetime import date, datetime
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
    RecentUpdateDigest,
)
from hsas.infrastructure.storage import JsonInformationRepository
from hsas.infrastructure.storage.json_store import read_json, write_json


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
_DATE_CHANGE_FIELDS = (
    "date_status", "opens_at", "starts_at", "ends_at", "due_at", "due_on",
    "scheduled_on", "recurrence", "all_day",
)
_INFORMATION_CHANGE_FIELDS = (
    "title", "category", "location", "description", "assessment_format",
    "submission_method", "weight_percent", "word_limit", "requirements",
    "policies", "links", "warnings",
)
_IMPACT_LABELS = {
    "title": "活动名称已更改",
    "category": "活动类型已更改",
    "location": "地点已更改",
    "description": "活动说明已更改",
    "assessment_format": "考核形式已更改",
    "submission_method": "提交方式已更改",
    "weight_percent": "成绩占比已更改",
    "word_limit": "字数限制已更改",
    "requirements": "活动要求已更改",
    "policies": "课程政策已更改",
    "links": "相关链接已更改",
    "warnings": "核对提示已更改",
    "recurrence": "重复安排已更改",
    "all_day": "全天状态已更改",
}


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
            audit = persist_recent_information_update(
                self.resources_dir, before, result.store, update
            )
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

    def save_recent_update_summary(
        self, payload: dict[str, Any], mutation_lock: Any
    ) -> dict[str, Any]:
        """Attach an Agent-written digest to the exact latest validated report."""
        if not isinstance(payload, dict):
            raise ValueError("summary payload must be an object.")
        expected = payload.get("applied_at")
        headline = payload.get("headline")
        body = payload.get("body")
        references = payload.get("highlights", [])
        if not isinstance(expected, str) or not expected:
            raise ValueError("applied_at must identify the report being summarized.")
        if not isinstance(headline, str) or not headline.strip() or len(headline) > 120:
            raise ValueError("headline must contain 1 to 120 characters.")
        if not isinstance(body, str) or not body.strip() or len(body) > 600:
            raise ValueError("body must contain 1 to 600 characters.")
        if not isinstance(references, list) or len(references) > 6:
            raise ValueError("highlights must be a list of at most 6 report references.")
        with mutation_lock:
            path = self.resources_dir / RECENT_UPDATE_PATH
            if not path.is_file():
                raise ValueError("No recent information update is available to summarize.")
            report = RecentInformationUpdate.model_validate(read_json(path))
            if report.applied_at.isoformat() != expected.replace("Z", "+00:00"):
                raise ValueError("The recent update changed; read the latest report before summarizing.")
            candidates = {
                (entry["category"], entry["course_id"], entry["record_id"]): entry
                for entry in _update_highlights(
                    [course.model_dump(mode="json") for course in report.courses]
                )
            }
            selected: list[dict[str, Any]] = []
            seen: set[tuple[str, str, str]] = set()
            for reference in references:
                if not isinstance(reference, dict) or set(reference) != {
                    "category", "course_id", "record_id"
                }:
                    raise ValueError("Each highlight needs category, course_id and record_id.")
                key = (
                    reference["category"], reference["course_id"], reference["record_id"]
                )
                if key not in candidates or key in seen:
                    raise ValueError("Highlight is missing, duplicated or not in this report.")
                seen.add(key)
                selected.append(candidates[key])
            digest = {
                "headline": headline.strip(),
                "body": body.strip(),
                "authored_by": "ai_agent",
                "highlights": selected,
                "omitted_count": max(0, len(candidates) - len(selected)),
            }
            updated = report.model_copy(update={"digest": RecentUpdateDigest.model_validate(digest)})
            validated = RecentInformationUpdate.model_validate(updated.model_dump(mode="json"))
            write_json(path, validated.model_dump(mode="json")).chmod(0o600)
            return validated.model_dump(mode="json")


def persist_recent_information_update(
    resources_dir: Path,
    before: InformationStore,
    after: InformationStore,
    update: InformationUpdate,
) -> dict[str, Any]:
    """Persist the user-visible audit for every canonical information write path."""
    audit = _build_recent_update(before, after, update)
    audit_path = write_json(resources_dir / RECENT_UPDATE_PATH, audit)
    audit_path.chmod(0o600)
    return audit


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
        labels = [
            str(
                entry.get("title")
                or entry.get("label")
                or entry.get("relative_path")
                or "资料"
            )
            if isinstance(entry, dict)
            else str(entry)
            for entry in value[:3]
        ]
        suffix = f" 等 {len(value)} 项" if len(value) > 3 else ""
        return "；".join(labels) + suffix
    if isinstance(value, dict):
        return "安排已更新"
    if value in (None, ""):
        return "已移除"
    return str(value)


def _item_outcome_details(
    previous: InformationItem | None,
    current: InformationItem,
    fields: tuple[str, ...] = _OUTCOME_FIELD_ORDER,
) -> list[str]:
    before = previous.model_dump(mode="json") if previous else {}
    after = current.model_dump(mode="json")
    details: list[str] = []
    for field_name in fields:
        value = after[field_name]
        if previous is None:
            if value in (None, "", [], {}) or (
                field_name == "date_status" and value == "unknown"
            ):
                continue
        elif before[field_name] == value:
            continue
        label = _OUTCOME_FIELD_LABELS.get(field_name, field_name)
        detail = (
            f"{label}：{_display_outcome_value(field_name, value)}"
            if previous is None
            else f"{label}：{_display_outcome_value(field_name, before[field_name])}"
            f" → {_display_outcome_value(field_name, value)}"
        )
        details.append(detail)
        if len(details) == 6:
            break
    return details


def _parse_temporal(value: Any) -> date | datetime | None:
    if isinstance(value, (date, datetime)):
        return value
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")) if "T" in value else date.fromisoformat(value)
    except ValueError:
        return None


def _date_impact(previous: InformationItem, current: InformationItem, fields: list[str]) -> list[str]:
    impact: list[str] = []
    if "date_status" in fields:
        impact.append(
            "日期已由暂定或未知转为确认"
            if current.date_status == "confirmed" and previous.date_status != "confirmed"
            else "日期确认状态已更改"
        )
    for field_name in ("due_at", "due_on", "starts_at", "scheduled_on", "opens_at", "ends_at"):
        if field_name not in fields:
            continue
        before = _parse_temporal(getattr(previous, field_name))
        after = _parse_temporal(getattr(current, field_name))
        label = _OUTCOME_FIELD_LABELS[field_name]
        if before is not None and after is not None:
            seconds = (after - before).total_seconds()
            if seconds:
                direction = "延后" if seconds > 0 else "提前"
                absolute = abs(seconds)
                amount = f"{absolute / 86400:g} 天" if absolute >= 86400 else f"{absolute / 3600:g} 小时"
                impact.append(f"{label}已{direction} {amount}")
            else:
                impact.append(f"{label}的具体时间已更改")
        elif before is None and after is not None:
            impact.append(f"{label}已补充")
        elif before is not None and after is None:
            impact.append(f"{label}已移除，需重新确认安排")
        else:
            impact.append(f"{label}已调整")
        break
    impact.extend(_IMPACT_LABELS[field] for field in ("recurrence", "all_day") if field in fields)
    return list(dict.fromkeys(impact))


def _information_impact(fields: list[str]) -> list[str]:
    return list(dict.fromkeys(_IMPACT_LABELS[field] for field in fields if field in _IMPACT_LABELS))


def _item_outcomes(
    previous: InformationItem | None, current: InformationItem
) -> list[tuple[str, dict[str, Any]]]:
    kind = "deadline" if current.category in _DEADLINE_CATEGORIES else "activity"
    base = {
        "record_id": current.item_id,
        "title": current.title,
        "kind": kind,
        **_outcome_source(current),
    }
    if previous is None:
        return [("activities_added", {**base, "details": _item_outcome_details(None, current)})]
    before = previous.model_dump(mode="json")
    after = current.model_dump(mode="json")
    date_fields = [field for field in _DATE_CHANGE_FIELDS if before[field] != after[field]]
    information_fields = [field for field in _INFORMATION_CHANGE_FIELDS if before[field] != after[field]]
    outcomes: list[tuple[str, dict[str, Any]]] = []
    if date_fields:
        outcomes.append(("activity_date_changes", {
            **base,
            "details": _item_outcome_details(previous, current, tuple(date_fields)),
            "impact": _date_impact(previous, current, date_fields),
        }))
    if information_fields:
        outcomes.append(("activity_information_changes", {
            **base,
            "details": _item_outcome_details(previous, current, tuple(information_fields)),
            "impact": _information_impact(information_fields),
        }))
    return outcomes


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


def _update_highlights(visible_courses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Provide eligible highlight records in user importance order."""
    groups: tuple[tuple[str, str, str], ...] = (
        ("date", "日期变化", "activity_date_changes"),
        ("information", "信息变化", "activity_information_changes"),
        ("activity", "新增活动", "activities_added"),
        ("material", "资料新增", "materials_added"),
        ("material", "资料更新", "materials_updated"),
        ("material", "资料移除", "materials_removed"),
    )
    highlights: list[dict[str, Any]] = []
    for category, label, group in groups:
        for course in visible_courses:
            for entry in course[group]:
                highlights.append({
                    "category": category,
                    "label": label,
                    "course_id": course["course_id"],
                    "course_title": course["course_title"],
                    "record_id": entry["record_id"],
                    "title": entry["title"],
                    "details": entry.get("details", []),
                    "impact": entry.get("impact", []),
                    "relative_path": entry.get("relative_path"),
                    "source_url": entry.get("source_url"),
                    "text_path": entry.get("text_path"),
                })

    return highlights


def _build_update_digest(
    visible_courses: list[dict[str, Any]],
    counts: dict[str, int],
) -> dict[str, Any]:
    """Create a short fallback digest from the validated audit buckets."""
    highlights = _update_highlights(visible_courses)
    highlight_limit = 6
    total = sum(counts.get(action, 0) for action in ("added", "modified", "removed"))
    digest_highlights = highlights[:highlight_limit]
    omitted_count = max(0, len(highlights) - len(digest_highlights))
    if not total:
        headline = "本次整理未改变正式课程事实"
        body = "Agent 已完成资料核对，当前没有需要写入日历的新增或变更。"
    else:
        headline = (
            f"本次整理重点核对了 {counts.get('modified', 0)} 项已有信息"
            if counts.get("modified", 0)
            else f"本次整理新增了 {counts.get('added', 0)} 项课程信息"
        )
        body = (
            f"已完成 {len(visible_courses)} 门课程的正式整理："
            f"新增 {counts.get('added', 0)} 项，"
            f"变更 {counts.get('modified', 0)} 项，"
            f"移除 {counts.get('removed', 0)} 项。"
        )
        if counts.get("activity_date_changes", 0):
            body += f" 其中 {counts['activity_date_changes']} 项日期变化需要优先留意。"
    return {
        "headline": headline,
        "body": body,
        "authored_by": "system",
        "highlights": digest_highlights,
        "omitted_count": omitted_count,
    }


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
                "activity_date_changes": [],
                "activity_information_changes": [],
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
            for group, outcome in _item_outcomes(previous, current):
                course_bucket[group].append(outcome)
    outcome_groups = (
        "activities_added",
        "activities_updated",
        "activities_confirmed",
        "activity_date_changes",
        "activity_information_changes",
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
        "digest": _build_update_digest(
            visible_courses,
            {
                **counts,
                **{
                    group: sum(len(course[group]) for course in visible_courses)
                    for group in outcome_groups
                },
            },
        ),
        "courses": visible_courses,
    }).model_dump(mode="json")
