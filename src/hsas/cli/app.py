"""Unified HIQS command-line interface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from hsas.application.moodle_sync import CourseSynchronizationService
from hsas.core import HIQSPortError, build_port
from hsas.infrastructure.moodle.settings import Settings
from hsas.infrastructure.moodle.gateway import MoodleCourseGateway
from hsas.infrastructure.runtime import (
    ensure_resources_layout,
    get_runtime_paths,
    hku_portal_profile_dir,
)
from .commands.information import information_app
from .commands.class_planner import class_planner_app
from .commands.calendar import calendar_app
from .commands.changes import changes_app
from .commands.inbox import inbox_app
from .commands.ocr import ocr_app
from .commands.course_information import sis_course_info_app
from .commands.enrollment import sis_enrollment_app
from .commands.materials import materials_app
from hsas.web.server import serve_dashboard


app = typer.Typer(no_args_is_help=True, help="HKU Information Query System")
app.add_typer(information_app, name="information")
app.add_typer(materials_app, name="materials")
app.add_typer(changes_app, name="changes")
app.add_typer(inbox_app, name="inbox")
app.add_typer(ocr_app, name="ocr")
app.add_typer(class_planner_app, name="class-planner")
app.add_typer(calendar_app, name="calendar")
app.add_typer(sis_course_info_app, name="sis-course-info")
app.add_typer(sis_enrollment_app, name="sis-enrollment")


@app.callback()
def main(
    ctx: typer.Context,
    resources_dir: Annotated[
        Path | None,
        typer.Option("--resources", help="Override the private resources directory"),
    ] = None,
) -> None:
    """Resolve and initialize the private runtime directory."""
    resources = (
        get_runtime_paths().create().resources_dir
        if resources_dir is None
        else ensure_resources_layout(resources_dir)
    )
    ctx.obj = {"resources": resources}


@app.command("list-status")
def list_status(ctx: typer.Context) -> None:
    """Show information-database and downloaded-material status."""
    resources = _resources(ctx)
    typer.echo(f"Resources: {resources}")
    status = build_port(resources).status_snapshot()
    summary = status["summary"]
    if not status["available"]:
        typer.echo("Information: unavailable (ask AI to prepare an update)")
    else:
        typer.echo(
            f"Information: {summary['course_count']} course(s), "
            f"{summary['item_count']} item(s), "
            f"{summary['calendar_item_count']} calendar item(s); "
            f"updated={status['updated_at']}"
        )

    counts = status["material_status"]["counts"]
    typer.echo(
        f"Materials: {counts['course_archives']} course archive(s), "
        f"{counts['downloaded_files']} downloaded file(s), "
        f"{counts['searchable_files']} searchable text sidecar(s)"
    )
    pending = status["pending_review"]
    typer.echo(
        f"AI review: {pending['course_count']} course(s), "
        f"{pending['change_count']} pending review item(s)"
    )
    typer.echo(f"OCR queue: {counts['ocr']} document(s)")
    typer.echo(f"Personal inbox: {status['personal_inbox'].get('pending_count', 0)} draft(s)")
    enrollment = status["sis_enrollment"]
    typer.echo(
        f"Student Center: {enrollment['course_count']} course(s); "
        f"term={enrollment.get('term') or 'unknown'}; "
        f"pending review={enrollment['review']['pending_change_count']}"
    )
    planner = status["class_planner"]
    typer.echo(
        f"Class Planner: {planner['course_count']} course(s), "
        f"{planner['meeting_count']} meeting(s); "
        f"synced={planner['synced_at'] or 'never'}; "
        f"pending review={planner.get('review', {}).get('pending_change_count', 0)}"
    )
    sis = status["sis_course_info"]
    typer.echo(
        f"HKU SIS course information: {sis['course_count']} course(s); "
        f"synced={sis['synced_at'] or 'never'}; "
        f"pending review={sis['review']['pending_change_count']}"
    )


@app.command("query")
def query(
    ctx: typer.Context,
    question: Annotated[
        str,
        typer.Argument(help="Course question to retrieve grounded context for"),
    ],
    course_ids: Annotated[
        list[str] | None,
        typer.Option("--course", help="Restrict retrieval to course IDs"),
    ] = None,
    material_limit: Annotated[
        int,
        typer.Option(min=1, max=20, help="Maximum source-text excerpts"),
    ] = 6,
    item_limit: Annotated[
        int,
        typer.Option(min=1, max=100, help="Maximum structured information items"),
    ] = 20,
) -> None:
    """Return a cited local RAG packet for an AI to answer from."""
    resources = _resources(ctx)
    try:
        context = build_port(resources).query_course(
            {
                "question": question,
                "course_ids": course_ids,
                "material_limit": material_limit,
                "item_limit": item_limit,
            }
        )
    except (HIQSPortError, OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(json.dumps(context, ensure_ascii=False, indent=2))


@app.command("login")
def login(ctx: typer.Context) -> None:
    """Open Moodle and persist the user-completed SSO/MFA session."""
    resources = _resources(ctx)
    _course_service(
        Settings.load(
            output_dir=resources,
            profile_dir=hku_portal_profile_dir(resources),
        )
    ).login()


@app.command("sync-courses")
def sync_courses(
    ctx: typer.Context,
    course: Annotated[
        str | None,
        typer.Argument(help="Optional Moodle course ID or URL; omit to sync all courses"),
    ] = None,
) -> None:
    """Download all accessible course files and create local text sidecars."""
    resources = _resources(ctx)
    settings = Settings.load(
        output_dir=resources,
        profile_dir=hku_portal_profile_dir(resources),
    )
    service = _course_service(settings)
    if course is None:
        result = service.sync_all()
        typer.echo(
            f"Synced {len(result.succeeded_course_ids)}/{result.discovered_course_count} "
            f"courses; {len(result.failures)} failed -> {result.report_path}"
        )
        return
    result = service.sync_course(course)
    typer.echo(
        f"Synced {result.course_title}: {result.change_count} change(s) -> "
        f"{result.output_path}"
    )


@app.command("ui")
def ui(
    ctx: typer.Context,
    port: Annotated[
        int,
        typer.Option(min=0, max=65535, help="Local TCP port; use 0 for any free port"),
    ] = 8765,
    open_browser: Annotated[
        bool,
        typer.Option("--open/--no-open", help="Open the calendar in the default browser"),
    ] = True,
) -> None:
    """Run the private information calendar on this Mac only."""
    serve_dashboard(_resources(ctx), port=port, open_browser=open_browser)


def _course_service(settings: Settings | None = None) -> CourseSynchronizationService:
    return CourseSynchronizationService(
        MoodleCourseGateway(settings, notify=typer.echo, wait_for_user=input)
    )


def _resources(ctx: typer.Context) -> Path:
    if isinstance(ctx.obj, dict) and isinstance(ctx.obj.get("resources"), Path):
        return ctx.obj["resources"]
    return get_runtime_paths().resources_dir


if __name__ == "__main__":
    app()
