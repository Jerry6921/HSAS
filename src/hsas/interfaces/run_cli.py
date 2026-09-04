"""Unified HIQS command-line interface."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from hsas.application.synchronize_courses import CourseSynchronizationService
from hsas.application.manage_changes import collect_pending_changes
from hsas.application.retrieve_course_context import build_course_question_context
from hsas.domain.courses import ArchiveIndex, iter_files
from hsas.infrastructure.moodle.load_settings import Settings
from hsas.infrastructure.moodle.synchronize_courses import MoodleCourseGateway
from hsas.infrastructure.runtime import ensure_resources_layout, get_runtime_paths

from .manage_information import INFORMATION_REPOSITORY, information_app
from .manage_changes import CHANGE_REPOSITORY, changes_app
from .query_materials import materials_app
from .run_dashboard import serve_dashboard


app = typer.Typer(no_args_is_help=True, help="HKU Information Query System")
app.add_typer(information_app, name="information")
app.add_typer(materials_app, name="materials")
app.add_typer(changes_app, name="changes")


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
    information_path = resources / "information.json"
    if not INFORMATION_REPOSITORY.exists(information_path):
        typer.echo("Information: unavailable (ask AI to prepare an update)")
    else:
        try:
            store = INFORMATION_REPOSITORY.load(information_path)
        except Exception as exc:
            typer.echo(f"Information: invalid ({type(exc).__name__})")
        else:
            calendar_count = sum(
                item.starts_at is not None
                or item.opens_at is not None
                or item.due_at is not None
                or item.due_on is not None
                or item.scheduled_on is not None
                or item.recurrence is not None
                for item in store.items
            )
            typer.echo(
                f"Information: {len(store.courses)} course(s), {len(store.items)} item(s), "
                f"{calendar_count} calendar item(s); updated={store.updated_at.isoformat()}"
            )

    archives = files = searchable = 0
    for archive_path in sorted((resources / "courses").glob("*/course.json")):
        try:
            index = ArchiveIndex.from_json(archive_path)
        except Exception:
            continue
        archives += 1
        for _activity, stored_file in iter_files(index.archive):
            files += 1
            if stored_file.analysis and stored_file.analysis.extracted_text_path:
                searchable += 1
    typer.echo(
        f"Materials: {archives} course archive(s), {files} downloaded file(s), "
        f"{searchable} searchable text sidecar(s)"
    )
    pending = collect_pending_changes(resources, CHANGE_REPOSITORY)
    typer.echo(
        f"AI review: {len(pending.courses)} course(s), "
        f"{pending.pending_change_count} pending review item(s)"
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
    information_path = resources / "information.json"
    try:
        information = (
            INFORMATION_REPOSITORY.load(information_path)
            if INFORMATION_REPOSITORY.exists(information_path)
            else None
        )
        context = build_course_question_context(
            resources,
            question,
            information=information,
            course_ids=set(course_ids) if course_ids else None,
            material_limit=material_limit,
            item_limit=item_limit,
        )
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(context.model_dump_json(indent=2))


@app.command("login")
def login() -> None:
    """Open Moodle and persist the user-completed SSO/MFA session."""
    _course_service().login()


@app.command("sync-courses")
def sync_courses(
    ctx: typer.Context,
    course: Annotated[
        str | None,
        typer.Argument(help="Optional Moodle course ID or URL; omit to sync all courses"),
    ] = None,
) -> None:
    """Download all accessible course files and create local text sidecars."""
    settings = Settings.load(output_dir=_resources(ctx))
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
