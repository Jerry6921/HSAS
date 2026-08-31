from __future__ import annotations

from datetime import date as Date
from pathlib import Path

import typer
from pydantic import ValidationError

from moodle_collector.storage.local_store import write_model
from moodle_collector.transformation.common.course_index import ArchiveIndex
from .plan_schema import IntegratedPlan
from .execution_schema import ExecutionLog
from .plan_validator import PlanValidationReport, validate_integrated_plan
from .planner_engine import PlannerEngine
from .profile_schema import StudentProfile


def generate_plan(
    profile_path: Path = Path("src/resources/student_profile.json"),
    output_path: Path = Path("src/resources/integrated_plan.json"),
    resources_dir: Path = Path("src/resources"),
    execution_path: Path = Path("src/resources/execution_log.json"),
    days: int | None = None,
    start: str | None = None,
    fresh: bool = False,
) -> None:
    """Generate or update the cross-course timetable."""
    profile = _load_profile(profile_path)
    archives = _load_archives(resources_dir)
    existing = None
    if output_path.exists() and not fresh:
        existing = _load_plan(output_path)
    execution_log = _load_execution_log(execution_path)
    try:
        start_date = Date.fromisoformat(start) if start else None
    except ValueError as exc:
        raise typer.BadParameter("start must use YYYY-MM-DD") from exc

    plan = PlannerEngine().generate(
        profile,
        archives,
        existing_plan=existing,
        execution_log=execution_log,
        start_date=start_date,
        horizon_days=days,
    )
    report = validate_integrated_plan(plan, profile, archives, execution_log)
    if not report.valid:
        _print_report(report)
        raise typer.Exit(code=1)
    write_model(output_path, plan)
    typer.echo(
        f"Plan updated: {len(plan.items)} item(s), "
        f"{len(plan.timetable)} timetable block(s) -> {output_path}"
    )
    _print_report(report)


def _load_profile(path: Path) -> StudentProfile:
    if not path.exists():
        raise typer.BadParameter(f"profile does not exist: {path}")
    try:
        return StudentProfile.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        raise typer.BadParameter(f"invalid Student Profile {path}: {exc}") from exc


def _load_plan(path: Path) -> IntegratedPlan:
    if not path.exists():
        raise typer.BadParameter(f"plan does not exist: {path}")
    try:
        return IntegratedPlan.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        raise typer.BadParameter(f"invalid Integrated Plan {path}: {exc}") from exc


def _load_execution_log(path: Path) -> ExecutionLog:
    if not path.exists():
        return ExecutionLog()
    try:
        return ExecutionLog.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        raise typer.BadParameter(f"invalid Execution Log {path}: {exc}") from exc


def _load_archives(resources_dir: Path) -> list[ArchiveIndex]:
    courses_dir = resources_dir / "courses"
    paths = sorted(courses_dir.glob("*/course.json"))
    if not paths:
        raise typer.BadParameter(
            f"no course archives found under {courses_dir}; sync Moodle first"
        )
    try:
        return [ArchiveIndex.from_json(path) for path in paths]
    except (OSError, ValidationError, ValueError) as exc:
        raise typer.BadParameter(f"invalid course archive: {exc}") from exc


def _print_report(report: PlanValidationReport) -> None:
    typer.echo(
        f"Validation: {'valid' if report.valid else 'invalid'}; "
        f"{len(report.errors)} error(s), {len(report.warnings)} warning(s)"
    )
    for issue in [*report.errors, *report.warnings]:
        paths = f" [{', '.join(issue.paths)}]" if issue.paths else ""
        typer.echo(
            f"  {issue.severity.upper()} {issue.code}: {issue.message}{paths}"
        )
