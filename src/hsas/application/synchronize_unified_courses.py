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
    ) -> UnifiedCourseSyncResult:
        async with self.broker.open() as session:
            results = await asyncio.gather(
                session.sync_moodle(
                    courses,
                    progress_callback=progress_callback,
                    cancel_requested=cancel_requested,
                ),
                session.sync_sis_course_info(
                    courses,
                    progress_callback=progress_callback,
                    cancel_requested=cancel_requested,
                ),
                session.sync_timetable(
                    progress_callback=progress_callback,
                    cancel_requested=cancel_requested,
                ),
                return_exceptions=True,
            )
        moodle, sis_course_info, timetable = results
        return UnifiedCourseSyncResult(moodle, sis_course_info, timetable)


__all__ = ["UnifiedCourseSyncResult", "UnifiedCourseSyncService"]
