"""Unified HSAS command-line interface."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from integrated_planner.execution_schema import ExecutionLog
from integrated_planner.plan_schema import IntegratedPlan
from integrated_planner.profile_schema import StudentProfile
from integrated_planner.workflow import generate_plan
from moodle_collector.transformation.common.course_changes import CourseChangeSet
from moodle_collector.workflow import (
    list_courses,
    login as login_to_moodle,
    sync_all,
    sync_course,
)


DEFAULT_RESOURCES = Path("src/resources")

app = typer.Typer(
    no_args_is_help=True,
    help="HKU Study Assistance System",
)


@app.command("list-status")
def list_status(
    resources_dir: Annotated[
        Path,
        typer.Option("--resources", help="Shared resources directory"),
    ] = DEFAULT_RESOURCES,
) -> None:
    """Show Moodle, course sync, Profile, execution, and plan status."""
    list_courses()
    typer.echo("\nPlanning status:")
    _show_profile(resources_dir / "student_profile.json")
    _show_execution_log(resources_dir / "execution_log.json")
    _show_plan(resources_dir / "integrated_plan.json")
    _show_changes(resources_dir / "courses")


@app.command("login")
def login() -> None:
    """Open Moodle and persist the user-completed SSO/MFA session."""
    login_to_moodle()


@app.command("sync-courses")
def sync_courses(
    course: Annotated[
        str | None,
        typer.Argument(
            help="Optional Moodle course ID or URL; omit to sync all courses"
        ),
    ] = None,
) -> None:
    """Sync one course when specified, otherwise sync every available course."""
    if course is None:
        sync_all()
    else:
        sync_course(course)


@app.command("update-plan")
def update_plan(
    profile_path: Annotated[
        Path,
        typer.Option("--profile", help="Student Profile JSON path"),
    ] = DEFAULT_RESOURCES / "student_profile.json",
    output_path: Annotated[
        Path,
        typer.Option("--output", help="Integrated Plan JSON path"),
    ] = DEFAULT_RESOURCES / "integrated_plan.json",
    resources_dir: Annotated[
        Path,
        typer.Option("--resources", help="Shared resources directory"),
    ] = DEFAULT_RESOURCES,
    execution_path: Annotated[
        Path,
        typer.Option("--execution-log", help="Execution Log JSON path"),
    ] = DEFAULT_RESOURCES / "execution_log.json",
    days: Annotated[
        int | None,
        typer.Option(min=1, max=365, help="Override planning horizon"),
    ] = None,
    start: Annotated[
        str | None,
        typer.Option(help="Planning start date in YYYY-MM-DD format"),
    ] = None,
    fresh: Annotated[
        bool,
        typer.Option(help="Ignore the existing plan and its preserved progress"),
    ] = False,
) -> None:
    """Generate and validate the deterministic cross-course plan."""
    generate_plan(
        profile_path=profile_path,
        output_path=output_path,
        resources_dir=resources_dir,
        execution_path=execution_path,
        days=days,
        start=start,
        fresh=fresh,
    )


def _show_profile(path: Path) -> None:
    try:
        profile = StudentProfile.model_validate_json(path.read_text(encoding="utf-8"))
        typer.echo(
            f"  Profile: {profile.profile_status}; timezone={profile.timezone}; "
            f"updated={profile.updated_at or 'never'}"
        )
    except Exception as exc:
        typer.echo(f"  Profile: unavailable ({type(exc).__name__})")


def _show_execution_log(path: Path) -> None:
    try:
        log = ExecutionLog.model_validate_json(path.read_text(encoding="utf-8"))
        actual = sum(record.actual_minutes for record in log.records)
        typer.echo(
            f"  Execution: {len(log.records)} record(s); "
            f"actual={actual} minute(s)"
        )
    except Exception as exc:
        typer.echo(f"  Execution: unavailable ({type(exc).__name__})")


def _show_plan(path: Path) -> None:
    try:
        plan = IntegratedPlan.model_validate_json(path.read_text(encoding="utf-8"))
        typer.echo(
            f"  Plan: {plan.plan_status}; {len(plan.items)} item(s); "
            f"{len(plan.timetable)} block(s); updated={plan.updated_at or 'never'}"
        )
        if plan.capacity_summary.unscheduled_workload_minutes:
            typer.echo(
                "  Capacity warning: "
                f"{plan.capacity_summary.unscheduled_workload_minutes} minute(s) "
                "remain unscheduled"
            )
    except Exception as exc:
        typer.echo(f"  Plan: unavailable ({type(exc).__name__})")


def _show_changes(courses_dir: Path) -> None:
    reports: list[CourseChangeSet] = []
    for path in sorted(courses_dir.glob("*/changes/latest.json")):
        try:
            reports.append(
                CourseChangeSet.model_validate_json(path.read_text(encoding="utf-8"))
            )
        except Exception:
            continue
    changed = [report for report in reports if report.changed]
    typer.echo(
        f"  Changes: {len(changed)} course(s) changed across "
        f"{len(reports)} report(s)"
    )


if __name__ == "__main__":
    app()
