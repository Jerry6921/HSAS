"""Thin AI-facing CLI adapters for Profile and execution services."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from hsas.application import (
    PlanGenerationError,
    PlanGenerationRequest,
    generate_validated_plan,
)
from hsas.application.record_execution import (
    ExecutionServiceError,
    add_execution_record,
    correct_execution_record,
    load_execution_log,
)
from hsas.application.update_profile import (
    ProfileServiceError,
    apply_profile_patch,
    load_profile,
)
from hsas.infrastructure.runtime import get_runtime_paths
from hsas.application.retrieve_materials import search_for_plan_item, search_materials
from hsas.infrastructure.storage.persist_data import read_json


profile_app = typer.Typer(
    no_args_is_help=True,
    help="Manage confirmed Student Profile data",
)
execution_app = typer.Typer(
    no_args_is_help=True,
    help="Manage confirmed study execution data",
)
materials_app = typer.Typer(
    no_args_is_help=True,
    help="Retrieve grounded excerpts from local course materials",
)


@profile_app.command("show")
def profile_show(
    ctx: typer.Context,
    profile_path: Annotated[
        Path | None,
        typer.Option("--profile", help="Student Profile JSON path"),
    ] = None,
) -> None:
    """Print the validated Student Profile as JSON."""
    profile_path = profile_path or _resources(ctx) / "student_profile.json"
    try:
        profile = load_profile(profile_path)
    except ProfileServiceError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(profile.model_dump_json(indent=2))


@profile_app.command("validate")
def profile_validate(
    ctx: typer.Context,
    profile_path: Annotated[
        Path | None,
        typer.Option("--profile", help="Student Profile JSON path"),
    ] = None,
) -> None:
    """Validate the complete Student Profile without changing it."""
    profile_path = profile_path or _resources(ctx) / "student_profile.json"
    try:
        profile = load_profile(profile_path)
    except ProfileServiceError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        f"Profile valid: status={profile.profile_status}; "
        f"updated={profile.updated_at or 'never'}"
    )


@profile_app.command("apply")
def profile_apply(
    ctx: typer.Context,
    patch_path: Annotated[
        Path,
        typer.Argument(help="JSON file containing a minimal Profile patch"),
    ],
    profile_path: Annotated[
        Path | None,
        typer.Option("--profile", help="Student Profile JSON path"),
    ] = None,
    confirmed: Annotated[
        bool,
        typer.Option(
            "--confirmed",
            help="Assert that the student explicitly confirmed this patch",
        ),
    ] = False,
) -> None:
    """Apply one explicitly confirmed, validated Profile patch."""
    resources = _resources(ctx)
    profile_path = profile_path or resources / "student_profile.json"
    try:
        patch = read_json(patch_path)
        profile, changed = apply_profile_patch(
            profile_path,
            patch,
            confirmed=confirmed,
        )
    except (OSError, ValueError, ProfileServiceError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        f"Profile updated atomically: {', '.join(changed)}; "
        f"status={profile.profile_status} -> {profile_path}"
    )
    if profile_path.resolve() == (resources / "student_profile.json").resolve():
        _refresh_plan(resources)
    else:
        typer.echo("Custom Profile path used; run `hsas update-plan` explicitly.")


@execution_app.command("list")
def execution_list(
    ctx: typer.Context,
    execution_path: Annotated[
        Path | None,
        typer.Option("--execution-log", help="Execution Log JSON path"),
    ] = None,
) -> None:
    """Print validated execution records as JSON."""
    execution_path = execution_path or _resources(ctx) / "execution_log.json"
    try:
        log = load_execution_log(execution_path)
    except ExecutionServiceError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(log.model_dump_json(indent=2))


@execution_app.command("validate")
def execution_validate(
    ctx: typer.Context,
    execution_path: Annotated[
        Path | None,
        typer.Option("--execution-log", help="Execution Log JSON path"),
    ] = None,
) -> None:
    """Validate the complete Execution Log without changing it."""
    execution_path = execution_path or _resources(ctx) / "execution_log.json"
    try:
        log = load_execution_log(execution_path)
    except ExecutionServiceError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        f"Execution Log valid: {len(log.records)} record(s); "
        f"updated={log.updated_at or 'never'}"
    )


@execution_app.command("add")
def execution_add(
    ctx: typer.Context,
    plan_item_id: Annotated[str, typer.Argument(help="Integrated Plan item ID")],
    actual_minutes: Annotated[
        int,
        typer.Option("--actual-minutes", min=0, help="Confirmed clock time spent"),
    ],
    progress_minutes: Annotated[
        int,
        typer.Option(
            "--progress-minutes",
            min=0,
            help="Confirmed equivalent planned work completed",
        ),
    ],
    planned_minutes: Annotated[
        int,
        typer.Option(
            "--planned-minutes",
            min=1,
            help="Approximate time budget previously proposed for this study action",
        ),
    ],
    completed: Annotated[
        bool,
        typer.Option("--completed", help="Student confirmed the whole item is complete"),
    ] = False,
    notes: Annotated[
        str | None,
        typer.Option("--notes", help="Optional user-confirmed note"),
    ] = None,
    record_id: Annotated[
        str | None,
        typer.Option("--record-id", help="Stable ID for idempotent retries"),
    ] = None,
    plan_path: Annotated[
        Path | None,
        typer.Option("--plan", help="Integrated Plan JSON path"),
    ] = None,
    execution_path: Annotated[
        Path | None,
        typer.Option("--execution-log", help="Execution Log JSON path"),
    ] = None,
) -> None:
    """Append one user-confirmed execution event."""
    resources = _resources(ctx)
    plan_path = plan_path or resources / "integrated_plan.json"
    execution_path = execution_path or resources / "execution_log.json"
    try:
        _, record, created = add_execution_record(
            execution_path,
            plan_path,
            plan_item_id=plan_item_id,
            actual_minutes=actual_minutes,
            progress_minutes=progress_minutes,
            item_completed=completed,
            planned_minutes=planned_minutes,
            notes=notes,
            record_id=record_id,
        )
    except ExecutionServiceError as exc:
        raise typer.BadParameter(str(exc)) from exc
    action = "added" if created else "already present; retry accepted"
    typer.echo(f"Execution record {action}: {record.record_id} -> {execution_path}")
    if (
        execution_path.resolve() == (resources / "execution_log.json").resolve()
        and plan_path.resolve() == (resources / "integrated_plan.json").resolve()
    ):
        _refresh_plan(resources)
    else:
        typer.echo("Custom execution/Plan path used; run `hsas update-plan` explicitly.")


@execution_app.command("correct")
def execution_correct(
    ctx: typer.Context,
    record_id: Annotated[str, typer.Argument(help="Execution record ID")],
    actual_minutes: Annotated[
        int | None,
        typer.Option("--actual-minutes", min=0),
    ] = None,
    progress_minutes: Annotated[
        int | None,
        typer.Option("--progress-minutes", min=0),
    ] = None,
    completed: Annotated[
        bool | None,
        typer.Option("--completed/--not-completed"),
    ] = None,
    notes: Annotated[str | None, typer.Option("--notes")] = None,
    plan_path: Annotated[
        Path | None,
        typer.Option("--plan", help="Integrated Plan JSON path"),
    ] = None,
    execution_path: Annotated[
        Path | None,
        typer.Option("--execution-log", help="Execution Log JSON path"),
    ] = None,
) -> None:
    """Correct one execution event without changing its identity."""
    resources = _resources(ctx)
    plan_path = plan_path or resources / "integrated_plan.json"
    execution_path = execution_path or resources / "execution_log.json"
    try:
        _, record = correct_execution_record(
            execution_path,
            plan_path,
            record_id,
            actual_minutes=actual_minutes,
            progress_minutes=progress_minutes,
            item_completed=completed,
            notes=notes,
        )
    except ExecutionServiceError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"Execution record corrected: {record.record_id} -> {execution_path}")
    if (
        execution_path.resolve() == (resources / "execution_log.json").resolve()
        and plan_path.resolve() == (resources / "integrated_plan.json").resolve()
    ):
        _refresh_plan(resources)
    else:
        typer.echo("Custom execution/Plan path used; run `hsas update-plan` explicitly.")


@materials_app.command("search")
def materials_search(
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(help="Concept or question to retrieve")],
    course_ids: Annotated[
        list[str] | None,
        typer.Option("--course", help="Restrict retrieval to one or more course IDs"),
    ] = None,
    limit: Annotated[
        int,
        typer.Option(min=1, max=20, help="Maximum returned chunks"),
    ] = 6,
    resources_dir: Annotated[
        Path | None,
        typer.Option("--resources", help="Shared resources directory"),
    ] = None,
) -> None:
    """Search extracted course text and return page-aware JSON evidence."""
    resources_dir = resources_dir or _resources(ctx)
    try:
        result = search_materials(
            resources_dir,
            query,
            course_ids=set(course_ids) if course_ids else None,
            limit=limit,
        )
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(result.model_dump_json(indent=2))


@materials_app.command("for-item")
def materials_for_item(
    ctx: typer.Context,
    plan_item_id: Annotated[str, typer.Argument(help="Integrated Plan item ID")],
    limit: Annotated[
        int,
        typer.Option(min=1, max=20, help="Maximum returned chunks"),
    ] = 6,
    plan_path: Annotated[
        Path | None,
        typer.Option("--plan", help="Integrated Plan JSON path"),
    ] = None,
    resources_dir: Annotated[
        Path | None,
        typer.Option("--resources", help="Shared resources directory"),
    ] = None,
) -> None:
    """Retrieve course evidence using a key plan item's grounded context."""
    resources_dir = resources_dir or _resources(ctx)
    plan_path = plan_path or resources_dir / "integrated_plan.json"
    try:
        _, result = search_for_plan_item(
            resources_dir,
            plan_path,
            plan_item_id,
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


def _refresh_plan(resources: Path) -> None:
    try:
        result = generate_validated_plan(PlanGenerationRequest(resources_dir=resources))
    except PlanGenerationError as exc:
        typer.echo(
            f"Confirmed input saved; Plan refresh failed and the previous Plan was retained: {exc}",
            err=True,
        )
        return
    typer.echo(
        f"Plan refreshed and validated: {len(result.plan.items)} key item(s) -> "
        f"{result.output_path}"
    )
