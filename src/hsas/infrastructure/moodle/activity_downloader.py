from __future__ import annotations

import asyncio
from collections import deque
import hashlib
import mimetypes
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from collections.abc import Callable
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from playwright.async_api import APIResponse, BrowserContext

from hsas.infrastructure.storage.json_store import safe_filename, write_bytes
from hsas.domain.courses.archive_index import iter_activities
from hsas.domain.courses.models import CourseActivity, CourseArchive, StoredFile
from hsas.domain.courses.evidence import LinkedPageEvidence, RecursiveCollectionReport
from hsas.domain.courses.statistics import refresh_archive_stats
from hsas.infrastructure.moodle.cancellation import MoodleSyncCancelled, raise_if_cancelled
from hsas.infrastructure.moodle.link_discovery import DiscoveryResult, MoodleDiscoveryService
from hsas.infrastructure.moodle.page_parser import ParseResult, MoodleParseService
from hsas.infrastructure.moodle.response_downloader import MoodleDownloadService


DownloadProgressCallback = Callable[[str, CourseActivity, int, int], None]


DOCUMENT_EXTENSIONS = {
    ".7z", ".aac", ".csv", ".doc", ".docx", ".gif", ".html", ".ipynb",
    ".jpeg", ".jpg", ".json", ".m", ".md", ".mov", ".mp3", ".mp4", ".odp",
    ".ods", ".odt", ".pdf", ".png", ".ppt", ".pptx", ".py", ".r", ".rar",
    ".tex", ".txt", ".wav", ".webm", ".webp", ".xls", ".xlsx", ".xml", ".zip",
}
DOCUMENT_CONTENT_TYPES = {
    "application/msword",
    "application/pdf",
    "application/vnd.ms-excel",
    "application/vnd.ms-powerpoint",
    "application/vnd.oasis.opendocument.presentation",
    "application/vnd.oasis.opendocument.spreadsheet",
    "application/vnd.oasis.opendocument.text",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/zip",
    "text/csv",
    "text/plain",
}
SENSITIVE_QUERY_KEYS = {"sesskey", "token", "wstoken"}


def sanitize_source_url(url: str) -> str:
    parts = urlsplit(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.casefold() not in SENSITIVE_QUERY_KEYS
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def _same_origin(url: str, base_url: str) -> bool:
    target = urlsplit(url)
    base = urlsplit(base_url)
    return target.scheme in {"http", "https"} and target.netloc == base.netloc


def _with_redirect(url: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["redirect"] = "1"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def _filename_from_disposition(value: str | None) -> str | None:
    if not value:
        return None
    extended = re.search(r"filename\*=UTF-8''([^;]+)", value, flags=re.IGNORECASE)
    if extended:
        return unquote(extended.group(1).strip().strip('"'))
    normal = re.search(r'filename="?([^";]+)', value, flags=re.IGNORECASE)
    return normal.group(1).strip() if normal else None


def _content_type(response: APIResponse) -> str:
    return response.headers.get("content-type", "").split(";", 1)[0].strip().lower()


def _fallback_extension(content_type: str) -> str:
    overrides = {
        "application/pdf": ".pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    }
    return overrides.get(content_type) or mimetypes.guess_extension(content_type) or ""


def _choose_filename(response: APIResponse, activity: CourseActivity, index: int) -> str:
    disposition_name = _filename_from_disposition(
        response.headers.get("content-disposition")
    )
    url_name = unquote(PurePosixPath(urlsplit(response.url).path).name)
    candidate = disposition_name or url_name
    if not candidate or candidate.casefold() in {"view.php", "pluginfile.php"}:
        candidate = f"{activity.module_id}-{safe_filename(activity.name)}-{index}"
    path = Path(candidate)
    stem = safe_filename(path.stem)
    suffix = path.suffix.lower() or _fallback_extension(_content_type(response))
    return f"{stem}{suffix}"


def _is_storable(response: APIResponse, body_prefix: bytes = b"") -> bool:
    content_type = _content_type(response)
    suffix = PurePosixPath(urlsplit(response.url).path).suffix.casefold()
    disposition = response.headers.get("content-disposition", "").casefold()
    return (
        body_prefix.startswith(b"%PDF-")
        or "attachment" in disposition
        or content_type in DOCUMENT_CONTENT_TYPES
        or content_type.startswith("image/")
        or content_type.startswith("audio/")
        or content_type.startswith("video/")
        or (
            bool(content_type)
            and content_type not in {"text/html", "application/xhtml+xml"}
        )
        or suffix in DOCUMENT_EXTENSIONS
    )


def _google_workspace_export_url(url: str) -> str | None:
    """Return a direct export URL for a linked Google document when possible."""
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or parts.netloc != "docs.google.com":
        return None
    match = re.match(r"^/(document|presentation|spreadsheets)/d/([^/]+)", parts.path)
    if not match:
        return None
    product, document_id = match.groups()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", document_id):
        return None
    if product == "presentation":
        return f"https://docs.google.com/presentation/d/{document_id}/export/pptx"
    export_format = "docx" if product == "document" else "xlsx"
    return f"https://docs.google.com/{product}/d/{document_id}/export?format={export_format}"


def _conditional_headers(previous: StoredFile | None) -> dict[str, str]:
    if previous is None:
        return {}
    headers: dict[str, str] = {}
    if previous.etag:
        headers["If-None-Match"] = previous.etag
    if previous.last_modified:
        headers["If-Modified-Since"] = previous.last_modified
    return headers


def _previous_for_url(
    url: str,
    previous_files: dict[str, StoredFile],
    *,
    use_single_fallback: bool = False,
) -> StoredFile | None:
    previous = previous_files.get(sanitize_source_url(url))
    if previous is None and use_single_fallback and len(previous_files) == 1:
        previous = next(iter(previous_files.values()))
    return previous


def _reuse_not_modified(
    previous: StoredFile | None,
    *,
    storage_root: Path,
) -> StoredFile | None:
    if previous is None or not (storage_root / previous.relative_path).exists():
        return None
    reused = previous.model_copy(deep=True)
    reused.validated_at = datetime.now(timezone.utc)
    return reused


async def _get_with_validation(
    context: BrowserContext,
    url: str,
    *,
    previous: StoredFile | None,
    storage_root: Path,
    timeout_ms: int,
) -> tuple[APIResponse | None, StoredFile | None]:
    """Issue a conditional GET and return a local file on HTTP 304."""
    response = await context.request.get(
        url,
        headers=_conditional_headers(previous),
        fail_on_status_code=False,
        timeout=timeout_ms,
    )
    if response.status != 304:
        return response, None

    reused = _reuse_not_modified(previous, storage_root=storage_root)
    await response.dispose()
    if reused is not None:
        return None, reused

    # The cache metadata survived but the local file did not. Recover with a
    # normal GET instead of treating a server-side 304 as a successful file.
    response = await context.request.get(
        url,
        fail_on_status_code=False,
        timeout=timeout_ms,
    )
    return response, None


def _file_candidates(html: str, page_url: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[str] = []
    seen: set[str] = set()
    for node, attribute in [
        *[(node, "href") for node in soup.select("a[href]")],
        *[(node, "src") for node in soup.select("embed[src], iframe[src]")],
        *[(node, "data") for node in soup.select("object[data]")],
    ]:
        raw_url = node.get(attribute)
        if not raw_url:
            continue
        url = urljoin(page_url, raw_url)
        google_export = _google_workspace_export_url(url)
        path = urlsplit(url).path.casefold()
        if not _same_origin(url, base_url) and google_export is None:
            continue
        if (
            google_export is None
            and "pluginfile.php" not in path
            and PurePosixPath(path).suffix not in DOCUMENT_EXTENSIONS
        ):
            continue
        url = google_export or url
        clean = sanitize_source_url(url)
        if clean not in seen:
            seen.add(clean)
            candidates.append(clean)
    # The activity-level budget is enforced by ``download_activity_files``.
    # Do not truncate here: a timetable, reading list, or resource index can
    # legitimately expose more than twenty files on a single page.
    return candidates


def _page_candidates(html: str, page_url: str, base_url: str) -> list[str]:
    """Find explicitly content-bearing Moodle pages, never general navigation."""
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[str] = []
    seen: set[str] = set()
    allowed_prefixes = (
        "/mod/book/view.php",
        "/mod/folder/view.php",
        "/mod/lesson/view.php",
        "/mod/page/view.php",
        "/mod/resource/view.php",
        "/mod/url/view.php",
    )
    current = sanitize_source_url(page_url)
    for node, attribute in [
        *[(node, "href") for node in soup.select("a[href]")],
        *[(node, "src") for node in soup.select("iframe[src]")],
        *[(node, "data") for node in soup.select("object[data]")],
    ]:
        raw_url = node.get(attribute)
        if not raw_url:
            continue
        url = sanitize_source_url(urljoin(page_url, raw_url))
        parts = urlsplit(url)
        if url == current or not _same_origin(url, base_url):
            continue
        path = parts.path.casefold()
        if "pluginfile.php" in path:
            continue
        if PurePosixPath(path).suffix in DOCUMENT_EXTENSIONS:
            continue
        if not path.startswith(allowed_prefixes):
            continue
        if url not in seen:
            seen.add(url)
            candidates.append(url)
    return candidates


DISCOVERY_SERVICE = MoodleDiscoveryService(_file_candidates, _page_candidates)
PARSE_SERVICE = MoodleParseService(DISCOVERY_SERVICE, sanitize_source_url)
DOWNLOAD_SERVICE = MoodleDownloadService(_get_with_validation)


def parse_html_evidence(html: str, page_url: str, base_url: str) -> ParseResult:
    return PARSE_SERVICE.parse(html, page_url, base_url)


def discover_html_links(html: str, page_url: str, base_url: str) -> DiscoveryResult:
    return DISCOVERY_SERVICE.discover(html, page_url, base_url)


def _record_linked_page(
    activity: CourseActivity, url: str, depth: int, html: str, base_url: str
) -> DiscoveryResult:
    """Persist bounded inert evidence for intermediate pages in a link chain."""
    parsed = parse_html_evidence(html, url, base_url)
    typed_page = LinkedPageEvidence(
        url=parsed.url,
        depth=depth,
        title=parsed.title,
        content_text=parsed.text,
    )
    activity.linked_pages.append(typed_page)
    return parsed.discovered


async def _save_response(
    response: APIResponse,
    *,
    activity: CourseActivity,
    index: int,
    destination_dir: Path,
    storage_root: Path,
    max_download_bytes: int,
    previous_files: dict[str, StoredFile] | None = None,
    source_url_override: str | None = None,
    claimed_paths: set[Path] | None = None,
) -> StoredFile | None:
    content_length = response.headers.get("content-length")
    if content_length and int(content_length) > max_download_bytes:
        return None
    body = await response.body()
    if len(body) > max_download_bytes or not _is_storable(response, body[:8]):
        return None
    digest = hashlib.sha256(body).hexdigest()
    checked_at = datetime.now(timezone.utc)
    source_url = sanitize_source_url(source_url_override or response.url)
    previous = (previous_files or {}).get(source_url)
    if previous is not None:
        previous_path = storage_root / previous.relative_path
        if previous.sha256 == digest and previous_path.exists():
            reused = previous.model_copy(deep=True)
            reused.etag = response.headers.get("etag") or previous.etag
            reused.last_modified = (
                response.headers.get("last-modified") or previous.last_modified
            )
            reused.validated_at = checked_at
            return reused
        path = previous_path
    else:
        filename = _choose_filename(response, activity, index)
        path = destination_dir / filename
        if claimed_paths is not None and path in claimed_paths:
            path = destination_dir / f"{path.stem}-{index}{path.suffix}"
    if claimed_paths is not None:
        claimed_paths.add(path)
    write_bytes(path, body)
    return StoredFile(
        filename=path.name,
        relative_path=path.relative_to(storage_root).as_posix(),
        source_url=source_url,
        content_type=_content_type(response) or None,
        size_bytes=len(body),
        sha256=digest,
        downloaded_at=checked_at,
        etag=response.headers.get("etag"),
        last_modified=response.headers.get("last-modified"),
        validated_at=checked_at,
    )


async def download_activity_files(
    context: BrowserContext,
    activity: CourseActivity,
    *,
    base_url: str,
    destination_dir: Path,
    storage_root: Path,
    max_download_bytes: int,
    timeout_ms: int,
    previous_activity: CourseActivity | None = None,
    max_link_depth: int = 6,
    max_linked_pages: int = 100,
    max_linked_files: int = 200,
    cancel_requested: Callable[[], bool] | None = None,
) -> None:
    if not activity.url or activity.download_status != "pending":
        return
    activity_url = str(activity.url)
    google_export_url = _google_workspace_export_url(activity_url)
    if not _same_origin(activity_url, base_url) and google_export_url is None:
        activity.download_status = "external"
        return

    previous_files = {
        str(stored_file.source_url): stored_file
        for stored_file in (previous_activity.files if previous_activity else [])
    }
    claimed_paths: set[Path] = set()
    try:
        initial_url = google_export_url or (
            _with_redirect(activity_url)
            if activity.module in {"resource", "url"}
            else activity_url
        )
        # HTML pages can enqueue both files and more content pages; visited URLs
        # make cycles harmless while the activity-level budgets bound the crawl.
        queue: deque[tuple[str, int, str]] = deque([
            (initial_url, 0, "file" if google_export_url else "page")
        ])
        visited: set[str] = set()
        linked_pages = 0
        linked_files = 0
        while queue and linked_pages < max_linked_pages and linked_files < max_linked_files:
            raise_if_cancelled(cancel_requested)
            url, depth, candidate_kind = queue.popleft()
            clean_url = sanitize_source_url(url)
            if clean_url in visited:
                continue
            visited.add(clean_url)
            previous = _previous_for_url(
                clean_url,
                previous_files,
                use_single_fallback=(activity.module == "resource" and depth == 0),
            )
            response, reused = await DOWNLOAD_SERVICE.fetch(
                context,
                clean_url,
                previous=previous,
                storage_root=storage_root,
                timeout_ms=timeout_ms,
            )
            if reused is not None:
                claimed_paths.add(storage_root / reused.relative_path)
                activity.files.append(reused)
                linked_files += 1
                continue
            if response is None:
                continue
            try:
                if not response.ok:
                    continue
                content_type = _content_type(response)
                if content_type not in {"text/html", "application/xhtml+xml"}:
                    stored = await _save_response(
                        response,
                        activity=activity,
                        index=len(activity.files) + 1,
                        destination_dir=destination_dir,
                        storage_root=storage_root,
                        max_download_bytes=max_download_bytes,
                        previous_files=previous_files,
                        source_url_override=(
                            clean_url
                            if urlsplit(clean_url).netloc == "docs.google.com"
                            else None
                        ),
                        claimed_paths=claimed_paths,
                    )
                    if stored:
                        activity.files.append(stored)
                        linked_files += 1
                    continue

                html = await response.text()
                final_url = sanitize_source_url(response.url)
                linked_pages += 1
                discovered = _record_linked_page(activity, final_url, depth, html, base_url)
                final_suffix = PurePosixPath(urlsplit(final_url).path.casefold()).suffix
                if candidate_kind == "file" and final_suffix not in {".htm", ".html"}:
                    continue
                for candidate in discovered.file_urls:
                    if candidate not in visited and linked_files < max_linked_files:
                        suffix = PurePosixPath(urlsplit(candidate).path.casefold()).suffix
                        kind = "page" if suffix in {".htm", ".html"} else "file"
                        queue.append((candidate, depth + 1, kind))
                if depth < max_link_depth and linked_pages < max_linked_pages:
                    for candidate in discovered.page_urls:
                        if candidate not in visited:
                            queue.append((candidate, depth + 1, "page"))
            finally:
                await response.dispose()

        activity.collection_report = RecursiveCollectionReport(
            truncated=bool(queue),
            max_link_depth=max_link_depth,
            max_linked_pages=max_linked_pages,
            max_linked_files=max_linked_files,
            discovered_pages=linked_pages,
            discovered_files=linked_files,
        )

        activity.download_status = "downloaded" if activity.files else "skipped"
    except MoodleSyncCancelled:
        raise
    except Exception as exc:
        activity.download_status = "failed"
        activity.download_error = str(exc)[:300]


async def download_course_files(
    context: BrowserContext,
    archive: CourseArchive,
    *,
    base_url: str,
    course_root: Path,
    storage_root: Path,
    max_download_bytes: int,
    timeout_ms: int,
    concurrency: int,
    previous_archive: CourseArchive | None = None,
    progress_callback: DownloadProgressCallback | None = None,
    cancel_requested: Callable[[], bool] | None = None,
    max_link_depth: int = 6,
    max_linked_pages: int = 100,
    max_linked_files: int = 200,
) -> None:
    semaphore = asyncio.Semaphore(concurrency)
    jobs = []
    completed = 0
    total_jobs = 0
    completion_lock = asyncio.Lock()

    previous_activities = {
        activity.module_id: activity
        for activity in iter_activities(previous_archive)
    } if previous_archive else {}

    async def run(activity: CourseActivity, directory: Path) -> None:
        nonlocal completed
        raise_if_cancelled(cancel_requested)
        async with semaphore:
            raise_if_cancelled(cancel_requested)
            if progress_callback:
                progress_callback("start", activity, completed, total_jobs)
            await download_activity_files(
                context,
                activity,
                base_url=base_url,
                destination_dir=directory,
                storage_root=storage_root,
                max_download_bytes=max_download_bytes,
                timeout_ms=timeout_ms,
                previous_activity=previous_activities.get(activity.module_id),
                max_link_depth=max_link_depth,
                max_linked_pages=max_linked_pages,
                max_linked_files=max_linked_files,
                cancel_requested=cancel_requested,
            )
            raise_if_cancelled(cancel_requested)
            async with completion_lock:
                completed += 1
                if progress_callback:
                    progress_callback("complete", activity, completed, total_jobs)

    for section in archive.sections:
        section_dir = course_root / "files" / f"{section.number:02d}-{safe_filename(section.title)}"
        for activity in section.activities:
            if not activity.url or activity.download_status != "pending":
                continue
            activity_dir = section_dir / f"{activity.module_id}-{safe_filename(activity.name)}"
            jobs.append(run(activity, activity_dir))
    for activity in archive.unassigned_activities:
        if not activity.url or activity.download_status != "pending":
            continue
        directory = course_root / "files" / "unassigned" / activity.module_id
        jobs.append(run(activity, directory))

    total_jobs = len(jobs)
    await asyncio.gather(*jobs)
    refresh_archive_stats(archive)
