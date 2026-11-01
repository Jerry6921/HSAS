"""Moodle catalogue/pure-helper contracts that previously had no coverage."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hsas.infrastructure.moodle import gateway as gateway_module
from hsas.infrastructure.moodle.course_mapper import build_course_archive
from hsas.infrastructure.moodle.gateway import (
    _downloaded_courses,
    _resolve_course_target,
    _validated_course_id,
    list_courses_in_context,
)
from hsas.infrastructure.storage.json_store import write_model

ROOT = Path(__file__).parents[1]
BASE_URL = "https://moodle.hku.hk"


class _Locator:
    def __init__(self, found: int) -> None:
        self._found = found

    async def count(self) -> int:
        return self._found


class _Page:
    def __init__(self, url: str, *, found: int = 1, fail: bool = False) -> None:
        self.url = url
        self._found = found
        self._fail = fail

    async def goto(self, *_args, **_kwargs) -> None:
        if self._fail:
            raise RuntimeError("navigation failed")

    def locator(self, _css: str) -> _Locator:
        return _Locator(self._found)

    async def close(self) -> None:
        return None


class _Context:
    def __init__(self, page: _Page) -> None:
        self._page = page

    async def new_page(self) -> _Page:
        return self._page


def _settings(output_dir: Path) -> SimpleNamespace:
    return SimpleNamespace(
        output_dir=output_dir,
        dashboard_url=f"{BASE_URL}/my/",
        login_url=f"{BASE_URL}/login/index.php",
        selectors=lambda: SimpleNamespace(dashboard_ready=["#nav-drawer"]),
    )


def _archive(title: str = "Neuroscience Demo"):
    state = json.loads((ROOT / "tests/fixtures/course_state.json").read_text())
    return build_course_archive(
        state,
        course_title=title,
        raw_state_path="courses/138907/raw/course-state.json",
    )


def test_resolve_course_target_accepts_numeric_id() -> None:
    course_id, url = _resolve_course_target("138907", BASE_URL)

    assert course_id == "138907"
    assert url == f"{BASE_URL}/course/view.php?id=138907"


def test_resolve_course_target_accepts_same_origin_url() -> None:
    url = f"{BASE_URL}/course/view.php?id=42"

    assert _resolve_course_target(url, BASE_URL) == ("42", url)


@pytest.mark.parametrize(
    "value",
    [
        "https://evil.example/course/view.php?id=1",
        f"{BASE_URL}/course/view.php?id=abc",
        f"{BASE_URL}/course/view.php",
        "not-an-id",
    ],
)
def test_resolve_course_target_rejects_invalid_input(value: str) -> None:
    with pytest.raises(ValueError):
        _resolve_course_target(value, BASE_URL)


def test_validated_course_id_rejects_wrong_scheme() -> None:
    with pytest.raises(ValueError, match="host"):
        _validated_course_id("ftp://moodle.hku.hk/course/view.php?id=1", BASE_URL)


def test_downloaded_courses_reports_valid_and_corrupt_snapshots(tmp_path: Path) -> None:
    write_model(tmp_path / "courses/138907/course.json", _archive("Demo"))
    corrupt = tmp_path / "courses/999/course.json"
    corrupt.parent.mkdir(parents=True)
    corrupt.write_text("{not json", encoding="utf-8")

    downloaded = _downloaded_courses(_settings(tmp_path))

    assert downloaded["138907"] == "Demo"
    assert downloaded["999"] == "Invalid or incompatible course.json"


def test_list_courses_reports_logged_in_catalogue(tmp_path: Path, monkeypatch) -> None:
    write_model(tmp_path / "courses/138907/course.json", _archive("Demo"))

    async def fake_discover(page, *, dashboard_url, selectors):  # noqa: ANN001
        return [
            SimpleNamespace(
                course_id="138907",
                title="Neuroscience Demo",
                url=f"{BASE_URL}/course/view.php?id=138907",
            )
        ]

    monkeypatch.setattr(gateway_module, "discover_courses", fake_discover)
    page = _Page(url=f"{BASE_URL}/my/")

    result = asyncio.run(list_courses_in_context(_Context(page), _settings(tmp_path)))

    assert result.login_status == "logged in"
    assert result.login_error is None
    assert [entry.course_id for entry in result.available] == ["138907"]
    assert result.available[0].downloaded is True
    assert [entry.course_id for entry in result.downloaded] == ["138907"]


def test_list_courses_reports_navigation_failure(tmp_path: Path, monkeypatch) -> None:
    async def fake_discover(page, *, dashboard_url, selectors):  # noqa: ANN001
        raise AssertionError("discovery must not run after a navigation failure")

    monkeypatch.setattr(gateway_module, "discover_courses", fake_discover)
    page = _Page(url=f"{BASE_URL}/my/", fail=True)

    result = asyncio.run(list_courses_in_context(_Context(page), _settings(tmp_path)))

    assert result.login_status == "not logged in"
    assert result.login_error is not None
    assert "navigation failed" in result.login_error
