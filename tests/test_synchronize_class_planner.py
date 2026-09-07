from pathlib import Path

from hsas.infrastructure.class_planner.fetch_calendar import _is_portal_bridge
from hsas.infrastructure.class_planner.synchronize_calendar import (
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
