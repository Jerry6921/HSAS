"""Human recovery adapter for the same Agent course-planning port."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

course_planning_app = typer.Typer(
    no_args_is_help=True, help="Course planning and enrolment checkpoints"
)


def _call(ctx, method, *args):
    from hsas.core import HIQSPortError, build_port

    try:
        result = getattr(build_port(ctx.obj["resources"]), method)(*args)
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    except (HIQSPortError, OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from None


@course_planning_app.command("schema")
def schema(ctx: typer.Context):
    _call(ctx, "course_planning_schema")


@course_planning_app.command("show")
def show(ctx: typer.Context, run_id: str | None = None):
    _call(ctx, "course_plan", run_id)


@course_planning_app.command("create")
def create(ctx: typer.Context, request_file: Path, confirmed: bool = False):
    try:
        request = json.loads(request_file.read_text())
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from None
    _call(ctx, "create_course_plan", {"request": request, "confirmed": confirmed})


@course_planning_app.command("checkpoint")
def checkpoint(
    ctx: typer.Context,
    operation: Annotated[str, typer.Argument(help="authorize, reconcile, next, or cancel")],
    payload_file: Path,
    confirmed: bool = False,
):
    methods = {
        "authorize": "authorize_course_plan",
        "reconcile": "reconcile_course_plan",
        "next": "next_course_plan_action",
        "cancel": "cancel_course_plan",
    }
    if operation not in methods:
        raise typer.BadParameter("Choose authorize, reconcile, next, or cancel.")
    try:
        payload = json.loads(payload_file.read_text())
        if not isinstance(payload, dict):
            raise ValueError("Payload must be an object")
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from None
    payload["confirmed"] = confirmed
    _call(ctx, methods[operation], payload)
