"""Moodle-supplied module ids must never become unvalidated path components."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from hsas.domain.courses.models import CourseActivity
from hsas.infrastructure.moodle.activity_downloader import _save_response
from hsas.infrastructure.moodle.course_mapper import map_activity


class _FakeResponse:
    def __init__(self, url: str, body: bytes, headers: dict[str, str]) -> None:
        self.url = url
        self._body = body
        self.headers = headers

    async def body(self) -> bytes:
        return self._body


def _activity() -> CourseActivity:
    return CourseActivity(
        module_id="10",
        name="Course outline",
        category="resource",
        module="resource",
    )


def test_course_activity_rejects_path_metacharacters_in_module_id() -> None:
    with pytest.raises(ValidationError):
        CourseActivity(
            module_id="../../Library/LaunchAgents",
            name="evil",
            category="resource",
            module="resource",
        )


def test_course_activity_keeps_legacy_synthetic_ids() -> None:
    # Legacy archives stored page ids such as ``page-1``; they must still load.
    activity = CourseActivity(
        module_id="page-1",
        name="Week 1",
        category="resource",
        module="page",
    )
    assert activity.module_id == "page-1"


def test_mapper_rejects_non_numeric_live_module_id() -> None:
    with pytest.raises(ValueError, match="course-module id"):
        map_activity(
            {
                "id": "../../etc",
                "name": "evil",
                "module": "resource",
                "url": "https://moodle.hku.hk/mod/resource/view.php?id=1",
            }
        )


def test_save_response_refuses_write_outside_storage_root(tmp_path: Path) -> None:
    storage_root = tmp_path / "resources"
    outside = tmp_path / "outside"
    outside.mkdir(parents=True)
    response = _FakeResponse(
        "https://moodle.hku.hk/pluginfile.php/1/outline.pdf",
        b"%PDF-1.4 minimal",
        {"content-type": "application/pdf", "content-length": "14"},
    )

    result = asyncio.run(
        _save_response(
            response,
            activity=_activity(),
            index=0,
            destination_dir=outside,
            storage_root=storage_root,
            max_download_bytes=1024,
        )
    )

    assert result is None
    assert list(outside.iterdir()) == []
