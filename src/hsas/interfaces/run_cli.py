"""Unified HSAS command-line interface."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from .handle_commands import execution_app, materials_app, profile_app
from .run_dashboard import serve_dashboard
from hsas.application import PlanGenerationError, assess_plan_freshness
from hsas.infrastructure.runtime import (
    MigrationError,
    ensure_resources_layout,
    get_runtime_paths,
    migrate_legacy_data,
)
from hsas.domain.planning.define_execution import ExecutionLog
from hsas.domain.planning.define_plan import IntegratedPlan
from hsas.domain.planning.define_profile import StudentProfile
from hsas.application.orchestrate_plans import generate_plan
from hsas.infrastructure.moodle.load_settings import Settings
from hsas.domain.courses.detect_changes import CourseChangeSet
from hsas.application.synchronize_courses import CourseSynchronizationService
from hsas.infrastructure.moodle.synchronize_courses import MoodleCourseGateway
from hsas.infrastructure.storage import JsonPlanningRepository
from hsas.infrastructure.updates import UpdateError, update_installation


PROJECT_ROOT = Path(__file__).resolve().parents[3]
PLANNING_REPOSITORY = JsonPlanningRepository()

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
    """Resolve and initialize shared runtime paths for this command invocation."""
    if resources_dir is None:
        resources = get_runtime_paths().create().resources_dir
    else:
        resources = ensure_resources_layout(resources_dir)
    ctx.obj = {
        "resources": resources,
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
    _show_course_catalog(list_courses(Settings.load(output_dir=resources_dir)))
    typer.echo("\nPlanning status:")
    _show_profile(resources_dir / "student_profile.json")
    _show_execution_log(resources_dir / "execution_log.json")
    _show_plan(resources_dir / "integrated_plan.json")
    _show_plan_freshness(resources_dir)
    _show_changes(resources_dir / "courses")


@app.command("login")
def login() -> None:
    """Open Moodle and persist the user-completed SSO/MFA session."""
    login_to_moodle()


@app.command("ui")
def ui(
    ctx: typer.Context,
    port: Annotated[
        int,
        typer.Option(min=0, max=65535, help="Local TCP port; use 0 for an available port"),
    ] = 8765,
    open_browser: Annotated[
        bool,
        typer.Option("--open/--no-open", help="Open the dashboard in the default browser"),
    ] = True,
) -> None:
    """Run the private HSAS dashboard on this Mac only."""
    serve_dashboard(_resources(ctx), port=port, open_browser=open_browser)


@app.command("sync-courses")
def sync_courses(
    ctx: typer.Context,
    course: Annotated[
        str | None,
        typer.Argument(
            help="Optional Moodle course ID or URL; omit to sync all courses"
        ),
    ] = None,
    replan: Annotated[
        bool,
        typer.Option("--replan/--no-replan", help="Refresh the Plan after a successful sync"),
    ] = True,
) -> None:
    """Sync one course when specified, otherwise sync every available course."""
    settings = Settings.load(output_dir=_resources(ctx))
    if course is None:
        result = sync_all(settings)
        if result is not None:
            typer.echo(
                f"Synced {len(result.succeeded_course_ids)}/{result.discovered_course_count} "
                f"courses; {len(result.failures)} failed -> {result.report_path}"
            )
    else:
        result = sync_course(course, settings)
        if result is not None:
            typer.echo(
                f"Synced {result.course_title}: {result.change_count} change(s) -> "
                f"{result.output_path}"
            )
    if replan and result is not None:
        _refresh_plan_if_ready(settings.output_dir)


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
    try:
        result = generate_plan(
            profile_path=profile_path or resources_dir / "student_profile.json",
            output_path=output_path or resources_dir / "integrated_plan.json",
            resources_dir=resources_dir,
            execution_path=execution_path or resources_dir / "execution_log.json",
            days=days,
            start=start,
            fresh=fresh,
            repository=PLANNING_REPOSITORY,
        )
    except (PlanGenerationError, ValueError) as exc:
        if isinstance(exc, PlanGenerationError) and exc.report is not None:
            _print_validation_report(exc.report)
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        f"Plan updated: {len(result.plan.items)} key item(s), "
        f"{result.plan.workload_summary.total_remaining_minutes} estimated minute(s); "
        f"study times remain student-selected -> {result.output_path}"
    )
    _print_validation_report(result.report)


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
    expected_commit: Annotated[
        str | None,
        typer.Option(
            "--commit",
            help="Exact 40-character commit shown by a prior dry run",
        ),
    ] = None,
) -> None:
    """Inspect or apply an exact HSAS commit while preserving local data."""
    typer.echo("Inspecting release source: https://github.com/Jerry6921/HSAS (main)")
    try:
        result = update_installation(
            PROJECT_ROOT,
            dry_run=dry_run,
            expected_commit=expected_commit,
        )
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
    else:
        typer.echo(f"To apply exactly this release, rerun with `--commit {result.commit}`.")


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


def _show_plan_freshness(resources_dir: Path) -> None:
    freshness = assess_plan_freshness(resources_dir, PLANNING_REPOSITORY)
    typer.echo(f"  Plan freshness: {'current' if freshness.current else 'stale'}")
    for reason in freshness.reasons:
        typer.echo(f"    - {reason}")


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


def _refresh_plan_if_ready(resources_dir: Path) -> None:
    if not (resources_dir / "student_profile.json").is_file():
        typer.echo("Plan refresh deferred: Student Profile does not exist.")
        return
    try:
        result = generate_plan(
            resources_dir=resources_dir,
            repository=PLANNING_REPOSITORY,
        )
    except (PlanGenerationError, ValueError) as exc:
        typer.echo(f"Plan refresh deferred; existing Plan retained: {exc}", err=True)
        return
    typer.echo(
        f"Plan refreshed and validated: {len(result.plan.items)} key item(s) -> "
        f"{result.output_path}"
    )


def _print_validation_report(report) -> None:
    typer.echo(
        f"Validation: {'valid' if report.valid else 'invalid'}; "
        f"{len(report.errors)} error(s), {len(report.warnings)} warning(s)"
    )
    for issue in [*report.errors, *report.warnings]:
        paths = f" [{', '.join(issue.paths)}]" if issue.paths else ""
        typer.echo(f"  {issue.severity.upper()} {issue.code}: {issue.message}{paths}")


def _course_service(settings: Settings | None = None) -> CourseSynchronizationService:
    return CourseSynchronizationService(
        MoodleCourseGateway(
            settings,
            notify=typer.echo,
            wait_for_user=input,
        )
    )


def login_to_moodle() -> None:
    _course_service().login()


def list_courses(settings: Settings):
    return _course_service(settings).list_courses()


def sync_course(course: str, settings: Settings):
    return _course_service(settings).sync_course(course)


def sync_all(settings: Settings):
    return _course_service(settings).sync_all()


def _show_course_catalog(catalog) -> None:
    typer.echo(f"Login status: {catalog.login_status}")
    if catalog.login_error:
        typer.echo(f"Login check error: {catalog.login_error}")
    typer.echo(f"\nAvailable courses ({len(catalog.available)}):")
    if not catalog.available:
        typer.echo("  None. Run `hsas login` if the session expired.")
    for course in catalog.available:
        local_status = "downloaded" if course.downloaded else "not downloaded"
        typer.echo(f"  {course.course_id} [{local_status}] {course.title}")
        if course.url:
            typer.echo(f"    {course.url}")
    typer.echo(f"\nDownloaded courses ({len(catalog.downloaded)}):")
    if not catalog.downloaded:
        typer.echo("  None")
    for course in catalog.downloaded:
        typer.echo(f"  {course.course_id} {course.title}")


if __name__ == "__main__":
    app()
