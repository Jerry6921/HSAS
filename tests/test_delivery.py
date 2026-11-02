"""Automatic delivery still has to be able to say whether it is current.

Apple delivery runs on a launchd worker, so it can be seconds or minutes behind
the facts. Reporting "delivered" without that comparison turns a scheduled action
into a claim that the calendar is right.
"""

from __future__ import annotations

from hsas.application.delivery import build_delivery

FACTS_AT = "2026-10-27T06:17:29.118451Z"


def _status(**overrides) -> dict:
    report = {
        "status": "complete",
        "as_of": "2026-11-02T07:13:18.196475+00:00",
        "source_updated_at": FACTS_AT,
        "counts": {"events": 49, "reminders": 13},
        "verification": {"expected": 62, "matched": 62, "status": "verified"},
        "errors": [],
    }
    report.update(overrides)
    return {
        "configured": True,
        "worker": {"loaded": True},
        "last_sync": report,
    }


def test_delivery_tracks_the_facts_it_was_built_from() -> None:
    result = build_delivery(_status(), information_updated_at=FACTS_AT)

    assert result["up_to_date_with_facts"] is True
    assert result["behind_facts"] is False
    assert result["counts"] == {"events": 49, "reminders": 13}
    assert result["verification"]["matched"] == 62
    assert result["worker_loaded"] is True


def test_facts_edited_after_the_last_delivery_are_reported_as_behind() -> None:
    later = "2026-11-02T09:00:00+00:00"

    result = build_delivery(_status(), information_updated_at=later)

    assert result["behind_facts"] is True
    assert result["up_to_date_with_facts"] is False
    assert "worker will catch up" in result["why"]


def test_unconfigured_delivery_is_never_reported_as_up_to_date() -> None:
    result = build_delivery({"configured": False}, information_updated_at=FACTS_AT)

    assert result["configured"] is False
    assert result["up_to_date_with_facts"] is False
    assert result["behind_facts"] is False


def test_missing_timestamps_do_not_manufacture_a_verdict() -> None:
    result = build_delivery(_status(), information_updated_at=None)

    assert result["up_to_date_with_facts"] is False
    assert result["behind_facts"] is False
    assert "cannot compare" in result["why"]


def test_the_explicit_report_wins_over_an_older_last_sync_block() -> None:
    status = _status()
    status["report"] = status["last_sync"]
    status["last_sync"] = {"source_updated_at": "2020-01-01T00:00:00Z", "as_of": "2020-01-01T00:00:00Z"}

    result = build_delivery(status, information_updated_at=FACTS_AT)

    assert result["last_delivered_from_facts_at"] == FACTS_AT
    assert result["up_to_date_with_facts"] is True
