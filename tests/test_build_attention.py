from datetime import UTC, datetime

import pytest

from hsas.application.build_attention import build_attention_snapshot


NOW = datetime(2026, 9, 24, 4, 0, tzinfo=UTC)


def _snapshot() -> dict[str, object]:
    return {
        "timezone": "Asia/Hong_Kong",
        "courses": [
            {"course_id": "math", "code": "MATH1851", "title": "Calculus"},
        ],
        "items": [
            {
                "item_id": "assignment-1",
                "course_id": "math",
                "title": "Assignment 1",
                "category": "assignment",
                "date_status": "tentative",
                "due_on": "2026-09-30",
                "submission_method": None,
                "weight_percent": None,
                "links": [],
                "warnings": [],
                "sources": [
                    {
                        "source_type": "moodle",
                        "title": "Assignment page",
                        "url": "https://example.test/assignment",
                        "page_numbers": [],
                    }
                ],
            },
            {
                "item_id": "exam-unknown",
                "course_id": "math",
                "title": "Final exam",
                "category": "exam",
                "date_status": "unknown",
                "warnings": [],
                "sources": [],
            },
            {
                "item_id": "quiz-conflict",
                "course_id": "math",
                "title": "Quiz",
                "category": "quiz",
                "date_status": "confirmed",
                "due_at": "2026-09-26T10:00:00+08:00",
                "submission_method": "Moodle",
                "weight_percent": 10,
                "links": [{"label": "Submit", "url": "https://example.test"}],
                "warnings": ["Moodle and syllabus dates conflict"],
                "sources": [
                    {"source_type": "moodle", "title": "Moodle", "page_numbers": []},
                    {"source_type": "syllabus", "title": "Syllabus", "page_numbers": []},
                ],
            },
            {
                "item_id": "late-report",
                "course_id": "math",
                "title": "Late report",
                "category": "report",
                "date_status": "confirmed",
                "due_at": "2026-09-23T12:00:00+08:00",
                "warnings": ["Submission remains unresolved"],
                "sources": [],
            },
        ],
        "updates": {
            "courses": [
                {
                    "course_id": "math",
                    "affected_information_item_ids": ["assignment-1"],
                }
            ]
        },
        "review_closure": {
            "retry_tasks": [{"source": "moodle", "course_code": "MATH1851"}]
        },
        "moodle_session": {"login_status": "expired"},
    }


def test_attention_snapshot_covers_every_reason_and_is_deterministic() -> None:
    first = build_attention_snapshot(_snapshot(), now=NOW, horizon_days=14)
    second = build_attention_snapshot(_snapshot(), now=NOW, horizon_days=14)

    assert first == second
    reasons = {
        reason
        for item in first["items"]
        for reason in item["reason_codes"]
    }
    assert reasons == {
        "DUE_DATE_TENTATIVE",
        "DUE_DATE_UNKNOWN",
        "SUBMISSION_DETAILS_MISSING",
        "WEIGHT_UNKNOWN",
        "SOURCE_CONFLICT",
        "SOURCE_SYNC_FAILED",
        "SOURCE_CHANGED_REVIEW_PENDING",
        "LOGIN_REQUIRED",
        "OVERDUE_UNRESOLVED",
    }
    assert first["items"][0]["severity"] == "high"
    assignment = next(
        item for item in first["items"] if item["information_item_id"] == "assignment-1"
    )
    assert assignment["missing_fields"] == [
        "due_time",
        "submission_method",
    ]
    assert assignment["evidence"][0]["source_type"] == "moodle"
    assert {action["kind"] for action in assignment["actions"]} == {
        "open_item",
        "open_evidence",
        "review_changes",
    }


def test_attention_ignores_missing_source_coverage_and_out_of_horizon_items() -> None:
    snapshot = _snapshot()
    snapshot["items"] = [
        {
            "item_id": "far-away",
            "course_id": "math",
            "title": "Far away",
            "category": "assignment",
            "date_status": "confirmed",
            "due_at": "2026-11-30T12:00:00+08:00",
            "submission_method": None,
            "weight_percent": None,
            "links": [],
            "warnings": [],
            "sources": [],
        }
    ]
    snapshot["updates"] = {"courses": []}
    snapshot["review_closure"] = {"retry_tasks": []}
    snapshot["moodle_session"] = {"login_status": "logged_in"}

    result = build_attention_snapshot(snapshot, now=NOW)

    assert result["items"] == []


def test_attention_rejects_invalid_clock_and_horizon() -> None:
    with pytest.raises(ValueError, match="UTC offset"):
        build_attention_snapshot({}, now=datetime(2026, 9, 24))
    with pytest.raises(ValueError, match="between 1 and 90"):
        build_attention_snapshot({}, now=NOW, horizon_days=0)
