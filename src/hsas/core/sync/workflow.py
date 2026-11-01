"""Run the cancellable multi-source course synchronization workflow."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

from hsas.application.material_search import (
    invalidate_material_index,
    refresh_material_index,
)
from hsas.core.ports import HIQSPortError
from hsas.core.services.dashboard import pending_summary
from hsas.core.services.reviews import SourceReviewService
from hsas.core.sync.controller import CourseSyncController
from hsas.infrastructure.storage.json_store import read_json, write_json

DashboardError = HIQSPortError
ServiceFactory = Callable[[Path], Any]


class _WorkflowCancelled(RuntimeError):
    pass


def courses_matching_scope(
    courses: list[dict[str, Any]], course_scope: str
) -> list[dict[str, Any]]:
    """Return the enrollment entries whose course code matches ``course_scope``."""
    key = course_scope.strip().upper()
    return [
        course
        for course in courses
        if str(course.get("course_code") or "").strip().upper() == key
    ]


# Source failures that will not change just by retrying: the official catalogue
# does not know the course, or the enrolment snapshot has no matching entry.
_PERMANENT_FAILURE_MARKERS = (
    "has no matching entry",
    "SisCourseInfoLookupError",
    "未找到与当前 enrolment 对应的课程",
    "No Moodle course titles contain a Subject Area and Catalogue Number",
)


def classify_retry_task(task: dict[str, Any]) -> str:
    """Return ``permanent`` for failures a retry cannot fix, else ``transient``."""
    error = str(task.get("error") or "")
    if any(marker in error for marker in _PERMANENT_FAILURE_MARKERS):
        return "permanent"
    return "transient"


def annotate_retry_tasks(
    tasks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Tag every retry task with its kind so status can separate them."""
    annotated: list[dict[str, Any]] = []
    for task in tasks:
        kind = classify_retry_task(task)
        annotated.append({**task, "kind": kind, "retry_recommended": kind == "transient"})
    return annotated


def _workflow_stage_label(stage: str) -> str:
    return {
        "enrollment": "课程列表获取",
        "moodle": "Moodle 课程资料",
        "sis_course_info": "SIS 课程信息",
        "timetable": "官方课表",
    }.get(stage, stage)


@dataclass(slots=True)
class CourseSyncWorkflow:
    """Coordinate authentication, collection, progress, retries, and persistence."""

    resources_dir: Path
    mutation_lock: Lock
    controller: CourseSyncController
    review_service: SourceReviewService
    course_service_factory: ServiceFactory
    enrollment_gateway_factory: ServiceFactory
    unified_service_factory: ServiceFactory

    def start_course_sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Start the cancellable multi-source course synchronization workflow."""
        if payload.get("confirmed") is not True:
            raise DashboardError("请先确认开始课程同步工作流。")
        raw_course = payload.get("course")
        if raw_course is not None and (
            not isinstance(raw_course, str) or not raw_course.strip()
        ):
            raise DashboardError("course 必须是非空课程代码，或省略以同步全部课程。")
        course_scope = raw_course.strip() if isinstance(raw_course, str) else None
        return self.controller.start(
            lambda job_id, retry_tasks: self.run(
                job_id, retry_tasks, course_scope=course_scope
            )
        )

    def retry_failed_course_sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Retry only the source/course pairs left by the latest workflow."""
        if payload.get("confirmed") is not True:
            raise DashboardError("请先确认重试失败课程或来源。")
        result = self.course_sync_status().get("result")
        retry_tasks = list((result or {}).get("retry_tasks") or [])
        if not retry_tasks:
            raise DashboardError("最近一次同步没有可重试的失败项目。")
        include_permanent = payload.get("include_permanent") is True
        runnable = [
            task
            for task in retry_tasks
            if include_permanent or classify_retry_task(task) != "permanent"
        ]
        if not runnable:
            raise DashboardError(
                "最近一次同步只剩永久性来源失败（例如官方目录中不存在该课程），"
                "重试不会改变结果；请先核对来源，或显式请求 include_permanent。"
            )
        return self.controller.start(
            self.run,
            retry_tasks=runnable,
        )

    def course_sync_status(self) -> dict[str, Any]:
        return self.controller.snapshot(self._persisted_sync_result)

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
        return self.controller.cancel()

    def hydrate_course_materials(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Download and index one deferred Moodle course on Agent demand."""
        course_id = payload.get("course_id")
        if not isinstance(course_id, str) or not course_id.strip() or len(course_id) > 120:
            raise DashboardError("course_id must be a bounded non-empty string.")
        with self.mutation_lock:
            result = self.course_service_factory(self.resources_dir).sync_course(course_id.strip())
        try:
            refresh_material_index(self.resources_dir, {course_id.strip()})
        except (OSError, ValueError):
            invalidate_material_index(self.resources_dir)
        return {
            "status": "hydrated",
            "course_id": result.course_id,
            "course_title": result.course_title,
            "change_count": result.change_count,
            "output_path": str(result.output_path),
        }

    def run(
        self,
        job_id: str,
        retry_tasks: list[dict[str, Any]] | None = None,
        *,
        course_scope: str | None = None,
    ) -> None:
        def report(values: dict[str, object]) -> None:
            with self.controller.lock:
                if self.controller.job.get("job_id") == job_id:
                    if self.controller.cancel_event.is_set():
                        values = {**values, "detail": "正在取消"}
                    self.controller.job.update(values)

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
            with self.controller.lock:
                if self.controller.job.get("job_id") != job_id:
                    return
                cards = [
                    dict(card)
                    for card in self.controller.job.get("cards", [])
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
                                    for card in self.controller.job.get("cards", [])
                                    if card.get("stage") == stage
                                    and card.get("course_code") == course_code
                                ),
                                course_code,
                            ),
                            "state": state,
                            "detail": detail,
                        }
                    )
                summaries = dict(self.controller.job.get("phase_summaries", {}))
                summaries[stage] = {
                    "completed": completed,
                    "failed": failed,
                    "total": total,
                }
                self.controller.job.update(
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
            with self.controller.lock:
                if self.controller.job.get("job_id") != job_id:
                    return
                summaries = dict(self.controller.job.get("phase_summaries", {}))
                summaries[stage] = {
                    "completed": completed,
                    "failed": failed,
                    "total": total,
                }
                self.controller.job.update(
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
                        "detail": "正在打开 HKU Portal；完成一次登录后将自动连接 Moodle 与 SIS",
                        "completed": 0,
                        "total": 1,
                        "cards": [],
                    }
                )
                moodle_service = self.course_service_factory(self.resources_dir)
                report(
                    {
                        "detail": "正在通过 Moodle CAS 打开 HKU Portal 登录",
                    }
                )
                moodle_status = moodle_service.check_login_status()
                if moodle_status.status != "logged_in":
                    try:
                        moodle_service.login_until_ready(
                            cancel_requested=self.controller.cancel_event.is_set,
                        )
                    except InterruptedError:
                        if self.controller.cancel_event.is_set():
                            raise _WorkflowCancelled
                        raise
                if self.controller.cancel_event.is_set():
                    raise _WorkflowCancelled

                report(
                    {
                        "detail": "HKU Portal 登录已完成；正在复用会话连接 SIS",
                    }
                )

                if retry_tasks is None:
                    report(
                        {
                            "stage": "authentication",
                            "detail": "正在连接 SIS 并读取课程列表；若弹出验证窗口，请完成验证",
                        }
                    )
                    try:
                        enrollment = self.enrollment_gateway_factory(self.resources_dir).sync(
                            auto_login=True,
                            interactive_login=True,
                            cancel_requested=self.controller.cancel_event.is_set,
                        )
                    except InterruptedError:
                        if self.controller.cancel_event.is_set():
                            raise _WorkflowCancelled
                        raise
                    courses = list(enrollment["courses"])
                    if course_scope is not None:
                        courses = courses_matching_scope(courses, course_scope)
                        if not courses:
                            raise DashboardError(
                                f"当前学期注册列表中没有课程：{course_scope}"
                            )
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
                    enrollment = self.enrollment_gateway_factory(self.resources_dir).status()
                    courses = list(enrollment.get("courses") or [])
                    if not courses:
                        raise DashboardError("没有可用于精确重试的当前学期课程快照。")
                if self.controller.cancel_event.is_set():
                    raise _WorkflowCancelled

                if self.controller.cancel_event.is_set():
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
                    with self.controller.lock:
                        if self.controller.job.get("job_id") != job_id:
                            return
                        existing = dict(self.controller.job.get("phase_summaries", {}))
                        existing.update(summaries)
                        self.controller.job.update(
                            stage="collecting",
                            detail=("正在取消" if self.controller.cancel_event.is_set() else detail),
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
                sync_service = self.unified_service_factory(self.resources_dir)
                sync_kwargs = {
                    "download_materials": False,
                    "progress_callback": report_unified_progress,
                    "cancel_requested": self.controller.cancel_event.is_set,
                }
                if retry_tasks is None:
                    try:
                        unified_result = asyncio.run(sync_service.synchronize(courses, **sync_kwargs))
                    except TypeError as exc:
                        # Keep older injected adapters usable while they adopt the
                        # lazy-material contract.
                        if "download_materials" not in str(exc):
                            raise
                        sync_kwargs.pop("download_materials", None)
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

                if self.controller.cancel_event.is_set() or any(
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
                moodle_warnings = (
                    list(moodle_result.get("warnings") or [])
                    if isinstance(moodle_result, dict)
                    else []
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
                retry_remaining = annotate_retry_tasks(retry_remaining)
                # Derived-index maintenance belongs to CORE, not the collector.
                try:
                    refresh_material_index(self.resources_dir)
                except (OSError, ValueError):
                    invalidate_material_index(self.resources_dir)
            payload = {
                "discovered_course_count": len(courses),
                "succeeded_course_count": moodle_completed,
                "failed_course_count": failed_course_count,
                "source_failures": source_failures,
                "retry_tasks": retry_remaining,
                "warnings": moodle_warnings,
                "retry_mode": retry_tasks is not None,
                "materials_deferred": True,
                "term": enrollment.get("term"),
                "pending_review": pending_summary(
                    self.review_service.pending_batch(
                        self.review_service.load_information_optional()
                    )
                ),
            }
            write_json(self.resources_dir / "sync-workflow" / "latest.json", payload).chmod(0o600)
            with self.controller.lock:
                if self.controller.job.get("job_id") == job_id:
                    self.controller.job.update(
                        state="completed",
                        stage="finished",
                        detail=(
                            f"快速采集完成，{len(retry_remaining)} 个项目需要重试"
                            if retry_remaining
                            else "同步完成"
                            if retry_tasks is not None
                            else "快速采集完成；资料等待 Agent 按需下载"
                        ),
                        result=payload,
                        cards=[],
                    )
        except _WorkflowCancelled:
            with self.controller.lock:
                if self.controller.job.get("job_id") == job_id:
                    self.controller.job.update(
                        state="cancelled",
                        stage="finished",
                        detail="同步已取消",
                        cards=[],
                    )
        except Exception as exc:
            with self.controller.lock:
                if self.controller.job.get("job_id") == job_id:
                    self.controller.job.update(
                        state="failed",
                        stage="finished",
                        detail="同步失败，上一份有效资料已保留",
                        error=f"{type(exc).__name__}: {str(exc)[:300]}",
                    )


__all__ = ["CourseSyncWorkflow"]
