"""Deterministic, read-only Notion projection of validated course information.

The default projection is a course library. Agenda and execution state belong
to Apple apps; historical execution rows require an explicit compatibility flag. Neither exporting nor syncing may write canonical facts.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from hsas.domain.information import InformationStore
from hsas.domain.information.calendar import calendar_milestones
from hsas.domain.information.models import InformationItem
from hsas.domain.information.models import moodle_source_course_ids


def rich_text(value: str | None) -> dict[str, Any]:
    text = value or ""
    return {"rich_text": [
        {"type": "text", "text": {"content": text[i:i + 2000]}}
        for i in range(0, len(text), 2000)
    ]}


def title(value: str) -> dict[str, Any]:
    return {"title": [{"text": {"content": value[:2000]}}]}


def date_property(start: str | None, end: str | None = None) -> dict[str, Any]:
    return {"date": {"start": start, "end": end} if start else None}


def select(value: str) -> dict[str, Any]:
    return {"select": {"name": value}}


def _join(values: list[Any]) -> str:
    return "\n".join(str(value) for value in values)


def _record(kind: str, identity: str, properties: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"kind": kind, "identity": identity, "properties": properties, **extra}


def build_notion_projection(
    store: InformationStore,
    resolve_file: Callable[[str], tuple[Path, str]],
    *, source_documents: list[dict[str, Any]] | None = None,
    include_execution: bool = False,
) -> dict[str, Any]:
    """Build the course library; execution rows are an explicit legacy export option.

    resolve_file must whitelist current source files and reject path traversal.
    Missing materials are reported, never replaced with arbitrary disk files.
    Calendar expansion is bounded by each validated rule (maximum 5 years).
    """
    records: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    source_stamp = store.updated_at.isoformat()
    # Notion date properties retain minute precision; keep the exact source
    # revision in the report while projecting a round-trip-safe display value.
    sync_display_stamp = store.updated_at.replace(second=0, microsecond=0).isoformat()
    course_codes = {c.course_id: c.code for c in store.courses}
    assessment_archives: dict[str, list[str]] = {}
    for item in store.items:
        if item.weight_percent is not None or item.category in {
                "assignment", "quiz", "exam", "presentation", "project", "report"}:
            weight = f"{item.weight_percent:g}%" if item.weight_percent is not None else "占比未确认"
            summary = " · ".join(v for v in (item.title, weight, item.assessment_format) if v)
            assessment_archives.setdefault(item.course_id, []).append(summary)
    for course in store.courses:
        records.append(_record("courses", course.course_id, {
            "Course": title(f"{course.code} · {course.title}"),
            "HIQS Course ID": rich_text(course.course_id),
            "Code": rich_text(course.code), "Semester": rich_text(course.semester),
            "Overview": rich_text(course.overview),
            "Objectives": rich_text(_join(course.objectives)),
            "Assessment Archive": rich_text(_join(assessment_archives.get(course.course_id, []))),
            "Instructors": rich_text(_join(course.instructors)),
            "Policies": rich_text(_join(course.policies)),
            "Notes": rich_text(_join(course.notes)),
            "Links": rich_text(_join([f"{v.label}: {v.url}" for v in course.links])),
            "Teaching Period": date_property(
                course.starts_on.isoformat() if course.starts_on else None,
                course.ends_on.isoformat() if course.ends_on else None,
            ),
            "Last Synced": date_property(sync_display_stamp),
            "Source": select("HIQS"), "Sync State": select("current"),
        }, details=course.model_dump(mode="json")))

    for item in store.items if include_execution else []:
        value = item.model_dump(mode="json")
        due = value["due_at"] or value["due_on"]
        when = value["starts_at"] or value["scheduled_on"] or due or value["opens_at"]
        properties = {
            "Item": title(item.title), "HIQS Item ID": rich_text(item.item_id),
            "Category": select(item.category), "Date Status": select(item.date_status),
            "Actionable": {"checkbox": is_actionable(value)},
            "Task Role": select(item.task_role),
            "Description": rich_text(item.description),
            "Location": rich_text(item.location),
            "Assessment Format": rich_text(item.assessment_format),
            "Submission Method": rich_text(item.submission_method),
            "Weight %": {"number": item.weight_percent},
            "Word Limit": {"number": item.word_limit},
            "Requirements": rich_text(_join(item.requirements)),
            "Policies": rich_text(_join(item.policies)),
            "Warnings": rich_text(_join(item.warnings)),
            "Links": rich_text(_join([f"{v.label}: {v.url}" for v in item.links])),
            "Materials": rich_text(_join([v.title for v in item.materials])),
            "Source Evidence": rich_text(_join([
                v.model_dump_json(exclude_none=True) for v in item.sources
            ])),
            "Recurrence": rich_text(
                item.recurrence.model_dump_json() if item.recurrence else ""
            ),
            "All Day": {"checkbox": item.all_day},
            "When": date_property(when, value["ends_at"] if value["starts_at"] else None),
            "Due": date_property(due),
            "Opens": date_property(value["opens_at"]),
            "Ends": date_property(value["ends_at"]),
            "Schedule": date_property(value["scheduled_on"]),
            "Last Synced": date_property(sync_display_stamp),
            "Sync State": select("current"),
            "Source": select("HIQS"),
        }
        records.append(_record("items", item.item_id, properties,
            course_id=item.course_id, details=value,
            initial_status="To-do" if is_actionable(value) else None))
        for occurrence in expand_calendar(value, store.timezone):
            records.append(_record("calendar", occurrence["identity"], {
                "Activity": title(occurrence["title"]),
                "HIQS Occurrence ID": rich_text(occurrence["identity"]),
                "HIQS Item ID": rich_text(item.item_id),
                "Course Tag": select(course_codes[item.course_id]),
                "Category": select(item.category),
                "When": date_property(occurrence["start"], occurrence["end"]),
                "Location": rich_text(occurrence["location"]),
                "Date Status": select(item.date_status),
                "Sync State": select("current"),
            }, course_id=item.course_id, item_id=item.item_id))

    for course in store.courses:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for order, section in enumerate(course.material_sections):
            for material in section.materials:
                if not material.relative_path:
                    if material.url:
                        identity = f"{course.course_id}:url:{sha256(material.url.encode()).hexdigest()}"
                        grouped.setdefault(identity, []).append({
                            "section": section.title, "order": order,
                            "title": material.title, "url": material.url,
                        })
                    continue
                try:
                    path, mime = resolve_file(material.relative_path)
                    digest = sha256()
                    with path.open("rb") as stream:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                            digest.update(chunk)
                    identity = f"{course.course_id}:{digest.hexdigest()}"
                    grouped.setdefault(identity, []).append({
                        "section": section.title, "order": order, "title": path.name,
                        "relative_path": material.relative_path, "path": str(path),
                        "bytes": path.stat().st_size, "mime": mime,
                        "sha256": digest.hexdigest(), "url": material.url,
                    })
                except (OSError, RuntimeError, ValueError):
                    warnings.append({"course_id": course.course_id,
                        "relative_path": material.relative_path,
                        "reason": "missing_or_unauthorized_source"})
        for identity, copies in grouped.items():
            primary = min(copies, key=lambda v: (
                any(s in v["section"].casefold() for s in (
                    "reference copies", "submission resources", "course forum"
                )), v["order"], v.get("relative_path", ""),
            ))
            sections = list(dict.fromkeys(v["section"] for v in copies))
            records.append(_record("materials", identity, {
                "资料": title(primary["title"]),
                "资料 ID": rich_text(identity), "分类": rich_text(primary["section"]),
                "原分类": rich_text(_join(sections)),
                "分类顺序": {"number": primary["order"]},
                "SHA256": rich_text(primary.get("sha256")),
                "本地路径": rich_text(primary.get("relative_path")),
                "文件类型": rich_text(Path(primary["title"]).suffix[1:].upper()),
                "字节数": {"number": primary.get("bytes")},
                "来源": rich_text(primary.get("url")),
            }, course_id=course.course_id, file=primary,
                source_paths=[v["relative_path"] for v in copies if "relative_path" in v],
                source_sections=sections))
    _append_unreviewed_materials(store, records, warnings, resolve_file, source_documents or [])
    return {"schema_version": "1.0", "scope": "legacy" if include_execution else "library",
        "source_updated_at": source_stamp,
        "timezone": store.timezone, "records": records, "warnings": warnings,
        "counts": {kind: sum(r["kind"] == kind for r in records)
            for kind in ("courses", "items", "calendar", "materials")},
        "task_counts": {
            "actionable": sum(r["kind"] == "items" and bool(r.get("initial_status")) for r in records),
            "undated_actionable": sum(r["kind"] == "items" and bool(r.get("initial_status"))
                and not r["properties"]["When"]["date"] and not r["details"]["recurrence"] for r in records),
        }}


def _append_unreviewed_materials(store, records, warnings, resolve_file, documents):
    """Deliver collected originals without inferring new academic facts."""
    owners: dict[str, set[str]] = {}
    for course in store.courses:
        for source_id in moodle_source_course_ids(course):
            owners.setdefault(source_id, set()).add(course.course_id)
    known = {r["identity"]: r for r in records if r["kind"] == "materials"}
    covered_paths = {p for r in known.values() for p in r.get("source_paths", [])}
    for document in documents:
        relative = document.get("relative_path")
        course_ids = owners.get(document.get("course_id"), set())
        if not relative or relative in covered_paths or len(course_ids) != 1:
            continue
        course_id = next(iter(course_ids))
        try:
            path, mime = resolve_file(relative)
            digest = sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            checksum = digest.hexdigest()
            if document.get("sha256") and document["sha256"] != checksum:
                warnings.append({"course_id": course_id, "relative_path": relative,
                                 "reason": "source_content_changed"})
                continue
            identity = f"{course_id}:{checksum}"
            if identity in known:
                known[identity]["source_paths"].append(relative)
                covered_paths.add(relative)
                continue
            original = {"section": "待整理", "order": 9999, "title": path.name,
                "relative_path": relative, "path": str(path), "bytes": path.stat().st_size,
                "mime": mime, "sha256": checksum, "url": None}
            row = _record("materials", identity, {
                "资料": title(path.name), "资料 ID": rich_text(identity),
                "分类": rich_text("待整理"), "原分类": rich_text(""),
                "分类顺序": {"number": 9999}, "SHA256": rich_text(checksum),
                "本地路径": rich_text(relative), "文件类型": rich_text(path.suffix[1:].upper()),
                "字节数": {"number": original["bytes"]}, "来源": rich_text(""),
            }, course_id=course_id, file=original, source_paths=[relative],
                source_sections=[], unreviewed=True)
            records.append(row)
            known[identity] = row
            covered_paths.add(relative)
        except (OSError, RuntimeError, ValueError):
            warnings.append({"course_id": course_id, "relative_path": relative,
                             "reason": "missing_or_unauthorized_source"})


def is_actionable(item: dict[str, Any]) -> bool:
    if item.get("task_role") == "reference":
        return False
    if item.get("task_role") == "action":
        return True
    if item["category"] == "reading":
        return bool(item.get("due_at") or item.get("due_on") or item.get("requirements"))
    return item["category"] in {"assignment", "quiz", "exam", "presentation", "project",
                                "report", "deadline"}


def expand_calendar(item: dict[str, Any], timezone: str) -> list[dict[str, Any]]:
    """Expand weekly rules including cancellations, additions and overrides."""
    # Callers may pass minimal dictionaries as well as fully dumped models.
    model = InformationItem.model_validate({"course_id": "projection", "category": "other", **item})
    rows = []
    for role, start, end in calendar_milestones(model):
        value = start.isoformat()
        label = {"due": "Deadline", "opens": "Opens"}.get(role)
        rows.append({"identity": f"{item['item_id']}:{value[:10]}" + (f":{role}" if role else ""),
            "title": f"{item['title']} · {label}" if label else item["title"],
            "start": value, "end": end.isoformat() if end else None,
            "location": item.get("location")})
    recurrence = item.get("recurrence")
    if not recurrence:
        return rows
    first = datetime.fromisoformat(recurrence["valid_from"]).date()
    last = datetime.fromisoformat(recurrence["valid_until"]).date()
    if (last - first).days > 366 * 5:
        raise ValueError("Notion calendar rule exceeds the five-year expansion limit")
    dates = {first + timedelta(days=n) for n in range((last - first).days + 1)
        if (first + timedelta(days=n)).weekday() in recurrence["weekdays"]}
    dates.update(datetime.fromisoformat(d).date() for d in recurrence["additional_dates"])
    dates.difference_update(datetime.fromisoformat(d).date() for d in recurrence["excluded_dates"])
    exceptions = {v["date"]: v for v in recurrence["exceptions"]}
    dates.update(datetime.fromisoformat(d).date() for d, v in exceptions.items()
        if v["status"] == "changed")
    for day in sorted(dates):
        exception = exceptions.get(day.isoformat(), {})
        if exception.get("status") == "cancelled":
            continue
        start = exception.get("start_time") or recurrence["start_time"]
        end = exception.get("end_time") or recurrence["end_time"]
        zone = ZoneInfo(timezone)
        rows.append({"identity": f"{item['item_id']}:{day.isoformat()}",
            "title": exception.get("title") or item["title"],
            "start": datetime.fromisoformat(f"{day}T{start}").replace(tzinfo=zone).isoformat(),
            "end": datetime.fromisoformat(f"{day}T{end}").replace(tzinfo=zone).isoformat(),
            "location": exception.get("location") or item.get("location")})
    return rows
