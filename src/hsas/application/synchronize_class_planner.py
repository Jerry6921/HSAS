"""HKU Class Planner synchronization use cases."""

from __future__ import annotations

from dataclasses import dataclass

from hsas.application.ports.define_gateways import (
    ClassPlannerGateway,
    ClassPlannerSessionResult,
    ClassPlannerSyncResult,
)


@dataclass(frozen=True, slots=True)
class ClassPlannerSynchronizationService:
    gateway: ClassPlannerGateway

    def login_until_ready(
        self, *, timeout_seconds: int = 300
    ) -> ClassPlannerSessionResult:
        return self.gateway.login_until_ready(timeout_seconds=timeout_seconds)

    def sync(self, *, timeout_seconds: int = 90) -> ClassPlannerSyncResult:
        return self.gateway.sync(timeout_seconds=timeout_seconds)


__all__ = [
    "ClassPlannerSessionResult",
    "ClassPlannerSyncResult",
    "ClassPlannerSynchronizationService",
]
