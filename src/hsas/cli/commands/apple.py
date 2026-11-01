"""Thin Apple Calendar / Reminders setup and recovery adapter."""

import json
from typing import Annotated

import typer

from hsas.core import HIQSPortError, build_port
from hsas.infrastructure.runtime import get_runtime_paths


apple_app = typer.Typer(no_args_is_help=True, help="Apple Calendar / Reminders automatic synchronization")


def _port(ctx):
    resources = ctx.obj.get("resources") if isinstance(ctx.obj, dict) else None
    return build_port(resources or get_runtime_paths().resources_dir)


def _output(operation):
    try:
        result = operation()
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
        if (result.get("status") in {"failed", "partial", "permission_required"}
            or result.get("authorization", {}).get("status") in {"failed", "permission_required"}):
            raise typer.Exit(1)
    except (HIQSPortError, ValueError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from None


@apple_app.command("connect")
def connect(ctx: typer.Context, account: str = "icloud",
            confirmed: Annotated[bool, typer.Option("--confirmed")] = False):
    """Request macOS permissions and retain the chosen account and sync identity."""
    _output(lambda: _port(ctx).apple_configure({"account_mode": account, "confirmed": confirmed}))


@apple_app.command("check")
def check(ctx: typer.Context):
    _output(_port(ctx).apple_check)


@apple_app.command("plan")
def plan(ctx: typer.Context):
    _output(_port(ctx).apple_projection)


@apple_app.command("status")
def status(ctx: typer.Context):
    _output(_port(ctx).apple_status)


@apple_app.command("sync")
def sync(ctx: typer.Context):
    """Sync authorized HIQS facts to Apple; completed reminders remain completed."""
    _output(_port(ctx).apple_sync)


@apple_app.command("enable")
def enable(ctx: typer.Context, interval: Annotated[int, typer.Option(min=60, max=86400)] = 300,
           confirmed: Annotated[bool, typer.Option("--confirmed")] = False):
    """Install and verify a login worker after the first verified sync."""
    _output(lambda: _port(ctx).apple_worker({"enabled": True, "interval_seconds": interval, "confirmed": confirmed}))


@apple_app.command("disable")
def disable(ctx: typer.Context, confirmed: Annotated[bool, typer.Option("--confirmed")] = False):
    """Stop automatic synchronization while retaining Apple data."""
    _output(lambda: _port(ctx).apple_worker({"enabled": False, "confirmed": confirmed}))
