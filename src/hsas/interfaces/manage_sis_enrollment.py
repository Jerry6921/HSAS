"""CLI commands for SIS Student Center enrolment review."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from hsas.infrastructure.fetch_sis_enrollment import SisEnrollmentBrowserGateway
from hsas.infrastructure.manage_sis_enrollment import (
    SisEnrollmentReviewError,
    acknowledge_sis_enrollment_changes,
    collect_sis_enrollment_changes,
)
from hsas.infrastructure.runtime import get_runtime_paths
from hsas.infrastructure.storage.persist_data import read_json, write_json


sis_enrollment_app = typer.Typer(
    no_args_is_help=True,
    help="HKU SIS Student Center enrolment snapshots and AI review queue",
)


@sis_enrollment_app.command("sync")
def sync(ctx: typer.Context) -> None:
    """Capture the current-semester course list, opening sign-in when required."""
    result = SisEnrollmentBrowserGateway(_resources(ctx)).sync(auto_login=True)
    typer.echo(
        f"Student Center: {len(result['courses'])} course(s); "
        f"term={result.get('term') or 'unknown'}"
    )


@sis_enrollment_app.command("status")
def status(ctx: typer.Context) -> None:
    """Show the local enrolment snapshot and pending review count."""
    resources = _resources(ctx)
    value = SisEnrollmentBrowserGateway(resources).status()
    review = collect_sis_enrollment_changes(resources)
    typer.echo(
        f"Student Center: {value['course_count']} course(s); "
        f"term={value.get('term') or 'unknown'}; "
        f"pending review={review['pending_change_count']}"
    )


@sis_enrollment_app.command("changes")
def changes(
    ctx: typer.Context,
    output_path: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Export the current enrolment batch for AI review."""
    batch = collect_sis_enrollment_changes(_resources(ctx))
    if output_path is not None:
        write_json(output_path, batch)
        typer.echo(f"Student Center review batch -> {output_path}")
    typer.echo(f"Student Center review: {batch['pending_change_count']} change(s)")


@sis_enrollment_app.command("acknowledge")
def acknowledge(
    ctx: typer.Context,
    batch_path: Annotated[Path, typer.Argument()],
    confirmed: Annotated[bool, typer.Option("--confirmed")] = False,
) -> None:
    """Advance the enrolment checkpoint after a completed review."""
    try:
        batch = read_json(batch_path)
        if not isinstance(batch, dict):
            raise SisEnrollmentReviewError("Student Center batch must be a JSON object")
        checkpoint = acknowledge_sis_enrollment_changes(
            _resources(ctx), batch, confirmed=confirmed
        )
    except (OSError, ValueError, SisEnrollmentReviewError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"Student Center checkpoint -> {checkpoint['content_sha256']}")


def _resources(ctx: typer.Context) -> Path:
    if isinstance(ctx.obj, dict) and isinstance(ctx.obj.get("resources"), Path):
        return ctx.obj["resources"]
    return get_runtime_paths().resources_dir
