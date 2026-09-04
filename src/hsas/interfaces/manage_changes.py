"""AI-facing commands for pending Moodle change reviews."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from hsas.application.manage_changes import (
    ChangeQueueError,
    acknowledge_change_batch,
    collect_pending_changes,
)
from hsas.domain.courses.define_change_queue import PendingChangeBatch
from hsas.infrastructure.runtime import get_runtime_paths
from hsas.infrastructure.storage import JsonChangeQueueRepository, JsonInformationRepository
from hsas.infrastructure.storage.persist_data import read_json, write_json


changes_app = typer.Typer(
    no_args_is_help=True,
    help="Inspect and acknowledge Moodle changes awaiting AI review",
)
CHANGE_REPOSITORY = JsonChangeQueueRepository()
INFORMATION_REPOSITORY = JsonInformationRepository()


@changes_app.command("list")
def changes_list(ctx: typer.Context) -> None:
    """Print a compact machine-readable pending-change summary."""
    batch = _pending_batch(_resources(ctx))
    typer.echo(
        json.dumps(
            {
                "pending_course_count": len(batch.courses),
                "pending_change_count": batch.pending_change_count,
                "full_review_course_count": sum(
                    course.mode == "full" for course in batch.courses
                ),
                "courses": [
                    {
                        "course_id": course.course_id,
                        "course_title": course.course_title,
                        "mode": course.mode,
                        "change_count": len(course.changes),
                        "file_count": len(course.files),
                        "acknowledge_through": course.acknowledge_through.isoformat(),
                    }
                    for course in batch.courses
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@changes_app.command("show")
def changes_show(
    ctx: typer.Context,
    output_path: Annotated[
        Path | None,
        typer.Option("--output", help="Save the exact acknowledgement batch as JSON"),
    ] = None,
    course_ids: Annotated[
        list[str] | None,
        typer.Option("--course", help="Restrict the batch to course IDs"),
    ] = None,
) -> None:
    """Show pending changes with the precise local files the AI should read."""
    batch = _pending_batch(_resources(ctx), course_ids=set(course_ids or []))
    payload = batch.model_dump(mode="json")
    if output_path is None:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    write_json(output_path, payload)
    typer.echo(
        f"Pending change batch: {len(batch.courses)} course(s), "
        f"{batch.pending_change_count} review item(s) -> {output_path}"
    )


@changes_app.command("acknowledge")
def changes_acknowledge(
    ctx: typer.Context,
    batch_path: Annotated[Path, typer.Argument(help="Batch produced by changes show")],
    confirmed: Annotated[
        bool,
        typer.Option(help="Confirm every change in the batch was reviewed"),
    ] = False,
    no_information_change: Annotated[
        bool,
        typer.Option(
            "--reviewed-no-information-change",
            help="Confirm review found no information.json update to apply",
        ),
    ] = False,
) -> None:
    """Acknowledge a reviewed batch only when no information update was needed."""
    if not no_information_change:
        raise typer.BadParameter(
            "Use `information apply --changes BATCH` when facts changed; otherwise "
            "pass --reviewed-no-information-change."
        )
    try:
        batch = PendingChangeBatch.model_validate(read_json(batch_path))
        checkpoint = acknowledge_change_batch(
            _resources(ctx),
            batch,
            CHANGE_REPOSITORY,
            confirmed=confirmed,
        )
    except (OSError, ValueError, ChangeQueueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        f"Changes acknowledged through {checkpoint.updated_at.isoformat()} "
        f"for {len(batch.courses)} course(s)"
    )


def _pending_batch(
    resources: Path,
    *,
    course_ids: set[str] | None = None,
) -> PendingChangeBatch:
    information = None
    information_path = resources / "information.json"
    if INFORMATION_REPOSITORY.exists(information_path):
        information = INFORMATION_REPOSITORY.load(information_path)
    return collect_pending_changes(
        resources,
        CHANGE_REPOSITORY,
        information=information,
        course_ids=course_ids,
    )


def _resources(ctx: typer.Context) -> Path:
    root = ctx.find_root()
    if isinstance(root.obj, dict) and isinstance(root.obj.get("resources"), Path):
        return root.obj["resources"]
    return get_runtime_paths().resources_dir
