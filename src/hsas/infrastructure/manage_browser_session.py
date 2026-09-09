"""Share one authenticated Playwright context across course collectors."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, Callable

from playwright.async_api import BrowserContext

from hsas.application.ports.define_gateways import CourseCatalogEntry
from hsas.infrastructure.class_planner.synchronize_calendar import (
    ClassPlannerBrowserGateway,
)
from hsas.infrastructure.moodle.fetch_moodle import persistent_context
from hsas.infrastructure.moodle.load_settings import Settings
from hsas.infrastructure.moodle.record_session import record_moodle_session_status
from hsas.infrastructure.moodle.record_sync import record_sync_operation
from hsas.infrastructure.moodle.synchronize_courses import MoodleCourseGateway
from hsas.infrastructure.sis_course_info.fetch_course_pages import (
    restore_sis_session,
    save_sis_session,
)
from hsas.infrastructure.sis_course_info.synchronize_course_pages import (
    SisCourseInfoBrowserGateway,
    course_identity,
)


ProgressCallback = Callable[[dict[str, object]], None]
CancelRequested = Callable[[], bool]


@dataclass(slots=True)
class BrowserSyncSession:
    """Source-specific operations sharing one context and separate pages."""

    context: BrowserContext
    resources_dir: Path
    moodle: MoodleCourseGateway
    sis: SisCourseInfoBrowserGateway
    planner: ClassPlannerBrowserGateway
    _moodle_catalog_ready: asyncio.Event = field(default_factory=asyncio.Event)
    _available_by_code: dict[str, CourseCatalogEntry] = field(default_factory=dict)

    @staticmethod
    def _report(
        callback: ProgressCallback | None,
        stage: str,
        *,
        processed: int,
        completed: int,
        failed: int,
        total: int,
        detail: str,
    ) -> None:
        if callback is not None:
            callback(
                {
                    "stage": stage,
                    "processed": processed,
                    "completed": completed,
                    "failed": failed,
                    "total": total,
                    "detail": detail,
                }
            )

    async def sync_moodle(
        self,
        courses: list[dict[str, str]],
        *,
        progress_callback: ProgressCallback | None,
        cancel_requested: CancelRequested | None,
    ) -> dict[str, object]:
        failures: list[dict[str, str]] = []
        course_results: list[dict[str, object]] = []
        completed = 0
        processed = 0
        try:
            catalog = await self.moodle.list_courses_in_context(self.context)
            if catalog.login_status != "logged in":
                raise RuntimeError(catalog.login_error or "Moodle session is not authenticated")
            for entry in catalog.available:
                identity = course_identity(entry.title)
                if identity is not None and entry.course_id.isdigit():
                    self._available_by_code.setdefault(identity[0], entry)
        finally:
            self._moodle_catalog_ready.set()

        for course in courses:
            if cancel_requested is not None and cancel_requested():
                break
            code = course["course_code"]
            self._report(
                progress_callback,
                "moodle",
                processed=processed,
                completed=completed,
                failed=len(failures),
                total=len(courses),
                detail=f"Moodle 课程资料 · {code}",
            )
            entry = self._available_by_code.get(code)
            if entry is None:
                failure = {
                    "course_code": code,
                    "error": "Moodle 中未找到与当前 enrolment 对应的课程",
                }
                failures.append(failure)
                course_results.append(
                    {
                        "course_id": code,
                        "course": course.get("title", code),
                        "succeeded": False,
                        "error": failure["error"],
                    }
                )
            else:
                try:
                    result = await self.moodle.sync_course_in_context(
                        self.context,
                        entry.course_id,
                        cancel_requested=cancel_requested,
                    )
                except Exception as exc:
                    failure = {
                        "course_code": code,
                        "error": f"{type(exc).__name__}: {str(exc)[:240]}",
                    }
                    failures.append(failure)
                    course_results.append(
                        {
                            "course_id": entry.course_id,
                            "course": entry.title,
                            "succeeded": False,
                            "error": failure["error"],
                        }
                    )
                else:
                    completed += 1
                    course_results.append(
                        {
                            "course_id": result.course_id,
                            "course": result.course_title,
                            "succeeded": True,
                            "change_count": result.change_count,
                        }
                    )
            processed += 1
            self._report(
                progress_callback,
                "moodle",
                processed=processed,
                completed=completed,
                failed=len(failures),
                total=len(courses),
                detail=f"Moodle 课程资料 · {processed}/{len(courses)}",
            )

        record_sync_operation(
            self.resources_dir,
            scope="all",
            discovered_course_count=len(courses),
            course_results=course_results,
        )
        record_moodle_session_status(
            self.resources_dir,
            "logged_in",
            available_course_count=len(self._available_by_code),
        )
        return {"completed": completed, "failures": failures}

    async def sync_sis_course_info(
        self,
        courses: list[dict[str, str]],
        *,
        progress_callback: ProgressCallback | None,
        cancel_requested: CancelRequested | None,
    ):
        await self._moodle_catalog_ready.wait()
        selected = []
        for course in courses:
            entry = self._available_by_code.get(course["course_code"])
            selected.append(
                {
                    "course_code": course["course_code"],
                    "subject_area": course["subject_area"],
                    "catalogue_number": course["catalogue_number"],
                    "moodle_course_id": entry.course_id if entry else "",
                    "moodle_title": entry.title if entry else course.get("title", course["course_code"]),
                }
            )

        def report(value: dict[str, object]) -> None:
            processed = int(value.get("completed", 0))
            self._report(
                progress_callback,
                "sis_course_info",
                processed=processed,
                completed=processed,
                failed=0,
                total=len(courses),
                detail=f"SIS 课程信息 · {value.get('course_code', '')}",
            )

        result = await self.sis.sync_in_context(
            self.context,
            timeout_seconds=30,
            selected_courses=selected,
            progress_callback=report,
            cancel_requested=cancel_requested,
        )
        failed = len(result.failures)
        self._report(
            progress_callback,
            "sis_course_info",
            processed=len(courses),
            completed=len(courses) - failed,
            failed=failed,
            total=len(courses),
            detail=f"SIS 课程信息 · {len(courses)}/{len(courses)}",
        )
        return result

    async def sync_timetable(
        self,
        *,
        progress_callback: ProgressCallback | None,
        cancel_requested: CancelRequested | None,
    ):
        if cancel_requested is not None and cancel_requested():
            return None
        result = await self.planner.sync_in_context(self.context)
        self._report(
            progress_callback,
            "timetable",
            processed=1,
            completed=1,
            failed=0,
            total=1,
            detail="官方课表已完成",
        )
        return result


@dataclass(frozen=True, slots=True)
class BrowserSessionBroker:
    """Own the single persistent browser context for a unified sync run."""

    resources_dir: Path
    settings: Settings

    @asynccontextmanager
    async def open(self) -> AsyncIterator[BrowserSyncSession]:
        resources_dir = self.resources_dir.expanduser().resolve()
        sis = SisCourseInfoBrowserGateway(
            resources_dir,
            profile_dir=self.settings.profile_dir,
        )
        async with persistent_context(self.settings, headless=True) as context:
            await restore_sis_session(context, sis.session_state_path)
            try:
                yield BrowserSyncSession(
                    context=context,
                    resources_dir=resources_dir,
                    moodle=MoodleCourseGateway(self.settings),
                    sis=sis,
                    planner=ClassPlannerBrowserGateway(
                        resources_dir,
                        profile_dir=self.settings.profile_dir,
                    ),
                )
            finally:
                await save_sis_session(context, sis.session_state_path)


__all__ = ["BrowserSessionBroker", "BrowserSyncSession"]
