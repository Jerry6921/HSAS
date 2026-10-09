"""CLI for staged personal course-information updates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from hsas.core import HIQSPortError, build_port
from hsas.infrastructure.runtime import get_runtime_paths
from hsas.infrastructure.storage.json_store import read_json


inbox_app = typer.Typer(
    no_args_is_help=True,
    help="Stage and review user-provided course information",
)
@inbox_app.command("add")
def inbox_add(
    ctx: typer.Context,
    update_path: Annotated[Path, typer.Argument(help="Validated InformationUpdate JSON")],
    title: Annotated[str, typer.Option("--title", help="Short user-facing draft title")],
    note: Annotated[str | None, typer.Option("--note", help="Optional context from the user")] = None,
) -> None:
    """Add an AI-prepared personal update to the preview inbox."""
    try:
        result = build_port(_resources(ctx)).add_personal_inbox(
            {"update": read_json(update_path), "title": title, "note": note}
        )
    except (OSError, ValueError, HIQSPortError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"Personal inbox draft added: {result['entry_id']}")


@inbox_app.command("list")
def inbox_list(ctx: typer.Context) -> None:
    """Show pending drafts and their field-level preview."""
    try:
        value = build_port(_resources(ctx)).personal_inbox_snapshot()
    except (OSError, ValueError, HIQSPortError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2))


@inbox_app.command("show")
def inbox_show(
    ctx: typer.Context,
    entry_id: Annotated[str, typer.Argument(help="Personal inbox entry ID")],
) -> None:
    """Print the complete validated update stored in one draft."""
    try:
        value = build_port(_resources(ctx)).personal_inbox_entry(entry_id)
    except (OSError, ValueError, HIQSPortError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2))


@inbox_app.command("apply")
def inbox_apply(
    ctx: typer.Context,
    entry_id: Annotated[str, typer.Argument(help="Personal inbox entry ID")],
    confirmed: Annotated[
        bool,
        typer.Option("--confirmed", help="Confirm the displayed draft changes"),
    ] = False,
) -> None:
    """Apply one reviewed draft to information.json and mark it complete."""
    try:
        result = build_port(_resources(ctx)).apply_personal_inbox(
            {"entry_id": entry_id, "confirmed": confirmed}
        )
    except (OSError, ValueError, HIQSPortError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        "Personal inbox draft applied: "
        f"courses +{result['created_courses']}/~{result['updated_courses']}, "
        f"items +{result['created_items']}/~{result['updated_items']}"
    )


def _resources(ctx: typer.Context) -> Path:
    if isinstance(ctx.obj, dict) and isinstance(ctx.obj.get("resources"), Path):
        return ctx.obj["resources"]
    return get_runtime_paths().resources_dir
