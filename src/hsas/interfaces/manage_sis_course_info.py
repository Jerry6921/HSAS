"""CLI commands for authenticated HKU SIS course-information collection."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from hsas.application.synchronize_course_information import (
    SisCourseInfoSynchronizationService,
)
from hsas.infrastructure.runtime import get_runtime_paths
from hsas.infrastructure.sis_course_info import (
    SisCourseInfoBrowserGateway,
    sis_course_info_status,
)
from hsas.infrastructure.sis_course_info.manage_changes import (
    SisCourseInfoReviewError,
    acknowledge_sis_course_info_changes,
    collect_sis_course_info_changes,
)
from hsas.infrastructure.storage.persist_data import read_json, write_json


sis_course_info_app = typer.Typer(
    no_args_is_help=True,
    help="Official HKU SIS course pages collected from Moodle course codes",
)


@sis_course_info_app.command("login")
def login(
    ctx: typer.Context,
    timeout_seconds: Annotated[int, typer.Option("--timeout", min=30, max=900)] = 300,
) -> None:
    """Open HKU SIS and wait for user-completed HKU Portal sign-in."""
    result = _service(_resources(ctx)).login_until_ready(timeout_seconds=timeout_seconds)
    typer.echo(
        f"HKU SIS login ready for {result.available_course_count} Moodle course code(s)"
    )


@sis_course_info_app.command("sync")
def sync(
    ctx: typer.Context,
    timeout_seconds: Annotated[int, typer.Option("--timeout", min=10, max=900)] = 90,
) -> None:
    """Collect cleaned official course pages for every Moodle course code."""
    result = _service(_resources(ctx)).sync(timeout_seconds=timeout_seconds)
    typer.echo(
        f"HKU SIS course information: {len(result.succeeded_course_codes)}/"
        f"{result.discovered_course_count} collected, "
        f"{len(result.unchanged_course_codes)} unchanged, "
        f"{len(result.failures)} failed -> {result.output_path}"
    )


@sis_course_info_app.command("status")
def status(ctx: typer.Context) -> None:
    """Show the local official-course-information source status."""
    value = sis_course_info_status(_resources(ctx))
    if not value["available"]:
        typer.echo("HKU SIS course information: no local snapshot")
        return
    review = collect_sis_course_info_changes(_resources(ctx))
    typer.echo(
        f"HKU SIS course information: {value['course_count']} course(s), "
        f"{value['failure_count']} failure(s); synced={value['synced_at']}; "
        f"pending review={review['pending_change_count']}"
    )


@sis_course_info_app.command("changes")
def changes(
    ctx: typer.Context,
    output_path: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Export official course pages awaiting AI review."""
    batch = collect_sis_course_info_changes(_resources(ctx))
    if output_path is not None:
        write_json(output_path, batch)
        typer.echo(f"HKU SIS review batch -> {output_path}")
    typer.echo(
        f"HKU SIS review: {batch['pending_change_count']} course page(s) "
        f"across {batch['pending_snapshot_count']} snapshot(s)"
    )


@sis_course_info_app.command("acknowledge")
def acknowledge(
    ctx: typer.Context,
    batch_path: Annotated[Path, typer.Argument()],
    confirmed: Annotated[bool, typer.Option("--confirmed")] = False,
) -> None:
    """Advance the checkpoint after AI reviewed a batch with no fact changes."""
    try:
        batch = read_json(batch_path)
        if not isinstance(batch, dict):
            raise SisCourseInfoReviewError("HKU SIS batch must be a JSON object")
        checkpoint = acknowledge_sis_course_info_changes(
            _resources(ctx), batch, confirmed=confirmed
        )
    except (OSError, ValueError, SisCourseInfoReviewError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"HKU SIS checkpoint -> {checkpoint['acknowledged_through']}")


def _service(resources_dir: Path) -> SisCourseInfoSynchronizationService:
    return SisCourseInfoSynchronizationService(SisCourseInfoBrowserGateway(resources_dir))


def _resources(ctx: typer.Context) -> Path:
    if isinstance(ctx.obj, dict) and isinstance(ctx.obj.get("resources"), Path):
        return ctx.obj["resources"]
    return get_runtime_paths().resources_dir
