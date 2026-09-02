"""Plan generation and freshness use cases without CLI dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as Date
from pathlib import Path

from pydantic import ValidationError

from hsas.application.ports.define_repositories import PlanningRepository
from hsas.domain.planning.define_execution import ExecutionLog
from hsas.domain.planning.define_plan import IntegratedPlan
from hsas.domain.planning.validate_plan import PlanValidationReport, validate_integrated_plan
from hsas.domain.planning.generate_plan import PlannerEngine
from hsas.domain.planning.define_profile import StudentProfile
from hsas.domain.courses import ArchiveIndex


class PlanGenerationError(RuntimeError):
    """Raised when inputs are unavailable or the generated plan is invalid."""

    def __init__(self, message: str, report: PlanValidationReport | None = None) -> None:
        super().__init__(message)
        self.report = report


@dataclass(frozen=True, slots=True)
class PlanGenerationRequest:
    resources_dir: Path
    profile_path: Path | None = None
    output_path: Path | None = None
    execution_path: Path | None = None
    days: int | None = None
    start: str | None = None
    fresh: bool = False


@dataclass(frozen=True, slots=True)
class PlanGenerationResult:
    plan: IntegratedPlan
    report: PlanValidationReport
    output_path: Path


@dataclass(frozen=True, slots=True)
class PlanFreshness:
    current: bool
    reasons: tuple[str, ...]


def generate_validated_plan(
    request: PlanGenerationRequest,
    repository: PlanningRepository,
) -> PlanGenerationResult:
    resources = request.resources_dir
    profile_path = request.profile_path or resources / "student_profile.json"
    output_path = request.output_path or resources / "integrated_plan.json"
    execution_path = request.execution_path or resources / "execution_log.json"
    profile = _load_profile(profile_path, repository)
    archives = _load_archives(resources, repository)
    existing = None
    if repository.plan_exists(output_path) and not request.fresh:
        existing = _load_plan(output_path, repository)
    execution_log = _load_execution_log(execution_path, repository)
    try:
        start_date = Date.fromisoformat(request.start) if request.start else None
    except ValueError as exc:
        raise PlanGenerationError("start must use YYYY-MM-DD") from exc
    plan = PlannerEngine().generate(
        profile,
        archives,
        existing_plan=existing,
        execution_log=execution_log,
        start_date=start_date,
        horizon_days=request.days,
    )
    course_ids = {index.archive.course.course_id for index in archives}
    source_warnings = repository.sync_warnings(resources, course_ids)
    plan.source_snapshot.warnings = source_warnings
    plan.plan_warnings = list(dict.fromkeys([*plan.plan_warnings, *source_warnings]))
    report = validate_integrated_plan(plan, profile, archives, execution_log)
    if not report.valid:
        raise PlanGenerationError("generated Integrated Plan failed validation", report)
    repository.save_plan(output_path, plan)
    return PlanGenerationResult(plan=plan, report=report, output_path=output_path)


def assess_plan_freshness(
    resources_dir: Path,
    repository: PlanningRepository,
) -> PlanFreshness:
    """Compare a plan's recorded source revisions with current validated inputs."""
    plan_path = resources_dir / "integrated_plan.json"
    if not repository.plan_exists(plan_path):
        return PlanFreshness(False, ("Integrated Plan does not exist.",))
    reasons: list[str] = []
    try:
        plan = _load_plan(plan_path, repository)
        profile = _load_profile(resources_dir / "student_profile.json", repository)
        execution = _load_execution_log(resources_dir / "execution_log.json", repository)
        archives = _load_archives(resources_dir, repository)
    except PlanGenerationError as exc:
        return PlanFreshness(False, (str(exc),))
    snapshot = plan.source_snapshot
    if snapshot.student_profile_updated_at != profile.updated_at:
        reasons.append("Student Profile changed after the current Plan was generated.")
    if snapshot.execution_log_updated_at != execution.updated_at:
        reasons.append("Execution Log changed after the current Plan was generated.")
    expected = {
        value.course_id: (value.collected_at, value.schema_version)
        for value in snapshot.course_archives
    }
    current = {
        index.archive.course.course_id: (
            index.archive.collected_at,
            index.archive.schema_version,
        )
        for index in archives
    }
    if expected != current:
        reasons.append("Course archives changed after the current Plan was generated.")
    reasons.extend(repository.sync_warnings(resources_dir, set(current)))
    return PlanFreshness(not reasons, tuple(dict.fromkeys(reasons)))


def _load_profile(path: Path, repository: PlanningRepository) -> StudentProfile:
    if not repository.profile_exists(path):
        raise PlanGenerationError(f"profile does not exist: {path}")
    try:
        return repository.load_profile(path)
    except (OSError, ValidationError) as exc:
        raise PlanGenerationError(f"invalid Student Profile {path}: {exc}") from exc


def _load_plan(path: Path, repository: PlanningRepository) -> IntegratedPlan:
    try:
        return repository.load_plan(path)
    except (OSError, ValidationError) as exc:
        raise PlanGenerationError(f"invalid Integrated Plan {path}: {exc}") from exc


def _load_execution_log(path: Path, repository: PlanningRepository) -> ExecutionLog:
    try:
        return repository.load_execution_log(path)
    except (OSError, ValidationError) as exc:
        raise PlanGenerationError(f"invalid Execution Log {path}: {exc}") from exc


def _load_archives(
    resources_dir: Path,
    repository: PlanningRepository,
) -> list[ArchiveIndex]:
    courses_dir = resources_dir / "courses"
    try:
        archives = repository.load_archives(resources_dir)
    except (OSError, ValidationError, ValueError) as exc:
        raise PlanGenerationError(f"invalid course archive: {exc}") from exc
    if not archives:
        raise PlanGenerationError(f"no course archives found under {courses_dir}; sync Moodle first")
    return archives
