"""AI-facing commands for locally downloaded course materials."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from hsas.application.retrieve_materials import search_materials
from hsas.domain.courses import ArchiveIndex, iter_files
from hsas.infrastructure.runtime import get_runtime_paths


materials_app = typer.Typer(
    no_args_is_help=True,
    help="List and search locally downloaded course materials",
)


@materials_app.command("list")
def materials_list(
    ctx: typer.Context,
    course_ids: Annotated[
        list[str] | None,
        typer.Option("--course", help="Restrict the manifest to course IDs"),
    ] = None,
) -> None:
    """Print a machine-readable manifest of every locally downloaded file."""
    resources = _resources(ctx)
    selected = set(course_ids or [])
    documents: list[dict] = []
    try:
        for archive_path in sorted((resources / "courses").glob("*/course.json")):
            index = ArchiveIndex.from_json(archive_path)
            course_id = index.archive.course.course_id
            if selected and course_id not in selected:
                continue
            for activity, stored_file in iter_files(index.archive):
                analysis = stored_file.analysis
                documents.append(
                    {
                        "course_id": course_id,
                        "course_title": index.archive.course.title,
                        "activity_id": activity.module_id,
                        "activity_name": activity.name,
                        "filename": stored_file.filename,
                        "relative_path": stored_file.relative_path,
                        "local_path": str((resources / stored_file.relative_path).resolve()),
                        "content_type": stored_file.content_type,
                        "size_bytes": stored_file.size_bytes,
                        "sha256": stored_file.sha256,
                        "downloaded_at": stored_file.downloaded_at.isoformat(),
                        "text_path": (
                            str((resources / analysis.extracted_text_path).resolve())
                            if analysis and analysis.extracted_text_path
                            else None
                        ),
                        "analysis_status": analysis.status if analysis else None,
                        "analysis_warnings": analysis.warnings if analysis else [],
                    }
                )
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        json.dumps(
            {
                "resources_dir": str(resources.resolve()),
                "document_count": len(documents),
                "documents": documents,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@materials_app.command("search")
def materials_search(
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(help="Concept or question to retrieve")],
    course_ids: Annotated[
        list[str] | None,
        typer.Option("--course", help="Restrict retrieval to course IDs"),
    ] = None,
    limit: Annotated[
        int,
        typer.Option(min=1, max=20, help="Maximum returned chunks"),
    ] = 6,
) -> None:
    """Search extracted course text and return page-aware JSON evidence."""
    try:
        result = search_materials(
            _resources(ctx),
            query,
            course_ids=set(course_ids) if course_ids else None,
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
