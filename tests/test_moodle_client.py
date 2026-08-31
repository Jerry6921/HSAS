import asyncio
import json
from pathlib import Path

import pytest

from moodle_collector.acquisition.moodle_client import (
    MoodleAjaxError,
    decode_ajax_response,
    discover_all_course_states,
    enrich_course_state_from_html,
    parse_discovered_courses,
)
from moodle_collector.settings import SelectorConfig


ROOT = Path(__file__).parents[1]


def fixture_state() -> dict:
    return json.loads((ROOT / "tests/fixtures/course_state.json").read_text())


def test_decode_ajax_response_with_json_string_data() -> None:
    state = fixture_state()
    payload = [{"error": False, "data": json.dumps(state)}]
    assert decode_ajax_response(payload)["course"]["id"] == "138907"


def test_decode_double_encoded_result() -> None:
    state = fixture_state()
    assert decode_ajax_response(json.dumps(json.dumps(state)))["cm"][0]["id"] == "200"


def test_decode_ajax_error() -> None:
    with pytest.raises(MoodleAjaxError, match="Not allowed"):
        decode_ajax_response(
            [{"error": True, "exception": {"message": "Not allowed"}}]
        )


def test_enrich_course_state_retains_full_rendered_label_text() -> None:
    state = {"cm": [{"id": "42", "name": "Assessment Methods..."}]}
    html = """
    <li id="module-42">
      <div>Assessment and Weighting</div>
      <div>Final Exam -- 60%</div>
    </li>
    """

    enriched = enrich_course_state_from_html(state, html)

    assert enriched["cm"][0]["content_text"] == (
        "Assessment and Weighting\nFinal Exam -- 60%"
    )


def test_parse_discovered_courses_deduplicates_dashboard_links() -> None:
    selectors = SelectorConfig(
        dashboard_ready=["body"],
        course_links=["a.course"],
        course_title=["h1"],
        sections=["section"],
        section_title=["h2"],
        activity_links=["a.activity"],
        activity_name=["span.name"],
    )
    html = """
    <a class="course" href="/course/view.php?id=123">Course name Course A</a>
    <a class="course" href="/course/view.php?id=123">Course name Course A</a>
    <a class="course" href="/course/view.php?id=456">Course B</a>
    """

    courses = parse_discovered_courses(
        html,
        "https://moodle.example.edu/my/",
        selectors,
    )

    assert [course.course_id for course in courses] == ["123", "456"]
    assert courses[0].title == "Course A"


def test_discover_all_course_states_keeps_per_course_failures(monkeypatch) -> None:
    selectors = SelectorConfig(
        dashboard_ready=["body"],
        course_links=["a.course"],
        course_title=["h1"],
        sections=["section"],
        section_title=["h2"],
        activity_links=["a.activity"],
        activity_name=["span.name"],
    )

    class FakePage:
        url = ""

        async def goto(self, url: str, **_kwargs) -> None:
            self.url = url

        async def content(self) -> str:
            if "/my" in self.url:
                return """
                <a class="course" href="/course/view.php?id=123">Course A</a>
                <a class="course" href="/course/view.php?id=456">Course B</a>
                """
            course_id = self.url.rsplit("=", 1)[-1]
            return f"<h1>Resolved {course_id}</h1>"

    async def fake_fetch(_context, _page, *, base_url: str, course_id: str):
        assert base_url == "https://moodle.example.edu"
        if course_id == "456":
            raise MoodleAjaxError("not available")
        return fixture_state()

    monkeypatch.setattr(
        "moodle_collector.acquisition.moodle_client.fetch_course_state",
        fake_fetch,
    )
    results = asyncio.run(
        discover_all_course_states(
            object(),
            FakePage(),
            dashboard_url="https://moodle.example.edu/my/",
            base_url="https://moodle.example.edu",
            selectors=selectors,
        )
    )

    assert results[0].succeeded is True
    assert results[0].title == "Resolved 123"
    assert results[1].succeeded is False
    assert "not available" in results[1].error
