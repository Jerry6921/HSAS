"""Persistence contracts required by planning use cases."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from hsas.domain.courses import ArchiveIndex
from hsas.domain.planning.define_execution import ExecutionLog
from hsas.domain.planning.define_plan import IntegratedPlan
from hsas.domain.planning.define_profile import StudentProfile


class PlanningRepository(Protocol):
    """Read and atomically persist validated planning aggregates."""

    def profile_exists(self, path: Path) -> bool: ...

    def plan_exists(self, path: Path) -> bool: ...

    def load_profile(self, path: Path) -> StudentProfile: ...

    def load_plan(self, path: Path) -> IntegratedPlan: ...

    def load_execution_log(self, path: Path) -> ExecutionLog: ...

    def load_archives(self, resources_dir: Path) -> list[ArchiveIndex]: ...

    def save_profile(self, path: Path, profile: StudentProfile) -> None: ...

    def save_plan(self, path: Path, plan: IntegratedPlan) -> None: ...

    def save_execution_log(self, path: Path, log: ExecutionLog) -> None: ...

    def sync_warnings(self, resources_dir: Path, course_ids: set[str]) -> list[str]: ...
