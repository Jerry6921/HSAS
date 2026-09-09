"""Serve the local HIQS calendar, course overview, and Moodle controls."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any, Callable
from urllib.parse import parse_qs, quote, urlparse
import webbrowser
from uuid import uuid4

from pydantic import ValidationError

from hsas.application.synchronize_courses import CourseSynchronizationService
from hsas.application.synchronize_unified_courses import UnifiedCourseSyncService
from hsas.domain.information.generate_calendar import build_ics
from hsas.application.synchronize_class_planner import (
    ClassPlannerSynchronizationService,
)
from hsas.application.synchronize_course_information import (
    SisCourseInfoSynchronizationService,
)
from hsas.application.manage_changes import collect_pending_changes
from hsas.application.manage_inbox import (
    PersonalInboxError,
    apply_personal_inbox_entry,
    personal_inbox_snapshot,
)
from hsas.infrastructure.documents.run_ocr import (
    collect_ocr_queue,
    ocr_capabilities,
    run_ocr_queue,
)
from hsas.infrastructure.manage_browser_session import BrowserSessionBroker
from hsas.infrastructure.class_planner import (
    ClassPlannerBrowserGateway,
    class_planner_status,
)
from hsas.infrastructure.fetch_sis_enrollment import SisEnrollmentBrowserGateway
from hsas.infrastructure.manage_sis_enrollment import collect_sis_enrollment_changes
from hsas.infrastructure.sis_course_info import (
    SisCourseInfoBrowserGateway,
    sis_course_info_status,
)
from hsas.infrastructure.sis_course_info.manage_changes import (
    collect_sis_course_info_changes,
)
from hsas.domain.courses import ArchiveIndex, PendingChangeBatch, iter_activities, iter_files
from hsas.domain.courses.define_change_queue import CourseReview
from hsas.domain.information import CourseRecord, InformationStore
from hsas.infrastructure.moodle.load_settings import Settings
from hsas.infrastructure.moodle.record_session import load_moodle_session_status
from hsas.infrastructure.moodle.synchronize_courses import MoodleCourseGateway
from hsas.infrastructure.runtime import hku_portal_profile_dir
from hsas.infrastructure.storage import (
    JsonChangeQueueRepository,
    JsonInformationRepository,
    JsonPersonalInboxRepository,
)
from hsas.infrastructure.storage.persist_data import read_json


ASSET_ROOT = Path(__file__).with_name("web")
ALLOWED_ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/assets/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/assets/ripple.js": ("ripple.js", "text/javascript; charset=utf-8"),
    "/assets/canvas-effects.js": ("canvas-effects.js", "text/javascript; charset=utf-8"),
    "/assets/app.js": ("app.js", "text/javascript; charset=utf-8"),
}
INFORMATION_REPOSITORY = JsonInformationRepository()
CHANGE_REPOSITORY = JsonChangeQueueRepository()
INBOX_REPOSITORY = JsonPersonalInboxRepository()
MAX_REQUEST_BYTES = 16 * 1024


class _WorkflowCancelled(RuntimeError):
    pass


def _workflow_stage_label(stage: str) -> str:
    return {
        "enrollment": "课程列表获取",
        "moodle": "Moodle 课程资料",
        "sis_course_info": "SIS 课程信息",
        "timetable": "官方课表",
    }.get(stage, stage)


def _sis_enrollment_gateway(resources_dir: Path) -> SisEnrollmentBrowserGateway:
    return SisEnrollmentBrowserGateway(resources_dir)


class DashboardError(RuntimeError):
    """Safe, user-facing dashboard read failure."""


@dataclass(slots=True)
class DashboardService:
    resources_dir: Path
    mutation_lock: Lock = field(default_factory=Lock, repr=False)
    sync_job_lock: Lock = field(default_factory=Lock, repr=False)
    sync_cancel_event: Event = field(default_factory=Event, repr=False)
    sync_thread: Thread | None = field(default=None, repr=False)
    sync_job: dict[str, Any] = field(
        default_factory=lambda: {
            "job_id": None,
            "state": "idle",
            "stage": None,
            "detail": None,
            "completed": 0,
            "total": 0,
            "cancel_requested": False,
            "result": None,
            "error": None,
            "cards": [],
            "phase_summaries": {},
        },
        repr=False,
    )

    def information_snapshot(self) -> dict[str, Any]:
        """Return the validated AI-authored database used by the calendar UI."""
        path = self.resources_dir / "information.json"
        if not INFORMATION_REPOSITORY.exists(path):
            store = InformationStore()
            pending = self._pending_batch(None)
            courses = self._dashboard_courses(store, pending)
            try:
                inbox = personal_inbox_snapshot(
                    self.resources_dir,
                    information=store,
                    inbox_repository=INBOX_REPOSITORY,
                    information_repository=INFORMATION_REPOSITORY,
                )
            except PersonalInboxError as exc:
                raise DashboardError(str(exc)) from exc
            return {
                "available": False,
                "schema_version": "1.0",
                "timezone": "Asia/Hong_Kong",
                "updated_at": None,
                "updated_by": None,
                "courses": courses,
                "items": [],
                "summary": {
                    "course_count": len(courses),
                    "item_count": 0,
                    "calendar_item_count": 0,
                    "unknown_date_count": 0,
                },
                "pending_review": _pending_summary(pending),
                "material_status": self._material_status(store, pending),
                "personal_inbox": inbox,
                "sis_enrollment": self._sis_enrollment_status(),
                "class_planner": self._class_planner_status(),
                "sis_course_info": self._sis_course_info_status(),
                "moodle_session": load_moodle_session_status(self.resources_dir),
                "updates": _pending_updates(pending),
                "warnings": [
                    "information.json 尚未建立。请让 AI 阅读本地课程资料并生成更新。"
                ],
            }
        try:
            store = INFORMATION_REPOSITORY.load(path)
        except (OSError, ValueError, ValidationError) as exc:
            raise DashboardError(
                f"information.json 无法通过模型校验：{type(exc).__name__}"
            ) from exc
        calendar_count = sum(
            item.starts_at is not None
            or item.opens_at is not None
            or item.due_at is not None
            or item.due_on is not None
            or item.scheduled_on is not None
            or item.recurrence is not None
            for item in store.items
        )
        payload = store.model_dump(mode="json")
        pending = self._pending_batch(store)
        courses = self._dashboard_courses(store, pending)
        try:
            inbox = personal_inbox_snapshot(
                self.resources_dir,
                information=store,
                inbox_repository=INBOX_REPOSITORY,
                information_repository=INFORMATION_REPOSITORY,
            )
        except PersonalInboxError as exc:
            raise DashboardError(str(exc)) from exc
        return {
            "available": True,
            **payload,
            "courses": courses,
            "summary": {
                "course_count": len(courses),
                "item_count": len(store.items),
                "calendar_item_count": calendar_count,
                "unknown_date_count": sum(
                    item.date_status == "unknown" for item in store.items
                ),
            },
            "pending_review": _pending_summary(pending),
            "material_status": self._material_status(store, pending),
            "personal_inbox": inbox,
            "sis_enrollment": self._sis_enrollment_status(),
            "class_planner": self._class_planner_status(),
            "sis_course_info": self._sis_course_info_status(),
            "moodle_session": load_moodle_session_status(self.resources_dir),
            "updates": _pending_updates(pending),
            "warnings": [],
        }

    def _sis_enrollment_status(self) -> dict[str, Any]:
        try:
            value = _sis_enrollment_gateway(self.resources_dir).status()
            value["review"] = collect_sis_enrollment_changes(self.resources_dir)
            return value
        except (OSError, ValueError) as exc:
            return {
                "available": False,
                "course_count": 0,
                "term": None,
                "login_status": "unknown",
                "review": {"pending_change_count": 0, "changes": []},
                "error": f"{type(exc).__name__}: {str(exc)[:200]}",
            }

    def _class_planner_status(self) -> dict[str, Any]:
        try:
            return class_planner_status(self.resources_dir)
        except (OSError, ValueError) as exc:
            return {
                "available": False,
                "synced_at": None,
                "course_count": 0,
                "meeting_count": 0,
                "term_ids": [],
                "changes": {},
                "error": f"{type(exc).__name__}: {str(exc)[:200]}",
            }

    def _sis_course_info_status(self) -> dict[str, Any]:
        try:
            value = sis_course_info_status(self.resources_dir)
            value["review"] = collect_sis_course_info_changes(self.resources_dir)
            return value
        except (OSError, ValueError) as exc:
            return {
                "available": False,
                "synced_at": None,
                "course_count": 0,
                "changed_course_count": 0,
                "failure_count": 0,
                "login_status": "unknown",
                "review": {"pending_change_count": 0, "changes": []},
                "error": f"{type(exc).__name__}: {str(exc)[:200]}",
            }

    def calendar_ics(self) -> bytes:
        path = self.resources_dir / "information.json"
        if not INFORMATION_REPOSITORY.exists(path):
            raise DashboardError("information.json 尚未建立。")
        try:
            return build_ics(INFORMATION_REPOSITORY.load(path)).encode("utf-8")
        except (OSError, ValueError, ValidationError) as exc:
            raise DashboardError(f"日历导出失败：{type(exc).__name__}") from exc

    def add_course(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Add one manually defined course to the canonical information store."""
        if payload.get("confirmed") is not True:
            raise DashboardError("请先确认添加课程。")
        raw_course = payload.get("course")
        if not isinstance(raw_course, dict):
            raise DashboardError("course 必须是有效的课程 object。")
        try:
            course = CourseRecord.model_validate(raw_course)
        except ValidationError as exc:
            raise DashboardError(f"课程资料无法通过校验：{exc}") from exc
        path = self.resources_dir / "information.json"
        with self.mutation_lock:
            try:
                store = (
                    INFORMATION_REPOSITORY.load(path)
                    if INFORMATION_REPOSITORY.exists(path)
                    else InformationStore()
                )
                if any(value.course_id == course.course_id for value in store.courses):
                    raise DashboardError(f"课程 ID 已存在：{course.course_id}")
                updated = InformationStore(
                    timezone=store.timezone,
                    updated_at=datetime.now(UTC),
                    updated_by="manual",
                    courses=[*store.courses, course],
                    items=store.items,
                )
                INFORMATION_REPOSITORY.save(path, updated)
            except DashboardError:
                raise
            except (OSError, ValueError, ValidationError) as exc:
                raise DashboardError(
                    f"添加课程失败：{type(exc).__name__}: {str(exc)[:300]}"
                ) from exc
        return {"course_id": course.course_id, "created": True}

    def delete_course(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Remove a course, its items, and its active local Moodle archive."""
        course_id = payload.get("course_id")
        if not isinstance(course_id, str) or not course_id.strip():
            raise DashboardError("course_id 必须是有效的课程 ID。")
        if payload.get("confirmed") is not True or payload.get("confirmation") != course_id:
            raise DashboardError("课程删除确认与目标课程不一致。")
        result = self._delete_courses([course_id])
        return {
            "course_id": course_id,
            "deleted": True,
            "deleted_item_count": result["deleted_item_count"],
            "files_moved_to_trash": bool(result["files_moved_to_trash"]),
        }

    def delete_courses(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Atomically remove selected courses and their related local data."""
        raw_ids = payload.get("course_ids")
        if not isinstance(raw_ids, list) or not raw_ids:
            raise DashboardError("course_ids 必须包含至少一个课程 ID。")
        if any(not isinstance(value, str) or not value.strip() for value in raw_ids):
            raise DashboardError("course_ids 包含无效的课程 ID。")
        course_ids = list(dict.fromkeys(value.strip() for value in raw_ids))
        if payload.get("confirmed") is not True or payload.get("confirmation") != course_ids:
            raise DashboardError("课程批量删除确认与目标课程不一致。")
        result = self._delete_courses(course_ids)
        return {
            "course_ids": course_ids,
            "deleted": True,
            "deleted_course_count": len(course_ids),
            **result,
        }

    def _delete_courses(self, course_ids: list[str]) -> dict[str, Any]:
        path = self.resources_dir / "information.json"
        with self.mutation_lock:
            try:
                store = (
                    INFORMATION_REPOSITORY.load(path)
                    if INFORMATION_REPOSITORY.exists(path)
                    else InformationStore()
                )
                records = {value.course_id: value for value in store.courses}
                archives = {
                    index.archive.course.course_id: index
                    for index in CHANGE_REPOSITORY.load_archives(self.resources_dir)
                }
                used_archives: set[str] = set()
                archive_paths: list[tuple[Path, str]] = []
                planned_paths: set[Path] = set()
                for course_id in course_ids:
                    record = records.get(course_id)
                    matched_archive = (
                        _matching_archive(record, archives, used_archives)
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
                        raise DashboardError(f"课程不存在：{course_id}")
                    if archive_path not in planned_paths:
                        archive_paths.append((archive_path, moodle_course_id))
                        planned_paths.add(archive_path)
                selected_ids = set(course_ids)
                removed_items = [item for item in store.items if item.course_id in selected_ids]
                kept_courses = [value for value in store.courses if value.course_id not in selected_ids]
                kept_items = [item for item in store.items if item.course_id not in selected_ids]
                updated = InformationStore(
                    timezone=store.timezone,
                    updated_at=datetime.now(UTC),
                    updated_by="manual",
                    courses=kept_courses,
                    items=kept_items,
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
                    INFORMATION_REPOSITORY.save(path, updated)
                except Exception:
                    for archive_path, trash_target in reversed(moved_archives):
                        if trash_target.exists() and not archive_path.exists():
                            archive_path.parent.mkdir(parents=True, exist_ok=True)
                            trash_target.replace(archive_path)
                    raise
            except DashboardError:
                raise
            except (OSError, ValueError, ValidationError) as exc:
                raise DashboardError(
                    f"删除课程失败：{type(exc).__name__}: {str(exc)[:300]}"
                ) from exc
        return {
            "deleted_item_count": len(removed_items),
            "files_moved_to_trash": len(moved_archives),
        }

    def verify_moodle_session(self) -> dict[str, Any]:
        """Verify the saved Moodle browser session without changing course data."""
        if not self.mutation_lock.acquire(blocking=False):
            return {
                **load_moodle_session_status(self.resources_dir),
                "verification_deferred": True,
            }
        try:
            result = _course_service(self.resources_dir).check_login_status()
        except Exception as exc:
            return {
                **load_moodle_session_status(self.resources_dir),
                "error": f"{type(exc).__name__}: {str(exc)[:300]}",
            }
        finally:
            self.mutation_lock.release()
        return {
            **load_moodle_session_status(self.resources_dir),
            "error": result.error,
            "verification_deferred": False,
        }

    def _dashboard_courses(
        self,
        store: InformationStore,
        pending: PendingChangeBatch,
    ) -> list[dict[str, Any]]:
        archives = {
            index.archive.course.course_id: index
            for index in CHANGE_REPOSITORY.load_archives(self.resources_dir)
        }
        pending_by_course = {review.course_id: review for review in pending.courses}
        entries = []
        matched_archive_ids: set[str] = set()
        for record in store.courses:
            index = _matching_archive(record, archives, matched_archive_ids)
            if index is not None:
                matched_archive_ids.add(index.archive.course.course_id)
            entries.append((record.course_id, record, index))
        entries.extend(
            (course_id, None, index)
            for course_id, index in archives.items()
            if course_id not in matched_archive_ids
        )
        result: list[dict[str, Any]] = []
        for course_id, record, index in entries:
            archive = index.archive if index else None
            if record is not None:
                value = record.model_dump(mode="json")
            else:
                assert archive is not None
                value = {
                    "course_id": course_id,
                    "code": archive.course.title,
                    "title": archive.course.title,
                    "moodle_course_id": course_id,
                    "semester": None,
                    "color": _course_color(course_id),
                    "overview": None,
                    "objectives": [],
                    "instructors": [],
                    "links": [],
                    "policies": [],
                    "notes": [],
                    "sources": [],
                }
            weighted = [
                item
                for item in store.items
                if item.course_id == course_id and item.weight_percent is not None
            ]
            value["grade_distribution"] = [
                {
                    "item_id": item.item_id,
                    "title": item.title,
                    "category": item.category,
                    "weight_percent": item.weight_percent,
                }
                for item in weighted
            ]
            value["materials"] = _course_materials(
                self.resources_dir,
                index,
                pending_by_course.get(archive.course.course_id) if archive else None,
            )
            value["moodle"] = (
                {
                    "url": str(archive.course.url),
                    "collected_at": archive.collected_at.isoformat(),
                    "activity_count": archive.stats.activity_count,
                    "downloaded_file_count": archive.stats.downloaded_file_count,
                    "failed_download_count": archive.stats.failed_download_count,
                }
                if archive
                else None
            )
            result.append(value)
        return result

    def _material_status(
        self,
        store: InformationStore,
        pending: PendingChangeBatch,
    ) -> dict[str, Any]:
        ocr_queue = collect_ocr_queue(self.resources_dir)
        google_authorization = []
        for index in CHANGE_REPOSITORY.load_archives(self.resources_dir):
            for activity in iter_activities(index.archive):
                source_url = str(activity.url) if activity.url else ""
                error = activity.download_error or ""
                if activity.download_status != "external":
                    continue
                if "docs.google.com" not in source_url and "google workspace" not in error.casefold():
                    continue
                google_authorization.append(
                    {
                        "course_id": index.archive.course.course_id,
                        "course_title": index.archive.course.title,
                        "activity_id": activity.module_id,
                        "title": activity.name,
                        "url": source_url or None,
                        "message": error or "Google Workspace access is required",
                    }
                )
        date_unknown = [
            {
                "item_id": item.item_id,
                "course_id": item.course_id,
                "title": item.title,
            }
            for item in store.items
            if item.date_status == "unknown"
        ]
        conflict_markers = ("conflict", "disagree", "inconsistent", "冲突", "不一致")
        source_conflicts = [
            {
                "item_id": item.item_id,
                "course_id": item.course_id,
                "title": item.title,
                "warnings": item.warnings,
            }
            for item in store.items
            if any(
                marker in warning.casefold()
                for warning in item.warnings
                for marker in conflict_markers
            )
        ]
        try:
            sis_pending = collect_sis_course_info_changes(self.resources_dir)[
                "pending_change_count"
            ]
        except (OSError, ValueError):
            sis_pending = 0
        try:
            enrollment_pending = collect_sis_enrollment_changes(self.resources_dir)[
                "pending_change_count"
            ]
        except (OSError, ValueError):
            enrollment_pending = 0
        counts = {
            "ai_review": pending.pending_change_count + sis_pending + enrollment_pending,
            "ocr": len(ocr_queue),
            "google_authorization": len(google_authorization),
            "date_unknown": len(date_unknown),
            "source_conflicts": len(source_conflicts),
        }
        return {
            "counts": counts,
            "ocr": {"capabilities": ocr_capabilities(), "queue": ocr_queue},
            "google_authorization": google_authorization,
            "date_unknown": date_unknown,
            "source_conflicts": source_conflicts,
        }

    def process_ocr_queue(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Run OCR locally for all currently queued local documents."""
        if payload.get("confirmed") is not True:
            raise DashboardError("请先确认开始本地批量 OCR。")
        with self.mutation_lock:
            try:
                return run_ocr_queue(self.resources_dir)
            except (OSError, ValueError) as exc:
                raise DashboardError(f"OCR 处理失败：{type(exc).__name__}: {str(exc)[:300]}") from exc

    def apply_personal_inbox(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Apply one explicitly confirmed personal-information draft."""
        if payload.get("confirmed") is not True:
            raise DashboardError("请先确认写入个人补充信息。")
        entry_id = payload.get("entry_id")
        if not isinstance(entry_id, str) or not entry_id.strip():
            raise DashboardError("entry_id 必须是有效的 Inbox 条目 ID。")
        with self.mutation_lock:
            try:
                result = apply_personal_inbox_entry(
                    self.resources_dir,
                    entry_id.strip(),
                    confirmed=True,
                    inbox_repository=INBOX_REPOSITORY,
                    information_repository=INFORMATION_REPOSITORY,
                )
            except (OSError, ValueError, PersonalInboxError) as exc:
                raise DashboardError(str(exc)) from exc
        return {
            "entry_id": entry_id.strip(),
            "created_courses": result.created_courses,
            "updated_courses": result.updated_courses,
            "created_items": result.created_items,
            "updated_items": result.updated_items,
        }

    def material_file(self, relative_path: str) -> tuple[Path, str]:
        """Resolve only a file referenced by the latest validated course snapshots."""
        allowed = {
            value["original_relative_path"]
            for value in _source_inventory(self.resources_dir).values()
        }
        if relative_path not in allowed:
            raise DashboardError("该文件不在当前课程快照中。")
        resources = self.resources_dir.resolve()
        path = (resources / relative_path).resolve()
        if not path.is_relative_to(resources) or not path.is_file():
            raise DashboardError("本地课件不存在或路径无效。")
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return path, content_type

    def source_preview(
        self,
        relative_path: str,
        page_numbers: list[int] | None = None,
    ) -> dict[str, Any]:
        """Return a bounded preview for a source in the current Moodle archive."""
        source = _source_inventory(self.resources_dir).get(relative_path)
        if source is None:
            raise DashboardError("该来源不在当前课程快照中。")
        text_path = source.get("text_relative_path")
        preview_text = ""
        truncated = False
        if text_path:
            resolved = _safe_resource_file(self.resources_dir, text_path)
            raw_text = resolved.read_text(encoding="utf-8", errors="replace")
            preview_text = _select_source_units(raw_text, page_numbers or [])
            if len(preview_text) > 30000:
                preview_text = preview_text[:30000].rstrip() + "\n\n…预览已截断"
                truncated = True
        content_type = source.get("content_type") or "application/octet-stream"
        preview_kind = (
            "pdf"
            if content_type == "application/pdf"
            else "image"
            if content_type.startswith("image/")
            else "text"
        )
        return {
            "title": source["title"],
            "relative_path": relative_path,
            "original_relative_path": source["original_relative_path"],
            "content_type": content_type,
            "preview_kind": preview_kind,
            "text": preview_text,
            "truncated": truncated,
            "page_numbers": page_numbers or [],
        }

    def _pending_review_summary(self, information) -> dict[str, int]:
        return _pending_summary(self._pending_batch(information))

    def _pending_batch(
        self,
        information: InformationStore | None,
    ) -> PendingChangeBatch:
        try:
            return collect_pending_changes(
                self.resources_dir,
                CHANGE_REPOSITORY,
                information=information,
            )
        except (OSError, ValueError, ValidationError) as exc:
            raise DashboardError(
                f"待处理 Moodle 变化无法读取：{type(exc).__name__}"
            ) from exc

    def login_moodle(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Open a visible browser and wait for the user to complete SSO/MFA."""
        if payload.get("confirmed") is not True:
            raise DashboardError("请先确认打开 Moodle 登录窗口。")
        with self.mutation_lock:
            try:
                result = _course_service(self.resources_dir).login_until_ready()
            except Exception as exc:
                raise DashboardError(
                    f"Moodle 登录未完成：{type(exc).__name__}: {str(exc)[:300]}"
                ) from exc
        return {
            "status": result.status,
            "checked_at": result.checked_at,
            "available_course_count": result.available_course_count,
            "error": result.error,
        }

    def synchronize_courses(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Synchronize all courses or one explicitly selected Moodle course."""
        if payload.get("confirmed") is not True:
            raise DashboardError("请先确认开始同步 Moodle 课程资料。")
        course = payload.get("course")
        if course is not None and (not isinstance(course, str) or not course.strip()):
            raise DashboardError("course 必须是 Moodle course ID 或同源 URL。")
        course = course.strip() if isinstance(course, str) else None
        with self.mutation_lock:
            try:
                service = _course_service(self.resources_dir)
                if course:
                    result = service.sync_course(course)
                    return {
                        "scope": "single",
                        "discovered_course_count": 1,
                        "succeeded_course_count": 1,
                        "failed_course_count": 0,
                        "course_id": result.course_id,
                        "report_path": str(result.output_path),
                        "pending_review": self._pending_review_summary(
                            _load_information_if_available(self.resources_dir)
                        ),
                    }
                result = service.sync_all()
            except Exception as exc:
                raise DashboardError(
                    f"Moodle 同步失败，上一份有效资料已保留："
                    f"{type(exc).__name__}: {str(exc)[:300]}"
                ) from exc
        return {
            "scope": "all",
            "discovered_course_count": result.discovered_course_count,
            "succeeded_course_count": len(result.succeeded_course_ids),
            "failed_course_count": len(result.failures),
            "course_id": None,
            "report_path": str(result.report_path),
            "pending_review": self._pending_review_summary(
                _load_information_if_available(self.resources_dir)
            ),
        }

    def start_course_sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Start the cancellable multi-source course synchronization workflow."""
        if payload.get("confirmed") is not True:
            raise DashboardError("请先确认开始课程同步工作流。")
        with self.sync_job_lock:
            if self.sync_thread is not None and self.sync_thread.is_alive():
                raise DashboardError("已有课程同步工作流正在进行。")
            job_id = uuid4().hex
            self.sync_cancel_event = Event()
            self.sync_job = {
                "job_id": job_id,
                "state": "running",
                "stage": "starting",
                "detail": "正在启动课程同步工作流",
                "completed": 0,
                "total": 0,
                "cancel_requested": False,
                "result": None,
                "error": None,
                "cards": [],
                "phase_summaries": {},
            }
            self.sync_thread = Thread(
                target=self._run_course_sync_job,
                args=(job_id,),
                name=f"hiqs-sync-{job_id[:8]}",
                daemon=True,
            )
            self.sync_thread.start()
            return dict(self.sync_job)

    def course_sync_status(self) -> dict[str, Any]:
        with self.sync_job_lock:
            return dict(self.sync_job)

    def cancel_course_sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("confirmed") is not True:
            raise DashboardError("请先确认取消课程同步工作流。")
        with self.sync_job_lock:
            if self.sync_job.get("state") != "running":
                raise DashboardError("当前没有正在运行的课程同步工作流。")
            self.sync_cancel_event.set()
            self.sync_job["cancel_requested"] = True
            self.sync_job["detail"] = "正在取消"
            return dict(self.sync_job)

    def _run_course_sync_job(self, job_id: str) -> None:
        def report(values: dict[str, object]) -> None:
            with self.sync_job_lock:
                if self.sync_job.get("job_id") == job_id:
                    if self.sync_cancel_event.is_set():
                        values = {**values, "detail": "正在取消"}
                    self.sync_job.update(values)

        def begin_phase(stage: str, courses: list[dict[str, str]]) -> None:
            report(
                {
                    "stage": stage,
                    "detail": _workflow_stage_label(stage),
                    "completed": 0,
                    "total": len(courses),
                    "cards": [
                        {
                            "key": f"{stage}:{course['course_code']}",
                            "stage": stage,
                            "course_code": course["course_code"],
                            "title": course.get("title") or course["course_code"],
                            "state": "pending",
                            "detail": "等待处理",
                        }
                        for course in courses
                    ],
                }
            )

        def update_card(
            stage: str,
            course_code: str,
            state: str,
            detail: str,
            *,
            completed: int,
            failed: int,
            total: int,
        ) -> None:
            with self.sync_job_lock:
                if self.sync_job.get("job_id") != job_id:
                    return
                cards = [
                    dict(card)
                    for card in self.sync_job.get("cards", [])
                    if not (card.get("stage") == stage and card.get("course_code") == course_code)
                ]
                if state != "completed":
                    cards.append(
                        {
                            "key": f"{stage}:{course_code}",
                            "stage": stage,
                            "course_code": course_code,
                            "title": next(
                                (
                                    card.get("title")
                                    for card in self.sync_job.get("cards", [])
                                    if card.get("stage") == stage
                                    and card.get("course_code") == course_code
                                ),
                                course_code,
                            ),
                            "state": state,
                            "detail": detail,
                        }
                    )
                summaries = dict(self.sync_job.get("phase_summaries", {}))
                summaries[stage] = {
                    "completed": completed,
                    "failed": failed,
                    "total": total,
                }
                self.sync_job.update(
                    cards=cards,
                    completed=completed,
                    total=total,
                    phase_summaries=summaries,
                    detail=f"{_workflow_stage_label(stage)} · {completed}/{total} 已完成",
                )

        def complete_phase(
            stage: str,
            *,
            completed: int,
            failed: int,
            total: int,
            detail: str,
        ) -> None:
            with self.sync_job_lock:
                if self.sync_job.get("job_id") != job_id:
                    return
                summaries = dict(self.sync_job.get("phase_summaries", {}))
                summaries[stage] = {
                    "completed": completed,
                    "failed": failed,
                    "total": total,
                }
                self.sync_job.update(
                    stage=stage,
                    cards=[],
                    completed=completed,
                    total=total,
                    phase_summaries=summaries,
                    detail=detail,
                )

        try:
            with self.mutation_lock:
                report(
                    {
                        "stage": "authentication",
                        "detail": "正在打开 HKU Portal，请完成一次登录",
                        "completed": 0,
                        "total": 1,
                        "cards": [],
                    }
                )
                planner_service = _class_planner_service(self.resources_dir)
                planner_service.login_until_ready()
                if self.sync_cancel_event.is_set():
                    raise _WorkflowCancelled

                moodle_service = _course_service(self.resources_dir)
                report(
                    {
                        "detail": "正在用共享 HKU 会话连接 Moodle 与 SIS",
                    }
                )
                moodle_status = moodle_service.check_login_status()
                if moodle_status.status != "logged_in":
                    moodle_service.login_until_ready()
                if self.sync_cancel_event.is_set():
                    raise _WorkflowCancelled

                report(
                    {
                        "stage": "authentication",
                        "detail": "正在确认 SIS 会话并读取当前学期课程列表",
                    }
                )
                enrollment = _sis_enrollment_gateway(self.resources_dir).sync(auto_login=True)
                courses = list(enrollment["courses"])
                begin_phase("enrollment", courses)
                for index, course in enumerate(courses, start=1):
                    update_card(
                        "enrollment",
                        course["course_code"],
                        "completed",
                        "已确认当前学期注册",
                        completed=index,
                        failed=0,
                        total=len(courses),
                    )
                if self.sync_cancel_event.is_set():
                    raise _WorkflowCancelled

                if self.sync_cancel_event.is_set():
                    raise _WorkflowCancelled
                source_progress_lock = Lock()
                source_progress = {
                    "moodle": {"processed": 0, "completed": 0, "failed": 0, "total": len(courses)},
                    "sis_course_info": {"processed": 0, "completed": 0, "failed": 0, "total": len(courses)},
                    "timetable": {"processed": 0, "completed": 0, "failed": 0, "total": 1},
                }

                def report_source_progress(
                    stage: str,
                    *,
                    processed: int,
                    completed: int,
                    failed: int,
                    detail: str,
                ) -> None:
                    with source_progress_lock:
                        source_progress[stage].update(
                            processed=processed,
                            completed=completed,
                            failed=failed,
                        )
                        aggregate_completed = sum(
                            int(value["processed"]) for value in source_progress.values()
                        )
                        aggregate_total = sum(
                            int(value["total"]) for value in source_progress.values()
                        )
                        summaries = {
                            name: {
                                "completed": int(value["completed"]),
                                "failed": int(value["failed"]),
                                "total": int(value["total"]),
                            }
                            for name, value in source_progress.items()
                        }
                    with self.sync_job_lock:
                        if self.sync_job.get("job_id") != job_id:
                            return
                        existing = dict(self.sync_job.get("phase_summaries", {}))
                        existing.update(summaries)
                        self.sync_job.update(
                            stage="collecting",
                            detail=("正在取消" if self.sync_cancel_event.is_set() else detail),
                            completed=aggregate_completed,
                            total=aggregate_total,
                            cards=[],
                            phase_summaries=existing,
                        )

                def report_unified_progress(values: dict[str, object]) -> None:
                    stage = str(values["stage"])
                    report_source_progress(
                        stage,
                        processed=int(values.get("processed", 0)),
                        completed=int(values.get("completed", 0)),
                        failed=int(values.get("failed", 0)),
                        detail=str(values.get("detail") or _workflow_stage_label(stage)),
                    )

                report(
                    {
                        "stage": "collecting",
                        "detail": "正在并发同步 Moodle、SIS 课程信息与官方课表",
                        "completed": 0,
                        "total": len(courses) * 2 + 1,
                        "cards": [],
                    }
                )
                unified_result = asyncio.run(
                    _unified_course_sync_service(self.resources_dir).synchronize(
                        courses,
                        progress_callback=report_unified_progress,
                        cancel_requested=self.sync_cancel_event.is_set,
                    )
                )
                moodle_result, sis_result, planner_result = unified_result.values

                if self.sync_cancel_event.is_set() or any(
                    isinstance(result, _WorkflowCancelled)
                    for result in (moodle_result, sis_result, planner_result)
                ):
                    raise _WorkflowCancelled

                source_failures: list[dict[str, str]] = []
                for source, result, total in (
                    ("moodle", moodle_result, len(courses)),
                    ("sis_course_info", sis_result, len(courses)),
                    ("timetable", planner_result, 1),
                ):
                    if not isinstance(result, Exception):
                        continue
                    source_failures.append(
                        {
                            "source": source,
                            "error": f"{type(result).__name__}: {str(result)[:300]}",
                        }
                    )
                    report_source_progress(
                        source,
                        processed=total,
                        completed=0,
                        failed=total,
                        detail=f"{_workflow_stage_label(source)}需要重试",
                    )

                moodle_failures = (
                    list(moodle_result["failures"])
                    if isinstance(moodle_result, dict)
                    else []
                )
                moodle_completed = (
                    int(moodle_result["completed"])
                    if isinstance(moodle_result, dict)
                    else 0
                )
                sis_failures = (
                    list(sis_result.failures)
                    if not isinstance(sis_result, Exception)
                    else []
                )
                failed_course_count = len(moodle_failures) + len(sis_failures)
                if isinstance(moodle_result, Exception):
                    failed_course_count += len(courses)
                if isinstance(sis_result, Exception):
                    failed_course_count += len(courses)
            payload = {
                "discovered_course_count": len(courses),
                "succeeded_course_count": moodle_completed,
                "failed_course_count": failed_course_count,
                "source_failures": source_failures,
                "term": enrollment.get("term"),
                "pending_review": self._pending_review_summary(
                    _load_information_if_available(self.resources_dir)
                ),
            }
            with self.sync_job_lock:
                if self.sync_job.get("job_id") == job_id:
                    self.sync_job.update(
                        state="completed",
                        stage="finished",
                        detail=(
                            f"同步完成，{len(source_failures)} 个来源需要重试"
                            if source_failures
                            else "同步完成"
                        ),
                        result=payload,
                        cards=[],
                    )
        except _WorkflowCancelled:
            with self.sync_job_lock:
                if self.sync_job.get("job_id") == job_id:
                    self.sync_job.update(
                        state="cancelled",
                        stage="finished",
                        detail="同步已取消",
                        cards=[],
                    )
        except Exception as exc:
            with self.sync_job_lock:
                if self.sync_job.get("job_id") == job_id:
                    self.sync_job.update(
                        state="failed",
                        stage="finished",
                        detail="同步失败，上一份有效资料已保留",
                        error=f"{type(exc).__name__}: {str(exc)[:300]}",
                    )

    def login_class_planner(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Open Class Planner and wait for user-completed HKU Portal sign-in."""
        if payload.get("confirmed") is not True:
            raise DashboardError("请先确认打开 HKU Portal 登录窗口。")
        with self.mutation_lock:
            try:
                result = _class_planner_service(self.resources_dir).login_until_ready()
            except Exception as exc:
                raise DashboardError(
                    f"Class Planner 登录未完成：{type(exc).__name__}: {str(exc)[:300]}"
                ) from exc
        return {
            "status": result.status,
            "checked_at": result.checked_at,
            "course_count": result.course_count,
            "term_ids": list(result.term_ids),
            "error": result.error,
        }

    def synchronize_class_planner(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Collect the current authenticated HKU timetable snapshot."""
        if payload.get("confirmed") is not True:
            raise DashboardError("请先确认同步 HKU Class Planner 课表。")
        with self.mutation_lock:
            try:
                result = _class_planner_service(self.resources_dir).sync()
            except Exception as exc:
                raise DashboardError(
                    f"Class Planner 同步失败，上一份快照已保留："
                    f"{type(exc).__name__}: {str(exc)[:300]}"
                ) from exc
        return {
            "status": result.status,
            "synced_at": result.synced_at,
            "course_count": result.course_count,
            "meeting_count": result.meeting_count,
            "term_ids": list(result.term_ids),
            "changed": result.changed,
            "added_course_count": len(result.added_course_ids),
            "modified_course_count": len(result.modified_course_ids),
            "removed_course_count": len(result.removed_course_ids),
        }

    def login_sis_course_info(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Open HKU SIS and wait for user-completed HKU Portal sign-in."""
        if payload.get("confirmed") is not True:
            raise DashboardError("请先确认打开 HKU SIS 登录窗口。")
        with self.mutation_lock:
            try:
                result = _sis_course_info_service(self.resources_dir).login_until_ready()
            except Exception as exc:
                raise DashboardError(
                    f"HKU SIS 登录未完成：{type(exc).__name__}: {str(exc)[:300]}"
                ) from exc
        return {
            "status": result.status,
            "checked_at": result.checked_at,
            "available_course_count": result.available_course_count,
            "error": result.error,
        }

    def synchronize_sis_course_info(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Collect official pages for the codes discovered in Moodle archives."""
        if payload.get("confirmed") is not True:
            raise DashboardError("请先确认同步 HKU SIS 课程信息。")
        had_snapshot = (self.resources_dir / "sis-course-info" / "latest.json").is_file()
        with self.mutation_lock:
            try:
                result = _sis_course_info_service(self.resources_dir).sync()
            except Exception as exc:
                raise DashboardError(
                    f"HKU SIS 课程信息同步失败，"
                    f"{'上一份快照已保留' if had_snapshot else '尚未写入任何 SIS 课程信息'}："
                    f"{type(exc).__name__}: {str(exc)[:300]}"
                ) from exc
        return {
            "status": result.status,
            "synced_at": result.synced_at,
            "discovered_course_count": result.discovered_course_count,
            "succeeded_course_count": len(result.succeeded_course_codes),
            "unchanged_course_count": len(result.unchanged_course_codes),
            "skipped_course_count": len(result.skipped_course_titles),
            "failed_course_count": len(result.failures),
        }


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        service: DashboardService,
    ) -> None:
        self.dashboard_service = service
        self.dashboard_assets = _load_dashboard_assets()
        super().__init__(server_address, handler_class)


class DashboardRequestHandler(BaseHTTPRequestHandler):
    server: DashboardServer

    def do_GET(self) -> None:  # noqa: N802
        if not self._host_is_local():
            self._send_json(HTTPStatus.MISDIRECTED_REQUEST, {"error": "Invalid local host."})
            return
        path = urlparse(self.path).path
        if path == "/api/information":
            try:
                value = self.server.dashboard_service.information_snapshot()
            except DashboardError as exc:
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
                return
            self._send_json(HTTPStatus.OK, value)
            return
        if path == "/api/sync/status":
            self._send_json(
                HTTPStatus.OK,
                self.server.dashboard_service.course_sync_status(),
            )
            return
        if path == "/api/moodle/status":
            self._send_json(
                HTTPStatus.OK,
                self.server.dashboard_service.verify_moodle_session(),
            )
            return
        if path == "/api/calendar.ics":
            try:
                content = self.server.dashboard_service.calendar_ics()
            except DashboardError as exc:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
                return
            self.send_response(HTTPStatus.OK)
            self._security_headers()
            self.send_header("Content-Type", "text/calendar; charset=utf-8")
            self.send_header(
                "Content-Disposition", 'attachment; filename="HIQS-calendar.ics"'
            )
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return
        if path == "/api/material":
            relative_path = parse_qs(urlparse(self.path).query).get("path", [""])[0]
            try:
                file_path, content_type = self.server.dashboard_service.material_file(
                    relative_path
                )
            except DashboardError as exc:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
                return
            self._send_file(file_path, content_type)
            return
        if path == "/api/source-preview":
            query = parse_qs(urlparse(self.path).query)
            relative_path = query.get("path", [""])[0]
            try:
                pages = [int(value) for value in query.get("page", []) if int(value) > 0]
                value = self.server.dashboard_service.source_preview(relative_path, pages)
            except (DashboardError, ValueError) as exc:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
                return
            self._send_json(HTTPStatus.OK, value)
            return
        asset = self.server.dashboard_assets.get(path)
        if asset is None:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found."})
            return
        content, content_type = asset
        self.send_response(HTTPStatus.OK)
        self._security_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self) -> None:  # noqa: N802
        if not self._host_is_local():
            self._send_json(HTTPStatus.MISDIRECTED_REQUEST, {"error": "Invalid local host."})
            return
        path = urlparse(self.path).path
        if path not in {
            "/api/moodle/login",
            "/api/sync",
            "/api/sync/start",
            "/api/sync/cancel",
            "/api/class-planner/login",
            "/api/class-planner/sync",
            "/api/sis-course-info/login",
            "/api/sis-course-info/sync",
            "/api/ocr/run",
            "/api/inbox/apply",
            "/api/courses/add",
            "/api/courses/delete",
            "/api/courses/delete-many",
        }:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found."})
            return
        try:
            payload = self._read_json()
            if path == "/api/moodle/login":
                result = self.server.dashboard_service.login_moodle(payload)
            elif path == "/api/sync":
                result = self.server.dashboard_service.synchronize_courses(payload)
            elif path == "/api/sync/start":
                result = self.server.dashboard_service.start_course_sync(payload)
            elif path == "/api/sync/cancel":
                result = self.server.dashboard_service.cancel_course_sync(payload)
            elif path == "/api/class-planner/login":
                result = self.server.dashboard_service.login_class_planner(payload)
            elif path == "/api/class-planner/sync":
                result = self.server.dashboard_service.synchronize_class_planner(payload)
            elif path == "/api/sis-course-info/login":
                result = self.server.dashboard_service.login_sis_course_info(payload)
            elif path == "/api/sis-course-info/sync":
                result = self.server.dashboard_service.synchronize_sis_course_info(payload)
            elif path == "/api/ocr/run":
                result = self.server.dashboard_service.process_ocr_queue(payload)
            elif path == "/api/courses/add":
                result = self.server.dashboard_service.add_course(payload)
            elif path == "/api/courses/delete":
                result = self.server.dashboard_service.delete_course(payload)
            elif path == "/api/courses/delete-many":
                result = self.server.dashboard_service.delete_courses(payload)
            else:
                result = self.server.dashboard_service.apply_personal_inbox(payload)
        except DashboardError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        except Exception as exc:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": f"Unexpected local UI error: {type(exc).__name__}"},
            )
            return
        self._send_json(HTTPStatus.OK, result)

    def _read_json(self) -> dict[str, Any]:
        if self.headers.get("X-HIQS-Request") != "1":
            raise DashboardError("缺少本地请求标记。")
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip()
        if content_type != "application/json":
            raise DashboardError("Content-Type 必须是 application/json。")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise DashboardError("Content-Length 无效。") from exc
        if length <= 0 or length > MAX_REQUEST_BYTES:
            raise DashboardError("请求内容为空或过大。")
        try:
            value = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DashboardError("请求内容必须是有效 JSON。") from exc
        if not isinstance(value, dict):
            raise DashboardError("请求内容必须是 JSON object。")
        return value

    def _host_is_local(self) -> bool:
        bound_port = self.server.server_address[1]
        allowed = {f"127.0.0.1:{bound_port}", f"localhost:{bound_port}"}
        if bound_port == 80:
            allowed.update({"127.0.0.1", "localhost"})
        return self.headers.get("Host", "").lower() in allowed

    def _send_json(self, status: HTTPStatus, value: dict[str, Any]) -> None:
        content = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._security_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _send_file(self, path: Path, content_type: str) -> None:
        inline_types = {
            "application/pdf",
            "image/gif",
            "image/jpeg",
            "image/png",
            "image/webp",
            "text/plain",
        }
        disposition = "inline" if content_type in inline_types else "attachment"
        encoded_name = quote(path.name, safe="")
        self.send_response(HTTPStatus.OK)
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header(
            "Content-Security-Policy",
            "sandbox; default-src 'none'; frame-ancestors 'self'",
        )
        self.send_header("Content-Type", content_type)
        self.send_header(
            "Content-Disposition",
            f"{disposition}; filename=material; filename*=UTF-8''{encoded_name}",
        )
        self.send_header("Content-Length", str(path.stat().st_size))
        self.end_headers()
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                self.wfile.write(chunk)

    def _security_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'",
        )

    def log_message(self, format: str, *args: object) -> None:
        return


def build_dashboard_server(
    resources_dir: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> DashboardServer:
    if host != "127.0.0.1":
        raise ValueError("HIQS UI only supports the loopback host 127.0.0.1")
    if port < 0 or port > 65535:
        raise ValueError("port must be between 0 and 65535")
    return DashboardServer(
        (host, port),
        DashboardRequestHandler,
        DashboardService(resources_dir=resources_dir),
    )


def _course_service(
    resources_dir: Path,
    *,
    profile_dir: Path | None = None,
) -> CourseSynchronizationService:
    settings = Settings.load(
        output_dir=resources_dir,
        profile_dir=profile_dir or hku_portal_profile_dir(resources_dir),
    )
    return CourseSynchronizationService(MoodleCourseGateway(settings))


def _unified_course_sync_service(resources_dir: Path) -> UnifiedCourseSyncService:
    settings = Settings.load(
        output_dir=resources_dir,
        profile_dir=hku_portal_profile_dir(resources_dir),
    )
    return UnifiedCourseSyncService(
        BrowserSessionBroker(resources_dir=resources_dir, settings=settings)
    )


def _class_planner_service(
    resources_dir: Path,
    *,
    profile_dir: Path | None = None,
) -> ClassPlannerSynchronizationService:
    return ClassPlannerSynchronizationService(
        ClassPlannerBrowserGateway(resources_dir, profile_dir=profile_dir)
    )


def _sis_course_info_service(
    resources_dir: Path,
    *,
    profile_dir: Path | None = None,
) -> SisCourseInfoSynchronizationService:
    return SisCourseInfoSynchronizationService(
        SisCourseInfoBrowserGateway(resources_dir, profile_dir=profile_dir)
    )


def _load_information_if_available(resources_dir: Path):
    path = resources_dir / "information.json"
    return INFORMATION_REPOSITORY.load(path) if INFORMATION_REPOSITORY.exists(path) else None


def serve_dashboard(
    resources_dir: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
    browser_opener: Callable[[str], bool] = webbrowser.open,
) -> None:
    server = build_dashboard_server(resources_dir, host=host, port=port)
    actual_port = server.server_address[1]
    url = f"http://{host}:{actual_port}/"
    print(f"HKU Information Query System: {url}", flush=True)
    print("Local-only calendar and Moodle controls. Press Ctrl-C to stop.", flush=True)
    if open_browser:
        browser_opener(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _load_dashboard_assets() -> dict[str, tuple[bytes, str]]:
    return {
        path: ((ASSET_ROOT / filename).read_bytes(), content_type)
        for path, (filename, content_type) in ALLOWED_ASSETS.items()
    }


def _pending_summary(batch: PendingChangeBatch) -> dict[str, int]:
    return {
        "course_count": len(batch.courses),
        "change_count": batch.pending_change_count,
        "full_review_count": sum(course.mode == "full" for course in batch.courses),
    }


def _pending_updates(batch: PendingChangeBatch) -> dict[str, Any]:
    """Shape pending review data for the local update-diff view."""
    return {
        "generated_at": batch.generated_at.isoformat(),
        "courses": [
            {
                "course_id": review.course_id,
                "course_title": review.course_title,
                "mode": review.mode,
                "acknowledge_through": review.acknowledge_through.isoformat(),
                "changes": [change.model_dump(mode="json") for change in review.changes],
                "files": [
                    {
                        "filename": file.filename,
                        "relative_path": file.relative_path,
                        "text_path": file.text_path,
                        "exists": file.exists,
                        "change_action": file.change_action,
                    }
                    for file in review.files
                ],
                "affected_information_item_ids": review.affected_information_item_ids,
            }
            for review in batch.courses
        ],
    }


def _safe_resource_file(resources_dir: Path, relative_path: str) -> Path:
    resources = resources_dir.resolve()
    path = (resources / relative_path).resolve()
    if not path.is_relative_to(resources) or not path.is_file():
        raise DashboardError("本地来源不存在或路径无效。")
    return path


def _source_inventory(resources_dir: Path) -> dict[str, dict[str, Any]]:
    inventory: dict[str, dict[str, Any]] = {}
    for index in CHANGE_REPOSITORY.load_archives(resources_dir):
        course_json = (
            index.source_path.resolve().relative_to(resources_dir.resolve()).as_posix()
            if index.source_path
            else f"courses/{index.archive.course.course_id}/course.json"
        )
        if (resources_dir / course_json).is_file():
            inventory[course_json] = {
                "title": f"{index.archive.course.title} · course.json",
                "original_relative_path": course_json,
                "text_relative_path": course_json,
                "content_type": "application/json",
            }
        for _activity, stored_file in iter_files(index.archive):
            text_path = stored_file.analysis.extracted_text_path if stored_file.analysis else None
            value = {
                "title": stored_file.filename,
                "original_relative_path": stored_file.relative_path,
                "text_relative_path": text_path,
                "content_type": stored_file.content_type
                or mimetypes.guess_type(stored_file.filename)[0]
                or "application/octet-stream",
            }
            inventory[stored_file.relative_path] = value
            if text_path:
                inventory[text_path] = value
    manifest_path = resources_dir / "sis-course-info" / "latest.json"
    if manifest_path.is_file():
        manifest = read_json(manifest_path)
        for course in manifest.get("courses", []) if isinstance(manifest, dict) else []:
            if not isinstance(course, dict):
                continue
            text_path = course.get("text_relative_path")
            html_path = course.get("html_relative_path")
            if not isinstance(text_path, str) or not (resources_dir / text_path).is_file():
                continue
            value = {
                "title": f"{course.get('course_code', 'Course')} · HKU SIS Course Information",
                "original_relative_path": text_path,
                "text_relative_path": text_path,
                "content_type": "text/plain",
            }
            inventory[text_path] = value
            if isinstance(html_path, str) and (resources_dir / html_path).is_file():
                inventory[html_path] = value
    return inventory


def _select_source_units(text: str, page_numbers: list[int]) -> str:
    if not page_numbers:
        return text
    wanted = set(page_numbers)
    chunks: list[str] = []
    current: list[str] = []
    selected = False
    for line in text.splitlines():
        if line.startswith("--- ") and line.endswith(" ---"):
            if selected and current:
                chunks.append("\n".join(current))
            current = [line]
            selected = any(
                line.startswith(f"--- {label} {number} ")
                or line == f"--- {label} {number} ---"
                for label in ("Page", "Slide", "Speaker notes", "Document part")
                for number in wanted
            )
        elif selected:
            current.append(line)
    if selected and current:
        chunks.append("\n".join(current))
    return "\n\n".join(chunks) or text


def _course_color(course_id: str) -> str:
    palette = ("#2563eb", "#0f766e", "#7c3aed", "#c2410c", "#be123c", "#0369a1")
    return palette[sum(course_id.encode("utf-8")) % len(palette)]


def _matching_archive(
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
        if course_id not in already_matched
        and code in index.archive.course.title.casefold()
    ]
    return candidates[0] if len(candidates) == 1 else None


def _course_materials(
    resources: Path,
    index: ArchiveIndex | None,
    review: CourseReview | None,
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {"learning": [], "information": []}
    if index is None:
        return grouped
    changed = {
        item.relative_path: item.change_action
        for item in (review.files if review else [])
        if item.relative_path != "course.json"
    }
    archive = index.archive
    section_titles = {
        activity.module_id: section.title
        for section in archive.sections
        for activity in section.activities
    }
    section_titles.update(
        {activity.module_id: "其他" for activity in archive.unassigned_activities}
    )
    for activity in iter_activities(archive):
        if activity.files:
            for stored_file in activity.files:
                material_type = _material_type(
                    activity.name,
                    stored_file.filename,
                    activity.category,
                    section_titles.get(activity.module_id, ""),
                )
                bucket = _material_bucket(material_type)
                path = (resources / stored_file.relative_path).resolve()
                grouped[bucket].append(
                    {
                        "id": f"{activity.module_id}:{stored_file.source_url}",
                        "title": stored_file.filename,
                        "activity_name": activity.name,
                        "section_title": section_titles.get(activity.module_id),
                        "category": activity.category,
                        "material_type": material_type,
                        "relative_path": stored_file.relative_path,
                        "source_url": str(stored_file.source_url),
                        "content_type": stored_file.content_type,
                        "size_bytes": stored_file.size_bytes,
                        "downloaded_at": stored_file.downloaded_at.isoformat(),
                        "text_available": bool(
                            stored_file.analysis
                            and stored_file.analysis.extracted_text_path
                        ),
                        "text_path": (
                            stored_file.analysis.extracted_text_path
                            if stored_file.analysis
                            else None
                        ),
                        "exists": path.is_file(),
                        "change_action": changed.get(stored_file.relative_path),
                        "download_status": activity.download_status,
                        "download_error": activity.download_error,
                    }
                )
        else:
            material_type = _material_type(
                activity.name,
                "",
                activity.category,
                section_titles.get(activity.module_id, ""),
            )
            bucket = _material_bucket(material_type)
            grouped[bucket].append(
                {
                    "id": activity.module_id,
                    "title": activity.name,
                    "activity_name": activity.name,
                    "section_title": section_titles.get(activity.module_id),
                    "category": activity.category,
                    "material_type": material_type,
                    "relative_path": None,
                    "source_url": str(activity.url) if activity.url else None,
                    "content_type": None,
                    "size_bytes": None,
                    "downloaded_at": None,
                    "text_available": False,
                    "exists": False,
                    "change_action": None,
                    "download_status": activity.download_status,
                    "download_error": activity.download_error,
                }
            )
    return grouped


def _material_type(
    activity_name: str,
    filename: str,
    category: str,
    section_title: str,
) -> str:
    value = f"{activity_name} {filename} {section_title}".casefold()
    if category in {"assignment", "quiz"}:
        return "assessment"
    if category in {"announcement", "forum"}:
        return "announcement"
    rules = (
        ("exercises", ("exercise", "problem set", "worksheet", "practice", "习题", "练习")),
        ("tutorial", ("tutorial", "tut ", "workshop", "导修", "辅导课")),
        ("notes", ("note", "handout", "summary", "formula sheet", "讲义", "笔记")),
        ("lecture", ("lecture", "lect ", "slide", "课件", "课堂")),
        ("reading", ("reading", "article", "paper", "textbook", "阅读", "论文")),
        (
            "assessment",
            ("assessment", "assignment", "quiz", "exam", "project", "report", "评核", "作业", "测验", "考试"),
        ),
        (
            "course_information",
            ("introduction", "overview", "syllabus", "course outline", "grading", "schedule", "timetable", "welcome", "简介", "介绍", "课程大纲", "评分", "安排"),
        ),
        ("announcement", ("announcement", "notice", "公告", "通知")),
    )
    for material_type, markers in rules:
        if any(marker in value for marker in markers):
            return material_type
    if filename.casefold().endswith((".ppt", ".pptx")):
        return "lecture"
    return "other"


def _material_bucket(material_type: str) -> str:
    if material_type in {"assessment", "course_information", "announcement"}:
        return "information"
    return "learning"
