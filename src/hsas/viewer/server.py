"""Serve the read-only viewer on the loopback interface.

The viewer never writes: there is no POST handler, no form, and every file it
serves has already been whitelisted by the same material service MCP uses.
"""

from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from urllib.parse import parse_qs, unquote, urlparse
import webbrowser

from hsas.application.delivery import build_delivery
from hsas.core import HIQSPort, HIQSPortError

from .pages import render_course, render_courses, render_error, render_status, render_text
from .revisions import data_revision

LOOPBACK = "127.0.0.1"
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def _snapshot(core: HIQSPort) -> dict:
    return core.information_snapshot()


def _revision(core: HIQSPort) -> str:
    return data_revision(core.resources_dir)


class _Handler(BaseHTTPRequestHandler):
    server_version = "HIQS-Viewer"
    core: HIQSPort  # set on the subclass built by create_viewer_server

    def log_message(self, *_args) -> None:  # keep stdout clean for the CLI
        return

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in SECURITY_HEADERS.items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_json(self, status: int, payload: dict) -> None:
        self._send(status, json.dumps(payload).encode("utf-8"), "application/json")

    def _send_html(self, status: int, html: str) -> None:
        self._send(status, html.encode("utf-8"), "text/html; charset=utf-8")

    def do_HEAD(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        self.do_GET()

    def do_POST(self) -> None:  # noqa: N802
        self._send_html(HTTPStatus.METHOD_NOT_ALLOWED, render_error(405, "This viewer is read-only."))

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        try:
            if path == "/":
                snapshot = _snapshot(self.core)
                self._send_html(
                    HTTPStatus.OK,
                    render_status(
                        snapshot,
                        self.core.attention_snapshot(),
                        build_delivery(
                            self.core.apple_status(),
                            information_updated_at=snapshot.get("updated_at"),
                        ),
                        rev=_revision(self.core),
                    ),
                )
            elif path == "/rev":
                self._send_json(HTTPStatus.OK, {"rev": _revision(self.core)})
            elif path == "/courses":
                self._send_html(
                    HTTPStatus.OK,
                    render_courses(_snapshot(self.core), rev=_revision(self.core)),
                )
            elif path.startswith("/courses/"):
                course_id = unquote(path[len("/courses/"):])
                html = render_course(
                    _snapshot(self.core), course_id, rev=_revision(self.core)
                )
                if html is None:
                    self._send_html(HTTPStatus.NOT_FOUND, render_error(404, "No such course."))
                else:
                    self._send_html(HTTPStatus.OK, html)
            elif path in ("/file", "/preview"):
                self._serve_material(path, query.get("path") or [""])
            else:
                self._send_html(HTTPStatus.NOT_FOUND, render_error(404, "No such page."))
        except HIQSPortError as exc:
            self._send_html(HTTPStatus.NOT_FOUND, render_error(404, str(exc)))

    def _serve_material(self, route: str, requested: list[str]) -> None:
        relative = requested[0]
        if not relative:
            self._send_html(HTTPStatus.BAD_REQUEST, render_error(400, "Missing path."))
            return
        if route == "/file":
            path, content_type = self.core.material_file(relative)
            content = path.read_bytes()
            self._send(HTTPStatus.OK, content, content_type)
            return
        preview = self.core.source_preview(relative)
        self._send_html(
            HTTPStatus.OK,
            render_text(
                str(preview.get("title") or "source"),
                str(preview.get("text") or ""),
                truncated=bool(preview.get("truncated")),
            ),
        )


def create_viewer_server(core: HIQSPort, *, host: str = LOOPBACK, port: int = 0) -> ThreadingHTTPServer:
    """Build a server without starting it, so tests can bind port 0."""
    handler = type("ViewerHandler", (_Handler,), {"core": core})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


def serve_viewer(
    core: HIQSPort,
    *,
    host: str = LOOPBACK,
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    """Serve until interrupted. Always binds loopback unless host is given."""
    if host not in {LOOPBACK, "localhost"}:
        raise ValueError("the viewer only binds the loopback interface")
    server = create_viewer_server(core, host=host, port=port)
    url = f"http://{host}:{server.server_address[1]}/"
    print(f"HIQS viewer: {url}", flush=True)
    if open_browser:
        threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


__all__ = ["create_viewer_server", "serve_viewer"]
