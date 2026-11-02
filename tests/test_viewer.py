"""The viewer must show the truth cheaply, and must never write."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import threading
from unittest.mock import Mock
import urllib.error
import urllib.request

import pytest

from hsas.application.freshness import build_freshness
from hsas.core import HIQSPort, HIQSPortError
from hsas.viewer import create_viewer_server
from hsas.viewer.revisions import data_revision
from hsas.viewer.pages import (
    render_course,
    render_courses,
    render_status,
    render_text,
)

NOW = datetime(2026, 11, 2, 7, 0, tzinfo=UTC)


def _snapshot() -> dict:
    return {
        "available": True,
        "courses": [
            {
                "course_id": "C1",
                "code": "BMED2206",
                "title": "Engineering in Biology",
                "moodle": {
                    "collected_at": (NOW - timedelta(days=9)).isoformat(),
                    "download_failed_count": 2,
                },
                "materials": {
                    "all": [
                        {
                            "title": "Lecture Note 3.pdf",
                            "activity_name": "Biomaterials",
                            "section_title": "Lectures",
                            "relative_path": "courses/C1/files/Lecture 3.pdf",
                            "downloaded_at": "2026-10-20T00:00:00+00:00",
                        },
                        {
                            "title": "Lecture Note 5.pdf",
                            "activity_name": "Tissue engineering",
                            "section_title": "Lectures",
                            "relative_path": "courses/C1/files/Lecture 5.pdf",
                            "downloaded_at": "2026-10-27T00:00:00+00:00",
                        },
                        {
                            "title": "Lab manual.pdf",
                            "activity_name": "Lab",
                            "relative_path": "courses/C1/files/Lab manual.pdf",
                            "downloaded_at": "2026-10-28T00:00:00+00:00",
                        },
                        {
                            "title": "Electrochemistry.pdf",
                            "activity_name": "Electrochemistry (2026-10-30 by Prof. Zhang)",
                            "relative_path": "courses/C1/files/Electrochemistry.pdf",
                            "downloaded_at": "2026-10-01T00:00:00+00:00",
                        },
                    ]
                },
                "material_sections": [
                    {
                        "title": "Lectures",
                        "materials": [
                            {
                                "title": "Note 1.pdf",
                                "material_type": "PDF",
                                "relative_path": "courses/C1/files/Note 1.pdf",
                                "page_numbers": [3],
                            }
                        ],
                    }
                ],
            }
        ],
        "items": [
            {
                "item_id": "item-1",
                "course_id": "C1",
                "title": "Quiz 2",
                "category": "quiz",
                "due_at": "2026-11-10T10:00:00+08:00",
                "date_status": "confirmed",
            }
        ],
        "summary": {"course_count": 1, "item_count": 1, "calendar_item_count": 1},
        "pending_review": {"change_count": 0},
        "freshness": build_freshness(
            {
                "updated_at": (NOW - timedelta(days=1)).isoformat(),
                "courses": [{"moodle": {"collected_at": (NOW - timedelta(days=9)).isoformat()}}],
                "sis_enrollment": {"observed_at": (NOW - timedelta(days=1)).isoformat()},
                "class_planner": {"synced_at": (NOW - timedelta(days=1)).isoformat()},
                "sis_course_info": {"synced_at": (NOW - timedelta(days=1)).isoformat()},
            },
            now=NOW,
        ),
    }


def test_status_page_leads_with_staleness_not_with_counts() -> None:
    html = render_status(_snapshot(), {"items": []})

    assert "Needs a sync" in html
    assert "stale: moodle" in html
    assert html.index("Freshness") < html.index("Contents")
    assert "9d" in html and "/ 3d limit" in html


def test_status_page_says_nothing_when_everything_is_fresh() -> None:
    snapshot = _snapshot()
    snapshot["freshness"] = build_freshness(
        {
            "updated_at": (NOW - timedelta(hours=1)).isoformat(),
            "courses": [{"moodle": {"collected_at": (NOW - timedelta(hours=1)).isoformat()}}],
            "sis_enrollment": {"observed_at": (NOW - timedelta(hours=1)).isoformat()},
            "class_planner": {"synced_at": (NOW - timedelta(hours=1)).isoformat()},
            "sis_course_info": {"synced_at": (NOW - timedelta(hours=1)).isoformat()},
        },
        now=NOW,
    )

    html = render_status(snapshot, {"items": []})

    assert "All sources are within their freshness limit" in html
    assert "Needs a sync" not in html


def test_courses_page_lists_materials_and_the_last_capture() -> None:
    html = render_courses(_snapshot())

    assert "BMED2206" in html
    assert "Engineering in Biology" in html
    assert "/courses/C1" in html


def test_course_page_links_each_material_to_its_file_and_text() -> None:
    html = render_course(_snapshot(), "C1")

    assert html is not None
    assert "Note 1.pdf" in html
    assert "p.3" in html
    assert "/file?path=courses/C1/files/Note%201.pdf" in html
    assert "/preview?path=courses/C1/files/Note%201.pdf" in html
    assert "Quiz 2" in html


def test_home_page_surfaces_the_newest_lecture_per_course() -> None:
    html = render_status(_snapshot(), {"items": []})

    assert "Latest lecture materials" in html
    # The lecture's own date outranks a later download and a newer lab manual.
    assert "Electrochemistry.pdf" in html
    assert "Lecture Note 5.pdf" not in html
    assert "/file?path=courses/C1/files/Electrochemistry.pdf" in html
    assert "2026-10-30" in html


def test_home_page_reports_apple_delivery_against_the_current_facts() -> None:
    delivery = {
        "configured": True,
        "worker_loaded": True,
        "counts": {"events": 49, "reminders": 13},
        "verification": {"matched": 62, "expected": 62, "status": "verified"},
        "last_delivered_at": "2026-11-02T07:13:18+00:00",
        "facts_updated_at": "2026-10-27T06:17:29Z",
        "up_to_date_with_facts": True,
        "why": "Apple reflects the current facts",
    }

    html = render_status(_snapshot(), {"items": []}, delivery)

    assert "Apple delivery" in html
    assert "49" in html and "13" in html
    assert "62/62" in html
    assert "up to date with the facts" in html
    assert "worker loaded" in html


def test_home_page_says_when_apple_delivery_is_behind() -> None:
    delivery = {
        "configured": True,
        "worker_loaded": True,
        "up_to_date_with_facts": False,
        "behind_facts": True,
        "why": "facts changed after the last Apple delivery; the worker will catch up",
        "counts": {"events": 49, "reminders": 13},
        "verification": {},
    }

    html = render_status(_snapshot(), {"items": []}, delivery)

    assert "facts changed after the last Apple delivery" in html


def test_unconfigured_apple_delivery_is_stated_plainly() -> None:
    html = render_status(_snapshot(), {"items": []}, {"configured": False})

    assert "Not configured" in html


def test_unknown_course_is_none_rather_than_an_empty_page() -> None:
    assert render_course(_snapshot(), "nope") is None


def test_page_content_is_escaped() -> None:
    snapshot = _snapshot()
    snapshot["courses"][0]["title"] = "<script>alert(1)</script>"

    html = render_courses(snapshot)

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_empty_preview_says_so_instead_of_rendering_nothing() -> None:
    assert "(no extracted text for this file)" in render_text("x", "")


def _serve(port: Mock) -> tuple[object, str]:
    server = create_viewer_server(port, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def _port(tmp_path: Path) -> Mock:
    port = Mock(spec=HIQSPort)
    port.resources_dir = tmp_path
    port.information_snapshot.return_value = _snapshot()
    port.attention_snapshot.return_value = {"items": []}
    file_path = tmp_path / "note.pdf"
    file_path.write_bytes(b"%PDF-1.4 test")
    port.material_file.return_value = (file_path, "application/pdf")
    port.source_preview.return_value = {
        "title": "Note 1.pdf",
        "text": "extracted text",
        "truncated": False,
    }
    return port


def test_server_renders_each_page_and_serves_the_original_file(tmp_path: Path) -> None:
    server, base = _serve(_port(tmp_path))
    try:
        for route in ("/", "/courses", "/courses/C1"):
            with urllib.request.urlopen(base + route) as response:
                assert response.status == 200
                assert "text/html" in response.headers["Content-Type"]
                assert response.headers["X-Content-Type-Options"] == "nosniff"
                assert response.headers["Cache-Control"] == "no-store"

        with urllib.request.urlopen(base + "/file?path=courses/C1/files/Note%201.pdf") as response:
            assert response.headers["Content-Type"] == "application/pdf"
            assert response.read() == b"%PDF-1.4 test"

        with urllib.request.urlopen(base + "/preview?path=courses/C1/files/Note%201.pdf") as response:
            assert "extracted text" in response.read().decode()
    finally:
        server.shutdown()


def test_server_refuses_to_write_and_reports_missing_things(tmp_path: Path) -> None:
    port = _port(tmp_path)
    port.material_file.side_effect = HIQSPortError("该文件不在当前课程快照中。")
    server, base = _serve(port)
    try:
        with pytest.raises(urllib.error.HTTPError) as method:
            urllib.request.urlopen(urllib.request.Request(base + "/", method="POST"), data=b"x")
        assert method.value.code == 405

        with pytest.raises(urllib.error.HTTPError) as unknown:
            urllib.request.urlopen(base + "/courses/nope")
        assert unknown.value.code == 404

        with pytest.raises(urllib.error.HTTPError) as no_path:
            urllib.request.urlopen(base + "/file")
        assert no_path.value.code == 400

        with pytest.raises(urllib.error.HTTPError) as rejected:
            urllib.request.urlopen(base + "/file?path=../../etc/passwd")
        assert rejected.value.code == 404
    finally:
        server.shutdown()


def test_the_revision_changes_only_when_a_rendered_file_moves(tmp_path: Path) -> None:
    information = tmp_path / "information.json"
    first = data_revision(tmp_path)
    information.write_text("{}", encoding="utf-8")
    second = data_revision(tmp_path)
    assert first != second

    information.write_text('{"courses": []}', encoding="utf-8")
    third = data_revision(tmp_path)
    assert third != second

    (tmp_path / "unrelated.txt").write_text("noise", encoding="utf-8")
    assert data_revision(tmp_path) == third


def test_pages_carry_a_cheap_refresh_when_a_revision_is_supplied() -> None:
    with_rev = render_status(_snapshot(), {"items": []}, None, rev="abc123")
    without_rev = render_status(_snapshot(), {"items": []})

    assert "/rev" in with_rev and "abc123" in with_rev
    assert "/rev" not in without_rev


def test_the_server_reports_a_revision_and_the_page_uses_it(tmp_path: Path) -> None:
    port = _port(tmp_path)
    (tmp_path / "information.json").write_text("{}", encoding="utf-8")
    server, base = _serve(port)
    try:
        first = json.loads(urllib.request.urlopen(base + "/rev").read())["rev"]
        page = urllib.request.urlopen(base + "/").read().decode()
        assert first in page

        (tmp_path / "information.json").write_text('{"courses": []}', encoding="utf-8")
        second = json.loads(urllib.request.urlopen(base + "/rev").read())["rev"]
        assert second != first
    finally:
        server.shutdown()


def test_the_viewer_refuses_a_non_loopback_host() -> None:
    from hsas.viewer.server import serve_viewer

    with pytest.raises(ValueError, match="loopback"):
        serve_viewer(Mock(spec=HIQSPort), host="0.0.0.0", open_browser=False)
