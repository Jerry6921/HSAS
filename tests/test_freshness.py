"""Staleness must be a judgement the system states, not arithmetic nobody does."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hsas.application.attention import build_attention_snapshot
from hsas.application.freshness import (
    FRESH,
    NEVER,
    STALE,
    THRESHOLDS_DAYS,
    build_freshness,
    evaluate,
)

NOW = datetime(2026, 11, 2, 7, 0, tzinfo=UTC)


def _ago(days: float) -> str:
    return (NOW - timedelta(days=days)).isoformat()


def test_a_source_is_fresh_inside_its_own_threshold_and_stale_outside_it() -> None:
    inside = evaluate("moodle", _ago(2.9), now=NOW)
    outside = evaluate("moodle", _ago(3.1), now=NOW)

    assert (inside.state, inside.age_days) == (FRESH, 2.9)
    assert outside.state == STALE
    assert outside.threshold_days == THRESHOLDS_DAYS["moodle"]
    assert evaluate("sis_course_info", _ago(20), now=NOW).state == FRESH


def test_unknown_or_unparseable_timestamps_are_never_not_fresh() -> None:
    assert evaluate("moodle", None, now=NOW).state == NEVER
    assert evaluate("moodle", "", now=NOW).state == NEVER
    assert evaluate("moodle", "last tuesday", now=NOW).state == NEVER
    assert evaluate("moodle", None, now=NOW).age_days is None


def test_timestamps_are_read_with_or_without_an_offset() -> None:
    assert evaluate("information", "2026-11-01T07:00:00Z", now=NOW).age_days == 1.0
    assert evaluate("information", "2026-11-01T07:00:00+00:00", now=NOW).age_days == 1.0
    assert evaluate("information", "2026-11-01T15:00:00+08:00", now=NOW).age_days == 1.0


def test_sources_name_their_capture_time_differently() -> None:
    snapshot = {
        "updated_at": _ago(1),
        "sis_enrollment": {"observed_at": _ago(2)},
        "class_planner": {"synced_at": _ago(30)},
        "sis_course_info": {"collected_at": _ago(40)},
        "courses": [{"moodle": {"collected_at": _ago(9)}}],
    }

    by_source = {
        entry["source"]: entry
        for entry in build_freshness(snapshot, now=NOW)["sources"]
    }

    assert by_source["sis_enrollment"]["captured_at"] == _ago(2)
    assert by_source["sis_enrollment"]["state"] == FRESH
    assert by_source["class_planner"]["state"] == STALE
    assert by_source["sis_course_info"]["state"] == STALE
    assert by_source["moodle"]["state"] == STALE


def test_the_newest_course_capture_represents_moodle() -> None:
    snapshot = {
        "courses": [
            {"moodle": {"collected_at": _ago(9)}},
            {"moodle": {"collected_at": _ago(1)}},
            {"moodle": None},
            {},
        ],
    }

    moodle = next(
        entry for entry in build_freshness(snapshot, now=NOW)["sources"]
        if entry["source"] == "moodle"
    )

    assert moodle["state"] == FRESH
    assert moodle["age_days"] == 1.0


def test_the_summary_names_what_is_stale_and_what_was_never_collected() -> None:
    snapshot = {
        "updated_at": _ago(1),
        "courses": [{"moodle": {"collected_at": _ago(9)}}],
        "sis_enrollment": {},
        "class_planner": {"synced_at": _ago(2)},
        "sis_course_info": {"synced_at": _ago(2)},
    }

    freshness = build_freshness(snapshot, now=NOW)

    assert freshness["stale_sources"] == ["moodle"]
    assert freshness["never_collected"] == ["sis_enrollment"]
    assert freshness["all_fresh"] is False


def test_a_stale_source_becomes_an_attention_item_with_an_allowed_action() -> None:
    snapshot = {
        "timezone": "Asia/Hong_Kong",
        "courses": [],
        "items": [],
        "freshness": build_freshness(
            {
                "updated_at": _ago(1),
                "courses": [{"moodle": {"collected_at": _ago(9)}}],
                "sis_enrollment": {"observed_at": _ago(1)},
                "class_planner": {"synced_at": _ago(1)},
                "sis_course_info": {"synced_at": _ago(1)},
            },
            now=NOW,
        ),
        "moodle_session": {"login_status": "logged_in"},
    }

    result = build_attention_snapshot(snapshot, now=NOW)

    stale = [item for item in result["items"] if "SOURCE_STALE" in item["reason_codes"]]
    assert [item["affected_source"] for item in stale] == ["moodle"]
    assert stale[0]["actions"][0]["kind"] == "refresh_source"


def test_fresh_sources_produce_no_attention_noise() -> None:
    snapshot = {
        "timezone": "Asia/Hong_Kong",
        "courses": [],
        "items": [],
        "freshness": build_freshness(
            {
                "updated_at": _ago(1),
                "courses": [{"moodle": {"collected_at": _ago(1)}}],
                "sis_enrollment": {"observed_at": _ago(1)},
                "class_planner": {"synced_at": _ago(1)},
                "sis_course_info": {"synced_at": _ago(1)},
            },
            now=NOW,
        ),
        "moodle_session": {"login_status": "logged_in"},
    }

    result = build_attention_snapshot(snapshot, now=NOW)

    assert [item for item in result["items"] if "SOURCE_STALE" in item["reason_codes"]] == []
