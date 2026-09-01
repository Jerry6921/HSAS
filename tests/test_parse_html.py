from pathlib import Path

from hsas.infrastructure.moodle.load_settings import SelectorConfig
from hsas.infrastructure.moodle.parse_html import parse_course


ROOT = Path(__file__).parents[1]


def test_parse_course() -> None:
    html = (ROOT / "tests/fixtures/course.html").read_text(encoding="utf-8")
    selectors = SelectorConfig.load(ROOT / "config/selectors.example.json")
    result = parse_course(html, "https://moodle.example.edu/course/view.php?id=42", selectors)

    assert result.course.course_id == "42"
    assert result.course.title == "COMP0000 Demo Course"
    assert result.sections[0].resources[0].title == "Lecture slides"
    assert result.sections[0].assignments[0].title == "Assignment 1"
    assert result.sections[0].announcements[0].title == "Announcements"
