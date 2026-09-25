import asyncio
from pathlib import Path

from hsas.infrastructure.class_planner.fetch_calendar import (
    APP_URL,
    _calendar_payload_from_app,
    _is_authenticated_portal_page,
    _is_calendar_url,
    _is_class_planner_app,
    _is_portal_bridge,
    _is_portal_resume_page,
    _resume_after_portal_login,
    capture_calendar_response_in_context,
)
from hsas.infrastructure.class_planner.synchronize_calendar import (
    ClassPlannerBrowserGateway,
    _diff,
    _sanitize,
    _summary,
    class_planner_status,
)
from hsas.infrastructure.storage.persist_data import write_json


def payload(course_title: str = "Engineering Fundamentals") -> dict:
    return {
        "mainTable": [
            {
                "id": "4261-012345-1001",
                "STRM": "4261",
                "CRSE_ID": "012345",
                "CLASS_NBR": 1001,
                "COURSE_SUBCLASS": "DEMO1001-1A",
                "COURSE_TITLE_LONG": course_title,
                "email": "student@example.invalid",
            }
        ],
        "patterns": [
            {
                "strm": "4261",
                "crse_id": "012345",
                "day_str": "Mon",
                "start_time": "09:00 AM",
                "end_time": "09:50 AM",
                "descrshort": "DEMO1",
            }
        ],
        "access_token": "secret",
    }


def test_only_official_hku_portal_aad_bridge_triggers_resume() -> None:
    assert _is_portal_bridge("https://hkuportal.hku.hk/cas/aad") is True
    assert _is_portal_bridge("https://hkuportal.hku.hk/login.html") is False
    assert _is_portal_bridge("https://example.invalid/cas/aad") is False


def test_current_and_legacy_calendar_api_urls_are_recognized() -> None:
    assert _is_calendar_url(
        "https://api.hku.hk/sis/app/cspa/calendar?email=user%40connect.hku.hk&strm=4261"
    )
    assert _is_calendar_url(
        "https://class-planner.hku.hk/api/calendar?email=user%40connect.hku.hk&strm=4261"
    )
    assert not _is_calendar_url("https://api.hku.hk/sis/app/cspa/subclasses/terms")
    assert not _is_calendar_url("https://example.invalid/sis/app/cspa/calendar")


def test_authenticated_class_planner_app_is_not_a_portal_resume_page() -> None:
    assert _is_class_planner_app("https://class-planner.hku.hk/app") is True
    assert _is_class_planner_app("https://class-planner.hku.hk/app/") is True
    assert _is_class_planner_app("https://class-planner.hku.hk/api/calendar") is False
    assert _is_class_planner_app("https://hkuportal.hku.hk/app") is False


def test_calendar_payload_is_recovered_inside_authenticated_app() -> None:
    class Page:
        url = "https://class-planner.hku.hk/app"
        evaluated_script = ""

        async def evaluate(self, script: str) -> dict:
            self.evaluated_script = script
            return payload()

    page = Page()
    result = asyncio.run(_calendar_payload_from_app(page))
    assert result == payload()
    assert "/api/calendar" in page.evaluated_script
    assert "credentials: \"include\"" in page.evaluated_script


def test_calendar_payload_recovery_ignores_non_app_pages() -> None:
    class Page:
        url = "https://hkuportal.hku.hk/login.html"

        async def evaluate(self, _script: str) -> dict:
            raise AssertionError("non-app pages must not be inspected")

    assert asyncio.run(_calendar_payload_from_app(Page())) is None


def test_visible_login_reuses_and_foregrounds_persistent_blank_page(
    monkeypatch,
) -> None:
    class Page:
        url = "about:blank"
        goto_urls: list[str] = []
        foreground_count = 0
        closed = False

        def is_closed(self) -> bool:
            return self.closed

        async def bring_to_front(self) -> None:
            self.foreground_count += 1

        async def goto(self, url: str, **_kwargs) -> None:
            self.goto_urls.append(url)
            self.url = url

        async def close(self) -> None:
            self.closed = True

    class Context:
        def __init__(self, page: Page) -> None:
            self.pages = [page]
            self.listener = None

        async def new_page(self):
            raise AssertionError("interactive login must reuse the visible blank page")

        def on(self, _event: str, listener) -> None:
            self.listener = listener

        def remove_listener(self, _event: str, listener) -> None:
            assert listener is self.listener

    async def resume(*_args, **_kwargs) -> dict:
        return payload()

    page = Page()
    monkeypatch.setattr(
        "hsas.infrastructure.class_planner.fetch_calendar._resume_after_portal_login",
        resume,
    )

    result = asyncio.run(
        capture_calendar_response_in_context(
            Context(page),
            headless=False,
            timeout_seconds=10,
        )
    )

    assert result == payload()
    assert page.goto_urls == [APP_URL]
    assert page.foreground_count == 2
    assert page.closed is True


def test_authenticated_app_reloads_only_once_to_retrigger_calendar(
    monkeypatch,
) -> None:
    class Page:
        url = "https://class-planner.hku.hk/app"
        reload_count = 0

        async def reload(self, **_kwargs) -> None:
            self.reload_count += 1
            if not future.done():
                future.set_result(payload())

    class Context:
        def __init__(self, page: Page) -> None:
            self.pages = [page]

        async def cookies(self, *_args) -> list:
            return []

    async def run() -> tuple[dict, int]:
        nonlocal future
        future = asyncio.get_running_loop().create_future()
        page = Page()
        result = await _resume_after_portal_login(
            Context(page),
            future,
            timeout_seconds=1,
        )
        return result, page.reload_count

    future = None
    monkeypatch.setattr(
        "hsas.infrastructure.class_planner.fetch_calendar.APP_RETRY_DELAY_SECONDS",
        0,
    )
    result, reload_count = asyncio.run(run())
    assert result == payload()
    assert reload_count == 1


def test_authenticated_portal_pages_return_to_class_planner() -> None:
    assert _is_portal_resume_page("https://hkuportal.hku.hk/cas/aad") is True
    assert _is_portal_resume_page("https://hkuportal.hku.hk/") is True
    assert _is_portal_resume_page("https://hkuportal.hku.hk/home") is True
    assert _is_portal_resume_page("https://hkuportal.hku.hk/login.html") is False
    assert _is_portal_resume_page("https://hkuportal.hku.hk/cas/signin") is False
    assert _is_portal_resume_page("https://login.microsoftonline.com/") is False


def test_authenticated_portal_login_url_can_resume_after_login() -> None:
    class Locator:
        def __init__(self, selector: str) -> None:
            self.selector = selector

        async def count(self) -> int:
            return 0

        async def inner_text(self, **_kwargs) -> str:
            return "Welcome to HKU Portal · My Favourites · Log out"

    class Page:
        url = "https://hkuportal.hku.hk/login.html"

        def locator(self, selector: str) -> Locator:
            return Locator(selector)

    assert asyncio.run(_is_authenticated_portal_page(Page())) is True


def test_portal_login_persists_captured_calendar_before_closing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def capture(*_args, **_kwargs):
        return payload()

    monkeypatch.setattr(
        "hsas.infrastructure.class_planner.synchronize_calendar.capture_calendar_response",
        capture,
    )

    result = ClassPlannerBrowserGateway(tmp_path).login_until_ready()

    assert result.status == "logged_in"
    assert result.course_count == 1
    assert (tmp_path / "class-planner" / "latest.json").is_file()
    assert class_planner_status(tmp_path)["meeting_count"] == 1


def test_class_planner_snapshot_is_summarized_and_sanitized() -> None:
    value = _sanitize(payload())
    assert "access_token" not in value
    assert "email" not in value["mainTable"][0]
    assert _summary(value) == {
        "course_count": 1,
        "meeting_count": 1,
        "term_ids": ["4261"],
    }


def test_class_planner_diff_tracks_course_level_changes() -> None:
    first = payload()
    changed = payload("Engineering Fundamentals II")
    initial = _diff(None, first)
    update = _diff(first, changed)
    assert initial["added"] == ["4261-012345-1001"]
    assert update["changed"] is True
    assert update["added"] == []
    assert update["modified"] == ["4261-012345-1001"]
    assert update["removed"] == []
    assert update["details"][0]["fields"] == ["course"]

    meeting_changed = payload()
    meeting_changed["patterns"][0]["start_time"] = "10:00 AM"
    assert _diff(first, meeting_changed)["modified"] == ["4261-012345-1001"]


def test_class_planner_diff_ignores_live_enrolment_statistics() -> None:
    first = payload()
    first["mainTable"][0]["APPROVED_HEAD_CNT"] = None
    changed = payload()
    changed["mainTable"][0]["APPROVED_HEAD_CNT"] = 42

    update = _diff(first, changed)

    assert update["changed"] is False
    assert update["modified"] == []
    assert update["details"] == []


def test_class_planner_status_reads_local_snapshot(tmp_path: Path) -> None:
    write_json(
        tmp_path / "class-planner" / "latest.json",
        {
            "synced_at": "2026-09-06T10:00:00+00:00",
            "changes": {"changed": True, "added": ["4261-012345-1001"]},
            "payload": _sanitize(payload()),
        },
    )
    status = class_planner_status(tmp_path)
    assert status["available"] is True
    assert status["course_count"] == 1
    assert status["meeting_count"] == 1
    assert status["term_ids"] == ["4261"]
    assert status["login_status"] == "login_required"
