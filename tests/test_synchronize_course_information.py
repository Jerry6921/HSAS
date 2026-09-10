import asyncio
from pathlib import Path

from hsas.infrastructure.sis_course_info.manage_changes import (
    acknowledge_sis_course_info_changes,
    collect_sis_course_info_changes,
)
from hsas.infrastructure.sis_course_info.synchronize_course_pages import (
    cleaned_visible_text,
    course_identity,
    isolate_course_content,
    safe_rendered_html,
)
from hsas.infrastructure.sis_course_info.fetch_course_pages import (
    LOGIN_URL,
    open_login_until_authenticated,
    restore_sis_session,
    save_sis_session,
)
from hsas.infrastructure.class_planner import ClassPlannerBrowserGateway
from hsas.infrastructure.sis_course_info import SisCourseInfoBrowserGateway
from hsas.infrastructure.storage.persist_data import write_json


def test_course_identity_splits_standard_moodle_course_codes() -> None:
    assert course_identity("BMED2206 Engineering in Biology [Section 1A]") == (
        "BMED2206",
        "BMED",
        "2206",
    )
    assert course_identity("MATH1851_1AB Calculus") == (
        "MATH1851",
        "MATH",
        "1851",
    )
    assert course_identity("AASO_FORUM Academic Advising") is None


def test_sis_and_class_planner_share_hku_portal_profile(tmp_path: Path) -> None:
    assert SisCourseInfoBrowserGateway(tmp_path).profile_dir == (
        ClassPlannerBrowserGateway(tmp_path).profile_dir
    )


def test_sis_session_cookies_survive_browser_process_restart(tmp_path: Path) -> None:
    class Context:
        restored = []

        async def cookies(self, _urls):
            return [
                {"name": "PS_TOKEN", "value": "private", "domain": "sis-main.hku.hk", "path": "/"},
                {"name": "unrelated", "value": "drop", "domain": "example.invalid", "path": "/"},
            ]

        async def add_cookies(self, cookies):
            self.restored = cookies

    state_path = tmp_path / "shared-profile" / "sis-session.json"
    first = Context()
    asyncio.run(save_sis_session(first, state_path))
    second = Context()
    asyncio.run(restore_sis_session(second, state_path))

    assert [cookie["name"] for cookie in second.restored] == ["PS_TOKEN"]
    assert state_path.stat().st_mode & 0o777 == 0o600


def test_sis_login_detects_new_people_soft_token_before_page_redirect() -> None:
    class Page:
        url = LOGIN_URL

        def __init__(self, context):
            self.context = context

        async def goto(self, _url, **_kwargs):
            self.context.token = "new-token"

    class Context:
        token = "expired-token"

        def __init__(self):
            self.pages = [Page(self)]

        async def cookies(self, _urls):
            return [
                {
                    "name": "PS_TOKEN",
                    "value": self.token,
                    "domain": "sis-main.hku.hk",
                    "path": "/",
                }
            ]

    context = Context()
    page = asyncio.run(
        open_login_until_authenticated(context, timeout_seconds=1)
    )

    assert page is context.pages[0]
    assert context.token == "new-token"


def test_cleaned_page_artifact_contains_text_without_active_markup() -> None:
    text = cleaned_visible_text("Course Grade\t A+ to F\n\n\n<script>secret()</script>")
    html = safe_rendered_html(
        course_code="CCHU9053",
        text=text,
        source_url="https://sis-main.hku.hk/example?SUBJECT=CCHU",
    )
    assert "Course Grade A+ to F" in text
    assert "<script>secret()</script>" not in html
    assert "&lt;script&gt;secret()&lt;/script&gt;" in html


def test_course_content_drops_people_soft_navigation() -> None:
    value = "Jerry Zhou\nHome\nCCHU9053 - Demo\nCourse Grade\nA+ to F\nReturn to Search\nFooter"
    assert isolate_course_content(value, "CCHU9053") == (
        "CCHU9053 - Demo\nCourse Grade\nA+ to F\n"
    )


def test_sis_review_batch_tracks_and_acknowledges_latest_course_page(tmp_path: Path) -> None:
    root = tmp_path / "sis-course-info"
    snapshot = {
        "synced_at": "2026-09-08T10:00:00+00:00",
        "changes": [
            {
                "action": "added",
                "course_code": "BMED2206",
                "authority": "supporting",
                "text_relative_path": "sis-course-info/courses/BMED2206/latest.txt",
            }
        ],
    }
    write_json(root / "latest.json", snapshot)
    write_json(root / "history" / "20260908T100000Z.json", snapshot)

    batch = collect_sis_course_info_changes(tmp_path)

    assert batch["pending_change_count"] == 1
    assert batch["authority"] == "supporting"
    acknowledge_sis_course_info_changes(tmp_path, batch, confirmed=True)
    assert collect_sis_course_info_changes(tmp_path)["pending_change_count"] == 0
