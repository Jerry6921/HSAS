"""Filesystem implementation of application planning repositories."""

from __future__ import annotations

from pathlib import Path

from hsas.domain.courses import ArchiveIndex
from hsas.domain.planning.define_execution import ExecutionLog
from hsas.domain.planning.define_plan import IntegratedPlan
from hsas.domain.planning.define_profile import StudentProfile
from hsas.infrastructure.moodle.record_sync import sync_warnings
from hsas.infrastructure.storage.persist_data import read_json, write_model


class JsonPlanningRepository:
    """Load validated models and persist them with atomic JSON replacement."""

    def profile_exists(self, path: Path) -> bool:
        return path.is_file()

    def plan_exists(self, path: Path) -> bool:
        return path.is_file()

    def load_profile(self, path: Path) -> StudentProfile:
        return StudentProfile.model_validate(read_json(path))

    def load_plan(self, path: Path) -> IntegratedPlan:
        return IntegratedPlan.model_validate(read_json(path))

    def load_execution_log(self, path: Path) -> ExecutionLog:
        if not path.is_file():
            return ExecutionLog()
        return ExecutionLog.model_validate(read_json(path))

    def load_archives(self, resources_dir: Path) -> list[ArchiveIndex]:
        paths = sorted((resources_dir / "courses").glob("*/course.json"))
        return [ArchiveIndex.from_json(path) for path in paths]

    def save_profile(self, path: Path, profile: StudentProfile) -> None:
        write_model(path, profile)

    def save_plan(self, path: Path, plan: IntegratedPlan) -> None:
        write_model(path, plan)

    def save_execution_log(self, path: Path, log: ExecutionLog) -> None:
        write_model(path, log)

    def sync_warnings(self, resources_dir: Path, course_ids: set[str]) -> list[str]:
        return sync_warnings(resources_dir, course_ids)
