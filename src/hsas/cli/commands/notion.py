"""Thin CLI for Notion delivery and local automatic synchronization."""

from __future__ import annotations

import getpass
import json
from pathlib import Path
import time
from threading import Thread
from typing import Annotated
import webbrowser

import typer

notion_app = typer.Typer(no_args_is_help=True, help="Notion workspace, sync and import adapter")


def _resources(ctx):
    from hsas.infrastructure.runtime import get_runtime_paths

    resources = ctx.obj.get("resources") if isinstance(ctx.obj, dict) else None
    return Path(resources or get_runtime_paths().resources_dir)


def _port(ctx):
    from hsas.core import build_port

    return build_port(_resources(ctx))


def _output(operation):
    from hsas.core import HIQSPortError

    try:
        typer.echo(json.dumps(operation(), ensure_ascii=False, indent=2))
    except (HIQSPortError, ValueError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from None


@notion_app.command("status")
def status(ctx: typer.Context):
    """Show configuration and resumable sync report without the token."""
    _output(_port(ctx).notion_status)


@notion_app.command("plan")
def plan(ctx: typer.Context):
    """Print the validated, read-only Notion projection."""
    _output(_port(ctx).notion_projection)


@notion_app.command("check")
def check(ctx: typer.Context):
    _output(_port(ctx).notion_check)


@notion_app.command("configure")
def configure(ctx: typer.Context,
              config_file: Annotated[Path, typer.Argument(help="Non-secret workspace IDs JSON")]):
    """Verify and save an independent connection; token entry is hidden."""
    config = json.loads(config_file.read_text())
    config["token"] = getpass.getpass("Notion integration token (stored locally, never printed): ")
    _output(lambda: _port(ctx).notion_configure(config))


@notion_app.command("sync")
def sync(ctx: typer.Context):
    """Synchronize course facts and original materials into Notion."""
    _output(_port(ctx).notion_sync)


@notion_app.command("export")
def export(ctx: typer.Context, destination: Annotated[Path | None, typer.Argument()] = None,
           include_files: Annotated[bool, typer.Option("--files/--no-files")] = True,
           allow_outside: Annotated[bool, typer.Option(
               "--allow-outside",
               help="Human recovery path: allow a destination outside resources/exports.",
           )] = True):
    """Export a private package; omit the destination to use resources/exports."""
    _output(lambda: _port(ctx).notion_export({
        "destination": str(destination) if destination else None,
        "include_files": include_files,
        "confirmed": True,
        "allow_outside": allow_outside,
    }))


@notion_app.command("open")
def open_workspace(ctx: typer.Context):
    url = _port(ctx).notion_status().get("workspace_url")
    if not url:
        raise typer.BadParameter("Run hsas notion configure first")
    webbrowser.open(url)


@notion_app.command("watch")
def watch(ctx: typer.Context,
          interval: Annotated[int, typer.Option(min=60, max=86400)] = 300):
    """Keep Notion in sync in a local worker; Ctrl-C stops it cleanly.

    Source collection and AI fact review remain separate trusted use cases.
    Each cycle reconciles remote edits and retries unfinished file uploads.
    """
    from hsas.core import HIQSPortError

    port = _port(ctx)
    _output(port.notion_check)
    try:
        while True:
            try:
                result = port.notion_sync()
                typer.echo(json.dumps(result, ensure_ascii=False))
            except HIQSPortError as exc:
                typer.echo(f"Notion cycle failed; retrying in {interval}s: {exc}", err=True)
            time.sleep(interval)
    except KeyboardInterrupt:
        typer.echo("Notion worker stopped")


@notion_app.command("worker-plist")
def make_worker(ctx: typer.Context, destination: Path,
                interval: Annotated[int, typer.Option(min=60, max=86400)] = 300):
    """Generate a login-worker plist after connection verification."""
    _output(lambda: _port(ctx).notion_worker({"destination": str(destination),
                                             "interval_seconds": interval}))


@notion_app.command("controls")
def controls(ctx: typer.Context):
    """Show actual source progress and a copyable AI review prompt."""
    _output(_port(ctx).notion_controls)


@notion_app.command("work")
def work(ctx: typer.Context,
         interval: Annotated[int, typer.Option(min=60, max=86400)] = 300):
    """Consume native Notion button requests and publish live progress."""
    from hsas.infrastructure.notion.worker import worker_lock

    port = _port(ctx)
    _output(port.notion_check)
    try:
        with worker_lock(_resources(ctx)):
            _work_loop(port, interval)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None


def _work_loop(port, interval):
    from hsas.core import HIQSPortError

    delivery, next_delivery = None, 0.0
    def publish():
        try:
            typer.echo(json.dumps(port.notion_sync(), ensure_ascii=False))
        except HIQSPortError as exc:
            typer.echo(f"Notion publication failed: {exc}", err=True)
    try:
        while True:
            running = False
            try:
                tick = port.notion_controls_tick({"allow_start": delivery is None or not delivery.is_alive()})
                running = tick["source_running"]
            except HIQSPortError as exc:
                typer.echo(f"Notion controls unavailable: {exc}", err=True)
            if not running and time.monotonic() >= next_delivery and (delivery is None or not delivery.is_alive()):
                delivery = Thread(target=publish, name="notion-delivery", daemon=True)
                delivery.start()
                next_delivery = time.monotonic() + interval
            time.sleep(5)
    except KeyboardInterrupt:
        typer.echo("Notion worker stopped")
