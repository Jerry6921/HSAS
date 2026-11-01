import pytest

from hsas.application.information_audit import audit_information
from hsas.application.notion_projection import expand_calendar
from hsas.domain.information import InformationStore
from hsas.domain.information.calendar import build_ics, expand_occurrences


def _store(recurrence, *, timezone="Asia/Hong_Kong"):
    return InformationStore.model_validate(
        {
            "updated_at": "2026-09-07T08:00:00+00:00",
            "timezone": timezone,
            "courses": [{"course_id": "1", "code": "DEMO1001", "title": "Demo"}],
            "items": [{
                "item_id": "weekly",
                "course_id": "1",
                "title": "Lecture",
                "category": "class",
                "date_status": "confirmed",
                "location": "Room A",
                "recurrence": recurrence,
            }],
        }
    )


def _occurrence_set(item, timezone):
    return {
        (start.isoformat(), end.isoformat() if end else None)
        for start, end in expand_occurrences(item, timezone)
    }


def test_projection_audit_and_ics_share_cancellation_makeup_and_change_facts():
    store = _store({
        "weekdays": [0],
        "valid_from": "2026-10-05",
        "valid_until": "2026-10-26",
        "start_time": "09:00:00",
        "end_time": "09:50:00",
        "excluded_dates": ["2026-10-12"],
        "additional_dates": ["2026-10-13", "2026-10-20"],
        "exceptions": [
            {"date": "2026-10-20", "status": "cancelled"},
            {
                "date": "2026-10-19",
                "status": "changed",
                "start_time": "10:00:00",
                "end_time": "10:50:00",
                "location": "Room B",
            },
        ],
    })
    item = store.items[0]
    expected = _occurrence_set(item, store.timezone)
    projected = {
        (row["start"], row["end"])
        for row in expand_calendar(item.model_dump(mode="json"), store.timezone)
        if row["identity"].startswith("weekly:2026-")
    }
    assert projected == expected
    audit = audit_information(store)
    assert audit["items"][0]["calendar_occurrence_ids"] == [
        "weekly:2026-10-05",
        "weekly:2026-10-13",
        "weekly:2026-10-19",
        "weekly:2026-10-26",
    ]
    ics = build_ics(store)
    assert "RRULE:FREQ=WEEKLY;BYDAY=MO;UNTIL=20261026T155959Z" in ics
    assert "EXDATE;TZID=Asia/Hong_Kong:20261012T090000,20261019T090000" in ics
    assert "RDATE;TZID=Asia/Hong_Kong:20261013T090000" in ics
    assert "20261020T090000" not in ics
    assert "DTSTART;TZID=Asia/Hong_Kong:20261019T100000" in ics


def test_short_rule_without_matching_weekday_keeps_only_explicit_occurrences():
    store = _store({
        "weekdays": [4],
        "valid_from": "2026-11-02",
        "valid_until": "2026-11-03",
        "start_time": "10:00:00",
        "end_time": "11:00:00",
        "additional_dates": ["2026-11-04"],
    })
    item = store.items[0]
    assert len(expand_occurrences(item, store.timezone)) == 1
    assert len(expand_calendar(item.model_dump(mode="json"), store.timezone)) == 1
    assert build_ics(store).count("BEGIN:VEVENT") == 1


def test_expansion_rejects_rules_over_five_years_in_all_callers():
    store = _store({
        "weekdays": [0],
        "valid_from": "2026-01-01",
        "valid_until": "2032-01-02",
        "start_time": "10:00:00",
        "end_time": "11:00:00",
    })
    item = store.items[0]
    with pytest.raises(ValueError, match="five-year"):
        expand_occurrences(item, store.timezone)
    with pytest.raises(ValueError, match="five-year"):
        expand_calendar(item.model_dump(mode="json"), store.timezone)
    with pytest.raises(ValueError, match="five-year"):
        build_ics(store)


def test_cross_timezone_occurrences_are_localized_by_the_requested_zone():
    store = _store(
        {
            "weekdays": [6],
            "valid_from": "2026-10-25",
            "valid_until": "2026-11-01",
            "start_time": "09:00:00",
            "end_time": "10:00:00",
        },
        timezone="America/New_York",
    )
    starts = [start for start, _ in expand_occurrences(store.items[0], store.timezone)]
    assert [value.isoformat() for value in starts] == [
        "2026-10-25T09:00:00-04:00",
        "2026-11-01T09:00:00-05:00",
    ]

