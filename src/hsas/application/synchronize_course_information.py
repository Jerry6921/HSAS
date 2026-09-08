"""HKU SIS course-information synchronization use cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from hsas.application.ports.define_gateways import (
    SisCourseInfoGateway,
    SisCourseInfoSessionResult,
    SisCourseInfoSyncResult,
)


@dataclass(frozen=True, slots=True)
class SisCourseInfoSynchronizationService:
    gateway: SisCourseInfoGateway

    def login_until_ready(
        self, *, timeout_seconds: int = 300
    ) -> SisCourseInfoSessionResult:
        return self.gateway.login_until_ready(timeout_seconds=timeout_seconds)

    def sync(
        self,
        *,
        timeout_seconds: int = 90,
        selected_courses: list[dict[str, str]] | None = None,
        progress_callback: Callable[[dict[str, object]], None] | None = None,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> SisCourseInfoSyncResult:
        return self.gateway.sync(
            timeout_seconds=timeout_seconds,
            selected_courses=selected_courses,
            progress_callback=progress_callback,
            cancel_requested=cancel_requested,
        )


__all__ = [
    "SisCourseInfoSessionResult",
    "SisCourseInfoSyncResult",
    "SisCourseInfoSynchronizationService",
]
