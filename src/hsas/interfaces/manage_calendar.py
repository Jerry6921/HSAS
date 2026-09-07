"""Calendar export commands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from hsas.domain.information.generate_calendar import build_ics
from hsas.infrastructure.runtime import get_runtime_paths
from hsas.infrastructure.storage import JsonInformationRepository
from hsas.infrastructure.storage.persist_data import write_text


calendar_app = typer.Typer(no_args_is_help=True, help="Export the HIQS calendar")
INFORMATION_REPOSITORY = JsonInformationRepository()


@calendar_app.command("export")
def export_calendar(
    ctx: typer.Context,
    output_path: Annotated[
        Path,
        typer.Argument(help="Destination .ics file"),
    ] = Path("HIQS-calendar.ics"),
) -> None:
    """Export all dated course information to an iCalendar file."""
    resources = _resources(ctx)
    information_path = resources / "information.json"
    if not INFORMATION_REPOSITORY.exists(information_path):
        raise typer.BadParameter("information.json is unavailable")
    store = INFORMATION_REPOSITORY.load(information_path)
    write_text(output_path, build_ics(store))
    typer.echo(f"Calendar exported: {output_path}")


def _resources(ctx: typer.Context) -> Path:
    if isinstance(ctx.obj, dict) and isinstance(ctx.obj.get("resources"), Path):
        return ctx.obj["resources"]
    return get_runtime_paths().resources_dir
