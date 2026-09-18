"""Coordinate one authenticated, multi-source course synchronization run."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, AsyncContextManager, Callable, Protocol


ProgressCallback = Callable[[dict[str, object]], None]
CancelRequested = Callable[[], bool]


class UnifiedBrowserSession(Protocol):
    async def sync_moodle(
        self,
        courses: list[dict[str, str]],
        *,
        progress_callback: ProgressCallback | None,
        cancel_requested: CancelRequested | None,
    ) -> dict[str, Any]: ...

    async def sync_sis_course_info(
        self,
        courses: list[dict[str, str]],
        *,
        progress_callback: ProgressCallback | None,
        cancel_requested: CancelRequested | None,
    ) -> Any: ...

    async def sync_timetable(
        self,
        *,
        progress_callback: ProgressCallback | None,
        cancel_requested: CancelRequested | None,
    ) -> Any: ...


class BrowserSessionBrokerPort(Protocol):
    def open(self) -> AsyncContextManager[UnifiedBrowserSession]: ...


@dataclass(frozen=True, slots=True)
class UnifiedCourseSyncResult:
    moodle: object
    sis_course_info: object
    timetable: object

    @property
    def values(self) -> tuple[object, object, object]:
        return self.moodle, self.sis_course_info, self.timetable


@dataclass(frozen=True, slots=True)
class UnifiedCourseSyncService:
    """Run independent collectors concurrently inside one browser session."""

    broker: BrowserSessionBrokerPort

    async def synchronize(
        self,
        courses: list[dict[str, str]],
        *,
        progress_callback: ProgressCallback | None = None,
        cancel_requested: CancelRequested | None = None,
        source_scopes: dict[str, list[dict[str, str]] | None] | None = None,
    ) -> UnifiedCourseSyncResult:
        scopes = source_scopes or {
            "moodle": courses,
            "sis_course_info": courses,
            "timetable": None,
        }
        async with self.broker.open() as session:
            tasks: dict[str, object] = {}
            if "moodle" in scopes:
                tasks["moodle"] = session.sync_moodle(
                    scopes["moodle"] or [],
                    progress_callback=progress_callback,
                    cancel_requested=cancel_requested,
                )
            if "sis_course_info" in scopes:
                tasks["sis_course_info"] = session.sync_sis_course_info(
                    scopes["sis_course_info"] or [],
                    progress_callback=progress_callback,
                    cancel_requested=cancel_requested,
                )
            if "timetable" in scopes:
                tasks["timetable"] = session.sync_timetable(
                    progress_callback=progress_callback,
                    cancel_requested=cancel_requested,
                )
            names = list(tasks)
            results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        values = dict(zip(names, results, strict=True))
        moodle = values.get("moodle")
        sis_course_info = values.get("sis_course_info")
        timetable = values.get("timetable")
        return UnifiedCourseSyncResult(moodle, sis_course_info, timetable)


__all__ = ["UnifiedCourseSyncResult", "UnifiedCourseSyncService"]
