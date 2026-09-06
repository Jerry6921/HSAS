"""CLI for staged personal course-information updates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from hsas.application.manage_inbox import (
    PersonalInboxError,
    add_personal_inbox_entry,
    apply_personal_inbox_entry,
    load_personal_inbox,
    personal_inbox_snapshot,
)
from hsas.infrastructure.runtime import get_runtime_paths
from hsas.infrastructure.storage import JsonInformationRepository, JsonPersonalInboxRepository
from hsas.infrastructure.storage.persist_data import read_json


inbox_app = typer.Typer(
    no_args_is_help=True,
    help="Stage and review user-provided course information",
)
INBOX_REPOSITORY = JsonPersonalInboxRepository()
INFORMATION_REPOSITORY = JsonInformationRepository()


@inbox_app.command("add")
def inbox_add(
    ctx: typer.Context,
    update_path: Annotated[Path, typer.Argument(help="Validated InformationUpdate JSON")],
    title: Annotated[str, typer.Option("--title", help="Short user-facing draft title")],
    note: Annotated[str | None, typer.Option("--note", help="Optional context from the user")] = None,
) -> None:
    """Add an AI-prepared personal update to the preview inbox."""
    try:
        entry = add_personal_inbox_entry(
            _resources(ctx),
            read_json(update_path),
            title=title,
            note=note,
            repository=INBOX_REPOSITORY,
        )
    except (OSError, ValueError, PersonalInboxError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"Personal inbox draft added: {entry.entry_id}")


@inbox_app.command("list")
def inbox_list(ctx: typer.Context) -> None:
    """Show pending drafts and their field-level preview."""
    try:
        value = personal_inbox_snapshot(
            _resources(ctx),
            inbox_repository=INBOX_REPOSITORY,
            information_repository=INFORMATION_REPOSITORY,
        )
    except (OSError, ValueError, PersonalInboxError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2))


@inbox_app.command("show")
def inbox_show(
    ctx: typer.Context,
    entry_id: Annotated[str, typer.Argument(help="Personal inbox entry ID")],
) -> None:
    """Print the complete validated update stored in one draft."""
    inbox = load_personal_inbox(_resources(ctx), INBOX_REPOSITORY)
    entry = next((value for value in inbox.entries if value.entry_id == entry_id), None)
    if entry is None:
        raise typer.BadParameter(f"Personal inbox entry was not found: {entry_id}")
    typer.echo(entry.model_dump_json(indent=2))


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
        result = apply_personal_inbox_entry(
            _resources(ctx),
            entry_id,
            confirmed=confirmed,
            inbox_repository=INBOX_REPOSITORY,
            information_repository=INFORMATION_REPOSITORY,
        )
    except (OSError, ValueError, PersonalInboxError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        "Personal inbox draft applied: "
        f"courses +{result.created_courses}/~{result.updated_courses}, "
        f"items +{result.created_items}/~{result.updated_items}"
    )


def _resources(ctx: typer.Context) -> Path:
    if isinstance(ctx.obj, dict) and isinstance(ctx.obj.get("resources"), Path):
        return ctx.obj["resources"]
    return get_runtime_paths().resources_dir
