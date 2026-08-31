from __future__ import annotations

import asyncio
import hashlib
import mimetypes
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from playwright.async_api import APIResponse, BrowserContext

from ..storage.json_store import safe_filename
from ..transformation.archive_stats import refresh_archive_stats
from ..transformation.models import CourseActivity, CourseArchive, StoredFile


DOCUMENT_EXTENSIONS = {
    ".csv", ".doc", ".docx", ".gif", ".jpeg", ".jpg", ".odp", ".ods",
    ".odt", ".pdf", ".png", ".ppt", ".pptx", ".txt", ".webp", ".xls",
    ".xlsx", ".zip",
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
    return (
        body_prefix.startswith(b"%PDF-")
        or content_type in DOCUMENT_CONTENT_TYPES
        or content_type.startswith("image/")
        or suffix in DOCUMENT_EXTENSIONS
    )


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
        path = urlsplit(url).path.casefold()
        if not _same_origin(url, base_url):
            continue
        if "pluginfile.php" not in path and PurePosixPath(path).suffix not in DOCUMENT_EXTENSIONS:
            continue
        clean = sanitize_source_url(url)
        if clean not in seen:
            seen.add(clean)
            candidates.append(clean)
    return candidates[:20]


async def _save_response(
    response: APIResponse,
    *,
    activity: CourseActivity,
    index: int,
    destination_dir: Path,
    storage_root: Path,
    max_download_bytes: int,
) -> StoredFile | None:
    content_length = response.headers.get("content-length")
    if content_length and int(content_length) > max_download_bytes:
        return None
    body = await response.body()
    if len(body) > max_download_bytes or not _is_storable(response, body[:8]):
        return None
    filename = _choose_filename(response, activity, index)
    destination_dir.mkdir(parents=True, exist_ok=True)
    path = destination_dir / filename
    if path.exists():
        path = destination_dir / f"{path.stem}-{index}{path.suffix}"
    path.write_bytes(body)
    return StoredFile(
        filename=path.name,
        relative_path=path.relative_to(storage_root).as_posix(),
        source_url=sanitize_source_url(response.url),
        content_type=_content_type(response) or None,
        size_bytes=len(body),
        sha256=hashlib.sha256(body).hexdigest(),
        downloaded_at=datetime.now(timezone.utc),
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
) -> None:
    if not activity.url or activity.download_status != "pending":
        return
    activity_url = str(activity.url)
    if not _same_origin(activity_url, base_url):
        activity.download_status = "external"
        return

    try:
        initial_url = _with_redirect(activity_url) if activity.module == "resource" else activity_url
        response = await context.request.get(
            initial_url,
            fail_on_status_code=False,
            timeout=timeout_ms,
        )
        if not response.ok:
            raise RuntimeError(f"HTTP {response.status}")

        content_type = _content_type(response)
        if content_type not in {"text/html", "application/xhtml+xml"}:
            stored = await _save_response(
                response,
                activity=activity,
                index=1,
                destination_dir=destination_dir,
                storage_root=storage_root,
                max_download_bytes=max_download_bytes,
            )
            await response.dispose()
            if stored:
                activity.files.append(stored)
        else:
            html = await response.text()
            final_url = response.url
            await response.dispose()
            for index, candidate in enumerate(
                _file_candidates(html, final_url, base_url), start=1
            ):
                file_response = await context.request.get(
                    candidate,
                    fail_on_status_code=False,
                    timeout=timeout_ms,
                )
                if file_response.ok:
                    stored = await _save_response(
                        file_response,
                        activity=activity,
                        index=index,
                        destination_dir=destination_dir,
                        storage_root=storage_root,
                        max_download_bytes=max_download_bytes,
                    )
                    if stored:
                        activity.files.append(stored)
                await file_response.dispose()

        activity.download_status = "downloaded" if activity.files else "skipped"
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
) -> None:
    semaphore = asyncio.Semaphore(concurrency)
    jobs = []

    async def run(activity: CourseActivity, directory: Path) -> None:
        async with semaphore:
            await download_activity_files(
                context,
                activity,
                base_url=base_url,
                destination_dir=directory,
                storage_root=storage_root,
                max_download_bytes=max_download_bytes,
                timeout_ms=timeout_ms,
            )

    for section in archive.sections:
        section_dir = course_root / "files" / f"{section.number:02d}-{safe_filename(section.title)}"
        for activity in section.activities:
            activity_dir = section_dir / f"{activity.module_id}-{safe_filename(activity.name)}"
            jobs.append(run(activity, activity_dir))
    for activity in archive.unassigned_activities:
        directory = course_root / "files" / "unassigned" / activity.module_id
        jobs.append(run(activity, directory))

    await asyncio.gather(*jobs)
    refresh_archive_stats(archive)
