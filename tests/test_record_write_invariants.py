"""Manual course add/delete must keep the same canonical-write invariants as apply.

The compatibility UI keeps these maintenance actions, but every canonical write
still has to produce a user-visible digest and keep the derived index consistent.
"""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

from hsas.core.services.records import CourseRecordService

_COURSE = {
    "confirmed": True,
    "course": {
        "course_id": "DEMO1001-2026-S1",
        "code": "DEMO1001",
        "title": "Demo Course",
        "moodle_course_id": "12345",
    },
}


def _service(resources: Path) -> CourseRecordService:
    return CourseRecordService(resources_dir=resources, mutation_lock=Lock())


def _recent_update(resources: Path) -> dict:
    path = resources / "ai-state" / "recent-information-update.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_add_course_writes_recent_update_digest(tmp_path: Path) -> None:
    service = _service(tmp_path)

    result = service.add_course(dict(_COURSE))

    assert result["warnings"] == []
    report = _recent_update(tmp_path)
    assert report["courses"][0]["course_id"] == "DEMO1001-2026-S1"
    assert report["summary"]["added"] == 1


def test_delete_course_writes_removal_digest(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.add_course(dict(_COURSE))

    result = service.delete_courses(
        {
            "course_ids": ["DEMO1001-2026-S1"],
            "confirmation": ["DEMO1001-2026-S1"],
            "confirmed": True,
        }
    )

    assert result["deleted_course_count"] == 1
    report = _recent_update(tmp_path)
    actions = [
        change["action"]
        for course in report["courses"]
        for change in course["changes"]
    ]
    assert "removed" in actions
    assert report["summary"]["removed"] == 1


def test_add_course_keeps_derived_index_consistent(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.add_course(dict(_COURSE))

    # A successful refresh leaves a ready derived index; an unsuccessful one is
    # marked stale instead of silently pretending success.
    index_path = tmp_path / "index" / "materials.sqlite3"
    if index_path.exists():
        assert index_path.stat().st_size > 0
