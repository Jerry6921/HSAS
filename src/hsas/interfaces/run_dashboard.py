"""Serve the local HIQS calendar, course overview, and Moodle controls."""

from __future__ import annotations

from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
from threading import Lock
from typing import Any, Callable
from urllib.parse import parse_qs, quote, urlparse
import webbrowser

from pydantic import ValidationError

from hsas.application.synchronize_courses import CourseSynchronizationService
from hsas.application.manage_changes import collect_pending_changes
from hsas.domain.courses import ArchiveIndex, PendingChangeBatch, iter_activities, iter_files
from hsas.domain.courses.define_change_queue import CourseReview
from hsas.domain.information import CourseRecord, InformationStore
from hsas.infrastructure.moodle.load_settings import Settings
from hsas.infrastructure.moodle.synchronize_courses import MoodleCourseGateway
from hsas.infrastructure.storage import JsonChangeQueueRepository, JsonInformationRepository


ASSET_ROOT = Path(__file__).with_name("web")
ALLOWED_ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/assets/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/assets/app.js": ("app.js", "text/javascript; charset=utf-8"),
}
INFORMATION_REPOSITORY = JsonInformationRepository()
CHANGE_REPOSITORY = JsonChangeQueueRepository()
MAX_REQUEST_BYTES = 16 * 1024


class DashboardError(RuntimeError):
    """Safe, user-facing dashboard read failure."""


@dataclass(slots=True)
class DashboardService:
    resources_dir: Path
    mutation_lock: Lock = field(default_factory=Lock, repr=False)

    def information_snapshot(self) -> dict[str, Any]:
        """Return the validated AI-authored database used by the calendar UI."""
        path = self.resources_dir / "information.json"
        if not INFORMATION_REPOSITORY.exists(path):
            store = InformationStore()
            pending = self._pending_batch(None)
            courses = self._dashboard_courses(store, pending)
            return {
                "available": False,
                "schema_version": "1.0",
                "timezone": "Asia/Hong_Kong",
                "updated_at": None,
                "updated_by": None,
                "courses": courses,
                "items": [],
                "summary": {
                    "course_count": len(courses),
                    "item_count": 0,
                    "calendar_item_count": 0,
                    "unknown_date_count": 0,
                },
                "pending_review": _pending_summary(pending),
                "updates": _pending_updates(pending),
                "warnings": [
                    "information.json 尚未建立。请让 AI 阅读本地课程资料并生成更新。"
                ],
            }
        try:
            store = INFORMATION_REPOSITORY.load(path)
        except (OSError, ValueError, ValidationError) as exc:
            raise DashboardError(
                f"information.json 无法通过模型校验：{type(exc).__name__}"
            ) from exc
        calendar_count = sum(
            item.starts_at is not None
            or item.opens_at is not None
            or item.due_at is not None
            or item.due_on is not None
            or item.scheduled_on is not None
            or item.recurrence is not None
            for item in store.items
        )
        payload = store.model_dump(mode="json")
        pending = self._pending_batch(store)
        courses = self._dashboard_courses(store, pending)
        return {
            "available": True,
            **payload,
            "courses": courses,
            "summary": {
                "course_count": len(courses),
                "item_count": len(store.items),
                "calendar_item_count": calendar_count,
                "unknown_date_count": sum(
                    item.date_status == "unknown" for item in store.items
                ),
            },
            "pending_review": _pending_summary(pending),
            "updates": _pending_updates(pending),
            "warnings": [],
        }

    def _dashboard_courses(
        self,
        store: InformationStore,
        pending: PendingChangeBatch,
    ) -> list[dict[str, Any]]:
        archives = {
            index.archive.course.course_id: index
            for index in CHANGE_REPOSITORY.load_archives(self.resources_dir)
        }
        pending_by_course = {review.course_id: review for review in pending.courses}
        entries = []
        matched_archive_ids: set[str] = set()
        for record in store.courses:
            index = _matching_archive(record, archives, matched_archive_ids)
            if index is not None:
                matched_archive_ids.add(index.archive.course.course_id)
            entries.append((record.course_id, record, index))
        entries.extend(
            (course_id, None, index)
            for course_id, index in archives.items()
            if course_id not in matched_archive_ids
        )
        result: list[dict[str, Any]] = []
        for course_id, record, index in entries:
            archive = index.archive if index else None
            if record is not None:
                value = record.model_dump(mode="json")
            else:
                assert archive is not None
                value = {
                    "course_id": course_id,
                    "code": archive.course.title,
                    "title": archive.course.title,
                    "moodle_course_id": course_id,
                    "semester": None,
                    "color": _course_color(course_id),
                    "overview": None,
                    "objectives": [],
                    "instructors": [],
                    "links": [],
                    "policies": [],
                    "notes": [],
                    "sources": [],
                }
            weighted = [
                item
                for item in store.items
                if item.course_id == course_id and item.weight_percent is not None
            ]
            value["grade_distribution"] = [
                {
                    "item_id": item.item_id,
                    "title": item.title,
                    "category": item.category,
                    "weight_percent": item.weight_percent,
                }
                for item in weighted
            ]
            value["materials"] = _course_materials(
                self.resources_dir,
                index,
                pending_by_course.get(archive.course.course_id) if archive else None,
            )
            value["moodle"] = (
                {
                    "url": str(archive.course.url),
                    "collected_at": archive.collected_at.isoformat(),
                    "activity_count": archive.stats.activity_count,
                    "downloaded_file_count": archive.stats.downloaded_file_count,
                    "failed_download_count": archive.stats.failed_download_count,
                }
                if archive
                else None
            )
            result.append(value)
        return result

    def material_file(self, relative_path: str) -> tuple[Path, str]:
        """Resolve only a file referenced by the latest validated course snapshots."""
        allowed = {
            value["original_relative_path"]
            for value in _source_inventory(self.resources_dir).values()
        }
        if relative_path not in allowed:
            raise DashboardError("该文件不在当前课程快照中。")
        resources = self.resources_dir.resolve()
        path = (resources / relative_path).resolve()
        if not path.is_relative_to(resources) or not path.is_file():
            raise DashboardError("本地课件不存在或路径无效。")
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return path, content_type

    def source_preview(
        self,
        relative_path: str,
        page_numbers: list[int] | None = None,
    ) -> dict[str, Any]:
        """Return a bounded preview for a source in the current Moodle archive."""
        source = _source_inventory(self.resources_dir).get(relative_path)
        if source is None:
            raise DashboardError("该来源不在当前课程快照中。")
        text_path = source.get("text_relative_path")
        preview_text = ""
        truncated = False
        if text_path:
            resolved = _safe_resource_file(self.resources_dir, text_path)
            raw_text = resolved.read_text(encoding="utf-8", errors="replace")
            preview_text = _select_source_units(raw_text, page_numbers or [])
            if len(preview_text) > 30000:
                preview_text = preview_text[:30000].rstrip() + "\n\n…预览已截断"
                truncated = True
        content_type = source.get("content_type") or "application/octet-stream"
        preview_kind = (
            "pdf"
            if content_type == "application/pdf"
            else "image"
            if content_type.startswith("image/")
            else "text"
        )
        return {
            "title": source["title"],
            "relative_path": relative_path,
            "original_relative_path": source["original_relative_path"],
            "content_type": content_type,
            "preview_kind": preview_kind,
            "text": preview_text,
            "truncated": truncated,
            "page_numbers": page_numbers or [],
        }

    def _pending_review_summary(self, information) -> dict[str, int]:
        return _pending_summary(self._pending_batch(information))

    def _pending_batch(
        self,
        information: InformationStore | None,
    ) -> PendingChangeBatch:
        try:
            return collect_pending_changes(
                self.resources_dir,
                CHANGE_REPOSITORY,
                information=information,
            )
        except (OSError, ValueError, ValidationError) as exc:
            raise DashboardError(
                f"待处理 Moodle 变化无法读取：{type(exc).__name__}"
            ) from exc

    def login_moodle(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Open a visible browser and wait for the user to complete SSO/MFA."""
        if payload.get("confirmed") is not True:
            raise DashboardError("请先确认打开 Moodle 登录窗口。")
        with self.mutation_lock:
            try:
                result = _course_service(self.resources_dir).login_until_ready()
            except Exception as exc:
                raise DashboardError(
                    f"Moodle 登录未完成：{type(exc).__name__}: {str(exc)[:300]}"
                ) from exc
        return {
            "status": result.status,
            "checked_at": result.checked_at,
            "available_course_count": result.available_course_count,
            "error": result.error,
        }

    def synchronize_courses(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Synchronize all courses or one explicitly selected Moodle course."""
        if payload.get("confirmed") is not True:
            raise DashboardError("请先确认开始同步 Moodle 课程资料。")
        course = payload.get("course")
        if course is not None and (not isinstance(course, str) or not course.strip()):
            raise DashboardError("course 必须是 Moodle course ID 或同源 URL。")
        course = course.strip() if isinstance(course, str) else None
        with self.mutation_lock:
            try:
                service = _course_service(self.resources_dir)
                if course:
                    result = service.sync_course(course)
                    return {
                        "scope": "single",
                        "discovered_course_count": 1,
                        "succeeded_course_count": 1,
                        "failed_course_count": 0,
                        "course_id": result.course_id,
                        "report_path": str(result.output_path),
                        "pending_review": self._pending_review_summary(
                            _load_information_if_available(self.resources_dir)
                        ),
                    }
                result = service.sync_all()
            except Exception as exc:
                raise DashboardError(
                    f"Moodle 同步失败，上一份有效资料已保留："
                    f"{type(exc).__name__}: {str(exc)[:300]}"
                ) from exc
        return {
            "scope": "all",
            "discovered_course_count": result.discovered_course_count,
            "succeeded_course_count": len(result.succeeded_course_ids),
            "failed_course_count": len(result.failures),
            "course_id": None,
            "report_path": str(result.report_path),
            "pending_review": self._pending_review_summary(
                _load_information_if_available(self.resources_dir)
            ),
        }


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        service: DashboardService,
    ) -> None:
        self.dashboard_service = service
        self.dashboard_assets = _load_dashboard_assets()
        super().__init__(server_address, handler_class)


class DashboardRequestHandler(BaseHTTPRequestHandler):
    server: DashboardServer

    def do_GET(self) -> None:  # noqa: N802
        if not self._host_is_local():
            self._send_json(HTTPStatus.MISDIRECTED_REQUEST, {"error": "Invalid local host."})
            return
        path = urlparse(self.path).path
        if path == "/api/information":
            try:
                value = self.server.dashboard_service.information_snapshot()
            except DashboardError as exc:
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
                return
            self._send_json(HTTPStatus.OK, value)
            return
        if path == "/api/material":
            relative_path = parse_qs(urlparse(self.path).query).get("path", [""])[0]
            try:
                file_path, content_type = self.server.dashboard_service.material_file(
                    relative_path
                )
            except DashboardError as exc:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
                return
            self._send_file(file_path, content_type)
            return
        if path == "/api/source-preview":
            query = parse_qs(urlparse(self.path).query)
            relative_path = query.get("path", [""])[0]
            try:
                pages = [int(value) for value in query.get("page", []) if int(value) > 0]
                value = self.server.dashboard_service.source_preview(relative_path, pages)
            except (DashboardError, ValueError) as exc:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
                return
            self._send_json(HTTPStatus.OK, value)
            return
        asset = self.server.dashboard_assets.get(path)
        if asset is None:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found."})
            return
        content, content_type = asset
        self.send_response(HTTPStatus.OK)
        self._security_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self) -> None:  # noqa: N802
        if not self._host_is_local():
            self._send_json(HTTPStatus.MISDIRECTED_REQUEST, {"error": "Invalid local host."})
            return
        path = urlparse(self.path).path
        if path not in {"/api/moodle/login", "/api/sync"}:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found."})
            return
        try:
            payload = self._read_json()
            if path == "/api/moodle/login":
                result = self.server.dashboard_service.login_moodle(payload)
            else:
                result = self.server.dashboard_service.synchronize_courses(payload)
        except DashboardError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        except Exception as exc:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": f"Unexpected local UI error: {type(exc).__name__}"},
            )
            return
        self._send_json(HTTPStatus.OK, result)

    def _read_json(self) -> dict[str, Any]:
        if self.headers.get("X-HIQS-Request") != "1":
            raise DashboardError("缺少本地请求标记。")
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip()
        if content_type != "application/json":
            raise DashboardError("Content-Type 必须是 application/json。")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise DashboardError("Content-Length 无效。") from exc
        if length <= 0 or length > MAX_REQUEST_BYTES:
            raise DashboardError("请求内容为空或过大。")
        try:
            value = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DashboardError("请求内容必须是有效 JSON。") from exc
        if not isinstance(value, dict):
            raise DashboardError("请求内容必须是 JSON object。")
        return value

    def _host_is_local(self) -> bool:
        bound_port = self.server.server_address[1]
        allowed = {f"127.0.0.1:{bound_port}", f"localhost:{bound_port}"}
        if bound_port == 80:
            allowed.update({"127.0.0.1", "localhost"})
        return self.headers.get("Host", "").lower() in allowed

    def _send_json(self, status: HTTPStatus, value: dict[str, Any]) -> None:
        content = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._security_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _send_file(self, path: Path, content_type: str) -> None:
        inline_types = {
            "application/pdf",
            "image/gif",
            "image/jpeg",
            "image/png",
            "image/webp",
            "text/plain",
        }
        disposition = "inline" if content_type in inline_types else "attachment"
        encoded_name = quote(path.name, safe="")
        self.send_response(HTTPStatus.OK)
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header(
            "Content-Security-Policy",
            "sandbox; default-src 'none'; frame-ancestors 'self'",
        )
        self.send_header("Content-Type", content_type)
        self.send_header(
            "Content-Disposition",
            f"{disposition}; filename=material; filename*=UTF-8''{encoded_name}",
        )
        self.send_header("Content-Length", str(path.stat().st_size))
        self.end_headers()
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                self.wfile.write(chunk)

    def _security_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'",
        )

    def log_message(self, format: str, *args: object) -> None:
        return


def build_dashboard_server(
    resources_dir: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> DashboardServer:
    if host != "127.0.0.1":
        raise ValueError("HIQS UI only supports the loopback host 127.0.0.1")
    if port < 0 or port > 65535:
        raise ValueError("port must be between 0 and 65535")
    return DashboardServer(
        (host, port),
        DashboardRequestHandler,
        DashboardService(resources_dir=resources_dir),
    )


def _course_service(resources_dir: Path) -> CourseSynchronizationService:
    settings = Settings.load(output_dir=resources_dir)
    return CourseSynchronizationService(MoodleCourseGateway(settings))


def _load_information_if_available(resources_dir: Path):
    path = resources_dir / "information.json"
    return INFORMATION_REPOSITORY.load(path) if INFORMATION_REPOSITORY.exists(path) else None


def serve_dashboard(
    resources_dir: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
    browser_opener: Callable[[str], bool] = webbrowser.open,
) -> None:
    server = build_dashboard_server(resources_dir, host=host, port=port)
    actual_port = server.server_address[1]
    url = f"http://{host}:{actual_port}/"
    print(f"HKU Information Query System: {url}")
    print("Local-only calendar and Moodle controls. Press Ctrl-C to stop.")
    if open_browser:
        browser_opener(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _load_dashboard_assets() -> dict[str, tuple[bytes, str]]:
    return {
        path: ((ASSET_ROOT / filename).read_bytes(), content_type)
        for path, (filename, content_type) in ALLOWED_ASSETS.items()
    }


def _pending_summary(batch: PendingChangeBatch) -> dict[str, int]:
    return {
        "course_count": len(batch.courses),
        "change_count": batch.pending_change_count,
        "full_review_count": sum(course.mode == "full" for course in batch.courses),
    }


def _pending_updates(batch: PendingChangeBatch) -> dict[str, Any]:
    """Shape pending review data for the local update-diff view."""
    return {
        "generated_at": batch.generated_at.isoformat(),
        "courses": [
            {
                "course_id": review.course_id,
                "course_title": review.course_title,
                "mode": review.mode,
                "acknowledge_through": review.acknowledge_through.isoformat(),
                "changes": [change.model_dump(mode="json") for change in review.changes],
                "files": [
                    {
                        "filename": file.filename,
                        "relative_path": file.relative_path,
                        "text_path": file.text_path,
                        "exists": file.exists,
                        "change_action": file.change_action,
                    }
                    for file in review.files
                ],
                "affected_information_item_ids": review.affected_information_item_ids,
            }
            for review in batch.courses
        ],
    }


def _safe_resource_file(resources_dir: Path, relative_path: str) -> Path:
    resources = resources_dir.resolve()
    path = (resources / relative_path).resolve()
    if not path.is_relative_to(resources) or not path.is_file():
        raise DashboardError("本地来源不存在或路径无效。")
    return path


def _source_inventory(resources_dir: Path) -> dict[str, dict[str, Any]]:
    inventory: dict[str, dict[str, Any]] = {}
    for index in CHANGE_REPOSITORY.load_archives(resources_dir):
        course_json = (
            index.source_path.resolve().relative_to(resources_dir.resolve()).as_posix()
            if index.source_path
            else f"courses/{index.archive.course.course_id}/course.json"
        )
        if (resources_dir / course_json).is_file():
            inventory[course_json] = {
                "title": f"{index.archive.course.title} · course.json",
                "original_relative_path": course_json,
                "text_relative_path": course_json,
                "content_type": "application/json",
            }
        for _activity, stored_file in iter_files(index.archive):
            text_path = stored_file.analysis.extracted_text_path if stored_file.analysis else None
            value = {
                "title": stored_file.filename,
                "original_relative_path": stored_file.relative_path,
                "text_relative_path": text_path,
                "content_type": stored_file.content_type
                or mimetypes.guess_type(stored_file.filename)[0]
                or "application/octet-stream",
            }
            inventory[stored_file.relative_path] = value
            if text_path:
                inventory[text_path] = value
    return inventory


def _select_source_units(text: str, page_numbers: list[int]) -> str:
    if not page_numbers:
        return text
    wanted = set(page_numbers)
    chunks: list[str] = []
    current: list[str] = []
    selected = False
    for line in text.splitlines():
        if line.startswith("--- ") and line.endswith(" ---"):
            if selected and current:
                chunks.append("\n".join(current))
            current = [line]
            selected = any(
                line.startswith(f"--- {label} {number} ")
                or line == f"--- {label} {number} ---"
                for label in ("Page", "Slide", "Speaker notes", "Document part")
                for number in wanted
            )
        elif selected:
            current.append(line)
    if selected and current:
        chunks.append("\n".join(current))
    return "\n\n".join(chunks) or text


def _course_color(course_id: str) -> str:
    palette = ("#2563eb", "#0f766e", "#7c3aed", "#c2410c", "#be123c", "#0369a1")
    return palette[sum(course_id.encode("utf-8")) % len(palette)]


def _matching_archive(
    record: CourseRecord,
    archives: dict[str, ArchiveIndex],
    already_matched: set[str],
) -> ArchiveIndex | None:
    explicit_id = record.moodle_course_id or record.course_id
    if explicit_id in archives and explicit_id not in already_matched:
        return archives[explicit_id]
    code = record.code.casefold()
    candidates = [
        index
        for course_id, index in archives.items()
        if course_id not in already_matched
        and code in index.archive.course.title.casefold()
    ]
    return candidates[0] if len(candidates) == 1 else None


def _course_materials(
    resources: Path,
    index: ArchiveIndex | None,
    review: CourseReview | None,
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {"learning": [], "information": []}
    if index is None:
        return grouped
    changed = {
        item.relative_path: item.change_action
        for item in (review.files if review else [])
        if item.relative_path != "course.json"
    }
    archive = index.archive
    section_titles = {
        activity.module_id: section.title
        for section in archive.sections
        for activity in section.activities
    }
    section_titles.update(
        {activity.module_id: "其他" for activity in archive.unassigned_activities}
    )
    for activity in iter_activities(archive):
        if activity.files:
            for stored_file in activity.files:
                material_type = _material_type(
                    activity.name,
                    stored_file.filename,
                    activity.category,
                    section_titles.get(activity.module_id, ""),
                )
                bucket = _material_bucket(material_type)
                path = (resources / stored_file.relative_path).resolve()
                grouped[bucket].append(
                    {
                        "id": f"{activity.module_id}:{stored_file.source_url}",
                        "title": stored_file.filename,
                        "activity_name": activity.name,
                        "section_title": section_titles.get(activity.module_id),
                        "category": activity.category,
                        "material_type": material_type,
                        "relative_path": stored_file.relative_path,
                        "source_url": str(stored_file.source_url),
                        "content_type": stored_file.content_type,
                        "size_bytes": stored_file.size_bytes,
                        "downloaded_at": stored_file.downloaded_at.isoformat(),
                        "text_available": bool(
                            stored_file.analysis
                            and stored_file.analysis.extracted_text_path
                        ),
                        "text_path": (
                            stored_file.analysis.extracted_text_path
                            if stored_file.analysis
                            else None
                        ),
                        "exists": path.is_file(),
                        "change_action": changed.get(stored_file.relative_path),
                        "download_status": activity.download_status,
                        "download_error": activity.download_error,
                    }
                )
        else:
            material_type = _material_type(
                activity.name,
                "",
                activity.category,
                section_titles.get(activity.module_id, ""),
            )
            bucket = _material_bucket(material_type)
            grouped[bucket].append(
                {
                    "id": activity.module_id,
                    "title": activity.name,
                    "activity_name": activity.name,
                    "section_title": section_titles.get(activity.module_id),
                    "category": activity.category,
                    "material_type": material_type,
                    "relative_path": None,
                    "source_url": str(activity.url) if activity.url else None,
                    "content_type": None,
                    "size_bytes": None,
                    "downloaded_at": None,
                    "text_available": False,
                    "exists": False,
                    "change_action": None,
                    "download_status": activity.download_status,
                    "download_error": activity.download_error,
                }
            )
    return grouped


def _material_type(
    activity_name: str,
    filename: str,
    category: str,
    section_title: str,
) -> str:
    value = f"{activity_name} {filename} {section_title}".casefold()
    if category in {"assignment", "quiz"}:
        return "assessment"
    if category in {"announcement", "forum"}:
        return "announcement"
    rules = (
        ("exercises", ("exercise", "problem set", "worksheet", "practice", "习题", "练习")),
        ("tutorial", ("tutorial", "tut ", "workshop", "导修", "辅导课")),
        ("notes", ("note", "handout", "summary", "formula sheet", "讲义", "笔记")),
        ("lecture", ("lecture", "lect ", "slide", "课件", "课堂")),
        ("reading", ("reading", "article", "paper", "textbook", "阅读", "论文")),
        (
            "assessment",
            ("assessment", "assignment", "quiz", "exam", "project", "report", "评核", "作业", "测验", "考试"),
        ),
        (
            "course_information",
            ("introduction", "overview", "syllabus", "course outline", "grading", "schedule", "timetable", "welcome", "简介", "介绍", "课程大纲", "评分", "安排"),
        ),
        ("announcement", ("announcement", "notice", "公告", "通知")),
    )
    for material_type, markers in rules:
        if any(marker in value for marker in markers):
            return material_type
    if filename.casefold().endswith((".ppt", ".pptx")):
        return "lecture"
    return "other"


def _material_bucket(material_type: str) -> str:
    if material_type in {"assessment", "course_information", "announcement"}:
        return "information"
    return "learning"
