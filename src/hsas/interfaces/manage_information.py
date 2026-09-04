"""AI-facing CLI commands for validated course information."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from hsas.application.update_information import (
    InformationServiceError,
    apply_information_update,
    build_information_template,
    load_information,
    validate_information_update,
)
from hsas.application.manage_changes import (
    ChangeQueueError,
    acknowledge_change_batch,
    validate_change_batch,
)
from hsas.domain.courses.define_change_queue import PendingChangeBatch
from hsas.domain.information import InformationUpdate
from hsas.infrastructure.runtime import get_runtime_paths
from hsas.infrastructure.storage import JsonChangeQueueRepository, JsonInformationRepository
from hsas.infrastructure.storage.persist_data import read_json, write_json


information_app = typer.Typer(
    no_args_is_help=True,
    help="Validate and write AI-authored course information",
)
INFORMATION_REPOSITORY = JsonInformationRepository()
CHANGE_REPOSITORY = JsonChangeQueueRepository()


@information_app.command("show")
def information_show(
    ctx: typer.Context,
    information_path: Annotated[
        Path | None,
        typer.Option("--information", help="Information database JSON path"),
    ] = None,
) -> None:
    """Print the validated information database."""
    path = information_path or _resources(ctx) / "information.json"
    try:
        store = load_information(path, INFORMATION_REPOSITORY)
    except InformationServiceError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(store.model_dump_json(indent=2))


@information_app.command("validate")
def information_validate(
    update_path: Annotated[
        Path,
        typer.Argument(help="AI-authored information update JSON"),
    ],
) -> None:
    """Validate an update without changing the local database."""
    try:
        update = validate_information_update(read_json(update_path))
    except (OSError, ValueError, InformationServiceError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        f"Information update valid: {len(update.courses)} course(s), "
        f"{len(update.items)} item(s)"
    )


@information_app.command("apply")
def information_apply(
    ctx: typer.Context,
    update_path: Annotated[
        Path,
        typer.Argument(help="Validated JSON prepared from course sources"),
    ],
    information_path: Annotated[
        Path | None,
        typer.Option("--information", help="Information database JSON path"),
    ] = None,
    confirmed: Annotated[
        bool,
        typer.Option(
            "--confirmed",
            help="Confirm that the update was reviewed against its cited sources",
        ),
    ] = False,
    changes_path: Annotated[
        Path | None,
        typer.Option(
            "--changes",
            help="Pending batch to acknowledge only after this update succeeds",
        ),
    ] = None,
) -> None:
    """Atomically upsert reviewed course facts into information.json."""
    resources = _resources(ctx)
    path = information_path or resources / "information.json"
    batch: PendingChangeBatch | None = None
    try:
        payload = read_json(update_path)
        if changes_path is not None:
            batch = PendingChangeBatch.model_validate(read_json(changes_path))
            validate_change_batch(resources, batch, CHANGE_REPOSITORY)
            update = validate_information_update(payload)
            if not update.courses and not update.items:
                raise ChangeQueueError(
                    "an empty information update cannot acknowledge Moodle changes; "
                    "use `changes acknowledge --reviewed-no-information-change`"
                )
        result = apply_information_update(
            path,
            payload,
            confirmed=confirmed,
            repository=INFORMATION_REPOSITORY,
        )
    except (OSError, ValueError, InformationServiceError, ChangeQueueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        "Information updated atomically: "
        f"courses +{result.created_courses}/~{result.updated_courses}, "
        f"items +{result.created_items}/~{result.updated_items} -> {path}"
    )
    if batch is not None:
        try:
            checkpoint = acknowledge_change_batch(
                resources,
                batch,
                CHANGE_REPOSITORY,
                confirmed=confirmed,
            )
        except (OSError, ValueError, ChangeQueueError) as exc:
            typer.echo(
                "Information was saved, but the Moodle changes remain pending: "
                f"{exc}",
                err=True,
            )
            raise typer.Exit(code=1) from exc
        typer.echo(
            f"Reviewed Moodle changes acknowledged: {len(batch.courses)} course(s); "
            f"checkpoint={checkpoint.updated_at.isoformat()}"
        )


@information_app.command("template")
def information_template(
    output_path: Annotated[
        Path,
        typer.Argument(help="Destination for a schema-valid example update"),
    ] = Path("information-update.json"),
    force: Annotated[
        bool,
        typer.Option(help="Replace an existing template file"),
    ] = False,
) -> None:
    """Create a ready-to-edit JSON update template for an AI agent."""
    if output_path.exists() and not force:
        raise typer.BadParameter("Output already exists; use --force to replace it.")
    write_json(output_path, build_information_template().model_dump(mode="json"))
    typer.echo(f"Information update template -> {output_path}")


@information_app.command("schema")
def information_schema(
    output_path: Annotated[
        Path | None,
        typer.Argument(help="Optional JSON Schema output path"),
    ] = None,
) -> None:
    """Print or save the exact JSON Schema accepted by the update command."""
    schema = InformationUpdate.model_json_schema()
    if output_path is None:
        typer.echo(json.dumps(schema, ensure_ascii=False, indent=2))
        return
    if output_path.exists():
        raise typer.BadParameter("Output already exists; choose a new path.")
    write_json(output_path, schema)
    typer.echo(f"Information update JSON Schema -> {output_path}")


def _resources(ctx: typer.Context) -> Path:
    if isinstance(ctx.obj, dict) and isinstance(ctx.obj.get("resources"), Path):
        return ctx.obj["resources"]
    return get_runtime_paths().resources_dir
