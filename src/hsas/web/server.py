"""Human-facing local HTTP adapter backed only by the HIQS port."""

from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, quote, unquote, urlparse
import webbrowser

from hsas.core import HIQSPort, HIQSPortError, build_port

ASSET_ROOT = Path(__file__).with_name("static")
ALLOWED_ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/assets/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/assets/ripple.js": ("ripple.js", "text/javascript; charset=utf-8"),
    "/assets/canvas-effects.js": ("canvas-effects.js", "text/javascript; charset=utf-8"),
    "/assets/modern-ui.css": ("modern-assets/modern-ui.css", "text/css; charset=utf-8"),
    "/assets/modern-ui.js": ("modern-assets/modern-ui.js", "text/javascript; charset=utf-8"),
    "/assets/app.js": ("app.js", "text/javascript; charset=utf-8"),
}
MAX_REQUEST_BYTES = 16 * 1024
DashboardError = HIQSPortError

class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        service: HIQSPort,
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
        if path == "/api/attention":
            query = parse_qs(urlparse(self.path).query)
            try:
                horizon_days = int(query.get("horizon_days", ["14"])[0])
                value = self.server.dashboard_service.attention_snapshot(horizon_days)
            except (DashboardError, ValueError) as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            self._send_json(HTTPStatus.OK, value)
            return
        if path == "/api/update/status":
            self._send_json(
                HTTPStatus.OK,
                self.server.dashboard_service.application_update_status(),
            )
            return
        if path == "/api/sync/status":
            self._send_json(
                HTTPStatus.OK,
                self.server.dashboard_service.course_sync_status(),
            )
            return
        if path == "/api/moodle/status":
            self._send_json(
                HTTPStatus.OK,
                self.server.dashboard_service.verify_moodle_session(),
            )
            return
        if path == "/api/calendar.ics":
            try:
                content = self.server.dashboard_service.calendar_ics()
            except DashboardError as exc:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
                return
            self.send_response(HTTPStatus.OK)
            self._security_headers()
            self.send_header("Content-Type", "text/calendar; charset=utf-8")
            self.send_header(
                "Content-Disposition", 'attachment; filename="HIQS-calendar.ics"'
            )
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
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
        if path.startswith("/api/evidence/"):
            evidence_id = unquote(path.removeprefix("/api/evidence/"))
            try:
                value = self.server.dashboard_service.get_evidence(evidence_id)
            except DashboardError as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            status = HTTPStatus.OK if value.get("status") == "found" else HTTPStatus.NOT_FOUND
            self._send_json(status, value)
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
            "/api/moodle/login",
            "/api/moodle/preview",
            "/api/sync",
            "/api/sync/start",
            "/api/sync/retry",
            "/api/sync/cancel",
            "/api/class-planner/login",
            "/api/class-planner/sync",
            "/api/sis-course-info/login",
            "/api/sis-course-info/sync",
            "/api/ocr/run",
            "/api/inbox/apply",
            "/api/attention/draft",
            "/api/courses/add",
            "/api/courses/delete",
            "/api/courses/delete-many",
            "/api/events/add",
            "/api/events/delete",
            "/api/update/apply",
        }:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found."})
            return
        try:
            payload = self._read_json()
            if path == "/api/moodle/login":
                result = self.server.dashboard_service.login_moodle(payload)
            elif path == "/api/moodle/preview":
                result = self.server.dashboard_service.moodle_page_preview(payload)
            elif path == "/api/sync":
                result = self.server.dashboard_service.synchronize_courses(payload)
            elif path == "/api/sync/start":
                result = self.server.dashboard_service.start_course_sync(payload)
            elif path == "/api/sync/retry":
                result = self.server.dashboard_service.retry_failed_course_sync(payload)
            elif path == "/api/sync/cancel":
                result = self.server.dashboard_service.cancel_course_sync(payload)
            elif path == "/api/class-planner/login":
                result = self.server.dashboard_service.login_class_planner(payload)
            elif path == "/api/class-planner/sync":
                result = self.server.dashboard_service.synchronize_class_planner(payload)
            elif path == "/api/sis-course-info/login":
                result = self.server.dashboard_service.login_sis_course_info(payload)
            elif path == "/api/sis-course-info/sync":
                result = self.server.dashboard_service.synchronize_sis_course_info(payload)
            elif path == "/api/ocr/run":
                result = self.server.dashboard_service.process_ocr_queue(payload)
            elif path == "/api/courses/add":
                result = self.server.dashboard_service.add_course(payload)
            elif path == "/api/courses/delete":
                result = self.server.dashboard_service.delete_course(payload)
            elif path == "/api/courses/delete-many":
                result = self.server.dashboard_service.delete_courses(payload)
            elif path == "/api/events/add":
                result = self.server.dashboard_service.add_calendar_event(payload)
            elif path == "/api/events/delete":
                result = self.server.dashboard_service.delete_calendar_event(payload)
            elif path == "/api/update/apply":
                result = self.server.dashboard_service.apply_application_update(payload)
            elif path == "/api/attention/draft":
                result = self.server.dashboard_service.add_attention_draft(payload)
            else:
                result = self.server.dashboard_service.apply_personal_inbox(payload)
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
            _material_content_security_policy(content_type),
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
            "default-src 'self'; script-src 'self'; "
            "style-src 'self' 'nonce-hiqs-local-ui'; "
            "img-src 'self' data:; font-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'",
        )

    def log_message(self, format: str, *args: object) -> None:
        return


def build_dashboard_server(
    resources_dir: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    service: HIQSPort | None = None,
) -> DashboardServer:
    if host != "127.0.0.1":
        raise ValueError("HIQS UI only supports the loopback host 127.0.0.1")
    if port < 0 or port > 65535:
        raise ValueError("port must be between 0 and 65535")
    return DashboardServer(
        (host, port),
        DashboardRequestHandler,
        service or build_port(resources_dir),
    )

def serve_dashboard(
    resources_dir: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
    browser_opener: Callable[[str], bool] = webbrowser.open,
    service: HIQSPort | None = None,
) -> None:
    server = build_dashboard_server(
        resources_dir,
        host=host,
        port=port,
        service=service,
    )
    actual_port = server.server_address[1]
    url = f"http://{host}:{actual_port}/"
    print(f"HKU Information Query System: {url}", flush=True)
    print("Local-only calendar and Moodle controls. Press Ctrl-C to stop.", flush=True)
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


def _material_content_security_policy(content_type: str) -> str:
    """Keep active documents sandboxed without disabling native media viewers."""
    if content_type == "application/pdf" or content_type.startswith("image/"):
        return "default-src 'none'; base-uri 'none'; frame-ancestors 'self'"
    return "sandbox; default-src 'none'; base-uri 'none'; frame-ancestors 'self'"
