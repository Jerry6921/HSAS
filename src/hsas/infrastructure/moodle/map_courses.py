from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from hsas.domain.courses.define_courses import (
    CourseActivity,
    CourseArchive,
    CourseInfoV2,
    CourseSectionV2,
)
from hsas.domain.courses.calculate_statistics import refresh_archive_stats


def classify_activity(module: str, name: str) -> str:
    module = module.casefold()
    lowered_name = name.casefold()
    if module == "assign":
        return "assignment"
    if module == "forum" and any(
        marker in lowered_name
        for marker in ("announcement", "announcements", "公告", "通知")
    ):
        return "announcement"
    if module == "forum":
        return "forum"
    if module == "quiz":
        return "quiz"
    if module == "url":
        return "url"
    if module in {"resource", "folder", "page", "book"}:
        return "resource"
    return "other"


def map_activity(raw: dict[str, Any]) -> CourseActivity:
    module = str(raw.get("module") or "unknown")
    name = str(raw.get("name") or "Untitled")
    if module == "url":
        download_status = "external"
    elif module in {"resource", "folder", "page", "book", "assign"}:
        download_status = "pending"
    else:
        download_status = "not_applicable"

    known_keys = {
        "id", "name", "module", "plugin", "modname", "url", "visible",
        "uservisible", "accessvisible", "stealth", "hascmrestrictions",
        "completionstate", "sectionid", "sectionnumber",
    }
    useful_metadata = {
        key: value
        for key, value in raw.items()
        if key not in known_keys
        and key
        in {
            "groupmode",
            "isoverallcomplete",
            "istrackeduser",
            "indent",
            "duedate",
            "due_at",
            "allowsubmissionsfromdate",
            "opens_at",
            "timeopen",
            "timeclose",
            "scheduled_at",
            "content_text",
        }
    }
    return CourseActivity(
        module_id=str(raw.get("id") or ""),
        name=name,
        category=classify_activity(module, name),
        module=module,
        plugin=raw.get("plugin"),
        module_name=raw.get("modname"),
        url=raw.get("url"),
        visible=bool(raw.get("visible", True)),
        user_visible=bool(raw.get("uservisible", True)),
        access_visible=bool(raw.get("accessvisible", True)),
        stealth=bool(raw.get("stealth", False)),
        has_restrictions=bool(raw.get("hascmrestrictions", False)),
        completion_state=raw.get("completionstate"),
        download_status=download_status,
        metadata=useful_metadata,
    )


def build_course_archive(
    state: dict[str, Any], *, course_title: str, raw_state_path: str
) -> CourseArchive:
    course = state["course"]
    raw_modules = {str(item["id"]): item for item in state.get("cm", [])}
    assigned_ids: set[str] = set()
    sections: list[CourseSectionV2] = []

    for raw_section in state.get("section", []):
        activities: list[CourseActivity] = []
        for module_id in raw_section.get("cmlist", []):
            module_id = str(module_id)
            raw_module = raw_modules.get(module_id)
            if raw_module is None:
                continue
            assigned_ids.add(module_id)
            activities.append(map_activity(raw_module))
        sections.append(
            CourseSectionV2(
                section_id=str(raw_section.get("id") or ""),
                number=int(raw_section.get("number", raw_section.get("section", 0))),
                title=str(raw_section.get("rawtitle") or raw_section.get("title") or "Untitled"),
                url=raw_section.get("sectionurl"),
                visible=bool(raw_section.get("visible", True)),
                current=bool(raw_section.get("current", False)),
                activities=activities,
            )
        )

    unassigned = [
        map_activity(raw)
        for module_id, raw in raw_modules.items()
        if module_id not in assigned_ids
    ]
    max_bytes = course.get("maxbytes")
    archive = CourseArchive(
        collected_at=datetime.now(timezone.utc),
        course=CourseInfoV2(
            course_id=str(course["id"]),
            title=course_title,
            url=course["baseurl"],
            declared_section_count=int(course.get("numsections", 0)),
            returned_section_count=len(sections),
            max_upload_bytes=int(max_bytes) if max_bytes is not None else None,
        ),
        sections=sections,
        unassigned_activities=unassigned,
        raw_state_path=raw_state_path,
    )
    refresh_archive_stats(archive)
    return archive
