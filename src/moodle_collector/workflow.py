from __future__ import annotations

import asyncio
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import typer
from playwright.async_api import BrowserContext

from .acquisition.file_downloader import download_course_files
from .acquisition.moodle_client import (
    discover_all_course_states,
    discover_courses,
    extract_course_title,
    fetch_course_state,
    open_page,
    persistent_context,
)
from .settings import Settings
from .storage.local_store import read_json, write_json, write_model
from .storage.course_snapshot import CourseSnapshotTransaction
from .sync_progress import SyncProgress
from .sync_report import record_sync_operation
from .transformation.assessment.builder import build_assessment_overview
from .transformation.common.course_changes import (
    CourseChangeSet,
    compare_course_archives,
)
from .transformation.common.course_index import ArchiveIndex
from .transformation.common.course_mapper import build_course_archive
from .transformation.common.course_schema import CourseArchive
from .transformation.course_materials.pdf_analyzer import analyze_course_pdfs


@dataclass(frozen=True, slots=True)
class SyncCourseResult:
    course_id: str
    course_title: str
    change_count: int
    output_path: Path


@dataclass(frozen=True, slots=True)
class SyncBatchResult:
    discovered_course_count: int
    succeeded_course_ids: tuple[str, ...]
    failures: tuple[dict[str, str], ...]
    report_path: Path

def _settings() -> Settings:
    return Settings.load()


def _validated_course_id(course_url: str, base_url: str) -> str:
    target = urlparse(course_url)
    base = urlparse(base_url)
    if target.scheme not in {"http", "https"} or target.netloc != base.netloc:
        raise typer.BadParameter("course-url must use the exact MOODLE_BASE_URL host")
    course_id = parse_qs(target.query).get("id", [None])[0]
    if not course_id or not course_id.isdigit():
        raise typer.BadParameter("course-url must contain a numeric ?id= course ID")
    return course_id


def _resolve_course_target(value: str, base_url: str) -> tuple[str, str]:
    """Accept a numeric Moodle course ID or a complete same-origin course URL."""
    if value.isdigit():
        course_url = urljoin(
            base_url.rstrip("/") + "/",
            f"course/view.php?id={value}",
        )
        return value, course_url
    return _validated_course_id(value, base_url), value


def _downloaded_courses(settings: Settings) -> dict[str, str]:
    courses_root = settings.output_dir / "courses"
    downloaded: dict[str, str] = {}
    if not courses_root.exists():
        return downloaded
    for course_json in sorted(courses_root.glob("*/course.json")):
        fallback_id = course_json.parent.name
        try:
            archive = CourseArchive.model_validate(read_json(course_json))
            downloaded[archive.course.course_id] = archive.course.title
        except Exception:
            downloaded[fallback_id] = "Invalid or incompatible course.json"
    return downloaded


def _stage(
    progress: SyncProgress | None,
    task_id: int | None,
    component: str,
    detail: str,
):
    if progress is None or task_id is None:
        return nullcontext()
    return progress.stage(task_id, component, detail)


async def _persist_course(
    context: BrowserContext,
    settings: Settings,
    *,
    course_id: str,
    course_title: str,
    state: dict,
    progress: SyncProgress | None = None,
    progress_task: int | None = None,
) -> tuple[CourseArchive, CourseChangeSet, Path]:
    """Download, analyze, structure assessments, and persist one course."""
    live_storage_root = settings.output_dir
    live_course_root = live_storage_root / "courses" / course_id
    course_path = live_course_root / "course.json"
    previous_archive: CourseArchive | None = None
    if course_path.exists():
        try:
            previous_archive = CourseArchive.model_validate(read_json(course_path))
        except Exception:
            previous_archive = None
    with CourseSnapshotTransaction.prepare(live_storage_root, course_id) as transaction:
        storage_root = transaction.staging_resources_dir
        course_root = transaction.staged_course_dir
        staged_course_path = course_root / "course.json"
        raw_path = course_root / "raw" / "course-state.json"
        raw_relative_path = raw_path.relative_to(storage_root).as_posix()
        with _stage(progress, progress_task, "StateMapper", "Mapping Moodle state"):
            archive = build_course_archive(
                state,
                course_title=course_title,
                raw_state_path=raw_relative_path,
            )
        with _stage(progress, progress_task, "FileStore", "Staging raw course state"):
            write_json(raw_path, state)
        with _stage(progress, progress_task, "Downloader", "Staging course files"):
            await download_course_files(
                context,
                archive,
                base_url=str(settings.base_url),
                course_root=course_root,
                storage_root=storage_root,
                max_download_bytes=settings.max_download_bytes,
                timeout_ms=settings.navigation_timeout_ms,
                concurrency=settings.download_concurrency,
                previous_archive=previous_archive,
                progress_callback=(
                    progress.download_callback(progress_task)
                    if progress is not None and progress_task is not None
                    else None
                ),
            )
        with _stage(progress, progress_task, "PdfAnalyzer", "Extracting PDF text"):
            analyze_course_pdfs(
                archive,
                storage_root=storage_root,
                course_root=course_root,
            )
        with _stage(
            progress,
            progress_task,
            "AssessmentParser",
            "Structuring assessments",
        ):
            index = ArchiveIndex(archive)
            archive.assessments = build_assessment_overview(
                index,
                storage_root=storage_root,
            )
        with _stage(
            progress,
            progress_task,
            "ChangeDetector",
            "Comparing deadlines, weights, activities, and materials",
        ):
            changes = compare_course_archives(previous_archive, archive)
            changes_root = course_root / "changes"
            write_model(changes_root / "latest.json", changes)
            if changes.changed:
                stamp = changes.detected_at.strftime("%Y%m%dT%H%M%SZ")
                write_model(changes_root / "history" / f"{stamp}.json", changes)
        with _stage(progress, progress_task, "FileStore", "Publishing course snapshot"):
            write_model(staged_course_path, archive)
            output_path = transaction.commit()
    return archive, changes, output_path


def login(settings: Settings | None = None) -> None:
    """Open a visible browser; finish SSO/MFA manually and save the profile."""
    active_settings = settings or _settings()

    async def run() -> None:
        async with persistent_context(active_settings, headless=False) as context:
            await open_page(context, str(active_settings.login_url))
            typer.echo("Complete HKU login/SSO/MFA in the opened browser.")
            await asyncio.to_thread(input, "After the Moodle dashboard is visible, press Enter here... ")
            moodle_host = urlparse(str(active_settings.base_url)).netloc
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
            selectors = active_settings.selectors()
            dashboard_found = False
            for css in selectors.dashboard_ready:
                if await page.locator(css).count():
                    dashboard_found = True
                    break
            if not dashboard_found:
                raise RuntimeError(
                    "Dashboard marker not found. Update dashboard_ready in the selector config."
                )
            typer.echo(f"Session saved in {active_settings.profile_dir}")

    asyncio.run(run())


def list_courses(settings: Settings | None = None) -> None:
    """Show login status, available Moodle courses, and downloaded courses."""
    active_settings = settings or _settings()

    async def run() -> None:
        downloaded = _downloaded_courses(active_settings)
        available = []
        login_status = "not logged in"
        login_error: str | None = None

        try:
            async with persistent_context(active_settings) as context:
                page = await open_page(context, str(active_settings.dashboard_url))
                selectors = active_settings.selectors()
                available = await discover_courses(
                    page,
                    dashboard_url=str(active_settings.dashboard_url),
                    selectors=selectors,
                )
                dashboard_found = False
                for css in selectors.dashboard_ready:
                    if await page.locator(css).count():
                        dashboard_found = True
                        break
                redirected_to_login = page.url.startswith(str(active_settings.login_url))
                if not redirected_to_login and (dashboard_found or available):
                    login_status = "logged in"
        except Exception as exc:
            login_error = f"{type(exc).__name__}: {str(exc)[:300]}"

        typer.echo(f"Login status: {login_status}")
        if login_error:
            typer.echo(f"Login check error: {login_error}")

        typer.echo(f"\nAvailable courses ({len(available)}):")
        if not available:
            typer.echo("  None. Run `hsas login` if the session expired.")
        for course in available:
            course_id = course.course_id or "unknown"
            local_status = "downloaded" if course_id in downloaded else "not downloaded"
            typer.echo(f"  {course_id} [{local_status}] {course.title}")
            typer.echo(f"    {course.url}")

        typer.echo(f"\nDownloaded courses ({len(downloaded)}):")
        if not downloaded:
            typer.echo("  None")
        for course_id, title in downloaded.items():
            typer.echo(f"  {course_id} {title}")

    asyncio.run(run())


def sync_course(
    course: str,
    settings: Settings | None = None,
) -> SyncCourseResult:
    """Download and fully process one Moodle course."""
    active_settings = settings or _settings()

    course_id, course_url = _resolve_course_target(
        course,
        str(active_settings.base_url),
    )

    async def run() -> SyncCourseResult:

        with SyncProgress() as progress:
            task_id = progress.add_course(course_id, course, stages=8)
            async with persistent_context(active_settings) as context:
                with progress.stage(
                    task_id,
                    "MoodleAPI",
                    "Fetching core_courseformat_get_state",
                ):
                    page = await open_page(context, course_url)
                    if urlparse(page.url).netloc != urlparse(
                        str(active_settings.base_url)
                    ).netloc:
                        raise RuntimeError(
                            "Session expired or SSO redirected. Run `hsas login`."
                        )
                    html = await page.content()
                    title = extract_course_title(html, active_settings.selectors())
                    state = await fetch_course_state(
                        context,
                        page,
                        base_url=str(active_settings.base_url),
                        course_id=course_id,
                    )
                archive, changes, output_path = await _persist_course(
                    context,
                    active_settings,
                    course_id=course_id,
                    course_title=title,
                    state=state,
                    progress=progress,
                    progress_task=task_id,
                )
            progress.finish_course(task_id, archive.course.title)
        typer.echo(
            f"Synced {archive.course.title}: "
            f"{archive.stats.activity_count} activities, "
            f"{archive.stats.downloaded_file_count} files, "
            f"{len(changes.changes)} change(s) -> {output_path}"
        )
        return SyncCourseResult(
            course_id=course_id,
            course_title=archive.course.title,
            change_count=len(changes.changes),
            output_path=output_path,
        )

    try:
        result = asyncio.run(run())
    except Exception as exc:
        record_sync_operation(
            active_settings.output_dir,
            scope="single",
            discovered_course_count=1,
            course_results=[
                {
                    "course_id": course_id,
                    "course": course,
                    "succeeded": False,
                    "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                }
            ],
        )
        raise
    record_sync_operation(
        active_settings.output_dir,
        scope="single",
        discovered_course_count=1,
        course_results=[
            {
                "course_id": result.course_id,
                "course": result.course_title,
                "succeeded": True,
                "change_count": result.change_count,
            }
        ],
    )
    return result


def sync_all(settings: Settings | None = None) -> SyncBatchResult:
    """Download and fully process every available Moodle course."""
    active_settings = settings or _settings()

    async def run() -> SyncBatchResult:
        selectors = active_settings.selectors()
        succeeded: list[str] = []
        change_counts: dict[str, int] = {}
        failures: list[dict[str, str]] = []

        with SyncProgress() as progress:
            discovery_task = progress.add_operation(
                "MoodleAPI",
                "Discovering available courses",
            )
            async with persistent_context(active_settings) as context:
                page = await open_page(context, str(active_settings.dashboard_url))
                results = await discover_all_course_states(
                    context,
                    page,
                    dashboard_url=str(active_settings.dashboard_url),
                    base_url=str(active_settings.base_url),
                    selectors=selectors,
                    progress_callback=lambda index, total, course: (
                        progress.update_discovery(
                            discovery_task,
                            index,
                            total,
                            course,
                        )
                    ),
                )
                progress.finish_operation(
                    discovery_task,
                    f"{len(results)} courses discovered",
                )
                write_json(
                    active_settings.output_dir / "courses.json",
                    [result.course.model_dump(mode="json") for result in results],
                )
                batch_task = progress.add_batch(len(results))

                for result in results:
                    course_id = result.course.course_id
                    if not result.succeeded or not course_id or result.state is None:
                        failures.append(
                            {
                                "course": result.course.title,
                                "course_id": course_id or "",
                                "error": result.error or "Course state was unavailable",
                            }
                        )
                        progress.advance_batch(
                            batch_task,
                            f"failed: {course_id or result.course.title}",
                        )
                        continue
                    course_task = progress.add_course(
                        course_id,
                        result.title,
                        stages=7,
                    )
                    try:
                        archive, changes, _ = await _persist_course(
                            context,
                            active_settings,
                            course_id=course_id,
                            course_title=result.title,
                            state=result.state,
                            progress=progress,
                            progress_task=course_task,
                        )
                        progress.finish_course(course_task, archive.course.title)
                        succeeded.append(course_id)
                        change_counts[course_id] = len(changes.changes)
                        progress.advance_batch(batch_task, f"completed: {course_id}")
                    except Exception as exc:
                        failures.append(
                            {
                                "course": result.course.title,
                                "course_id": course_id,
                                "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                            }
                        )
                        progress.advance_batch(batch_task, f"failed: {course_id}")

        course_results = [
            {
                "course_id": course_id,
                "course": course_id,
                "succeeded": True,
                "change_count": change_counts[course_id],
            }
            for course_id in succeeded
        ] + [
            {**failure, "succeeded": False}
            for failure in failures
        ]
        report_path = record_sync_operation(
            active_settings.output_dir,
            scope="all",
            discovered_course_count=len(results),
            course_results=course_results,
        )
        typer.echo(
            f"Synced {len(succeeded)}/{len(results)} courses; "
            f"{len(failures)} failed -> {report_path}"
        )
        return SyncBatchResult(
            discovered_course_count=len(results),
            succeeded_course_ids=tuple(succeeded),
            failures=tuple(failures),
            report_path=report_path,
        )

    return asyncio.run(run())
