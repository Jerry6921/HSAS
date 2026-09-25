"""Synchronous institutional-source operations used by the CORE facade."""

from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Any, Callable

from hsas.core.ports import HIQSPortError


class InstitutionalSourceService:
    def __init__(
        self,
        resources_dir: Path,
        mutation_lock: Lock,
        moodle_factory: Callable[[Path], Any],
        class_planner_factory: Callable[[Path], Any],
        sis_course_info_factory: Callable[[Path], Any],
        sis_enrollment_factory: Callable[[Path], Any],
        load_information: Callable[[Path], Any],
        pending_summary: Callable[[Any], dict[str, int]],
        collect_enrollment_changes: Callable[[Path], dict[str, Any]],
    ) -> None:
        self._resources_dir = resources_dir
        self._mutation_lock = mutation_lock
        self._moodle_factory = moodle_factory
        self._class_planner_factory = class_planner_factory
        self._sis_course_info_factory = sis_course_info_factory
        self._sis_enrollment_factory = sis_enrollment_factory
        self._load_information = load_information
        self._pending_summary = pending_summary
        self._collect_enrollment_changes = collect_enrollment_changes

    def login_moodle(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("confirmed") is not True:
            raise HIQSPortError("请先确认打开 Moodle 登录窗口。")
        with self._mutation_lock:
            try:
                result = self._moodle_factory(self._resources_dir).login_until_ready()
            except Exception as exc:
                raise HIQSPortError(
                    f"Moodle 登录未完成：{type(exc).__name__}: {str(exc)[:300]}"
                ) from exc
        return {
            "status": result.status,
            "checked_at": result.checked_at,
            "available_course_count": result.available_course_count,
            "error": result.error,
        }

    def synchronize_moodle(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("confirmed") is not True:
            raise HIQSPortError("请先确认开始同步 Moodle 课程资料。")
        course = payload.get("course")
        if course is not None and (not isinstance(course, str) or not course.strip()):
            raise HIQSPortError("course 必须是 Moodle course ID 或同源 URL。")
        course = course.strip() if isinstance(course, str) else None
        with self._mutation_lock:
            try:
                service = self._moodle_factory(self._resources_dir)
                if course:
                    result = service.sync_course(course)
                    return {
                        "scope": "single",
                        "discovered_course_count": 1,
                        "succeeded_course_count": 1,
                        "failed_course_count": 0,
                        "course_id": result.course_id,
                        "report_path": str(result.output_path),
                        "pending_review": self._review_summary(),
                    }
                result = service.sync_all()
            except Exception as exc:
                raise HIQSPortError(
                    "Moodle 同步失败，上一份有效资料已保留："
                    f"{type(exc).__name__}: {str(exc)[:300]}"
                ) from exc
        return {
            "scope": "all",
            "discovered_course_count": result.discovered_course_count,
            "succeeded_course_count": len(result.succeeded_course_ids),
            "failed_course_count": len(result.failures),
            "course_id": None,
            "report_path": str(result.report_path),
            "pending_review": self._review_summary(),
        }

    def login_class_planner(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("confirmed") is not True:
            raise HIQSPortError("请先确认打开 HKU Portal 登录窗口。")
        with self._mutation_lock:
            try:
                result = self._class_planner_factory(self._resources_dir).login_until_ready()
            except Exception as exc:
                raise HIQSPortError(
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
        if payload.get("confirmed") is not True:
            raise HIQSPortError("请先确认同步 HKU Class Planner 课表。")
        with self._mutation_lock:
            try:
                result = self._class_planner_factory(self._resources_dir).sync()
            except Exception as exc:
                raise HIQSPortError(
                    "Class Planner 同步失败，上一份快照已保留："
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
        if payload.get("confirmed") is not True:
            raise HIQSPortError("请先确认打开 HKU SIS 登录窗口。")
        with self._mutation_lock:
            try:
                result = self._sis_course_info_factory(self._resources_dir).login_until_ready()
            except Exception as exc:
                raise HIQSPortError(
                    f"HKU SIS 登录未完成：{type(exc).__name__}: {str(exc)[:300]}"
                ) from exc
        return {
            "status": result.status,
            "checked_at": result.checked_at,
            "available_course_count": result.available_course_count,
            "error": result.error,
        }

    def synchronize_sis_course_info(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("confirmed") is not True:
            raise HIQSPortError("请先确认同步 HKU SIS 课程信息。")
        had_snapshot = (self._resources_dir / "sis-course-info" / "latest.json").is_file()
        with self._mutation_lock:
            try:
                result = self._sis_course_info_factory(self._resources_dir).sync()
            except Exception as exc:
                detail = "上一份快照已保留" if had_snapshot else "尚未写入任何 SIS 课程信息"
                raise HIQSPortError(
                    f"HKU SIS 课程信息同步失败，{detail}："
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

    def synchronize_sis_enrollment(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("confirmed") is not True:
            raise HIQSPortError("Please confirm Student Center synchronization.")
        with self._mutation_lock:
            try:
                result = self._sis_enrollment_factory(self._resources_dir).sync(auto_login=True)
            except Exception as exc:
                raise HIQSPortError(
                    "Student Center synchronization failed; the previous snapshot was "
                    f"retained: {type(exc).__name__}: {str(exc)[:300]}"
                ) from exc
        return {
            "status": "synced",
            "course_count": len(result.get("courses", [])),
            "term": result.get("term"),
            "review": self._collect_enrollment_changes(self._resources_dir),
        }

    def _review_summary(self) -> dict[str, int]:
        return self._pending_summary(self._load_information(self._resources_dir))
