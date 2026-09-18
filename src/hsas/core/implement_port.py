"""Concrete CORE implementation of the public HIQS port."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
import mimetypes
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any
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
    course_identity,
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
from hsas.infrastructure.runtime import get_runtime_paths, hku_portal_profile_dir
from hsas.infrastructure.storage import (
    JsonChangeQueueRepository,
    JsonInformationRepository,
    JsonPersonalInboxRepository,
)
from hsas.infrastructure.storage.persist_data import read_json, write_json
from hsas.infrastructure.update_from_github import (
    ApplicationUpdateError,
    GitHubUpdateService,
)

from hsas.core.define_port import HIQSPort, HIQSPortError

INFORMATION_REPOSITORY = JsonInformationRepository()
CHANGE_REPOSITORY = JsonChangeQueueRepository()
INBOX_REPOSITORY = JsonPersonalInboxRepository()
PROJECT_ROOT = Path(__file__).resolve().parents[3]

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


DashboardError = HIQSPortError


@dataclass(slots=True)
class HIQSCore:
    resources_dir: Path
    update_service: GitHubUpdateService = field(
        default_factory=lambda: GitHubUpdateService(PROJECT_ROOT), repr=False
    )
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
            material_status = self._material_status(store, pending)
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
                "material_status": material_status,
                "review_closure": self._review_closure(store, pending, material_status),
                "course_reconciliation": self._course_reconciliation(store),
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
        material_status = self._material_status(store, pending)
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
            "material_status": material_status,
            "review_closure": self._review_closure(store, pending, material_status),
            "course_reconciliation": self._course_reconciliation(store),
            "personal_inbox": inbox,
            "sis_enrollment": self._sis_enrollment_status(),
            "class_planner": self._class_planner_status(),
            "sis_course_info": self._sis_course_info_status(),
            "moodle_session": load_moodle_session_status(self.resources_dir),
            "updates": _pending_updates(pending),
            "warnings": [],
        }

    def application_update_status(self) -> dict[str, object]:
        """Check the fixed public HIQS repository without mutating local files."""
        return self.update_service.status()

    def apply_application_update(self, payload: dict[str, Any]) -> dict[str, object]:
        """Fast-forward a clean source checkout and rebuild the local macOS app."""
        if payload.get("confirmed") is not True:
            raise DashboardError("请先确认更新 HIQS。")
        if self.course_sync_status().get("state") == "running":
            raise DashboardError("课程同步正在运行，请完成或取消同步后再更新。")
        with self.mutation_lock:
            try:
                return self.update_service.apply(confirmed=True)
            except ApplicationUpdateError as exc:
                raise DashboardError(str(exc)) from exc

    @staticmethod
    def _course_code(*values: object) -> str | None:
        for value in values:
            if not isinstance(value, str):
                continue
            identity = course_identity(value)
            if identity is not None:
                return identity[0]
        return None

    def _course_reconciliation(self, store: InformationStore) -> dict[str, Any]:
        """Compare current enrolment with every local source without merging facts."""
        enrollment = self._sis_enrollment_status()
        sis = self._sis_course_info_status()
        enrolled = {
            code: value
            for value in enrollment.get("courses", [])
            if isinstance(value, dict)
            and (code := self._course_code(value.get("course_code")))
        }
        moodle: dict[str, Any] = {}
        for index in CHANGE_REPOSITORY.load_archives(self.resources_dir):
            code = self._course_code(index.archive.course.title)
            if code:
                moodle[code] = index.archive
        sis_courses = {
            code: value
            for value in sis.get("courses", [])
            if isinstance(value, dict)
            and (code := self._course_code(value.get("course_code")))
        }
        planner_courses: dict[str, dict[str, Any]] = {}
        planner_path = self.resources_dir / "class-planner" / "latest.json"
        if planner_path.is_file():
            value = read_json(planner_path)
            payload = value.get("payload", {}) if isinstance(value, dict) else {}
            for row in payload.get("mainTable", []) if isinstance(payload, dict) else []:
                if not isinstance(row, dict):
                    continue
                code = self._course_code(
                    f"{row.get('SUBJECT_AREA', '')}{row.get('CATALOG_NBR', '')}",
                    row.get("COURSE_SUBCLASS"),
                )
                if code:
                    planner_courses[code] = row
        information = {
            code: course
            for course in store.courses
            if (code := self._course_code(course.code, course.title))
        }
        codes = sorted(set(enrolled) | set(moodle) | set(sis_courses) | set(planner_courses) | set(information))
        rows = []
        for code in codes:
            is_current = code in enrolled
            sources = {
                "enrollment": code in enrolled,
                "moodle": code in moodle,
                "sis_course_info": code in sis_courses,
                "class_planner": code in planner_courses,
                "information": code in information,
            }
            missing = [name for name, present in sources.items() if name != "information" and not present]
            pending_write = is_current and not sources["information"]
            legacy = not is_current and any(sources.values())
            state = "legacy" if legacy else "attention" if missing or pending_write else "complete"
            title = (
                getattr(information.get(code), "title", None)
                or (moodle[code].course.title if code in moodle else None)
                or planner_courses.get(code, {}).get("COURSE_TITLE_LONG")
                or enrolled.get(code, {}).get("title")
                or code
            )
            rows.append(
                {
                    "course_code": code,
                    "title": title,
                    "current_enrollment": is_current,
                    "state": state,
                    "sources": sources,
                    "missing_sources": missing,
                    "pending_information_write": pending_write,
                }
            )
        return {
            "rows": rows,
            "counts": {
                "total": len(rows),
                "complete": sum(row["state"] == "complete" for row in rows),
                "attention": sum(row["state"] == "attention" for row in rows),
                "legacy": sum(row["state"] == "legacy" for row in rows),
            },
            "source_labels": {
                "enrollment": "当前注册",
                "moodle": "Moodle",
                "sis_course_info": "SIS 课程信息",
                "class_planner": "官方课表",
                "information": "本地信息库",
            },
        }

    def _review_closure(
        self,
        store: InformationStore,
        pending: PendingChangeBatch,
        material_status: dict[str, Any],
    ) -> dict[str, Any]:
        counts = material_status["counts"]
        pending_total = int(counts["ai_review"]) + int(counts["ocr"]) + int(counts["google_authorization"])
        sync = self.course_sync_status()
        retry_tasks = list((sync.get("result") or {}).get("retry_tasks") or [])
        captured = any((self.resources_dir / name / "latest.json").is_file() for name in ("sis-enrollment", "sis-course-info", "class-planner")) or bool(CHANGE_REPOSITORY.load_archives(self.resources_dir))
        stages = [
            {"id": "capture", "label": "来源采集", "state": "complete" if captured else "pending"},
            {"id": "review", "label": "Agent 整理", "state": "complete" if pending_total == 0 else "pending", "count": pending_total},
            {"id": "write", "label": "校验写入", "state": "complete" if store.courses else "pending"},
            {"id": "checkpoint", "label": "Checkpoint", "state": "complete" if int(counts["ai_review"]) == 0 else "pending", "count": int(counts["ai_review"])},
        ]
        course_lines = [
            f"- {course.course_title} ({course.course_id})：{course.mode}，{len(course.files)} 个文件，{len(course.changes)} 项变更"
            for course in pending.courses
        ] or ["- 当前 Moodle 队列没有待审阅课程"]
        prompt = "\n".join(
            [
                "请处理本机 HIQS 的新增课程资料并完成信息闭环。",
                f"项目位置：{PROJECT_ROOT}",
                f"资料目录：{self.resources_dir}",
                "先完整阅读 src/AI_Skills/SKILL.md，并严格按其中的 validate、apply 与 checkpoint 流程操作。",
                "只整理待审阅或发生变化的来源；不要求 Moodle、SIS 与 Class Planner 同时提供同一事实。缺少来源不构成冲突，有可用证据即可写入；只有来源实际矛盾时才按优先级处理，并以 Moodle 资料为最高优先级。",
                "同时核对每门课程的完整 Moodle 材料清单，将每份课件写入 courses[].material_sections；栏位名称由你根据课程内容与组织方式自由归纳，不使用程序预设分类。",
                "待处理课程：",
                *course_lines,
                f"另有 SIS/注册来源待整理 {max(0, int(counts['ai_review']) - pending.pending_change_count)} 项，OCR {counts['ocr']} 项，Google 授权 {counts['google_authorization']} 项。",
                "完成写入后推进相应 checkpoint，再运行 hsas list-status，确认 information.json 可通过校验且待处理数量已经更新。",
            ]
        )
        return {
            "stages": stages,
            "pending_total": pending_total,
            "retry_tasks": retry_tasks,
            "agent_prompt": prompt,
            "complete": all(stage["state"] == "complete" for stage in stages) and not retry_tasks,
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
                record,
                course_id=value["course_id"],
                course_code=value["code"],
                course_title=value["title"],
            )
            value["agent_prompts"] = {
                "recent_lecture_materials": _recent_lecture_materials_prompt(
                    self.resources_dir,
                    course_id=value["course_id"],
                    moodle_course_id=(
                        archive.course.course_id
                        if archive
                        else value.get("moodle_course_id")
                    ),
                    course_code=value["code"],
                    course_title=value["title"],
                )
            }
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
        try:
            planner_pending = int(
                self._class_planner_status().get("review", {}).get("pending_change_count", 0)
            )
        except (OSError, ValueError, TypeError):
            planner_pending = 0
        counts = {
            "ai_review": pending.pending_change_count + sis_pending + enrollment_pending + planner_pending,
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

    def retry_failed_course_sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Retry only the source/course pairs left by the latest workflow."""
        if payload.get("confirmed") is not True:
            raise DashboardError("请先确认重试失败课程或来源。")
        with self.sync_job_lock:
            if self.sync_thread is not None and self.sync_thread.is_alive():
                raise DashboardError("已有课程同步工作流正在进行。")
            result = self.sync_job.get("result") or self._persisted_sync_result()
            retry_tasks = list((result or {}).get("retry_tasks") or [])
            if not retry_tasks:
                raise DashboardError("最近一次同步没有可重试的失败项目。")
            job_id = uuid4().hex
            self.sync_cancel_event = Event()
            self.sync_job = {
                "job_id": job_id,
                "state": "running",
                "stage": "starting",
                "detail": f"正在准备重试 {len(retry_tasks)} 个失败项目",
                "completed": 0,
                "total": len(retry_tasks),
                "cancel_requested": False,
                "result": {"retry_tasks": retry_tasks},
                "error": None,
                "cards": [],
                "phase_summaries": {},
            }
            self.sync_thread = Thread(
                target=self._run_course_sync_job,
                args=(job_id, retry_tasks),
                name=f"hiqs-retry-{job_id[:8]}",
                daemon=True,
            )
            self.sync_thread.start()
            return dict(self.sync_job)

    def course_sync_status(self) -> dict[str, Any]:
        with self.sync_job_lock:
            value = dict(self.sync_job)
            if value.get("state") == "idle":
                result = self._persisted_sync_result()
                if result:
                    value["result"] = result
            return value

    def _persisted_sync_result(self) -> dict[str, Any] | None:
        path = self.resources_dir / "sync-workflow" / "latest.json"
        if not path.is_file():
            return None
        try:
            value = read_json(path)
        except (OSError, ValueError):
            return None
        return value if isinstance(value, dict) else None

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

    def _run_course_sync_job(
        self,
        job_id: str,
        retry_tasks: list[dict[str, Any]] | None = None,
    ) -> None:
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
                try:
                    planner_service.login_until_ready(
                        cancel_requested=self.sync_cancel_event.is_set,
                    )
                except InterruptedError:
                    if self.sync_cancel_event.is_set():
                        raise _WorkflowCancelled
                    raise
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
                    try:
                        moodle_service.login_until_ready(
                            cancel_requested=self.sync_cancel_event.is_set,
                        )
                    except InterruptedError:
                        if self.sync_cancel_event.is_set():
                            raise _WorkflowCancelled
                        raise
                if self.sync_cancel_event.is_set():
                    raise _WorkflowCancelled

                if retry_tasks is None:
                    report(
                        {
                            "stage": "authentication",
                            "detail": "正在确认 SIS 会话并读取当前学期课程列表",
                        }
                    )
                    try:
                        enrollment = _sis_enrollment_gateway(self.resources_dir).sync(
                            auto_login=True,
                            cancel_requested=self.sync_cancel_event.is_set,
                        )
                    except InterruptedError:
                        if self.sync_cancel_event.is_set():
                            raise _WorkflowCancelled
                        raise
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
                else:
                    enrollment = _sis_enrollment_gateway(self.resources_dir).status()
                    courses = list(enrollment.get("courses") or [])
                    if not courses:
                        raise DashboardError("没有可用于精确重试的当前学期课程快照。")
                if self.sync_cancel_event.is_set():
                    raise _WorkflowCancelled

                if self.sync_cancel_event.is_set():
                    raise _WorkflowCancelled
                courses_by_code = {course["course_code"]: course for course in courses}
                if retry_tasks is None:
                    source_scopes: dict[str, list[dict[str, str]] | None] = {
                        "moodle": courses,
                        "sis_course_info": courses,
                        "timetable": None,
                    }
                else:
                    source_scopes = {}
                    for task in retry_tasks:
                        source = str(task.get("source") or "")
                        if source not in {"moodle", "sis_course_info", "timetable"}:
                            continue
                        if source == "timetable":
                            source_scopes[source] = None
                            continue
                        code = str(task.get("course_code") or "")
                        course = courses_by_code.get(code)
                        if course is not None:
                            source_scopes.setdefault(source, []).append(course)  # type: ignore[union-attr]
                    if not source_scopes:
                        raise DashboardError("失败清单与当前注册课程不再匹配。")
                source_progress_lock = Lock()
                source_progress = {
                    source: {
                        "processed": 0,
                        "completed": 0,
                        "failed": 0,
                        "total": 1 if source == "timetable" else len(scope or []),
                    }
                    for source, scope in source_scopes.items()
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
                sync_service = _unified_course_sync_service(self.resources_dir)
                sync_kwargs = {
                    "progress_callback": report_unified_progress,
                    "cancel_requested": self.sync_cancel_event.is_set,
                }
                if retry_tasks is None:
                    unified_result = asyncio.run(sync_service.synchronize(courses, **sync_kwargs))
                else:
                    unified_result = asyncio.run(
                        sync_service.synchronize(
                            courses,
                            source_scopes=source_scopes,
                            **sync_kwargs,
                        )
                    )
                moodle_result, sis_result, planner_result = unified_result.values

                if self.sync_cancel_event.is_set() or any(
                    isinstance(result, _WorkflowCancelled)
                    for result in (moodle_result, sis_result, planner_result)
                ):
                    raise _WorkflowCancelled

                source_failures: list[dict[str, str]] = []
                result_by_source = {
                    "moodle": moodle_result,
                    "sis_course_info": sis_result,
                    "timetable": planner_result,
                }
                retry_remaining: list[dict[str, str | None]] = []
                for source, scope in source_scopes.items():
                    result = result_by_source[source]
                    total = 1 if source == "timetable" else len(scope or [])
                    if not isinstance(result, Exception):
                        continue
                    error = f"{type(result).__name__}: {str(result)[:300]}"
                    source_failures.append(
                        {
                            "source": source,
                            "error": error,
                        }
                    )
                    if source == "timetable":
                        retry_remaining.append({"source": source, "course_code": None, "error": error})
                    else:
                        retry_remaining.extend(
                            {"source": source, "course_code": course["course_code"], "error": error}
                            for course in (scope or [])
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
                sis_failures = list(getattr(sis_result, "failures", ()) or ())
                retry_remaining.extend(
                    {"source": "moodle", "course_code": failure.get("course_code"), "error": failure.get("error", "")}
                    for failure in moodle_failures
                )
                retry_remaining.extend(
                    {"source": "sis_course_info", "course_code": failure.get("course_code"), "error": failure.get("error", "")}
                    for failure in sis_failures
                )
                failed_course_count = len(moodle_failures) + len(sis_failures)
                failed_course_count += sum(
                    1 for value in retry_remaining if value.get("course_code")
                ) - len(moodle_failures) - len(sis_failures)
            payload = {
                "discovered_course_count": len(courses),
                "succeeded_course_count": moodle_completed,
                "failed_course_count": failed_course_count,
                "source_failures": source_failures,
                "retry_tasks": retry_remaining,
                "retry_mode": retry_tasks is not None,
                "term": enrollment.get("term"),
                "pending_review": self._pending_review_summary(
                    _load_information_if_available(self.resources_dir)
                ),
            }
            write_json(self.resources_dir / "sync-workflow" / "latest.json", payload).chmod(0o600)
            with self.sync_job_lock:
                if self.sync_job.get("job_id") == job_id:
                    self.sync_job.update(
                        state="completed",
                        stage="finished",
                        detail=(
                            f"同步完成，{len(retry_remaining)} 个项目需要重试"
                            if retry_remaining
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
    record: CourseRecord | None,
    *,
    course_id: str,
    course_code: str,
    course_title: str,
) -> dict[str, Any]:
    grouped: dict[str, Any] = {
        "sections": [],
        "unclassified": [],
        "all": [],
    }
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
    materials: list[dict[str, Any]] = []
    for activity in iter_activities(archive):
        if activity.files:
            for stored_file in activity.files:
                path = (resources / stored_file.relative_path).resolve()
                material = {
                    "id": f"{activity.module_id}:{stored_file.source_url}",
                    "title": stored_file.filename,
                    "activity_name": activity.name,
                    "section_title": section_titles.get(activity.module_id),
                    "category": activity.category,
                    "material_type": None,
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
                material["agent_prompt"] = _material_summary_prompt(
                    resources,
                    material,
                    course_id=course_id,
                    course_code=course_code,
                    course_title=course_title,
                    moodle_course_id=archive.course.course_id,
                )
                materials.append(material)
        else:
            material = {
                "id": activity.module_id,
                "title": activity.name,
                "activity_name": activity.name,
                "section_title": section_titles.get(activity.module_id),
                "category": activity.category,
                "material_type": None,
                "relative_path": None,
                "source_url": str(activity.url) if activity.url else None,
                "content_type": None,
                "size_bytes": None,
                "downloaded_at": None,
                "text_available": False,
                "text_path": None,
                "exists": False,
                "change_action": None,
                "download_status": activity.download_status,
                "download_error": activity.download_error,
            }
            material["agent_prompt"] = _material_summary_prompt(
                resources,
                material,
                course_id=course_id,
                course_code=course_code,
                course_title=course_title,
                moodle_course_id=archive.course.course_id,
            )
            materials.append(material)

    unused = {material["id"]: material for material in materials}
    for section in record.material_sections if record is not None else []:
        values: list[dict[str, Any]] = []
        for reference in section.materials:
            matched = _match_archive_material(reference, unused.values())
            if matched is None:
                continue
            unused.pop(matched["id"], None)
            classified = dict(matched)
            classified["material_section"] = section.title
            classified["material_type"] = reference.material_type
            classified["classification_note"] = reference.note
            values.append(classified)
        if values:
            grouped["sections"].append(
                {
                    "title": section.title,
                    "description": section.description,
                    "materials": values,
                }
            )
    grouped["unclassified"] = list(unused.values())
    grouped["all"] = materials
    return grouped


def _match_archive_material(reference: Any, candidates: Any) -> dict[str, Any] | None:
    values = list(candidates)
    if reference.relative_path:
        match = next(
            (
                material
                for material in values
                if material.get("relative_path") == reference.relative_path
            ),
            None,
        )
        if match is not None:
            return match
    if reference.url:
        match = next(
            (
                material
                for material in values
                if material.get("source_url") == reference.url
            ),
            None,
        )
        if match is not None:
            return match
    title = reference.title.strip().casefold()
    title_matches = [
        material
        for material in values
        if str(material.get("title") or "").strip().casefold() == title
    ]
    return title_matches[0] if len(title_matches) == 1 else None


def _recent_lecture_materials_prompt(
    resources: Path,
    *,
    course_id: str,
    moodle_course_id: str | None,
    course_code: str,
    course_title: str,
) -> str:
    moodle_scope = moodle_course_id or course_id
    return "\n".join(
        [
            "请定位本机 HIQS 项目并完整阅读 src/AI_Skills/SKILL.md。",
            f"课程：{course_code} · {course_title}",
            f"课程记录 ID：{course_id}；Moodle 课程 ID：{moodle_scope}",
            f"资料目录：{resources}",
            "以 Asia/Hong_Kong 当前日期为准，从 information.json 的课程活动和重复日程中确定最近一次已经发生的 Lecture；若标题没有使用 Lecture 字样，请结合课程类型、时间和来源判断并说明依据。",
            f"运行 hsas information show，并运行 hsas materials list --course {moodle_scope}。读取该 Lecture 的主题、周次、说明和来源，再检查相关课件的文本 sidecar 或原文件。",
            "列出与该 Lecture 最相关的课件，按相关性排序；对每项说明匹配依据、相对路径以及相关页码或 slide。不要仅根据文件名判断，也不要改写 information.json。",
            "如果无法确认最近 Lecture 或找不到可靠关联，请明确指出缺少的证据。",
        ]
    )


def _material_summary_prompt(
    resources: Path,
    material: dict[str, Any],
    *,
    course_id: str,
    course_code: str,
    course_title: str,
    moodle_course_id: str,
) -> str:
    locator = material.get("relative_path") or material.get("source_url") or material["id"]
    text_path = material.get("text_path") or "尚无文本 sidecar，请检查 OCR/解析状态"
    return "\n".join(
        [
            "请定位本机 HIQS 项目并完整阅读 src/AI_Skills/SKILL.md。",
            f"课程：{course_code} · {course_title}",
            f"课程记录 ID：{course_id}；Moodle 课程 ID：{moodle_course_id}",
            f"课件：{material['title']}",
            f"Moodle 活动：{material.get('activity_name') or '未标明'}",
            f"课件位置：{locator}",
            f"文本副本：{text_path}",
            f"资料目录：{resources}",
            "请定位并阅读这份课件；必要时检查原文件、文本 sidecar 和 OCR 状态。用中文总结其主题结构、关键概念、公式或要求，并标注相关页码或 slide。",
            "同时说明它与课程活动或相邻课件的关系。仅根据实际内容总结；证据不足时明确说明，不要改写 information.json。",
        ]
    )


DashboardService = HIQSCore


def build_port(resources_dir: Path | None = None) -> HIQSPort:
    """Build the production CORE implementation behind the stable port."""
    resources = (
        get_runtime_paths().create().resources_dir
        if resources_dir is None
        else resources_dir
    )
    return HIQSCore(resources_dir=resources)
