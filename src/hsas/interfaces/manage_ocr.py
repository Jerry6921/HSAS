"""CLI for the local document OCR queue."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from hsas.infrastructure.documents.run_ocr import (
    collect_ocr_queue,
    ocr_capabilities,
    run_ocr_queue,
)
from hsas.infrastructure.runtime import get_runtime_paths


ocr_app = typer.Typer(no_args_is_help=True, help="Inspect and process the local OCR queue")


@ocr_app.command("status")
def ocr_status(ctx: typer.Context) -> None:
    """Print OCR capability and queued documents."""
    resources = _resources(ctx)
    typer.echo(
        json.dumps(
            {"capabilities": ocr_capabilities(), "queue": collect_ocr_queue(resources)},
            ensure_ascii=False,
            indent=2,
        )
    )


@ocr_app.command("run")
def ocr_run(
    ctx: typer.Context,
    course_ids: Annotated[
        list[str] | None,
        typer.Option("--course", help="Restrict OCR to Moodle course IDs"),
    ] = None,
    confirmed: Annotated[
        bool,
        typer.Option("--confirmed", help="Confirm local batch OCR and sidecar updates"),
    ] = False,
) -> None:
    """Run local OCR for every queued PDF and image-based PPTX."""
    if not confirmed:
        raise typer.BadParameter("OCR queue processing requires --confirmed")
    result = run_ocr_queue(
        _resources(ctx),
        course_ids=set(course_ids) if course_ids else None,
    )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


def _resources(ctx: typer.Context) -> Path:
    if isinstance(ctx.obj, dict) and isinstance(ctx.obj.get("resources"), Path):
        return ctx.obj["resources"]
    return get_runtime_paths().resources_dir
