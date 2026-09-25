"""AI-facing commands for locally downloaded course materials."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from hsas.application.material_search import list_materials, search_materials
from hsas.infrastructure.runtime import get_runtime_paths


materials_app = typer.Typer(
    no_args_is_help=True,
    help="List and search locally downloaded course materials",
)


@materials_app.command("list")
def materials_list(
    ctx: typer.Context,
    course_ids: Annotated[
        list[str] | None,
        typer.Option("--course", help="Restrict the manifest to course IDs"),
    ] = None,
) -> None:
    """Print a machine-readable manifest of every locally downloaded file."""
    resources = _resources(ctx)
    try:
        payload = list_materials(
            resources,
            course_ids=set(course_ids) if course_ids else None,
        )
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )
    )


@materials_app.command("search")
def materials_search(
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(help="Concept or question to retrieve")],
    course_ids: Annotated[
        list[str] | None,
        typer.Option("--course", help="Restrict retrieval to course IDs"),
    ] = None,
    limit: Annotated[
        int,
        typer.Option(min=1, max=20, help="Maximum returned chunks"),
    ] = 6,
) -> None:
    """Search extracted course text and return page-aware JSON evidence."""
    try:
        result = search_materials(
            _resources(ctx),
            query,
            course_ids=set(course_ids) if course_ids else None,
            limit=limit,
        )
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(result.model_dump_json(indent=2))


def _resources(ctx: typer.Context) -> Path:
    root = ctx.find_root()
    if isinstance(root.obj, dict) and isinstance(root.obj.get("resources"), Path):
        return root.obj["resources"]
    return get_runtime_paths().resources_dir
