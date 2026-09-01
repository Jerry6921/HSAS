"""Unified HSAS command-line interface."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from AI_interface import execution_app, materials_app, profile_app
from hsas_runtime import (
    MigrationError,
    get_runtime_paths,
    migrate_legacy_data,
)
from integrated_planner.execution_schema import ExecutionLog
from integrated_planner.plan_schema import IntegratedPlan
from integrated_planner.profile_schema import StudentProfile
from integrated_planner.workflow import generate_plan
from moodle_collector.settings import Settings
from moodle_collector.transformation.common.course_changes import CourseChangeSet
from moodle_collector.workflow import (
    list_courses,
    login as login_to_moodle,
    sync_all,
    sync_course,
)
from updator import UpdateError, update_installation


PROJECT_ROOT = Path(__file__).resolve().parents[1]

app = typer.Typer(
    no_args_is_help=True,
    help="HKU Study Assistance System",
)
app.add_typer(profile_app, name="profile")
app.add_typer(execution_app, name="execution")
app.add_typer(materials_app, name="materials")


@app.callback()
def main(
    ctx: typer.Context,
    resources_dir: Annotated[
        Path | None,
        typer.Option(
            "--resources",
            help="Override the platform-standard resources directory",
        ),
    ] = None,
) -> None:
    """Resolve shared runtime paths for this command invocation."""
    ctx.obj = {
        "resources": resources_dir or get_runtime_paths().resources_dir,
    }


@app.command("list-status")
def list_status(
    ctx: typer.Context,
    resources_dir: Annotated[
        Path | None,
        typer.Option("--resources", help="Shared resources directory"),
    ] = None,
) -> None:
    """Show Moodle, course sync, Profile, execution, and plan status."""
    resources_dir = resources_dir or _resources(ctx)
    typer.echo(f"Resources: {resources_dir}")
    list_courses(Settings.load(output_dir=resources_dir))
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
    ctx: typer.Context,
    course: Annotated[
        str | None,
        typer.Argument(
            help="Optional Moodle course ID or URL; omit to sync all courses"
        ),
    ] = None,
) -> None:
    """Sync one course when specified, otherwise sync every available course."""
    settings = Settings.load(output_dir=_resources(ctx))
    if course is None:
        sync_all(settings)
    else:
        sync_course(course, settings)


@app.command("update-plan")
def update_plan(
    ctx: typer.Context,
    profile_path: Annotated[
        Path | None,
        typer.Option("--profile", help="Student Profile JSON path"),
    ] = None,
    output_path: Annotated[
        Path | None,
        typer.Option("--output", help="Integrated Plan JSON path"),
    ] = None,
    resources_dir: Annotated[
        Path | None,
        typer.Option("--resources", help="Shared resources directory"),
    ] = None,
    execution_path: Annotated[
        Path | None,
        typer.Option("--execution-log", help="Execution Log JSON path"),
    ] = None,
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
    """Generate and validate the deterministic cross-course priority backlog."""
    resources_dir = resources_dir or _resources(ctx)
    generate_plan(
        profile_path=profile_path or resources_dir / "student_profile.json",
        output_path=output_path or resources_dir / "integrated_plan.json",
        resources_dir=resources_dir,
        execution_path=execution_path or resources_dir / "execution_log.json",
        days=days,
        start=start,
        fresh=fresh,
    )


@app.command("migrate-data")
def migrate_data(
    legacy_root: Annotated[
        Path,
        typer.Option(
            "--from",
            help="Legacy HSAS code directory containing src/resources",
        ),
    ] = PROJECT_ROOT,
) -> None:
    """Copy and verify legacy personal data into platform-standard storage."""
    try:
        result = migrate_legacy_data(legacy_root)
    except MigrationError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        f"Migration verified: {result.copied_files} copied, "
        f"{result.reused_files} reused, {result.verified_files} verified -> "
        f"{result.destination}"
    )
    typer.echo(f"Report: {result.destination / 'state/migration-report.json'}")
    typer.echo("Legacy files were retained for manual review:")
    for path in result.legacy_paths:
        typer.echo(f"  {path}")


@app.command("update-hsas")
def update_hsas(
    dry_run: Annotated[
        bool,
        typer.Option(help="Clone and compare without changing the installation"),
    ] = False,
) -> None:
    """Update HSAS from the trusted GitHub main branch, preserving local data."""
    typer.echo("Fetching trusted release: https://github.com/Jerry6921/HSAS (main)")
    try:
        result = update_installation(PROJECT_ROOT, dry_run=dry_run)
    except UpdateError as exc:
        typer.echo(f"Update failed safely: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    action = "Dry run" if result.dry_run else "Update complete"
    typer.echo(
        f"{action}: commit={result.commit[:12]}; "
        f"{result.copied_files} file(s) changed; "
        f"{result.removed_files} obsolete file(s) removed"
    )
    if not result.dry_run:
        typer.echo("Personal resources and browser session were not modified.")


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
            f"  Plan: {plan.plan_status}; mode={plan.planning_mode}; "
            f"{len(plan.items)} key item(s); updated={plan.updated_at or 'never'}"
        )
        typer.echo(
            "  Estimated remaining effort: "
            f"{plan.workload_summary.total_remaining_minutes} minute(s); "
            "student selects study times"
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


def _resources(ctx: typer.Context) -> Path:
    if isinstance(ctx.obj, dict) and isinstance(ctx.obj.get("resources"), Path):
        return ctx.obj["resources"]
    return get_runtime_paths().resources_dir


if __name__ == "__main__":
    app()
