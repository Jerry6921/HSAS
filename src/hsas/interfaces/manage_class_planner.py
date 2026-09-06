"""CLI commands for HKU Class Planner authentication and synchronization."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from hsas.application.synchronize_class_planner import (
    ClassPlannerSynchronizationService,
)
from hsas.infrastructure.class_planner import (
    ClassPlannerBrowserGateway,
    class_planner_status,
)
from hsas.infrastructure.runtime import get_runtime_paths


class_planner_app = typer.Typer(
    no_args_is_help=True,
    help="HKU Portal authenticated Class Planner timetable snapshots",
)


@class_planner_app.command("login")
def login(
    ctx: typer.Context,
    timeout_seconds: Annotated[
        int,
        typer.Option("--timeout", min=30, max=900, help="Visible login wait time"),
    ] = 300,
) -> None:
    """Open Class Planner and wait for user-completed HKU Portal sign-in."""
    result = _service(_resources(ctx)).login_until_ready(
        timeout_seconds=timeout_seconds
    )
    terms = ", ".join(result.term_ids) or "unknown"
    typer.echo(
        f"Class Planner login ready: {result.course_count} course(s), term(s) {terms}"
    )


@class_planner_app.command("sync")
def sync(
    ctx: typer.Context,
    timeout_seconds: Annotated[
        int,
        typer.Option("--timeout", min=10, max=900, help="Calendar response wait time"),
    ] = 90,
) -> None:
    """Save a privacy-filtered timetable snapshot using the browser session."""
    result = _service(_resources(ctx)).sync(timeout_seconds=timeout_seconds)
    typer.echo(
        f"Class Planner synced: {result.course_count} course(s), "
        f"{result.meeting_count} meeting(s), changed={str(result.changed).lower()} "
        f"-> {result.output_path}"
    )


@class_planner_app.command("status")
def status(ctx: typer.Context) -> None:
    """Show the latest local Class Planner snapshot summary."""
    value = class_planner_status(_resources(ctx))
    if not value["available"]:
        typer.echo("Class Planner: no local snapshot")
        return
    terms = ", ".join(value["term_ids"]) or "unknown"
    typer.echo(
        f"Class Planner: {value['course_count']} course(s), "
        f"{value['meeting_count']} meeting(s), term(s) {terms}; "
        f"synced={value['synced_at']}"
    )


def _service(resources_dir: Path) -> ClassPlannerSynchronizationService:
    return ClassPlannerSynchronizationService(
        ClassPlannerBrowserGateway(resources_dir)
    )


def _resources(ctx: typer.Context) -> Path:
    if isinstance(ctx.obj, dict) and isinstance(ctx.obj.get("resources"), Path):
        return ctx.obj["resources"]
    return get_runtime_paths().resources_dir
