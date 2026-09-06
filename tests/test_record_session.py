from pathlib import Path

from hsas.infrastructure.moodle.record_session import (
    load_moodle_session_status,
    record_moodle_session_status,
)


def test_moodle_session_status_defaults_and_round_trips(tmp_path: Path) -> None:
    assert load_moodle_session_status(tmp_path) == {
        "login_status": "login_required",
        "login_checked_at": None,
        "available_course_count": 0,
    }

    record_moodle_session_status(
        tmp_path,
        "logged_in",
        available_course_count=8,
    )
    status = load_moodle_session_status(tmp_path)
    assert status["login_status"] == "logged_in"
    assert status["login_checked_at"]
    assert status["available_course_count"] == 8
