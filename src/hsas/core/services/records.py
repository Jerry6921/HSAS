"""Manage explicitly confirmed course and personal-event records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from hsas.application.ports.repositories import (
    ChangeQueueRepository,
    InformationRepository,
)
from hsas.core.ports import HIQSPortError
from hsas.domain.courses import ArchiveIndex
from hsas.domain.information import (
    CourseRecord,
    InformationItem,
    InformationStore,
)
from hsas.infrastructure.storage import (
    JsonChangeQueueRepository,
    JsonInformationRepository,
)
from hsas.infrastructure.storage.json_store import write_json


USER_EVENT_SOURCE_TITLE = "HIQS Dashboard user-created event"


@dataclass(slots=True)
class CourseRecordService:
    """Own canonical course/event mutations and their recoverable trash workflow."""

    resources_dir: Path
    mutation_lock: Lock
    information_repository: InformationRepository = field(
        default_factory=JsonInformationRepository,
        repr=False,
    )
    change_repository: ChangeQueueRepository = field(
        default_factory=JsonChangeQueueRepository,
        repr=False,
    )

    def add_course(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("confirmed") is not True:
            raise HIQSPortError("请先确认添加课程。")
        raw_course = payload.get("course")
        if not isinstance(raw_course, dict):
            raise HIQSPortError("course 必须是有效的课程 object。")
        try:
            course = CourseRecord.model_validate(raw_course)
        except ValidationError as exc:
            raise HIQSPortError(f"课程资料无法通过校验：{exc}") from exc
        path = self.resources_dir / "information.json"
        with self.mutation_lock:
            try:
                store = self._load_optional_store(path)
                if any(value.course_id == course.course_id for value in store.courses):
                    raise HIQSPortError(f"课程 ID 已存在：{course.course_id}")
                self.information_repository.save(
                    path,
                    InformationStore(
                        timezone=store.timezone,
                        updated_at=datetime.now(UTC),
                        updated_by="manual",
                        courses=[*store.courses, course],
                        items=store.items,
                    ),
                )
            except HIQSPortError:
                raise
            except (OSError, ValueError, ValidationError) as exc:
                raise HIQSPortError(
                    f"添加课程失败：{type(exc).__name__}: {str(exc)[:300]}"
                ) from exc
        return {"course_id": course.course_id, "created": True}

    def delete_course(self, payload: dict[str, Any]) -> dict[str, Any]:
        course_id = payload.get("course_id")
        if not isinstance(course_id, str) or not course_id.strip():
            raise HIQSPortError("course_id 必须是有效的课程 ID。")
        if payload.get("confirmed") is not True or payload.get("confirmation") != course_id:
            raise HIQSPortError("课程删除确认与目标课程不一致。")
        result = self._delete_courses([course_id])
        return {
            "course_id": course_id,
            "deleted": True,
            "deleted_item_count": result["deleted_item_count"],
            "files_moved_to_trash": bool(result["files_moved_to_trash"]),
        }

    def delete_courses(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw_ids = payload.get("course_ids")
        if not isinstance(raw_ids, list) or not raw_ids:
            raise HIQSPortError("course_ids 必须包含至少一个课程 ID。")
        if any(not isinstance(value, str) or not value.strip() for value in raw_ids):
            raise HIQSPortError("course_ids 包含无效的课程 ID。")
        course_ids = list(dict.fromkeys(value.strip() for value in raw_ids))
        if payload.get("confirmed") is not True or payload.get("confirmation") != course_ids:
            raise HIQSPortError("课程批量删除确认与目标课程不一致。")
        result = self._delete_courses(course_ids)
        return {
            "course_ids": course_ids,
            "deleted": True,
            "deleted_course_count": len(course_ids),
            **result,
        }

    def add_calendar_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("confirmed") is not True:
            raise HIQSPortError("请先确认添加事件。")
        raw_event = payload.get("event")
        if not isinstance(raw_event, dict):
            raise HIQSPortError("event 必须是有效的事件 object。")
        course_id = raw_event.get("course_id")
        title = raw_event.get("title")
        if not isinstance(course_id, str) or not course_id.strip():
            raise HIQSPortError("事件必须属于一门课程。")
        if not isinstance(title, str) or not title.strip():
            raise HIQSPortError("事件标题不能为空。")
        now = datetime.now(UTC)
        item_id = f"manual-{now:%Y%m%d%H%M%S}-{uuid4().hex[:8]}"
        all_day = raw_event.get("all_day") is True
        event_data: dict[str, Any] = {
            "item_id": item_id,
            "course_id": course_id.strip(),
            "title": title.strip(),
            "category": raw_event.get("category", "other"),
            "date_status": "confirmed",
            "all_day": all_day,
            "location": _optional_text(raw_event.get("location")),
            "description": _optional_text(raw_event.get("description")),
            "sources": [
                {
                    "source_type": "manual",
                    "title": USER_EVENT_SOURCE_TITLE,
                    "observed_at": now.isoformat(),
                    "note": "Created and confirmed by the user in the local Dashboard.",
                }
            ],
            "last_verified_at": now.isoformat(),
        }
        if all_day:
            event_data["scheduled_on"] = raw_event.get("scheduled_on")
        else:
            event_data["starts_at"] = raw_event.get("starts_at")
            event_data["ends_at"] = raw_event.get("ends_at")
        try:
            item = InformationItem.model_validate(event_data)
        except ValidationError as exc:
            raise HIQSPortError(f"事件资料无法通过校验：{exc}") from exc
        path = self.resources_dir / "information.json"
        with self.mutation_lock:
            try:
                store = self._load_optional_store(path)
                if not any(course.course_id == item.course_id for course in store.courses):
                    raise HIQSPortError(f"课程不存在：{item.course_id}")
                self.information_repository.save(
                    path,
                    InformationStore(
                        timezone=store.timezone,
                        updated_at=now,
                        updated_by="manual",
                        courses=store.courses,
                        items=[*store.items, item],
                    ),
                )
            except HIQSPortError:
                raise
            except (OSError, ValueError, ValidationError) as exc:
                raise HIQSPortError(
                    f"添加事件失败：{type(exc).__name__}: {str(exc)[:300]}"
                ) from exc
        return {"item_id": item.item_id, "created": True}

    def delete_calendar_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        item_id = payload.get("item_id")
        if not isinstance(item_id, str) or not item_id.strip():
            raise HIQSPortError("item_id 必须是有效的事件 ID。")
        if payload.get("confirmed") is not True or payload.get("confirmation") != item_id:
            raise HIQSPortError("事件删除确认与目标事件不一致。")
        path = self.resources_dir / "information.json"
        with self.mutation_lock:
            try:
                store = self.information_repository.load(path)
                item = next((value for value in store.items if value.item_id == item_id), None)
                if item is None:
                    raise HIQSPortError(f"事件不存在：{item_id}")
                if not is_user_created_item(item.model_dump(mode="json")):
                    raise HIQSPortError("只能删除由用户在 Dashboard 中创建的事件。")
                now = datetime.now(UTC)
                trash_path = (
                    self.resources_dir
                    / ".trash"
                    / "items"
                    / f"{now:%Y%m%dT%H%M%SZ}-{item.item_id}.json"
                )
                write_json(
                    trash_path,
                    {"deleted_at": now.isoformat(), "item": item.model_dump(mode="json")},
                )
                self.information_repository.save(
                    path,
                    InformationStore(
                        timezone=store.timezone,
                        updated_at=now,
                        updated_by="manual",
                        courses=store.courses,
                        items=[value for value in store.items if value.item_id != item_id],
                    ),
                )
            except HIQSPortError:
                raise
            except (OSError, ValueError, ValidationError) as exc:
                raise HIQSPortError(
                    f"删除事件失败：{type(exc).__name__}: {str(exc)[:300]}"
                ) from exc
        return {
            "item_id": item_id,
            "deleted": True,
            "recoverable_from": str(trash_path.relative_to(self.resources_dir)),
        }

    def _load_optional_store(self, path: Path) -> InformationStore:
        return (
            self.information_repository.load(path)
            if self.information_repository.exists(path)
            else InformationStore()
        )

    def _delete_courses(self, course_ids: list[str]) -> dict[str, Any]:
        path = self.resources_dir / "information.json"
        with self.mutation_lock:
            try:
                store = self._load_optional_store(path)
                records = {value.course_id: value for value in store.courses}
                archives = {
                    index.archive.course.course_id: index
                    for index in self.change_repository.load_archives(self.resources_dir)
                }
                used_archives: set[str] = set()
                archive_paths: list[tuple[Path, str]] = []
                planned_paths: set[Path] = set()
                for course_id in course_ids:
                    record = records.get(course_id)
                    matched_archive = (
                        matching_archive(record, archives, used_archives)
                        if record is not None
                        else archives.get(course_id)
                    )
                    moodle_course_id = (
                        matched_archive.archive.course.course_id
                        if matched_archive is not None
                        else record.moodle_course_id
                        if record is not None and record.moodle_course_id
                        else course_id
                    )
                    archive_path = self.resources_dir / "courses" / moodle_course_id
                    if record is None and not archive_path.is_dir():
                        raise HIQSPortError(f"课程不存在：{course_id}")
                    if archive_path not in planned_paths:
                        archive_paths.append((archive_path, moodle_course_id))
                        planned_paths.add(archive_path)
                selected_ids = set(course_ids)
                removed_items = [item for item in store.items if item.course_id in selected_ids]
                updated = InformationStore(
                    timezone=store.timezone,
                    updated_at=datetime.now(UTC),
                    updated_by="manual",
                    courses=[value for value in store.courses if value.course_id not in selected_ids],
                    items=[item for item in store.items if item.course_id not in selected_ids],
                )
                moved_archives: list[tuple[Path, Path]] = []
                try:
                    for archive_path, moodle_course_id in archive_paths:
                        if not archive_path.is_dir():
                            continue
                        trash_root = self.resources_dir / ".trash" / "courses"
                        trash_root.mkdir(parents=True, exist_ok=True)
                        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
                        target = trash_root / f"{stamp}-{moodle_course_id}"
                        suffix = 1
                        while target.exists():
                            target = trash_root / f"{stamp}-{moodle_course_id}-{suffix}"
                            suffix += 1
                        archive_path.replace(target)
                        moved_archives.append((archive_path, target))
                    self.information_repository.save(path, updated)
                except Exception:
                    for archive_path, trash_target in reversed(moved_archives):
                        if trash_target.exists() and not archive_path.exists():
                            archive_path.parent.mkdir(parents=True, exist_ok=True)
                            trash_target.replace(archive_path)
                    raise
            except HIQSPortError:
                raise
            except (OSError, ValueError, ValidationError) as exc:
                raise HIQSPortError(
                    f"删除课程失败：{type(exc).__name__}: {str(exc)[:300]}"
                ) from exc
        return {
            "deleted_item_count": len(removed_items),
            "files_moved_to_trash": len(moved_archives),
        }


def matching_archive(
    record: CourseRecord,
    archives: dict[str, ArchiveIndex],
    already_matched: set[str],
) -> ArchiveIndex | None:
    explicit_id = record.moodle_course_id or record.course_id
    if explicit_id in archives and explicit_id not in already_matched:
        return archives[explicit_id]
    code = record.code.casefold()
    candidates = [
        index
        for course_id, index in archives.items()
        if course_id not in already_matched and code in index.archive.course.title.casefold()
    ]
    return candidates[0] if len(candidates) == 1 else None


def is_user_created_item(item: dict[str, Any]) -> bool:
    return any(
        source.get("source_type") == "manual"
        and source.get("title") == USER_EVENT_SOURCE_TITLE
        for source in item.get("sources") or []
        if isinstance(source, dict)
    )


def _optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


__all__ = ["CourseRecordService", "is_user_created_item", "matching_archive"]
