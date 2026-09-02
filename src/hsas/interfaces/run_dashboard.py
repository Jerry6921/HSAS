"""Run the local-only HSAS priority dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Lock
from typing import Any, Callable
from urllib.parse import quote, unquote, urlparse
import webbrowser

from pydantic import ValidationError

from hsas.application import (
    PlanGenerationError,
    PlanGenerationRequest,
    assess_plan_freshness,
    generate_validated_plan,
)
from hsas.application.record_execution import ExecutionServiceError, add_execution_record
from hsas.application.synchronize_courses import (
    check_login_status,
    login_until_ready,
    sync_all,
    sync_course,
)
from hsas.domain.courses import ArchiveIndex
from hsas.domain.courses.define_courses import (
    CourseActivity,
    CourseArchive,
    CourseSectionV2,
    StoredFile,
)
from hsas.domain.planning.define_plan import IntegratedPlan, PlanItem
from hsas.infrastructure.moodle.load_settings import Settings
from hsas.infrastructure.storage.persist_data import read_json


ASSET_ROOT = Path(__file__).with_name("web")
MAX_REQUEST_BYTES = 64 * 1024
ALLOWED_ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/assets/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/assets/app.js": ("app.js", "text/javascript; charset=utf-8"),
}
PRIORITY_RANK = {"critical": 0, "high": 1, "medium": 2, "planned": 3}


class DashboardError(RuntimeError):
    """Safe, user-facing dashboard operation failure."""


@dataclass(slots=True)
class DashboardService:
    resources_dir: Path
    mutation_lock: Lock

    def snapshot(self) -> dict[str, Any]:
        plan, plan_error = self._load_plan()
        freshness = assess_plan_freshness(self.resources_dir)
        courses = self._load_courses()
        sync_report = self._load_sync_report()
        items = [] if plan is None else [self._present_item(item) for item in plan.items]
        items.sort(key=lambda item: (PRIORITY_RANK[item["priority"]], item["due_sort"]))

        if plan is None:
            summary = {
                "key_item_count": 0,
                "urgent_item_count": 0,
                "remaining_minutes": 0,
                "updated_at": None,
                "status": "unavailable",
            }
            warnings = [plan_error] if plan_error else []
        else:
            summary = {
                "key_item_count": plan.workload_summary.key_item_count,
                "urgent_item_count": (
                    plan.plan_summary.critical_item_count
                    + plan.plan_summary.high_priority_item_count
                ),
                "remaining_minutes": plan.workload_summary.total_remaining_minutes,
                "updated_at": _iso(plan.updated_at),
                "status": "current" if freshness.current else "stale",
            }
            warnings = _present_dashboard_warnings(
                [*freshness.reasons, *plan.plan_warnings]
            )

        return {
            "summary": summary,
            "freshness": {
                "current": freshness.current,
                "reasons": list(freshness.reasons),
            },
            "items": items,
            "courses": courses,
            "sync": {
                "updated_at": sync_report.get("updated_at"),
                "last_scope": sync_report.get("last_scope"),
                "failures": sync_report.get("failures", []),
            },
            "warnings": warnings,
        }

    def record_execution(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("confirmed") is not True:
            raise DashboardError("Confirm the execution record before saving it.")
        plan_item_id = _required_text(payload, "plan_item_id")
        record_id = _required_text(payload, "record_id")
        planned_minutes = _required_int(payload, "planned_minutes", minimum=1)
        actual_minutes = _required_int(payload, "actual_minutes", minimum=0)
        progress_minutes = _required_int(payload, "progress_minutes", minimum=0)
        completed = payload.get("completed", False)
        if not isinstance(completed, bool):
            raise DashboardError("completed must be true or false.")
        notes = payload.get("notes")
        if notes is not None and not isinstance(notes, str):
            raise DashboardError("notes must be text.")
        notes = notes.strip() if isinstance(notes, str) else None
        if notes == "":
            notes = None

        with self.mutation_lock:
            try:
                _, record, created = add_execution_record(
                    self.resources_dir / "execution_log.json",
                    self.resources_dir / "integrated_plan.json",
                    plan_item_id=plan_item_id,
                    planned_minutes=planned_minutes,
                    actual_minutes=actual_minutes,
                    progress_minutes=progress_minutes,
                    item_completed=completed,
                    notes=notes,
                    record_id=record_id,
                )
            except ExecutionServiceError as exc:
                raise DashboardError(str(exc)) from exc

            plan_refreshed = False
            refresh_error: str | None = None
            try:
                generate_validated_plan(
                    PlanGenerationRequest(resources_dir=self.resources_dir)
                )
                plan_refreshed = True
            except (PlanGenerationError, ValueError) as exc:
                refresh_error = str(exc)

        return {
            "record_id": record.record_id,
            "created": created,
            "plan_refreshed": plan_refreshed,
            "refresh_error": refresh_error,
        }

    def synchronize(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("confirmed") is not True:
            raise DashboardError("Confirm Moodle synchronization before starting it.")
        course = payload.get("course")
        if course is not None and not isinstance(course, str):
            raise DashboardError("course must be a Moodle course ID or URL.")
        course = course.strip() if isinstance(course, str) else None
        settings = Settings.load(output_dir=self.resources_dir)

        with self.mutation_lock:
            try:
                result = sync_course(course, settings) if course else sync_all(settings)
            except Exception as exc:
                raise DashboardError(
                    f"Synchronization failed safely: {type(exc).__name__}: {str(exc)[:300]}"
                ) from exc

            plan_refreshed = False
            refresh_error: str | None = None
            if (self.resources_dir / "student_profile.json").is_file():
                try:
                    generate_validated_plan(
                        PlanGenerationRequest(resources_dir=self.resources_dir)
                    )
                    plan_refreshed = True
                except (PlanGenerationError, ValueError) as exc:
                    refresh_error = str(exc)

        if course:
            sync_result = {
                "scope": "single",
                "succeeded": 1,
                "failed": 0,
                "course_id": result.course_id,
            }
        else:
            sync_result = {
                "scope": "all",
                "succeeded": len(result.succeeded_course_ids),
                "failed": len(result.failures),
                "course_id": None,
            }
        return {
            **sync_result,
            "plan_refreshed": plan_refreshed,
            "refresh_error": refresh_error,
        }

    def check_moodle_session(self) -> dict[str, Any]:
        settings = Settings.load(output_dir=self.resources_dir)
        with self.mutation_lock:
            result = check_login_status(settings)
        return {
            "status": result.status,
            "checked_at": result.checked_at,
            "available_course_count": result.available_course_count,
            "error": result.error,
        }

    def login_moodle(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("confirmed") is not True:
            raise DashboardError("Confirm before opening the Moodle login browser.")
        settings = Settings.load(output_dir=self.resources_dir)
        with self.mutation_lock:
            try:
                result = login_until_ready(settings)
            except Exception as exc:
                raise DashboardError(
                    f"Moodle login was not completed: {type(exc).__name__}: {str(exc)[:300]}"
                ) from exc
        return {
            "status": result.status,
            "checked_at": result.checked_at,
            "available_course_count": result.available_course_count,
            "error": result.error,
        }

    def course_materials(self, course_id: str) -> dict[str, Any]:
        index = self._load_course_index(course_id)
        sections = [
            self._present_material_section(index, section)
            for section in index.archive.sections
            if section.activities
        ]
        if index.archive.unassigned_activities:
            sections.append(
                {
                    "section_id": None,
                    "title": "其他课程内容",
                    "current": False,
                    "visible": True,
                    "activities": [
                        self._present_material_activity(
                            course_id,
                            activity,
                        )
                        for activity in index.archive.unassigned_activities
                    ],
                }
            )
        return {
            "course_id": index.archive.course.course_id,
            "course_title": index.archive.course.title,
            "collected_at": _iso(index.archive.collected_at),
            "downloaded_file_count": index.archive.stats.downloaded_file_count,
            "analyzed_pdf_count": index.archive.stats.analyzed_pdf_count,
            "failed_download_count": index.archive.stats.failed_download_count,
            "sections": sections,
        }

    def course_information(self, course_id: str) -> dict[str, Any]:
        index = self._load_course_index(course_id)
        return {
            "course_id": index.archive.course.course_id,
            "course_title": index.archive.course.title,
            "collected_at": _iso(index.archive.collected_at),
            "course_json": index.archive.model_dump(mode="json"),
        }

    def resolve_material_file(
        self,
        course_id: str,
        module_id: str,
        file_index: int,
    ) -> tuple[Path, StoredFile]:
        index = self._load_course_index(course_id)
        activity = index.get_activity(module_id)
        if activity is None:
            raise DashboardError("Unknown course activity.")
        if file_index < 0 or file_index >= len(activity.files):
            raise DashboardError("Unknown course file.")
        stored_file = activity.files[file_index]
        resources = self.resources_dir.resolve()
        path = (resources / stored_file.relative_path).resolve()
        if not path.is_relative_to(resources) or not path.is_file():
            raise DashboardError("The downloaded course file is unavailable.")
        return path, stored_file

    def _load_plan(self) -> tuple[IntegratedPlan | None, str | None]:
        path = self.resources_dir / "integrated_plan.json"
        if not path.is_file():
            return None, "Integrated Plan does not exist. Sync courses and update the plan first."
        try:
            return IntegratedPlan.model_validate_json(path.read_text(encoding="utf-8")), None
        except (OSError, ValidationError) as exc:
            return None, f"Integrated Plan is invalid: {type(exc).__name__}"

    def _load_course_index(self, course_id: str) -> ArchiveIndex:
        if not course_id.isdigit():
            raise DashboardError("Invalid Moodle course ID.")
        path = self.resources_dir / "courses" / course_id / "course.json"
        if not path.is_file():
            raise DashboardError("Course archive does not exist.")
        try:
            return ArchiveIndex.from_json(path)
        except (OSError, ValidationError, ValueError) as exc:
            raise DashboardError("Course archive is invalid.") from exc

    def _load_courses(self) -> list[dict[str, Any]]:
        report = self._load_sync_report()
        statuses = report.get("courses")
        if not isinstance(statuses, dict):
            statuses = {}
        courses: list[dict[str, Any]] = []
        for path in sorted((self.resources_dir / "courses").glob("*/course.json")):
            try:
                archive = CourseArchive.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValidationError):
                courses.append(
                    {
                        "course_id": path.parent.name,
                        "title": "Invalid or incompatible course archive",
                        "collected_at": None,
                        "activity_count": 0,
                        "file_count": 0,
                        "sync_status": "invalid",
                        "change_count": 0,
                        "error": "The local course archive could not be validated.",
                    }
                )
                continue
            status = statuses.get(archive.course.course_id, {})
            succeeded = status.get("succeeded") if isinstance(status, dict) else None
            sync_status = "current" if succeeded is True else "failed" if succeeded is False else "unknown"
            courses.append(
                {
                    "course_id": archive.course.course_id,
                    "title": archive.course.title,
                    "collected_at": _iso(archive.collected_at),
                    "activity_count": archive.stats.activity_count,
                    "file_count": archive.stats.downloaded_file_count,
                    "sync_status": sync_status,
                    "change_count": (
                        int(status.get("change_count") or 0)
                        if isinstance(status, dict)
                        else 0
                    ),
                    "error": status.get("error") if isinstance(status, dict) else None,
                }
            )
        return courses

    def _load_sync_report(self) -> dict[str, Any]:
        path = self.resources_dir / "sync-report.json"
        if not path.is_file():
            return {}
        try:
            value = read_json(path)
        except (OSError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _present_item(item: PlanItem) -> dict[str, Any]:
        due_at = item.official_timing.due_at
        due_on = item.official_timing.due_on
        scheduled_at = item.official_timing.scheduled_at
        scheduled_on = item.official_timing.scheduled_on
        timing = due_at or scheduled_at
        timing_date = due_on or scheduled_on
        due_value = _iso(timing) if timing else timing_date.isoformat() if timing_date else None
        due_sort = due_value or "9999-12-31"
        total = item.effort.estimated_total_minutes
        completed = item.effort.completed_minutes
        remaining = item.effort.remaining_minutes
        progress_percent = 0
        if total and total > 0:
            progress_percent = min(100, round(completed / total * 100))
        reasons = [
            item.priority.rationale,
            item.academic_impact.importance_rationale,
            item.learning_demand.difficulty_rationale,
        ]
        reasons = [reason for reason in dict.fromkeys(reasons) if reason]
        return {
            "plan_item_id": item.plan_item_id,
            "course_id": item.course_id,
            "course_title": item.course_title,
            "item_type": item.item_type,
            "title": item.title,
            "description": item.description,
            "priority": item.priority.level,
            "priority_rationale": item.priority.rationale,
            "priority_inputs": item.priority.derived_from,
            "status": item.status,
            "readiness": item.readiness,
            "due": due_value,
            "due_confirmed": item.official_timing.is_confirmed,
            "due_sort": due_sort,
            "estimated_minutes": total,
            "completed_minutes": completed,
            "remaining_minutes": remaining,
            "actual_minutes": item.effort.actual_minutes_spent,
            "progress_percent": progress_percent,
            "completion_criteria": item.completion_criteria,
            "reasons": reasons,
            "warnings": item.warnings,
            "source_references": [
                {
                    "source_type": reference.source_type,
                    "relative_path": reference.relative_path,
                    "page_numbers": reference.page_numbers,
                    "note": reference.note,
                }
                for reference in item.source_references
            ],
        }

    def _present_material_section(
        self,
        index: ArchiveIndex,
        section: CourseSectionV2,
    ) -> dict[str, Any]:
        return {
            "section_id": section.section_id,
            "title": section.title,
            "current": section.current,
            "visible": section.visible,
            "activities": [
                self._present_material_activity(index.archive.course.course_id, activity)
                for activity in section.activities
            ],
        }

    def _present_material_activity(
        self,
        course_id: str,
        activity: CourseActivity,
    ) -> dict[str, Any]:
        files = []
        for file_index, stored_file in enumerate(activity.files):
            analysis = stored_file.analysis
            files.append(
                {
                    "filename": stored_file.filename,
                    "content_type": stored_file.content_type,
                    "size_bytes": stored_file.size_bytes,
                    "downloaded_at": _iso(stored_file.downloaded_at),
                    "available": (
                        self.resources_dir / stored_file.relative_path
                    ).is_file(),
                    "open_url": (
                        f"/api/courses/{quote(course_id)}/materials/"
                        f"{quote(activity.module_id, safe='')}/files/{file_index}"
                    ),
                    "analysis": (
                        {
                            "status": analysis.status,
                            "page_count": analysis.page_count,
                            "pages_with_text": analysis.pages_with_text,
                            "word_count": analysis.word_count,
                            "ocr_required": analysis.ocr_required,
                            "warnings": analysis.warnings,
                        }
                        if analysis is not None
                        else None
                    ),
                }
            )
        return {
            "module_id": activity.module_id,
            "name": activity.name,
            "category": activity.category,
            "visible": activity.visible and activity.user_visible and activity.access_visible,
            "has_restrictions": activity.has_restrictions,
            "download_status": activity.download_status,
            "download_error": activity.download_error,
            "moodle_url": str(activity.url) if activity.url else None,
            "files": files,
        }


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler: type[BaseHTTPRequestHandler],
        service: DashboardService,
    ) -> None:
        self.dashboard_assets = _load_dashboard_assets()
        super().__init__(server_address, handler)
        self.dashboard_service = service


class DashboardRequestHandler(BaseHTTPRequestHandler):
    server: DashboardServer

    def do_GET(self) -> None:  # noqa: N802
        if not self._host_is_local():
            self._send_json(HTTPStatus.MISDIRECTED_REQUEST, {"error": "Invalid local host."})
            return
        path = urlparse(self.path).path
        if path == "/api/dashboard":
            self._send_json(HTTPStatus.OK, self.server.dashboard_service.snapshot())
            return
        parts = [unquote(part) for part in path.strip("/").split("/")]
        if len(parts) == 4 and parts[:2] == ["api", "courses"] and parts[3] == "materials":
            try:
                value = self.server.dashboard_service.course_materials(parts[2])
            except DashboardError as exc:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
                return
            self._send_json(HTTPStatus.OK, value)
            return
        if len(parts) == 3 and parts[:2] == ["api", "courses"]:
            try:
                value = self.server.dashboard_service.course_information(parts[2])
            except DashboardError as exc:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
                return
            self._send_json(HTTPStatus.OK, value)
            return
        if (
            len(parts) == 7
            and parts[:2] == ["api", "courses"]
            and parts[3] == "materials"
            and parts[5] == "files"
        ):
            try:
                file_index = int(parts[6])
                file_path, stored_file = self.server.dashboard_service.resolve_material_file(
                    parts[2], parts[4], file_index
                )
            except (DashboardError, ValueError) as exc:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
                return
            self._send_material_file(file_path, stored_file)
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
        if path not in {
            "/api/executions",
            "/api/sync",
            "/api/moodle/session",
            "/api/moodle/login",
        }:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found."})
            return
        try:
            payload = self._read_json()
            if path == "/api/executions":
                result = self.server.dashboard_service.record_execution(payload)
            elif path == "/api/sync":
                result = self.server.dashboard_service.synchronize(payload)
            elif path == "/api/moodle/session":
                result = self.server.dashboard_service.check_moodle_session()
            else:
                result = self.server.dashboard_service.login_moodle(payload)
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
        if self.headers.get("X-HSAS-Request") != "1":
            raise DashboardError("Missing local request marker.")
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip()
        if content_type != "application/json":
            raise DashboardError("Content-Type must be application/json.")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise DashboardError("Invalid Content-Length.") from exc
        if length <= 0 or length > MAX_REQUEST_BYTES:
            raise DashboardError("Request body is empty or too large.")
        try:
            value = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DashboardError("Request body must be valid JSON.") from exc
        if not isinstance(value, dict):
            raise DashboardError("Request body must be a JSON object.")
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

    def _send_material_file(self, path: Path, stored_file: StoredFile) -> None:
        content = path.read_bytes()
        content_type = stored_file.content_type or "application/octet-stream"
        inline_types = {
            "application/pdf",
            "image/gif",
            "image/jpeg",
            "image/png",
            "image/webp",
            "text/plain",
        }
        disposition = "inline" if content_type in inline_types else "attachment"
        encoded_name = quote(stored_file.filename, safe="")
        self.send_response(HTTPStatus.OK)
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "sandbox; default-src 'none'")
        self.send_header("Content-Type", content_type)
        self.send_header(
            "Content-Disposition",
            f"{disposition}; filename=material; filename*=UTF-8''{encoded_name}",
        )
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

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
        raise ValueError("HSAS UI only supports the loopback host 127.0.0.1")
    if port < 0 or port > 65535:
        raise ValueError("port must be between 0 and 65535")
    service = DashboardService(resources_dir=resources_dir, mutation_lock=Lock())
    return DashboardServer((host, port), DashboardRequestHandler, service)


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
    print(f"HSAS UI: {url}")
    print("Local-only server. Press Ctrl-C to stop.")
    if open_browser:
        browser_opener(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DashboardError(f"{key} is required.")
    return value.strip()


def _load_dashboard_assets() -> dict[str, tuple[bytes, str]]:
    return {
        path: ((ASSET_ROOT / filename).read_bytes(), content_type)
        for path, (filename, content_type) in ALLOWED_ASSETS.items()
    }


def _required_int(payload: dict[str, Any], key: str, *, minimum: int) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise DashboardError(f"{key} must be an integer of at least {minimum}.")
    return value


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def _present_dashboard_warnings(values: list[str] | tuple[str, ...]) -> list[str]:
    unique = list(dict.fromkeys(values))
    missing_status: list[str] = []
    presented: list[str] = []
    missing_suffix = " has no synchronization status."
    omitted_prefix = "Items that are no longer key priorities were omitted during refresh: "
    for warning in unique:
        if warning.startswith("Course ") and warning.endswith(missing_suffix):
            missing_status.append(warning[len("Course ") : -len(missing_suffix)])
            continue
        if warning.startswith(omitted_prefix):
            item_ids = warning[len(omitted_prefix) :]
            presented.append(
                "计划刷新时，以下旧事项未继续进入当前关键优先级清单；"
                f"这不代表事项已经完成：{item_ids}"
            )
            continue
        presented.append(warning)
    if missing_status:
        presented.insert(
            0,
            f"{len(missing_status)} 门课程有本地归档，但最近的同步报告没有对应状态；"
            "课件仍可使用，最新 Moodle 状态尚未验证。课程 ID："
            + "、".join(missing_status),
        )
    return presented
