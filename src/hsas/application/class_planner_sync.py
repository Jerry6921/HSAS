"""HKU Class Planner synchronization use cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from hsas.application.ports.gateways import (
    ClassPlannerGateway,
    ClassPlannerSessionResult,
    ClassPlannerSyncResult,
)


@dataclass(frozen=True, slots=True)
class ClassPlannerSynchronizationService:
    gateway: ClassPlannerGateway

    def login_until_ready(
        self,
        *,
        timeout_seconds: int = 300,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> ClassPlannerSessionResult:
        if cancel_requested is None:
            return self.gateway.login_until_ready(timeout_seconds=timeout_seconds)
        return self.gateway.login_until_ready(
            timeout_seconds=timeout_seconds,
            cancel_requested=cancel_requested,
        )

    def sync(self, *, timeout_seconds: int = 90) -> ClassPlannerSyncResult:
        return self.gateway.sync(timeout_seconds=timeout_seconds)


__all__ = [
    "ClassPlannerSessionResult",
    "ClassPlannerSyncResult",
    "ClassPlannerSynchronizationService",
]
