"""AI-facing CLI commands for validated course information."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from hsas.application.information import (
    InformationServiceError,
    build_information_template,
    load_information,
)
from hsas.core import HIQSPortError, build_port
from hsas.domain.information import InformationUpdate
from hsas.infrastructure.runtime import get_runtime_paths
from hsas.infrastructure.storage import JsonInformationRepository
from hsas.infrastructure.storage.json_store import read_json, write_json
from hsas.codegen.typescript import schema_to_typescript


information_app = typer.Typer(
    no_args_is_help=True,
    help="Validate and write AI-authored course information",
)
INFORMATION_REPOSITORY = JsonInformationRepository()


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
    ctx: typer.Context,
    update_path: Annotated[
        Path,
        typer.Argument(help="AI-authored information update JSON"),
    ],
) -> None:
    """Validate an update without changing the local database."""
    try:
        result = build_port(_resources(ctx)).validate_information_update(
            {"update": read_json(update_path)}
        )
    except (OSError, ValueError, InformationServiceError, HIQSPortError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        f"Information update valid: {result['course_count']} course(s), "
        f"{result['item_count']} item(s)"
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
    class_planner_changes_path: Annotated[
        Path | None,
        typer.Option(
            "--class-planner-changes",
            help="Class Planner batch to checkpoint after this update succeeds",
        ),
    ] = None,
    sis_course_info_changes_path: Annotated[
        Path | None,
        typer.Option(
            "--sis-course-info-changes",
            help="HKU SIS course-information batch to checkpoint after this update succeeds",
        ),
    ] = None,
    sis_enrollment_changes_path: Annotated[
        Path | None,
        typer.Option(
            "--sis-enrollment-changes",
            help="Student Center enrolment batch to checkpoint after this update succeeds",
        ),
    ] = None,
) -> None:
    """Atomically upsert reviewed course facts into information.json."""
    resources = _resources(ctx)
    path = information_path or resources / "information.json"
    if path != resources / "information.json":
        raise typer.BadParameter(
            "--information may only select the canonical file inside --resources; "
            "use a separate --resources directory for isolated data."
        )
    try:
        review_batches = {
            source: read_json(batch_path)
            for source, batch_path in (
                ("moodle", changes_path),
                ("class_planner", class_planner_changes_path),
                ("sis_course_info", sis_course_info_changes_path),
                ("sis_enrollment", sis_enrollment_changes_path),
            )
            if batch_path is not None
        }
        result = build_port(resources).apply_information_update(
            {
                "update": read_json(update_path),
                "review_batches": review_batches,
                "confirmed": confirmed,
            }
        )
    except (OSError, ValueError, InformationServiceError, HIQSPortError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        "Information updated atomically: "
        f"courses +{result['created_courses']}/~{result['updated_courses']}, "
        f"items +{result['created_items']}/~{result['updated_items']} -> {path}"
    )
    audit = result["recent_update"]
    typer.echo(
        "Recent update report saved: "
        f"{audit['summary']['change_count']} field change(s), "
        f"{audit['summary']['course_count']} course(s)"
    )
    checkpoints = result["checkpoints"]
    if "moodle" in checkpoints:
        checkpoint = checkpoints["moodle"]
        typer.echo(
            "Reviewed Moodle changes acknowledged: "
            f"checkpoint={checkpoint['updated_at']}"
        )
    if "class_planner" in checkpoints:
        checkpoint = checkpoints["class_planner"]
        typer.echo(
            "Reviewed Class Planner changes acknowledged: "
            f"checkpoint={checkpoint['acknowledged_through']}"
        )
    if "sis_course_info" in checkpoints:
        checkpoint = checkpoints["sis_course_info"]
        typer.echo(
            "Reviewed HKU SIS course-information changes acknowledged: "
            f"checkpoint={checkpoint['acknowledged_through']}"
        )
    if "sis_enrollment" in checkpoints:
        checkpoint = checkpoints["sis_enrollment"]
        typer.echo(
            "Reviewed Student Center enrolment changes acknowledged: "
            f"checkpoint={checkpoint['content_sha256']}"
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


@information_app.command("types")
def information_types(
    ctx: typer.Context,
    output_path: Annotated[
        Path,
        typer.Argument(help="Destination TypeScript declaration file"),
    ] = Path("ui/src/generated/information-schema.ts"),
    force: Annotated[bool, typer.Option(help="Replace an existing generated file")] = False,
) -> None:
    """Generate deterministic TypeScript types from the canonical Pydantic schema."""
    if output_path.exists() and not force:
        raise typer.BadParameter("Output already exists; use --force to replace it.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    schema = InformationUpdate.model_json_schema()
    output_path.write_text(schema_to_typescript(schema), encoding="utf-8")
    typer.echo(f"TypeScript types -> {output_path}")


def _resources(ctx: typer.Context) -> Path:
    if isinstance(ctx.obj, dict) and isinstance(ctx.obj.get("resources"), Path):
        return ctx.obj["resources"]
    return get_runtime_paths().resources_dir
