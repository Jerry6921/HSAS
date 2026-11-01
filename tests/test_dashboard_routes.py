"""Smoke every compatibility-UI HTTP route so facade renames cannot 500 silently."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from hsas.infrastructure.moodle.course_mapper import build_course_archive
from hsas.infrastructure.storage.json_store import write_json, write_model
from hsas.web.server import build_dashboard_server

ROOT = Path(__file__).parents[1]

GET_JSON_ROUTES = (
    "/api/information",
    "/api/attention?horizon_days=7",
    "/api/update/status",
    "/api/sync/status",
)

GET_NOT_FOUND_ROUTES = (
    "/api/material?path=courses/138907/missing.pdf",
    "/api/source-preview?path=courses/138907/missing.pdf",
    "/api/evidence/unknown",
    "/api/evidence-explanation/unknown",
)

POST_ROUTES = (
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
)


@pytest.fixture
def base_url(tmp_path: Path):
    state = json.loads((ROOT / "tests/fixtures/course_state.json").read_text())
    archive = build_course_archive(
        state,
        course_title="Neuroscience Demo",
        raw_state_path="courses/138907/raw/course-state.json",
    )
    write_model(tmp_path / "courses/138907/course.json", archive)
    write_json(
        tmp_path / "information.json",
        {
            "schema_version": "1.0",
            "timezone": "Asia/Hong_Kong",
            "updated_at": "2026-10-27T06:17:29.118451Z",
            "updated_by": "ai_agent",
            "courses": [],
            "items": [],
        },
    )
    server = build_dashboard_server(tmp_path, port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _get(url: str) -> tuple[int, str, bytes]:
    try:
        with urlopen(url, timeout=10) as response:  # noqa: S310 - loopback only
            return response.status, response.headers.get("Content-Type", ""), response.read()
    except HTTPError as exc:
        return exc.code, exc.headers.get("Content-Type", ""), exc.read()


def _post(url: str) -> tuple[int, str, bytes]:
    request = Request(
        url,
        data=b"{}",
        headers={"Content-Type": "application/json", "X-HIQS-Request": "1"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:  # noqa: S310 - loopback only
            return response.status, response.headers.get("Content-Type", ""), response.read()
    except HTTPError as exc:
        return exc.code, exc.headers.get("Content-Type", ""), exc.read()


def test_get_json_routes_return_200_json(base_url: str) -> None:
    for route in GET_JSON_ROUTES:
        status, content_type, body = _get(base_url + route)
        assert status == 200, f"{route} -> {status}"
        assert "application/json" in content_type
        assert isinstance(json.loads(body), dict), route


def test_calendar_route_returns_ics(base_url: str) -> None:
    status, content_type, body = _get(base_url + "/api/calendar.ics")
    assert status == 200
    assert "text/calendar" in content_type
    assert body.startswith(b"BEGIN:VCALENDAR")


def test_unknown_material_routes_return_json_404(base_url: str) -> None:
    for route in GET_NOT_FOUND_ROUTES:
        status, content_type, body = _get(base_url + route)
        assert status == 404, f"{route} -> {status}"
        assert "application/json" in content_type
        payload = json.loads(body)
        assert payload.get("error") or payload.get("reason") or payload.get("status")


def test_post_routes_dispatch_and_reject_invalid_payloads(base_url: str) -> None:
    for route in POST_ROUTES:
        status, content_type, body = _post(base_url + route)
        assert status != 500, f"{route} raised an unhandled error"
        assert status != 405, f"{route} is not dispatched"
        assert "application/json" in content_type, route
        payload = json.loads(body)
        assert "error" in payload or payload, route
