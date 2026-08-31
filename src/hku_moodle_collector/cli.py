from __future__ import annotations

import asyncio
import json
from typing import Annotated
from urllib.parse import parse_qs, urlparse

import typer
from bs4 import BeautifulSoup

from .acquisition.browser import open_page, persistent_context
from .acquisition.discovery import discover_courses
from .acquisition.downloader import download_course_files
from .acquisition.moodle_api import fetch_course_state
from .config import Settings
from .storage.json_store import safe_filename, write_json
from .transformation.assessment_parser import build_assessment_overview
from .transformation.archive_index import ArchiveIndex
from .transformation.archive_stats import refresh_archive_stats
from .transformation.html_parser import parse_course
from .transformation.pdf_analysis import analyze_course_pdfs
from .transformation.state_mapper import build_course_archive

app = typer.Typer(no_args_is_help=True, help="Configurable HKU Moodle collector")


def _settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


def _validated_course_id(course_url: str, base_url: str) -> str:
    target = urlparse(course_url)
    base = urlparse(base_url)
    if target.scheme not in {"http", "https"} or target.netloc != base.netloc:
        raise typer.BadParameter("course-url must use the exact MOODLE_BASE_URL host")
    course_id = parse_qs(target.query).get("id", [None])[0]
    if not course_id or not course_id.isdigit():
        raise typer.BadParameter("course-url must contain a numeric ?id= course ID")
    return course_id


def _extract_title(html: str, selectors: list[str]) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            title = " ".join(node.get_text(" ", strip=True).split())
            if title:
                return title
    return "Untitled course"


@app.command()
def login() -> None:
    """Open a visible browser; finish SSO/MFA manually and save the profile."""

    async def run() -> None:
        settings = _settings()
        async with persistent_context(settings, headless=False) as context:
            await open_page(context, str(settings.login_url))
            typer.echo("Complete HKU login/SSO/MFA in the opened browser.")
            await asyncio.to_thread(input, "After the Moodle dashboard is visible, press Enter here... ")
            moodle_host = urlparse(str(settings.base_url)).netloc
            moodle_pages = [
                candidate
                for candidate in context.pages
                if urlparse(candidate.url).netloc == moodle_host
            ]
            if not moodle_pages:
                raise RuntimeError(
                    "No logged-in Moodle page found. Complete SSO before pressing Enter."
                )
            page = moodle_pages[-1]
            selectors = settings.selectors()
            dashboard_found = False
            for css in selectors.dashboard_ready:
                if await page.locator(css).count():
                    dashboard_found = True
                    break
            if not dashboard_found:
                raise RuntimeError(
                    "Dashboard marker not found. Update dashboard_ready in the selector config."
                )
            typer.echo(f"Session saved in {settings.profile_dir}")

    asyncio.run(run())


@app.command()
def discover() -> None:
    """Discover dashboard courses and write output/courses.json."""

    async def run() -> None:
        settings = _settings()
        async with persistent_context(settings) as context:
            page = await open_page(context, str(settings.dashboard_url))
            if page.url.startswith(str(settings.login_url)):
                raise RuntimeError("Session expired. Run `hku-moodle login` again.")
            courses = discover_courses(await page.content(), page.url, settings.selectors())
        path = settings.output_dir / "courses.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps([item.model_dump(mode="json") for item in courses], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        typer.echo(f"Found {len(courses)} courses -> {path}")

    asyncio.run(run())


@app.command()
def collect(
    course_url: Annotated[str, typer.Option("--course-url", help="URL copied from courses.json")],
    save_raw_html: Annotated[bool, typer.Option("--save-raw-html/--no-save-raw-html")] = True,
) -> None:
    """Fetch and parse one course page."""

    async def run() -> None:
        settings = _settings()
        if not course_url.startswith(str(settings.base_url).rstrip("/")):
            raise typer.BadParameter("course-url must be on MOODLE_BASE_URL")
        async with persistent_context(settings) as context:
            page = await open_page(context, course_url)
            html = await page.content()
            final_url = page.url
            if final_url.startswith(str(settings.login_url)):
                raise RuntimeError("Session expired. Run `hku-moodle login` again.")
        snapshot = parse_course(html, final_url, settings.selectors())
        name = safe_filename(snapshot.course.course_id or snapshot.course.title)
        json_path = write_json(snapshot, settings.output_dir / f"{name}.json")
        if save_raw_html:
            html_path = settings.output_dir / "raw" / f"{name}.html"
            html_path.parent.mkdir(parents=True, exist_ok=True)
            html_path.write_text(html, encoding="utf-8")
        typer.echo(f"Collected {snapshot.course.title} -> {json_path}")

    asyncio.run(run())


@app.command("sync-course")
def sync_course(
    course_url: Annotated[
        str,
        typer.Option("--course-url", help="Moodle course/view.php URL"),
    ],
    download_files: Annotated[
        bool,
        typer.Option("--download-files/--no-download-files"),
    ] = True,
    analyze_pdfs: Annotated[
        bool,
        typer.Option("--analyze-pdfs/--no-analyze-pdfs"),
    ] = True,
) -> None:
    """Collect structured course state and download same-origin course files."""

    async def run() -> None:
        settings = _settings()
        course_id = _validated_course_id(course_url, str(settings.base_url))
        storage_root = settings.output_dir
        course_root = storage_root / "courses" / course_id
        raw_path = course_root / "raw" / "course-state.json"
        raw_relative_path = raw_path.relative_to(storage_root).as_posix()

        async with persistent_context(settings) as context:
            page = await open_page(context, course_url)
            if urlparse(page.url).netloc != urlparse(str(settings.base_url)).netloc:
                raise RuntimeError("Session expired or SSO redirected. Run `hku-moodle login`.")
            html = await page.content()
            title = _extract_title(html, settings.selectors().course_title)
            state = await fetch_course_state(
                context,
                page,
                base_url=str(settings.base_url),
                course_id=course_id,
            )
            archive = build_course_archive(
                state,
                course_title=title,
                raw_state_path=raw_relative_path,
            )

            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text(
                json.dumps(state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            if download_files:
                await download_course_files(
                    context,
                    archive,
                    base_url=str(settings.base_url),
                    course_root=course_root,
                    storage_root=storage_root,
                    max_download_bytes=settings.max_download_bytes,
                    timeout_ms=settings.navigation_timeout_ms,
                    concurrency=settings.download_concurrency,
                )
            else:
                for section in archive.sections:
                    for activity in section.activities:
                        if activity.download_status == "pending":
                            activity.download_status = "skipped"
                for activity in archive.unassigned_activities:
                    if activity.download_status == "pending":
                        activity.download_status = "skipped"
                refresh_archive_stats(archive)

            if analyze_pdfs:
                analyze_course_pdfs(
                    archive,
                    storage_root=storage_root,
                    course_root=course_root,
                )
                archive.assessments = build_assessment_overview(
                    archive,
                    storage_root=storage_root,
                )

        output_path = write_json(archive, course_root / "course.json")
        typer.echo(
            f"Synced {archive.course.title}: "
            f"{archive.stats.activity_count} activities, "
            f"{archive.stats.downloaded_file_count} files -> {output_path}"
        )

    asyncio.run(run())


@app.command("analyze-course")
def analyze_course(
    course_id: Annotated[
        str,
        typer.Option("--course-id", help="Existing output/courses/<id> directory"),
    ],
) -> None:
    """Analyze already-downloaded PDFs and structure syllabus assessments."""
    if not course_id.isdigit():
        raise typer.BadParameter("course-id must be numeric")
    settings = _settings()
    course_root = settings.output_dir / "courses" / course_id
    course_json = course_root / "course.json"
    if not course_json.exists():
        raise typer.BadParameter(f"Course archive not found: {course_json}")

    archive = ArchiveIndex.from_json(course_json).archive
    archive.schema_version = "2.1"
    analyze_course_pdfs(
        archive,
        storage_root=settings.output_dir,
        course_root=course_root,
    )
    archive.assessments = build_assessment_overview(
        archive,
        storage_root=settings.output_dir,
    )
    write_json(archive, course_json)
    typer.echo(
        f"Analyzed {archive.stats.analyzed_pdf_count} PDFs, "
        f"{archive.stats.pdf_word_count} words, "
        f"{len(archive.assessments.items)} assessments -> {course_json}"
    )
